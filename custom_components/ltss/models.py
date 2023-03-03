"""Models for SQLAlchemy."""
from datetime import datetime, date
import logging

from sqlalchemy import (
    Column,
    DateTime,
    Text,
    BIGINT
)

from sqlalchemy.schema import Index
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy_utils import LtreeType, Ltree
from geoalchemy2 import Geometry
from sqlalchemy.orm import column_property, declarative_base
import json
import hashlib
import re

# SQLAlchemy Schema
# pylint: disable=invalid-name
Base = declarative_base()

_LOGGER = logging.getLogger(__name__)


def datetime_json_encoder(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError("Type %s not serializable" % type(o))


class LTSS(Base):  # type: ignore
    """State change history."""

    __tablename__ = "ltss_hass"
    time = Column(DateTime(timezone=True), default=datetime.utcnow, primary_key=True)
    entity_id = Column(Text, primary_key=True)
    state = Column(Text)
    attributes_key = Column(LtreeType)
    location = None  # when not activated, no location column will be added to the table/database

    @classmethod
    def activate_location_extraction(cls):
        """
        Method to activate proper Postgis handling of location.

        After activation, this cannot be deactivated (due to how the underlying SQLAlchemy ORM works).
        """
        cls.location = column_property(Column(Geometry('POINT', srid=4326)))

    @classmethod
    def from_event(cls, event):
        """Create object from a state_changed event."""
        entity_id = event.data["entity_id"]
        state = event.data.get("new_state")

        attrs = dict(state.attributes)

        location = None

        if cls.location:  # if the additional column exists, use Postgis' Geometry/Point data structure
            lat = attrs.pop('latitude', None)
            lon = attrs.pop('longitude', None)

            location = f'SRID=4326;POINT({lon} {lat})' if lon and lat else None

        state_json = json.dumps(attrs, default=datetime_json_encoder)
        attributes_key_data = re.sub(r'\\n', '', state_json)
        attributes_key = Ltree(f"{entity_id}.{hashlib.sha256(attributes_key_data.encode()).hexdigest()}")

        row = LTSS(
            entity_id=entity_id,
            time=event.time_fired,
            state=state.state,
            attributes_key=attributes_key,
            location=location
        )

        attributes_row = {
            "attributes_key": attributes_key,
            "attributes": state_json
        }

        return row, attributes_row


LTSS_time_entityid_composite_index = Index(
    'ltss_hass_time_entity_id_idx', LTSS.time.desc(), LTSS.entity_id, postgresql_using='btree'
)


class LTSS_ATTRIBUTES(Base):
    __tablename__ = f'{LTSS.__tablename__}_attributes'
    attributes_key = Column(LtreeType)
    attributes = Column(JSONB)
    ref_count = Column(BIGINT)
    __table_args__ = (
        ExcludeConstraint((attributes_key, '=')),
    )
    __mapper_args__ = {
        "primary_key": [attributes_key]
    }


LTSS_ATTRIBUTES_attributes_index = Index(
    'ltss_hass_attributes_attributes_idx', LTSS_ATTRIBUTES.attributes, postgresql_using='gin'
)
