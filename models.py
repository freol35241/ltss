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
from geoalchemy2 import Geometry
from sqlalchemy.ext.declarative import declarative_base

from homeassistant.helpers.json import JSONEncoder

# SQLAlchemy Schema
# pylint: disable=invalid-name
Base = declarative_base()

_LOGGER = logging.getLogger(__name__)


class LTSS(Base):  # type: ignore
    """State change history."""

    __tablename__ = "ltss"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    time = Column(DateTime(timezone=True), default=datetime.utcnow, primary_key=True)
    entity_id = Column(String(255), index=True)
    state = Column(String(255), index=True)
    attributes = Column(Text)
    location = Column(Geometry('POINT', srid=4326))

    @staticmethod
    def from_event(event):
        """Create object from a state_changed event."""
        entity_id = event.data["entity_id"]
        state = event.data.get("new_state")

        attrs = dict(state.attributes)
        lat = attrs.pop('latitude', None)
        lon = attrs.pop('longitude', None)

        row = LTSS(
            entity_id=entity_id,
            time=event.time_fired,
            state=state.state,
            attributes=json.dumps(attrs, cls=JSONEncoder),
            location=f'SRID=4326;POINT({lon} {lat})' if lon and lat else None
        )

        return row
