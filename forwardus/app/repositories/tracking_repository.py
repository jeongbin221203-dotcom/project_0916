"""Tracking event persistence."""

from __future__ import annotations

from app.models import Shipment, TrackingEvent


def list_events(shipment: Shipment) -> list[TrackingEvent]:
    return TrackingEvent.query.filter_by(shipment_pk=shipment.id).order_by(
        TrackingEvent.event_time, TrackingEvent.id
    ).all()


def add_event(shipment: Shipment, **fields) -> TrackingEvent:
    event = TrackingEvent(**fields)
    shipment.tracking_events.append(event)
    return event
