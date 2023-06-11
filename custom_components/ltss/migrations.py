import logging

from sqlalchemy import inspect, text, Text

from .models import LTSS, LTSS_attributes_index, LTSS_entityid_time_composite_index

_LOGGER = logging.getLogger(__name__)


def check_and_migrate(engine):
    # Inspect the DB
    iengine = inspect(engine)
    columns = iengine.get_columns(LTSS.__tablename__)
    indexes = iengine.get_indexes(LTSS.__tablename__)

    def index_exists(index_name):
        matches = [idx for idx in indexes if idx["name"] == index_name]
        return True if matches else False

    # Attributes column Text -> JSONB
    attributes_column = next(col for col in columns if col["name"] == "attributes")
    if isinstance(attributes_column["type"], Text):
        _LOGGER.warning(
            "Migrating you LTSS table to the latest schema, this might take a couple of minutes!"
        )
        migrate_attributes_text_to_jsonb(engine)
        _LOGGER.info("Migration completed successfully!")

    # Attributes Index?
    if not index_exists("ltss_attributes_idx"):
        _LOGGER.warning(
            "Creating an index for the attributes column, this might take a couple of minutes!"
        )
        create_attributes_index(engine)
        _LOGGER.info("Index created successfully!")

    # entity_id and time composite Index?
    if not index_exists("ltss_entityid_time_composite_idx"):
        _LOGGER.warning(
            "Creating a composite index over entity_id and time columns, this might take a couple of minutes!"
        )
        create_entityid_time_index(engine)
        _LOGGER.info("Index created successfully!")

        if index_exists("ix_ltss_entity_id"):
            _LOGGER.warning("Index on entity_id no longer needed, dropping...")
            drop_entityid_index(engine)

    # id column?
    if any(col["name"] == "id" for col in columns):
        _LOGGER.warning(
            "Migrating you LTSS table to the latest schema, this might take a couple of minutes!"
        )
        remove_id_column(engine)


def migrate_attributes_text_to_jsonb(engine):
    with engine.connect() as con:
        _LOGGER.info("Migrating attributes column from type text to type JSONB")
        con.execute(
            text(
                f"""ALTER TABLE {LTSS.__tablename__} 
            ALTER COLUMN attributes TYPE JSONB USING attributes::JSONB;"""
            ).execution_options(autocommit=True)
        )


def create_attributes_index(engine):
    _LOGGER.info("Creating GIN index on the attributes column")
    LTSS_attributes_index.create(bind=engine)


def create_entityid_time_index(engine):
    _LOGGER.info("Creating composite index over entity_id and time columns")
    LTSS_entityid_time_composite_index.create(bind=engine)


def drop_entityid_index(engine):
    with engine.connect() as con:
        con.execute(
            text(f"""DROP INDEX ix_ltss_entity_id;""").execution_options(
                autocommit=True
            )
        )


def remove_id_column(engine):
    with engine.begin() as con:
        con.execute(
            text(
                f"""ALTER TABLE {LTSS.__tablename__}
                    DROP CONSTRAINT {LTSS.__tablename__}_pkey CASCADE,
                    ADD PRIMARY KEY(time,entity_id);"""
            )
        )
        con.execute(
            text(
                f"""ALTER TABLE {LTSS.__tablename__}
                    DROP COLUMN id"""
            )
        )
        con.commit()
    _LOGGER.info("Migration completed successfully!")
