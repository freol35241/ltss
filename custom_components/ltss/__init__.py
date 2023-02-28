"""Support for recording details."""
import asyncio
import concurrent.futures
from contextlib import contextmanager
from datetime import datetime, timedelta
import logging
import queue
import threading
import time
import json
from typing import Any, Dict, Optional, Callable

import voluptuous as vol
from sqlalchemy import exc, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import scoped_session, sessionmaker

import psycopg2

from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_DOMAINS,
    CONF_ENTITIES,
    CONF_EXCLUDE,
    CONF_INCLUDE,
    EVENT_HOMEASSISTANT_START,
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_CHANGED,
    STATE_UNKNOWN,
)
from homeassistant.components import persistent_notification
from homeassistant.core import CoreState, HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entityfilter import (
    convert_include_exclude_filter,
    INCLUDE_EXCLUDE_BASE_FILTER_SCHEMA,
)
from homeassistant.helpers.typing import ConfigType
import homeassistant.util.dt as dt_util
from homeassistant.helpers.json import JSONEncoder

from .models import Base, LTSS
from .migrations import check_and_migrate

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ltss"

CONF_DB_URL = "db_url"
CONF_CHUNK_TIME_INTERVAL = "chunk_time_interval"

CONNECT_RETRY_WAIT = 3

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: INCLUDE_EXCLUDE_BASE_FILTER_SCHEMA.extend(
            {
                vol.Required(CONF_DB_URL): cv.string,
                vol.Optional(
                    CONF_CHUNK_TIME_INTERVAL, default=2592000000000
                ): cv.positive_int,  # 30 days
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up LTSS."""
    conf = config[DOMAIN]

    db_url = conf.get(CONF_DB_URL)
    chunk_time_interval = conf.get(CONF_CHUNK_TIME_INTERVAL)
    entity_filter = convert_include_exclude_filter(conf)

    instance = LTSS_DB(
        hass=hass,
        uri=db_url,
        chunk_time_interval=chunk_time_interval,
        entity_filter=entity_filter,
    )
    instance.async_initialize()
    instance.start()

    return await instance.async_db_ready


class LTSS_DB(threading.Thread):
    """A threaded LTSS class."""

    def __init__(
        self,
        hass: HomeAssistant,
        uri: str,
        chunk_time_interval: int,
        entity_filter: Callable[[str], bool],
    ) -> None:
        """Initialize the ltss."""
        threading.Thread.__init__(self, name="LTSS")

        self.hass = hass
        self.queue: Any = queue.Queue()
        self.recording_start = dt_util.utcnow()
        self.db_url = uri
        self.chunk_time_interval = chunk_time_interval
        self.async_db_ready = asyncio.Future()
        self.engine: Any = None
        self.run_info: Any = None

        self.entity_filter = entity_filter

        self.get_session = None

    @callback
    def async_initialize(self):
        """Initialize the ltss."""
        self.hass.bus.async_listen(EVENT_STATE_CHANGED, self.event_listener)

    def run(self):
        """Start processing events to save."""
        tries = 1
        connected = False

        while not connected and tries <= 10:
            if tries != 1:
                time.sleep(CONNECT_RETRY_WAIT)
            try:
                self._setup_connection()
                connected = True
                _LOGGER.debug("Connected to ltss database")
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.error(
                    "Error during connection setup: %s (retrying " "in %s seconds)",
                    err,
                    CONNECT_RETRY_WAIT,
                )
                tries += 1

        if not connected:

            @callback
            def connection_failed():
                """Connect failed tasks."""
                self.async_db_ready.set_result(False)
                persistent_notification.async_create(
                    self.hass,
                    "LTSS could not start, please check the log",
                    "LTSS",
                )

            self.hass.add_job(connection_failed)
            return

        shutdown_task = object()
        hass_started = concurrent.futures.Future()

        @callback
        def register():
            """Post connection initialize."""
            self.async_db_ready.set_result(True)

            def shutdown(event):
                """Shut down the ltss."""
                if not hass_started.done():
                    hass_started.set_result(shutdown_task)
                self.queue.put(None)
                self.join()

            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown)

            if self.hass.state == CoreState.running:
                hass_started.set_result(None)
            else:

                @callback
                def notify_hass_started(event):
                    """Notify that hass has started."""
                    hass_started.set_result(None)

                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_START, notify_hass_started
                )

        self.hass.add_job(register)
        result = hass_started.result()

        # If shutdown happened before Home Assistant finished starting
        if result is shutdown_task:
            return

        while True:
            event = self.queue.get()

            if event is None:
                self._close_connection()
                self.queue.task_done()
                return

            tries = 1
            updated = False
            while not updated and tries <= 10:
                if tries != 1:
                    time.sleep(CONNECT_RETRY_WAIT)
                try:
                    with self.get_session() as session:
                        with session.begin():
                            try:
                                row = LTSS.from_event(event)
                                session.add(row)
                            except (TypeError, ValueError):
                                _LOGGER.warning(
                                    "State is not JSON serializable: %s",
                                    event.data.get("new_state"),
                                )

                        updated = True

                except exc.OperationalError as err:
                    _LOGGER.error(
                        "Error in database connectivity: %s. "
                        "(retrying in %s seconds)",
                        err,
                        CONNECT_RETRY_WAIT,
                    )
                    tries += 1

                except exc.SQLAlchemyError:
                    updated = True
                    _LOGGER.exception("Error saving event: %s", event)

            if not updated:
                _LOGGER.error(
                    "Error in database update. Could not save "
                    "after %d tries. Giving up",
                    tries,
                )

            self.queue.task_done()

    @callback
    def event_listener(self, event):
        """Listen for new events and put them in the process queue."""
        # Filer on entity_id
        entity_id = event.data.get(ATTR_ENTITY_ID)
        state = event.data.get("new_state")

        if entity_id is not None and state is not None and state.state != STATE_UNKNOWN:
            if self.entity_filter(entity_id):
                self.queue.put(event)

    def _setup_connection(self):
        """Ensure database is ready to fly."""

        if self.engine is not None:
            self.engine.dispose()

        self.engine = create_engine(
            self.db_url,
            echo=False,
            json_serializer=lambda obj: json.dumps(obj, cls=JSONEncoder),
        )

        inspector = inspect(self.engine)

        with self.engine.connect() as con:
            con = con.execution_options(isolation_level="AUTOCOMMIT")
            available_extensions = {
                row.name: row.installed_version
                for row in con.execute(
                    text("SELECT name, installed_version FROM pg_available_extensions")
                )
            }

            # create table if necessary
            if not inspector.has_table(LTSS.__tablename__):
                self._create_table(available_extensions)

            if "timescaledb" in available_extensions:
                # chunk_time_interval can be adjusted even after first setup
                try:
                    con.execute(
                        text(
                            f"SELECT set_chunk_time_interval('{LTSS.__tablename__}', {self.chunk_time_interval})"
                        )
                    )
                except exc.ProgrammingError as exception:
                    if isinstance(exception.orig, psycopg2.errors.UndefinedTable):
                        # The table does exist but is not a hypertable, not much we can do except log that fact
                        _LOGGER.exception(
                            "TimescaleDB is available as an extension but the LTSS table is not a hypertable!"
                        )
                    else:
                        raise

        # check if table has been set up with location extraction
        if "location" in [
            column_conf["name"]
            for column_conf in inspector.get_columns(LTSS.__tablename__)
        ]:
            # activate location extraction in model/ORM
            LTSS.activate_location_extraction()

        # Migrate to newest schema if required
        check_and_migrate(self.engine)

        self.get_session = scoped_session(sessionmaker(bind=self.engine))

    def _create_table(self, available_extensions):
        _LOGGER.info("Creating LTSS table")
        with self.engine.connect() as con:
            con = con.execution_options(isolation_level="AUTOCOMMIT")
            if "postgis" in available_extensions:
                _LOGGER.info(
                    "PostGIS extension is available, activating location extraction..."
                )
                con.execute(text("CREATE EXTENSION IF NOT EXISTS postgis CASCADE"))

                # activate location extraction in model/ORM to add necessary column when calling create_all()
                LTSS.activate_location_extraction()

            Base.metadata.create_all(self.engine)

            if "timescaledb" in available_extensions:
                _LOGGER.info(
                    "TimescaleDB extension is available, creating hypertable..."
                )
                con.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))

                # Create hypertable
                con.execute(
                    text(
                        f"""SELECT create_hypertable(
                                '{LTSS.__tablename__}',
                                'time',
                                if_not_exists => TRUE);"""
                    )
                )

    def _close_connection(self):
        """Close the connection."""
        self.engine.dispose()
        self.engine = None
        self.get_session = None
