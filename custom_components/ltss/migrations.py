import logging

from sqlalchemy import inspect, text

from .models import LTSS, LTSS_ATTRIBUTES

_LOGGER = logging.getLogger(__name__)


def check_and_migrate(engine):
    
    # Inspect the DB
    inspector = inspect(engine)
    indexes = inspector.get_indexes(LTSS.__tablename__)

    def index_exists(index_name):
        matches = [idx for idx in indexes if idx["name"] == index_name]
        return True if matches else False

    def function_exists(func_name):
        with engine.connect() as conn:
            res = conn.execute(text(f"SELECT true FROM pg_catalog.pg_proc WHERE proname='{func_name}'"))
            for _ in res:
                return True
        return False

    def trigger_exists(trg_name):
        with engine.connect() as conn:
            res = conn.execute(text(f"SELECT true FROM pg_catalog.pg_trigger WHERE tgname='{trg_name}'"))
            for _ in res:
                return True
        return False

    fn_ref_count_increment_exists = function_exists('ltss_hass_attributes_ref_count_increment')
    fn_ref_count_decrement_exists = function_exists('ltss_hass_attributes_ref_count_decrement')
    trg_ref_count_increment_exists = trigger_exists('trg_ltss_hass_attributes_ref_count_increment')
    trg_ref_count_decrement_exists = trigger_exists('trg_ltss_hass_attributes_ref_count_decrement')
    if inspector.has_table('ltss'):
        # If we find an old column, not yet transformed into JSONB, we ignore it and force the cast on migration
        # to the new two table schema. No need to run the transform beforehand.
        if not inspector.has_table('ltss_hass') and not inspector.has_table('ltss_hass_attributes'):
            _LOGGER.warning(
                'Migrating your old LTSS table to the new 2 table schema, this might take a couple of minutes!'
            )

            with engine.begin() as con:
                con.execute(text('ALTER TABLE ltss RENAME TO ltss_old'))
                con.execute(
                    text(
                        f"""INSERT INTO {LTSS.__tablename__} (time, entity_id, state, location, attributes_key)
                               SELECT
                                 l.time,
                                 l.entity_id,
                                 l.state,
                                 l.location,
                                 CASE
                                   WHEN l.attributes IS NOT NULL THEN
                                     text2ltree(l.entity_id || '.' ||
                                       encode(
                                         sha256(regexp_replace(l.attributes::text, '\\\\n', '', 'ng')::bytea), 'hex')
                                       )
                                 END
                               FROM ltss_old l ON CONFLICT DO NOTHING"""
                    )
                )
                con.execute(
                    text(
                        f"""INSERT INTO {LTSS_ATTRIBUTES.__tablename__} (attributes_key, attributes)
                               SELECT text2ltree(l.entity_id || '.' ||
                                        encode(
                                          sha256(regexp_replace(l.attributes::text, '\\\\n', '', 'ng')::bytea), 'hex')
                                        ),
                                      l.attributes::jsonb
                               FROM ltss_old l WHERE l.attributes IS NOT NULL ON CONFLICT DO NOTHING"""
                    )
                )
                con.execute(
                    text(
                        f"""create or replace view ltss as
                                select
                                  row_number() over (rows unbounded preceding) as id,
                                  l.time,
                                  l.entity_id,
                                  l.state,
                                  l.location,
                                  a.attributes
                                from {LTSS.__tablename__}
                                left join {LTSS_ATTRIBUTES.__tablename__}
                                  on l.attributes_key is not null
                                 and l.attributes_key = a.attributes_key"""
                    )
                )
                if not fn_ref_count_increment_exists:
                    con.execute(
                        text(
                            f"""create or replace function ltss_hass_attributes_ref_count_increment() returns trigger
                                  language plpgsql as $$
                                begin
                                  update {LTSS_ATTRIBUTES.__tablename__}
                                     set ref_count = ref_count + 1
                                  where attributes_key = NEW.attributes_key;
                                  return null;
                                end; $$"""
                        )
                    )
                if not fn_ref_count_decrement_exists:
                    con.execute(
                        text(
                            f"""create or replace function ltss_hass_attributes_ref_count_decrement() returns trigger
                                  language plpgsql as $$
                               declare
                                 remaining bigint;
                               begin
                                 if OLD.attributes_key is null then
                                   return null;
                                 end if;

                                 update {LTSS_ATTRIBUTES.__tablename__}
                                    set ref_count = ref_count - 1
                                 where attributes_key = OLD.attributes_key
                                 returning ref_count
                                 into remaining;

                                 if remaining <= 0 then
                                   -- orphaned attributes row, deleting
                                   delete from {LTSS_ATTRIBUTES.__tablename__}
                                   where attributes_key = OLD.attributes_key;
                                 end if;
                               end; $$"""
                        )
                    )
                if not trg_ref_count_increment_exists:
                    con.execute(text(
                        f"""create trigger trg_ltss_hass_attributes_ref_count_increment
                            after insert or update on {LTSS.__tablename__}
                            for each row execute function ltss_hass_attributes_ref_count_increment()"""
                    ))
                if not trg_ref_count_decrement_exists:
                    con.execute(text(
                        f"""create trigger trg_ltss_hass_attributes_ref_count_decrement
                            after delete on {LTSS.__tablename__}
                            for each row execute function ltss_hass_attributes_ref_count_decrement()"""
                    ))
                # Not yet executed automatically:
                # con.execute(text("DROP TABLE ltss_old"))
                _LOGGER.warning(
                    'The old table has been renamed to \'ltss_old\' and all data is migrated. The old table is not ' +
                    'deleted though. If everything works please run the following command manually: \n' +
                    'DROP TABLE ltss_old;'
                )
                con.commit()
                _LOGGER.info('Migration completed successfully!')

