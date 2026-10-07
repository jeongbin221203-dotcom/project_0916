"""Buyer (consignee) model."""

from __future__ import annotations

from app.extensions import db, utc_now


class Buyer(db.Model):
    __tablename__ = "buyers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    country = db.Column(db.String(100), nullable=False, default="")
    address = db.Column(db.String(500), nullable=False, default="")
    contact_email = db.Column(db.String(200), nullable=False, default="")
    # 이 바이어를 등록한 회원. 같은 이름·나라라도 회원마다 따로 둡니다 — 전에는 전역 한 줄이라
    # 다른 회원이 같은 바이어를 쓰면 주소·이메일이 서로 덮어써졌습니다(전수 점검 1회차).
    user_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    shipments = db.relationship("Shipment", back_populates="buyer")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "country": self.country,
            "address": self.address,
            "contact_email": self.contact_email,
        }
