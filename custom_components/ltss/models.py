"""Models for SQLAlchemy."""
import json
from datetime import datetime
import logging

from sqlalchemy import (
    Column,
    BigInteger,
    DateTime,
    String,
    Text,
)

from sqlalchemy.schema import Index
from sqlalchemy.dialects.postgresql import JSONB
from geoalchemy2 import Geometry
from sqlalchemy.orm import column_property, declarative_base

# SQLAlchemy Schema
# pylint: disable=invalid-name
Base = declarative_base()

_LOGGER = logging.getLogger(__name__)


class LTSS(Base):  # type: ignore
    """State change history."""

    __tablename__ = "ltss"
    time = Column(DateTime(timezone=True), default=datetime.utcnow, primary_key=True)
    entity_id = Column(String(255), primary_key=True)
    state = Column(String(255), index=True)
    attributes = Column(JSONB)
    location = None  # when not activated, no location column will be added to the table/database

    @classmethod
    def activate_location_extraction(cls):
        """
        Method to activate proper Postgis handling of location.

        After activation, this cannot be deactivated (due to how the underlying SQLAlchemy ORM works).
        """
        cls.location = column_property(Column(Geometry("POINT", srid=4326)))

    @classmethod
    def from_event(cls, event):
        """Create object from a state_changed event."""
        entity_id = event.data["entity_id"]
        state = event.data.get("new_state")

        attrs = dict(state.attributes)

        location = None

        if (
            cls.location
        ):  # if the additional column exists, use Postgis' Geometry/Point data structure
            lat = attrs.pop("latitude", None)
            lon = attrs.pop("longitude", None)

            location = f"SRID=4326;POINT({lon} {lat})" if lon and lat else None

        row = LTSS(
            entity_id=entity_id,
            time=event.time_fired,
            state=state.state,
            attributes=attrs,
            location=location,
        )

        return row


LTSS_attributes_index = Index(
    "ltss_attributes_idx", LTSS.attributes, postgresql_using="gin"
)
LTSS_entityid_time_composite_index = Index(
    "ltss_entityid_time_composite_idx", LTSS.entity_id, LTSS.time.desc()
)
