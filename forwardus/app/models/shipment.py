"""Shipment model — the hub every other record links to."""

from __future__ import annotations

from app.extensions import db, utc_now

SHIPMENT_STATUSES = [
    "draft",
    "quoted",
    "booked",
    "departed",
    "in_transit",
    "arrived",
    "delivered",
    "closed",
    "cancelled",
]

STATUS_LABELS = {
    "draft": "작성 중",
    "quoted": "견적 완료",
    "booked": "부킹 완료",
    "departed": "출항",
    "in_transit": "운송 중",
    "arrived": "도착",
    "delivered": "배송 완료",
    "closed": "종료",
    "cancelled": "취소",
}


class Shipment(db.Model):
    __tablename__ = "shipments"

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.String(20), nullable=False, unique=True, index=True)
    project_name = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, nullable=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"), nullable=True)

    trade_type = db.Column(db.String(10), nullable=False, default="export")
    transport_mode = db.Column(db.String(10), nullable=False)  # SEA | AIR
    sea_mode = db.Column(db.String(10), nullable=True)  # FCL | LCL | None

    origin_code = db.Column(db.String(10), nullable=False)
    origin_name = db.Column(db.String(200), nullable=False, default="")
    destination_code = db.Column(db.String(10), nullable=False)
    destination_name = db.Column(db.String(200), nullable=False, default="")
    destination_country = db.Column(db.String(100), nullable=False, default="")

    requested_departure_date = db.Column(db.Date, nullable=True)
    cargo_ready_date = db.Column(db.Date, nullable=True)
    etd = db.Column(db.Date, nullable=True)
    eta = db.Column(db.Date, nullable=True)
    planned_eta = db.Column(db.Date, nullable=True)
    buyer_required_date = db.Column(db.Date, nullable=True)

    incoterms = db.Column(db.String(3), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    invoice_value = db.Column(db.Float, nullable=False)

    exporter_name = db.Column(db.String(200), nullable=False, default="")
    exporter_address = db.Column(db.String(500), nullable=False, default="")
    notify_party = db.Column(db.String(300), nullable=False, default="SAME AS CONSIGNEE")

    # 관세사에게 넘기는 수출신고 자료에만 쓰는 칸입니다.
    # 사업자등록번호는 신고서에 반드시 들어가는데 운송에는 쓰이지 않아 따로 둡니다.
    exporter_business_no = db.Column(db.String(20), nullable=False, default="")
    customs_trade_kind = db.Column(db.String(4), nullable=False, default="11")
    customs_payment_method = db.Column(db.String(4), nullable=False, default="TT")
    country_of_origin = db.Column(db.String(60), nullable=False, default="KR · 대한민국")

    carrier = db.Column(db.String(100), nullable=True)
    vessel_or_flight = db.Column(db.String(100), nullable=True)
    transit_days = db.Column(db.Integer, nullable=True)
    is_direct = db.Column(db.Boolean, nullable=True)
    freight_usd = db.Column(db.Float, nullable=True)
    schedule_source = db.Column(db.String(20), nullable=True)

    status = db.Column(db.String(20), nullable=False, default="draft")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    buyer = db.relationship("Buyer", back_populates="shipments")
    cargos = db.relationship("Cargo", back_populates="shipment", cascade="all, delete-orphan",
                             order_by="Cargo.line_no")

    @property
    def cargo(self):
        """대표 화물(첫 품목). 서류·요약처럼 한 건만 쓰는 곳에서 씁니다."""

        return self.cargos[0] if self.cargos else None
    documents = db.relationship("TradeDocument", back_populates="shipment", cascade="all, delete-orphan")
    requirement_documents = db.relationship(
        "RequirementDocument", back_populates="shipment", cascade="all, delete-orphan",
        order_by="RequirementDocument.uploaded_at")
    tracking_events = db.relationship(
        "TrackingEvent",
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="TrackingEvent.event_time",
    )
    costs = db.relationship("ShipmentCost", back_populates="shipment", cascade="all, delete-orphan")
    payments = db.relationship(
        "Payment", back_populates="shipment", cascade="all, delete-orphan", order_by="Payment.due_date"
    )

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def mode_label(self) -> str:
        if self.transport_mode == "AIR":
            return "AIR"
        return f"SEA · {self.sea_mode}" if self.sea_mode else "SEA"

    @property
    def total_cost_krw(self) -> int:
        return int(sum(cost.krw_amount for cost in self.costs))

    @property
    def delay_days(self) -> int:
        if self.eta and self.planned_eta:
            return (self.eta - self.planned_eta).days
        return 0

    def to_dict(self) -> dict:
        def _iso(value):
            return value.isoformat() if value else None

        return {
            "shipment_id": self.shipment_id,
            "project_name": self.project_name,
            "buyer": self.buyer.to_dict() if self.buyer else None,
            "trade_type": self.trade_type,
            "transport_mode": self.transport_mode,
            "sea_mode": self.sea_mode,
            "origin_code": self.origin_code,
            "origin_name": self.origin_name,
            "destination_code": self.destination_code,
            "destination_name": self.destination_name,
            "destination_country": self.destination_country,
            "cargo_ready_date": _iso(self.cargo_ready_date),
            "etd": _iso(self.etd),
            "eta": _iso(self.eta),
            "planned_eta": _iso(self.planned_eta),
            "buyer_required_date": _iso(self.buyer_required_date),
            "incoterms": self.incoterms,
            "currency": self.currency,
            "invoice_value": self.invoice_value,
            "carrier": self.carrier,
            "vessel_or_flight": self.vessel_or_flight,
            "transit_days": self.transit_days,
            "freight_usd": self.freight_usd,
            "schedule_source": self.schedule_source,
            "status": self.status,
            "cargo": self.cargo.to_dict() if self.cargo else None,
            "cargos": [item.to_dict() for item in self.cargos],
            "total_cost_krw": self.total_cost_krw,
        }
