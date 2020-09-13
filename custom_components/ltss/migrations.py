import logging

from sqlalchemy import inspect, text, Text

from .models import LTSS, LTSS_attributes_index

_LOGGER = logging.getLogger(__name__)

def check_and_migrate(engine):
    
    #Inspect the DB
    iengine = inspect(engine)
    
    # Attributes column Text -> JSONB
    columns = iengine.get_columns(LTSS.__tablename__)
    attributes_column = next(col for col in columns if col["name"] == 'attributes')
    
    if isinstance(attributes_column['type'], Text):
        _LOGGER.warning('Migrating you LTSS table to the latest schema, this might take a couple of minutes!')
        migrate_attributes_text_to_jsonb(engine)
        _LOGGER.info('Migration completed successfully!')
        
        
    # Attributes Index?
    indexes = iengine.get_indexes(LTSS.__tablename__)
    
    if not [idx for idx in indexes if idx["name"] == 'ltss_attributes_idx']:
        _LOGGER.warning('Creating an index for the attributes column, this might take a couple of minutes!')
        create_attributes_index(engine)
        _LOGGER.info('Index created successfully!')

def migrate_attributes_text_to_jsonb(engine):
    
    with engine.connect() as con:
        
        _LOGGER.info("Migrating attributes column from type text to type JSONB")
        con.execute(text(
            f"""ALTER TABLE {LTSS.__tablename__} 
            ALTER COLUMN attributes TYPE JSONB USING attributes::JSONB;"""
        ).execution_options(autocommit=True))
        
def create_attributes_index(engine):
        
        _LOGGER.info("Creating GIN index on the attributes column")
        LTSS_attributes_index.create(bind=engine)
