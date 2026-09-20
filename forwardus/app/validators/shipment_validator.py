"""Validation for route setup and shipment creation input."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.validators import ValidationError
from app.validators.cargo_validator import MAX_INVOICE_VALUE, parse_number, parse_optional_number

TRANSPORT_MODES = {"SEA", "AIR"}
SEA_MODES = {"FCL", "LCL"}
CURRENCIES = {"USD", "EUR", "JPY", "CNY", "KRW"}
AIR_INVALID_INCOTERMS = {"FOB", "CFR", "CIF"}
INCOTERMS = {"EXW", "FCA", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}


def parse_date(value: Any, field_name: str, *, required: bool = True, field: str | None = None) -> date | None:
    """Parse an ISO date string (YYYY-MM-DD)."""

    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(f"{field_name}을(를) 선택해주세요.", field)
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValidationError(f"{field_name} 형식이 올바르지 않습니다. (YYYY-MM-DD)", field) from exc


def require_text(value: Any, field_name: str, *, max_length: int = 200, field: str | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field_name}을(를) 입력해주세요.", field)
    if len(text) > max_length:
        raise ValidationError(f"{field_name}은(는) {max_length}자 이내로 입력해주세요.", field)
    return text


def optional_text(value: Any, *, max_length: int = 500) -> str:
    return str(value or "").strip()[:max_length]


def validate_route(payload: dict) -> dict:
    """Validate route setup: mode, locations, and requested departure date."""

    transport_mode = str(payload.get("transport_mode") or "").upper()
    if transport_mode not in TRANSPORT_MODES:
        raise ValidationError("운송 모드(SEA / AIR)를 선택해주세요.", "transport_mode")

    sea_mode = None
    if transport_mode == "SEA":
        sea_mode = str(payload.get("sea_mode") or "").upper()
        if sea_mode not in SEA_MODES:
            raise ValidationError("해상 운송 방식(FCL / LCL)을 선택해주세요.", "sea_mode")

    # 코드는 직접 입력 시 비어 있을 수 있습니다. 실제 확인은 planning_service에서
    # 목록 조회 또는 직접 입력 값으로 처리합니다.
    origin_code = optional_text(payload.get("origin_code"), max_length=10).upper()
    destination_code = optional_text(payload.get("destination_code"), max_length=10).upper()
    if origin_code and origin_code == destination_code:
        raise ValidationError("출발지와 도착지가 같습니다.", "destination_code")

    return {
        "project_name": require_text(payload.get("project_name"), "견적명", field="project_name"),
        "transport_mode": transport_mode,
        "sea_mode": sea_mode,
        "origin_code": origin_code,
        "destination_code": destination_code,
        "requested_departure_date": parse_date(
            payload.get("requested_departure_date"), "출발 희망일", field="requested_departure_date"
        ),
    }


def validate_trade_terms(payload: dict, transport_mode: str) -> dict:
    """Validate Incoterms, currency, and invoice value."""

    incoterms = str(payload.get("incoterms") or "").upper()
    if incoterms not in INCOTERMS:
        raise ValidationError("Incoterms를 선택해주세요.", "incoterms")
    if transport_mode == "AIR" and incoterms in AIR_INVALID_INCOTERMS:
        raise ValidationError("항공 운송에는 FOB, CFR, CIF 대신 FCA, CPT, CIP를 사용합니다.", "incoterms")

    currency = str(payload.get("currency") or "USD").upper()
    if currency not in CURRENCIES:
        raise ValidationError("통화를 확인해주세요.", "currency")

    return {
        "incoterms": incoterms,
        "currency": currency,
        "invoice_value": parse_number(
            payload.get("invoice_value"), "Invoice Value", max_value=MAX_INVOICE_VALUE, field="invoice_value"
        ),
    }


def validate_parties(payload: dict) -> dict:
    """Validate exporter and buyer information."""

    buyer = payload.get("buyer") or {}
    return {
        "exporter_name": require_text(payload.get("exporter_name"), "수출자(Exporter)명", field="exporter_name"),
        "exporter_address": optional_text(payload.get("exporter_address")),
        "notify_party": optional_text(payload.get("notify_party"), max_length=300) or "SAME AS CONSIGNEE",
        "buyer_name": require_text(buyer.get("name"), "Buyer(Consignee)명", field="buyer_name"),
        "buyer_country": optional_text(buyer.get("country"), max_length=100),
        "buyer_address": optional_text(buyer.get("address")),
        "buyer_email": optional_text(buyer.get("contact_email"), max_length=200),
    }


def validate_net_weight(value: Any, gross_weight_kg: float) -> float | None:
    net = parse_optional_number(value, "순중량(Net Weight)", field="net_weight_kg")
    if net is not None and net > gross_weight_kg:
        raise ValidationError("순중량은 총중량보다 클 수 없습니다.", "net_weight_kg")
    return net
