"""Tracking event model (also stores ETA change exceptions)."""

from __future__ import annotations

from app.extensions import db, utc_now

TRACKING_EVENTS = [
    "booking_confirmed",
    "container_pickup",
    "gate_in",
    "customs_cleared",
    "departed",
    "in_transit",
    "arrived",
    "import_customs",
    "out_for_delivery",
    "delivered",
]

EVENT_LABELS = {
    "booking_confirmed": "Booking Confirmed",
    "container_pickup": "Container Pick Up",
    "gate_in": "Gate In",
    "customs_cleared": "Customs Cleared",
    "departed": "Departed",
    "in_transit": "In Transit",
    "arrived": "Arrived",
    "import_customs": "Import Customs",
    "out_for_delivery": "Out for Delivery",
    "delivered": "Delivered",
    "eta_changed": "ETA Changed",
}

TRACKING_SOURCES = ["api", "mock", "manual"]


class TrackingEvent(db.Model):
    __tablename__ = "tracking_events"

    id = db.Column(db.Integer, primary_key=True)
    shipment_pk = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=False)
    event_code = db.Column(db.String(40), nullable=False)
    event_time = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200), nullable=False, default="")
    description = db.Column(db.String(500), nullable=False, default="")
    source = db.Column(db.String(20), nullable=False)
    is_exception = db.Column(db.Boolean, nullable=False, default=False)
    previous_eta = db.Column(db.Date, nullable=True)
    new_eta = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    shipment = db.relationship("Shipment", back_populates="tracking_events")

    @property
    def label(self) -> str:
        return EVENT_LABELS.get(self.event_code, self.event_code)
