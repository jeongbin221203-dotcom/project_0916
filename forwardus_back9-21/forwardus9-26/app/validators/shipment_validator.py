"""Validation for route setup and shipment creation input."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.processors.cost_calculator import INCOTERMS_INFO
from app.validators import ValidationError
from app.validators.cargo_validator import MAX_INVOICE_VALUE, parse_number, parse_optional_number

TRANSPORT_MODES = {"SEA", "AIR"}
SEA_MODES = {"FCL", "LCL"}
CURRENCIES = {"USD", "EUR", "JPY", "CNY", "KRW"}
# 조건 목록은 화면과 같은 표(INCOTERMS_INFO)에서 가져옵니다. 따로 적어 두면
# 한쪽만 고쳐져 화면에서 고른 조건(예: FAS)이 저장 단계에서 거절됩니다.
INCOTERMS = {row["code"] for row in INCOTERMS_INFO}
AIR_INVALID_INCOTERMS = {row["code"] for row in INCOTERMS_INFO if row.get("sea_only")}


# 수출 일정에 쓸 수 있는 날짜 범위. 이 밖은 잘못 입력한 것으로 봅니다.
# (9999-12-31 같은 값에 소요일을 더하면 날짜 계산 자체가 터집니다)
MIN_YEAR, MAX_YEAR = 2000, 2100


def parse_date(value: Any, field_name: str, *, required: bool = True, field: str | None = None) -> date | None:
    """Parse an ISO date string (YYYY-MM-DD)."""

    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(f"{field_name}을(를) 선택해주세요.", field)
        return None
    if isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(str(value).strip())
        except (ValueError, TypeError) as exc:
            raise ValidationError(f"{field_name} 형식이 올바르지 않습니다. (YYYY-MM-DD)",
                                  field) from exc
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise ValidationError(
            f"{field_name}은(는) {MIN_YEAR}년부터 {MAX_YEAR}년 사이여야 합니다.", field)
    return parsed


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


# 항공에 해상 전용 조건을 쓰는 것은 틀린 일이지만, 바이어가 계약서에 그렇게
# 적어 오는 일이 실제로 있습니다. 막지 않고 한 번 더 확인만 받습니다.
AIR_INCOTERMS_MESSAGE = ("항공 운송에는 FAS, FOB, CFR, CIF 대신 FCA, CPT, CIP를 씁니다. "
                         "FAS·FOB·CFR·CIF는 '본선 옆에 둔 때'·'본선에 적재된 때' 위험이 "
                         "넘어간다고 정한 해상·내수로 전용 조건이라 항공에는 넘어가는 시점이 없습니다.")
AIR_INCOTERMS_CONFIRM = "그래도 이 조건으로 진행하시려면 [다음]을 한 번 더 눌러주세요."


def validate_trade_terms(payload: dict, transport_mode: str) -> dict:
    """Validate Incoterms, currency, and invoice value."""

    incoterms = str(payload.get("incoterms") or "").upper()
    if incoterms not in INCOTERMS:
        raise ValidationError("Incoterms를 선택해주세요.", "incoterms")

    warning = ""
    if transport_mode == "AIR" and incoterms in AIR_INVALID_INCOTERMS:
        if not _truthy(payload.get("incoterms_confirmed")):
            raise ValidationError(f"{AIR_INCOTERMS_MESSAGE} {AIR_INCOTERMS_CONFIRM}",
                                  "incoterms", code="INCOTERMS_CONFIRM")
        warning = AIR_INCOTERMS_MESSAGE

    currency = str(payload.get("currency") or "USD").upper()
    if currency not in CURRENCIES:
        raise ValidationError("통화를 확인해주세요.", "currency")

    return {
        "incoterms": incoterms,
        "currency": currency,
        "incoterms_warning": warning,
        "invoice_value": parse_number(
            payload.get("invoice_value"), "Invoice Value", max_value=MAX_INVOICE_VALUE, field="invoice_value"
        ),
    }


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def validate_parties(payload: dict) -> dict:
    """Validate exporter and buyer information."""

    payload = payload if isinstance(payload, dict) else {}
    buyer = payload.get("buyer") or {}
    if not isinstance(buyer, dict):
        buyer = {}
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
