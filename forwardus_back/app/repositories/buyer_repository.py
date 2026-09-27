"""Buyer persistence."""

from __future__ import annotations

from app.extensions import db
from app.models import Buyer


def list_buyers() -> list[Buyer]:
    return Buyer.query.order_by(Buyer.name).all()


def get_or_create(name: str, country: str, address: str, contact_email: str) -> Buyer:
    """Reuse a buyer with the same name and country so history stays grouped."""

    buyer = Buyer.query.filter_by(name=name, country=country).first()
    if buyer:
        if address:
            buyer.address = address
        if contact_email:
            buyer.contact_email = contact_email
        return buyer
    buyer = Buyer(name=name, country=country, address=address, contact_email=contact_email)
    db.session.add(buyer)
    db.session.flush()
    return buyer
