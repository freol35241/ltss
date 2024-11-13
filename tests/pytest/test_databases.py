import time
from time import sleep

import docker as docker
import pytest
from sqlalchemy import text

from custom_components.ltss import LTSS_DB, LTSS


class TestDBSetup:
    @pytest.fixture(autouse=True)
    def reset_LTSS(self):
        # needed because the tests might change the underlying SQLAlchemy models and that needs to be reset
        cols = [col for col in LTSS.__table__._columns if col.name == "location"]
        if len(cols):
            LTSS.__table__._columns.remove(cols[0])

    @staticmethod
    def db_container(image):
        client = docker.from_env()
        container = client.containers.run(
            image,
            ports={5432: None},
            environment=["POSTGRES_HOST_AUTH_METHOD=trust"],
            detach=True,
            auto_remove=True,
        )

        start_time = time.time()

        # because a newly created postgresql container (with empty data directory) will immediately restart,
        # we have to wait for the second message to be sure postgres is ready for connections
        while (
            container.logs().count(b"database system is ready to accept connections")
            != 2
        ):
            if start_time + 30 <= time.time():  # timeout
                raise RuntimeError("Container (or database) won't start.")

            sleep(1)

        # to refresh the port mapping
        container.reload()
        return container

    @staticmethod
    def ltss_init_wrapper(container):
        return LTSS_DB(
            None,
            "postgresql://postgres@localhost:"
            + container.ports["5432/tcp"][0]["HostPort"],
            123,
            3.0,
            10,
            lambda x: False,
        )

    def test_lite(self):
        container = self.db_container("postgres:latest")

        try:
            ltss = self.ltss_init_wrapper(container)
            ltss._setup_connection()

            with ltss.engine.connect() as con:
                assert self._has_columns(con)
                assert not self._has_location_column(con)
        finally:
            container.stop()

    @pytest.mark.parametrize(
        "version",
        [
            "latest-pg9.6",
            "latest-pg10",
            "latest-pg11",
            "latest-pg12",
            "latest-pg13",
            "latest-pg14",
        ],
    )
    def test_timescaledb(self, version):
        container = self.db_container(f"timescale/timescaledb:{version}")
        try:
            ltss = self.ltss_init_wrapper(container)
            ltss._setup_connection()

            with ltss.engine.connect() as con:
                assert self._is_hypertable(con)
                assert self._has_columns(con)
        finally:
            container.stop()

    def test_default_db(self):
        # this is an old and outdated image but should be sufficient
        container = self.db_container("timescale/timescaledb-postgis:latest-pg12")

        try:
            ltss = self.ltss_init_wrapper(container)
            ltss._setup_connection()

            with ltss.engine.connect() as con:
                assert self._is_hypertable(con)
                assert self._has_columns(con)
                assert self._has_location_column(con)
        finally:
            container.stop()

    @staticmethod
    def _is_hypertable(con):
        timescaledb_version = con.execute(
            text(
                "SELECT installed_version "
                "FROM pg_available_extensions "
                "WHERE name = 'timescaledb'"
            )
        ).scalar()

        # timescaledb's table/column name changed with v2
        if int(timescaledb_version.split(".")[0]) >= 2:
            query = f"SELECT 1 FROM timescaledb_information.hypertables "
            f"WHERE hypertable_name = '{LTSS.__tablename__}'"
        else:
            query = f"SELECT 1 FROM timescaledb_information.hypertable "
            f"WHERE table_name = '{LTSS.__tablename__}'"

        return 1 == con.execute(text(query)).rowcount

    @staticmethod
    def _has_columns(con):
        return (
            4
            <= con.execute(
                text(
                    f"SELECT COLUMN_NAME\
        FROM information_schema.columns\
        WHERE table_name = '{LTSS.__tablename__}'"
                )
            ).rowcount
        )

    @staticmethod
    def _has_location_column(con):
        return (
            1
            == con.execute(
                text(
                    f"SELECT *\
        FROM information_schema.columns\
        WHERE table_name = '{LTSS.__tablename__}'\
        AND COLUMN_NAME = 'location'"
                )
            ).rowcount
        )
