"""서류 작성 ↔ 운송 계획이 함께 쓰는 "작성 중인 수출 건".

서류 작성 화면(직접 입력 · B/L/오퍼시트 올리기 · 대화)에서 적은 값을 회원마다 한 벌
저장해 두고, 운송 계획 화면이 열릴 때 그 값으로 Route · Incoterms · Cargo 칸을
미리 채웁니다. (planning.js가 쓰는 임시저장 모양으로 돌려줍니다)

서버에 두는 것은 SHARED_FIELDS · ITEM_FIELDS뿐입니다.
은행 계좌·SWIFT, 바이어 주소·이메일·담당자, Notify Party, 결제 조건은 저장하지 않습니다.
(사용자 결정: 은행·바이어 주소·연락처는 서버에 남기지 않음. 바이어 회사명은 남김)
그 값들은 브라우저의 sessionStorage에만 두고, 같은 탭에서 운송 계획으로 넘어갈 때
브라우저가 직접 채웁니다. (work_draft.js)
"""

from __future__ import annotations

from datetime import timezone

from app.extensions import db
from app.processors import bank_redaction
from app.services import ServiceError

SHARED_FIELDS = (
    "transport_mode", "sea_mode",
    "project_name",                             # 견적명 — 대시보드에서 이 건을 부르는 이름
    "exporter_name", "exporter_address",        # 송하인(수출자, 우리 회사)
    "buyer_name", "buyer_country",              # 수하인 회사명·나라 (주소·연락처는 제외)
    "origin_code", "origin_name", "destination_code", "destination_name",   # POL / POD
    "incoterms", "currency", "requested_departure_date", "buyer_required_date",
    # 신용장 조건. 운송 계획에서 "이 배로 실으면 L/C 마감을 넘는지" 보는 데 씁니다.
    "lc_no", "lc_latest_shipment_date", "lc_expiry_date", "lc_presentation_days",
)
ITEM_FIELDS = ("product_description", "hs_code", "package_type", "quantity", "length_cm",
               "width_cm", "height_cm", "weight_per_package_kg", "net_weight_kg",
               "unit_price", "amount")
SOURCES = ("document", "upload", "chat")
MAX_ITEMS = 20
MAX_TEXT = 300


def _text(value, limit: int = MAX_TEXT) -> str:
    text = str(value if value is not None else "").strip()[:limit]
    # 칸에 계좌번호가 섞여 들어와도 서버에는 남기지 않습니다.
    return bank_redaction.strip_bank_numbers(text)[0] if text else ""


def clean(payload) -> dict:
    """아는 칸만, 길이를 잘라 받습니다. {fields, items} 모양과 평평한 초안 모두 받습니다."""

    if not isinstance(payload, dict):
        raise ServiceError("저장할 내용을 읽지 못했습니다.", "VALIDATION_ERROR")
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else payload
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    data = {"fields": {key: _text(fields.get(key)) for key in SHARED_FIELDS
                       if _text(fields.get(key))}}
    data["items"] = [row for row in (
        {key: _text(item.get(key)) for key in ITEM_FIELDS if _text(item.get(key))}
        for item in items[:MAX_ITEMS] if isinstance(item, dict)) if row]
    return data


def _record(viewer):
    from app.models import WorkDraft

    return WorkDraft.query.filter_by(user_id=viewer.id).first()


def save(viewer, payload, source: str = "document") -> dict:
    from app.models import WorkDraft

    data = clean(payload)
    record = _record(viewer)
    if record is None:
        record = WorkDraft(user_id=viewer.id)
        db.session.add(record)
    # 빈 값으로 덮지 않습니다. 대화에서 품목만 적어도 앞서 적은 항구가 남습니다.
    if record.data:
        merged = {**(record.data.get("fields") or {}), **data["fields"]}
        data = {"fields": merged, "items": data["items"] or record.data.get("items") or []}
    record.data = data
    record.source = source if source in SOURCES else "document"
    db.session.commit()
    return as_dict(record)


def as_dict(record) -> dict:
    if record is None:
        return {}
    updated = record.updated_at.replace(tzinfo=timezone.utc)
    return {**record.data, "source": record.source, "updated_at": updated.isoformat(),
            "updated_ms": int(updated.timestamp() * 1000)}


def load(viewer) -> dict:
    return as_dict(_record(viewer))


def clear(viewer) -> None:
    record = _record(viewer)
    if record is not None:
        db.session.delete(record)
        db.session.commit()


# --- 운송 계획 화면 모양으로 -----------------------------------------------------------

def _location(code: str, shown: str) -> dict | None:
    from app.collectors import location_client

    code = (code or "").strip().upper()
    if not code:
        return None
    found = location_client.find_location(code)
    if found:
        return found
    # 목록에 없는 코드는 직접 입력한 항구처럼 넘깁니다. (planning.js의 custom과 같은 모양)
    name = (shown or code).split(" (")[0].strip() or code
    return {"code": code, "name": name, "country_code": code[:2], "custom": True}


def _total(items: list[dict]) -> str:
    total = 0.0
    for item in items:
        try:
            total += float(str(item.get("amount") or "0").replace(",", ""))
        except ValueError:
            return ""
    return f"{total:.2f}".rstrip("0").rstrip(".") if total else ""


def _lc(fields: dict) -> dict | None:
    """저장해 둔 L/C 날짜로 선적 마감을 다시 계산합니다. (날짜는 오늘 기준으로 바뀝니다)"""

    from app.processors import lc_schedule
    from app.validators import ValidationError
    from app.validators.shipment_validator import parse_date

    def day(key):
        try:
            return parse_date(fields[key], key) if fields.get(key) else None
        except ValidationError:
            return None

    from app.services.document_extract_service import transit_range

    mode = fields.get("transport_mode") or "SEA"
    return lc_schedule.as_text(lc_schedule.plan(
        latest_shipment=day("lc_latest_shipment_date"), expiry=day("lc_expiry_date"),
        presentation=fields.get("lc_presentation_days"), transport_mode=mode,
        transit_days=transit_range(fields.get("origin_code", ""),
                                   fields.get("destination_code", ""), mode)))


def planning_prefill(viewer) -> dict:
    """운송 계획 임시저장(planning.js saveDraft)과 같은 모양. 저장된 것이 없으면 빈 dict."""

    stored = load(viewer)
    if not stored:
        return {}
    fields = stored.get("fields") or {}
    items = stored.get("items") or []
    first = items[0] if items else {}
    line_keys = ("product_description", "hs_code", "package_type", "quantity", "length_cm",
                 "width_cm", "height_cm", "weight_per_package_kg", "net_weight_kg", "amount")
    planning_fields = {key: first[key] for key in line_keys if first.get(key) and key != "amount"}
    carried = ("project_name", "exporter_name", "exporter_address", "buyer_name",
               "buyer_country", "currency", "buyer_required_date")
    planning_fields.update({key: fields[key] for key in carried if fields.get(key)})
    if _total(items):
        planning_fields["invoice_value"] = _total(items)
    return {
        "savedAt": stored["updated_ms"],
        "step": 1,
        "from_work_draft": True,
        "source": stored["source"],
        "transport_mode": fields.get("transport_mode") or "SEA",
        "sea_mode": fields.get("sea_mode") or "",
        "departure_date": fields.get("requested_departure_date") or None,
        "origin": _location(fields.get("origin_code"), fields.get("origin_name")),
        "destination": _location(fields.get("destination_code"), fields.get("destination_name")),
        "incoterms": fields.get("incoterms") or "",
        "lc": _lc(fields),
        "fields": planning_fields,
        "cargo_lines": [{key: row[key] for key in line_keys if row.get(key)} for row in items[1:]],
    }
