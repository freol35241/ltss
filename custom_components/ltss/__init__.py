"""Support for recording details."""
import asyncio
import concurrent.futures
from contextlib import contextmanager
from datetime import datetime, timedelta
import logging
import queue
import threading
import time
from typing import Any, Dict, Optional

import voluptuous as vol
from sqlalchemy import exc, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import scoped_session, sessionmaker

from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_DOMAINS,
    CONF_ENTITIES,
    CONF_EXCLUDE,
    CONF_INCLUDE,
    EVENT_HOMEASSISTANT_START,
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_CHANGED,
    STATE_UNKNOWN
)
from homeassistant.components import persistent_notification
from homeassistant.core import CoreState, HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entityfilter import generate_filter
from homeassistant.helpers.typing import ConfigType
import homeassistant.util.dt as dt_util

from sqlalchemy import text

from .models import Base, LTSS
from .migrations import check_and_migrate

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ltss"

CONF_DB_URL = "db_url"

CONNECT_RETRY_WAIT = 3

FILTER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_EXCLUDE, default={}): vol.Schema(
            {
                vol.Optional(CONF_DOMAINS): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(CONF_ENTITIES): cv.entity_ids,
            }
        ),
        vol.Optional(CONF_INCLUDE, default={}): vol.Schema(
            {
                vol.Optional(CONF_DOMAINS): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(CONF_ENTITIES): cv.entity_ids,
            }
        ),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
		DOMAIN: FILTER_SCHEMA.extend(
			{
				vol.Required(CONF_DB_URL): cv.string,
			}
		)
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up LTSS."""
    conf = config[DOMAIN]

    db_url = conf.get(CONF_DB_URL)
    include = conf.get(CONF_INCLUDE, {})
    exclude = conf.get(CONF_EXCLUDE, {})
    instance = LTSS_DB(
        hass=hass,
        uri=db_url,
        include=include,
        exclude=exclude,
    )
    instance.async_initialize()
    instance.start()

    return await instance.async_db_ready

@contextmanager
def session_scope(*, session=None):
    """Provide a transactional scope around a series of operations."""

    if session is None:
        raise RuntimeError("Session required")

    need_rollback = False
    try:
        yield session
        if session.transaction:
            need_rollback = True
            session.commit()
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error("Error executing query: %s", err)
        if need_rollback:
            session.rollback()
        raise
    finally:
        session.close()


class LTSS_DB(threading.Thread):
    """A threaded LTSS class."""

    def __init__(
        self,
        hass: HomeAssistant,
        uri: str,
        include: Dict,
        exclude: Dict,
    ) -> None:
        """Initialize the ltss."""
        threading.Thread.__init__(self, name="LTSS")

        self.hass = hass
        self.queue: Any = queue.Queue()
        self.recording_start = dt_util.utcnow()
        self.db_url = uri
        self.async_db_ready = asyncio.Future()
        self.engine: Any = None
        self.run_info: Any = None

        self.entity_filter = generate_filter(
            include.get(CONF_DOMAINS, []),
            include.get(CONF_ENTITIES, []),
            exclude.get(CONF_DOMAINS, []),
            exclude.get(CONF_ENTITIES, []),
        )

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
                    with session_scope(session=self.get_session()) as session:
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

        self.engine = create_engine(self.db_url, echo=False)

        # Make sure TimescaleDB  and PostGIS extensions are loaded
        with self.engine.connect() as con:
            con.execute(
                text("CREATE EXTENSION IF NOT EXISTS postgis CASCADE"
                ).execution_options(autocommit=True))
            con.execute(
                text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"
                ).execution_options(autocommit=True))

        # Create all tables if not exists
        Base.metadata.create_all(self.engine)

        # Create hypertable
        with self.engine.connect() as con:
            con.execute(text(f"""SELECT create_hypertable(
                        '{LTSS.__tablename__}', 
                        'time', 
                        chunk_time_interval => interval '1 month', 
                        if_not_exists => TRUE);""").execution_options(autocommit=True))
            
        # Migrate to newest schema if required
        check_and_migrate(self.engine)
            
        self.get_session = scoped_session(sessionmaker(bind=self.engine))

    def _close_connection(self):
        """Close the connection."""
        self.engine.dispose()
        self.engine = None
        self.get_session = None
