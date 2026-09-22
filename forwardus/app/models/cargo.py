"""Cargo model holding user input and calculated freight units."""

from __future__ import annotations

from app.extensions import db


class Cargo(db.Model):
    __tablename__ = "cargos"

    id = db.Column(db.Integer, primary_key=True)
    shipment_pk = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=False)
    # 화물이 여러 건일 때 입력한 순서를 지킵니다.
    line_no = db.Column(db.Integer, nullable=False, default=1)

    product_description = db.Column(db.String(300), nullable=False)
    hs_code = db.Column(db.String(20), nullable=False, default="")
    package_type = db.Column(db.String(40), nullable=False, default="carton")

    length_cm = db.Column(db.Float, nullable=False)
    width_cm = db.Column(db.Float, nullable=False)
    height_cm = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    weight_per_package_kg = db.Column(db.Float, nullable=False)
    net_weight_kg = db.Column(db.Float, nullable=True)

    # 품목별 금액. 송장의 Amount 칸이 되고, 더하면 Invoice Value가 됩니다.
    unit_price = db.Column(db.Float, nullable=True)
    amount = db.Column(db.Float, nullable=True)

    # 단가의 기준. 비어 있으면 예전처럼 포장 개수(quantity)가 기준입니다.
    # 적혀 있으면 단가는 unit_quantity 기준이고 송장에는 "2,000 PCS × 3.20"으로
    # 찍힙니다. quantity(포장 개수)는 포장명세서에 씁니다.
    unit_quantity = db.Column(db.Float, nullable=True)
    price_unit = db.Column(db.String(10), nullable=False, default="")
    units_per_package = db.Column(db.Float, nullable=True)

    # 위험물이면 UN번호와 급(class)이 모든 운송 서류의 기준이 됩니다.
    is_dangerous = db.Column(db.Boolean, nullable=False, default=False)
    un_number = db.Column(db.String(10), nullable=False, default="")
    dg_class = db.Column(db.String(5), nullable=False, default="")
    packing_group = db.Column(db.String(5), nullable=False, default="")
    proper_shipping_name = db.Column(db.String(200), nullable=False, default="")

    total_cbm = db.Column(db.Float, nullable=False)
    total_weight_kg = db.Column(db.Float, nullable=False)
    revenue_ton = db.Column(db.Float, nullable=False)
    chargeable_weight_kg = db.Column(db.Float, nullable=False)
    container_type = db.Column(db.String(10), nullable=True)
    container_quantity = db.Column(db.Integer, nullable=True)

    shipment = db.relationship("Shipment", back_populates="cargos")

    def to_dict(self) -> dict:
        return {
            "product_description": self.product_description,
            "hs_code": self.hs_code,
            "package_type": self.package_type,
            "is_dangerous": self.is_dangerous,
            "un_number": self.un_number,
            "dg_class": self.dg_class,
            "packing_group": self.packing_group,
            "proper_shipping_name": self.proper_shipping_name,
            "length_cm": self.length_cm,
            "width_cm": self.width_cm,
            "height_cm": self.height_cm,
            "quantity": self.quantity,
            "weight_per_package_kg": self.weight_per_package_kg,
            "net_weight_kg": self.net_weight_kg,
            "unit_price": self.unit_price,
            "amount": self.amount,
            "unit_quantity": self.unit_quantity,
            "price_unit": self.price_unit,
            "units_per_package": self.units_per_package,
            "total_cbm": self.total_cbm,
            "total_weight_kg": self.total_weight_kg,
            "revenue_ton": self.revenue_ton,
            "chargeable_weight_kg": self.chargeable_weight_kg,
            "container_type": self.container_type,
            "container_quantity": self.container_quantity,
        }
