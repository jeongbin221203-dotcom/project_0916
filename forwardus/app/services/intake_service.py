"""말로 적은 수출 건을 운송 계획 칸으로 옮깁니다.

사람이 "부산에서 LA로 11월 초에 치약 500박스 FOB로 보냅니다"처럼 한 번에
적으면, 그 글에서 값을 뽑아 운송 계획 화면의 칸을 미리 채워 둡니다.
스무 개가 넘는 칸을 하나씩 찾아 누르지 않아도 되게 하려는 자리입니다.

여기서 꼭 지키는 것이 둘 있습니다.

**첫째, AI가 말한 값을 그대로 믿지 않습니다.**
항구와 공항은 우리 목록에서 다시 찾고, Incoterms와 통화와 포장 종류는
우리가 들고 있는 목록에 있는지 보고, 날짜와 숫자는 우리 검증기로 다시
읽습니다. 확인되지 않은 값은 칸에 넣지 않고 "이건 확인하지 못했다"고
적어 둡니다. 서류는 세관에 나가는 것이라, 틀린 값이 조용히 섞이는 쪽보다
비어 있는 칸이 낫습니다.

**둘째, 여기서 Shipment를 만들지 않습니다.**
칸을 채워 줄 뿐이고, 확인과 제출은 사람이 합니다. 스케줄을 고르는 일과
금액을 확인하는 일은 사람 눈을 거쳐야 합니다.
"""

from __future__ import annotations

import json
from datetime import date

from app.collectors import ai_client, location_client
from app.processors.cost_calculator import INCOTERMS_INFO
from app.services import ServiceError, planning_service
from app.validators import ValidationError
from app.validators.cargo_validator import PACKAGE_TYPE_INFO, parse_number
from app.validators.shipment_validator import optional_text, parse_date

MAX_TEXT = 4_000
MAX_ITEMS = 10

INCOTERMS = {row["code"] for row in INCOTERMS_INFO}
PACKAGE_TYPES = set(PACKAGE_TYPE_INFO)

# 위저드가 칸 이름으로 쓰는 것들. 화면의 input name과 같습니다.
TEXT_FIELDS = ("project_name", "exporter_name", "exporter_address", "notify_party",
               "buyer_name", "buyer_address", "buyer_email")

ITEM_NUMBERS = ("quantity", "length_cm", "width_cm", "height_cm",
                "weight_per_package_kg", "net_weight_kg", "amount")

LABELS = {
    "transport_mode": "운송 모드", "sea_mode": "해상 운송 방식",
    "origin": "출발지", "destination": "도착지",
    "departure_date": "출발 희망일", "buyer_required_date": "Buyer 요청 도착일",
    "incoterms": "Incoterms", "currency": "통화", "invoice_value": "송장 금액",
    "project_name": "견적명", "exporter_name": "수출자명",
    "exporter_address": "수출자 주소", "notify_party": "Notify Party",
    "buyer_name": "Buyer명", "buyer_country": "Buyer 국가",
    "buyer_address": "Buyer 주소", "buyer_email": "Buyer 이메일",
    "product_description": "품명", "hs_code": "HS부호",
    "package_type": "포장 종류", "quantity": "포장 개수",
    "length_cm": "가로(cm)", "width_cm": "세로(cm)", "height_cm": "높이(cm)",
    "weight_per_package_kg": "한 포장 무게(kg)", "net_weight_kg": "순중량(kg)",
    "amount": "품목 금액",
}

# 이것들이 없으면 Shipment를 만들 수 없습니다. (planning_service.create_shipment)
# schedule_id는 스케줄을 실제로 조회해 골라야 하는 값이라 여기서 다루지 않습니다.
REQUIRED = [
    ("project_name", 1), ("origin", 1), ("destination", 1), ("departure_date", 1),
    ("incoterms", 2),
    ("product_description", 3), ("package_type", 3), ("quantity", 3),
    ("length_cm", 3), ("width_cm", 3), ("height_cm", 3), ("weight_per_package_kg", 3),
    ("invoice_value", 3),
    ("exporter_name", 5), ("buyer_name", 5),
]


EXTRACT_PROMPT = """사용자가 수출하려는 화물을 우리말로 적었습니다.
그 글에 **적혀 있는 것만** 뽑아 JSON 한 덩어리로 돌려주세요.

지켜야 할 것
- 글에 없는 값은 넣지 마세요. 짐작하지 마세요. 모르면 그 키를 빼세요.
- 관세율·운임·환율·무게를 기억에서 꺼내 채우지 마세요. 사람이 적은 것만 옮깁니다.
- 숫자는 단위를 떼고 숫자만 적으세요. ("500박스" -> 500, "1.2톤" -> 1200)
- 날짜는 YYYY-MM-DD로 적으세요. 오늘은 {today}입니다.
  "다음 달 초"처럼 어림한 말은 그달 5일, "중순"은 15일, "말"은 25일로 적으세요.
- 설명도 인사말도 붙이지 마세요. JSON만 적습니다.

쓸 수 있는 키
  transport_mode   "SEA"(배) 또는 "AIR"(비행기)
  sea_mode         "FCL"(컨테이너 단독) 또는 "LCL"(혼재)
  origin           출발지를 적힌 그대로 ("부산", "인천공항")
  destination      도착지를 적힌 그대로 ("로스앤젤레스", "LA", "상하이")
  departure_date   출발 희망일
  buyer_required_date  Buyer가 받고 싶다고 한 날
  incoterms        EXW FCA FAS FOB CFR CIF CPT CIP DAP DPU DDP 중 하나
  currency         USD KRW EUR JPY CNY 같은 통화 코드
  invoice_value    송장 전체 금액 (숫자만)
  project_name     이 건을 부를 이름 (없으면 빼세요)
  exporter_name    보내는 회사 이름
  exporter_address 보내는 회사 주소
  notify_party     통지처
  buyer_name       받는 회사 이름
  buyer_country    받는 회사 나라의 두 글자 코드 (미국이면 US)
  buyer_address    받는 회사 주소
  buyer_email      받는 회사 이메일
  items            품목 목록. 품목마다 아래 키를 씁니다.
      product_description  품명
      hs_code              HS부호 (글에 숫자로 적혀 있을 때만)
      package_type         carton pallet wooden_crate drum flexible_bag uld bulk 중 하나
      quantity             포장 개수
      length_cm            한 포장의 가로 (cm)
      width_cm             한 포장의 세로 (cm)
      height_cm            한 포장의 높이 (cm)
      weight_per_package_kg  한 포장의 무게 (kg)
      net_weight_kg        순중량 (kg)
      amount               이 품목의 금액

이렇게 생긴 답을 기대합니다.
{{"transport_mode":"SEA","sea_mode":"LCL","origin":"부산","destination":"로스앤젤레스",
 "departure_date":"2026-11-05","incoterms":"FOB","currency":"USD",
 "items":[{{"product_description":"치약","quantity":500,"package_type":"carton"}}]}}"""


def available() -> bool:
    """AI 키가 있어야 글을 읽을 수 있습니다."""

    return ai_client.available()


def _json_from(answer: str) -> dict:
    """AI 답에서 JSON 덩어리만 꺼냅니다.

    ```json 울타리를 두르거나 앞뒤로 한마디 붙이는 일이 흔합니다.
    """

    text = (answer or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ServiceError("AI 답을 읽지 못했습니다. 다시 한 번 적어 주세요.")
    try:
        parsed = json.loads(text[start:end + 1])
    except ValueError:
        raise ServiceError("AI 답을 읽지 못했습니다. 다시 한 번 적어 주세요.")
    if not isinstance(parsed, dict):
        raise ServiceError("AI 답을 읽지 못했습니다. 다시 한 번 적어 주세요.")
    return parsed


def _pick(value, allowed: set, *, upper: bool = True) -> str:
    """우리가 들고 있는 목록에 있을 때만 씁니다. 없으면 빈 값입니다."""

    code = str(value or "").strip()
    code = code.upper() if upper else code.lower()
    return code if code in allowed else ""


def _date(value, notes: list, label: str) -> str:
    """날짜로 읽히고 지난 날이 아닐 때만 씁니다."""

    if not value:
        return ""
    try:
        parsed = parse_date(value, label)
    except ValidationError:
        notes.append(f"{label}을(를) 날짜로 읽지 못했습니다. 달력에서 직접 골라 주세요.")
        return ""
    if parsed < date.today():
        notes.append(f"{label}이(가) 지난 날짜({parsed.isoformat()})라 비워 두었습니다.")
        return ""
    return parsed.isoformat()


def _amount(value, label: str, notes: list) -> str:
    """숫자로 읽히면 글자로 돌려줍니다. 칸에 그대로 넣을 값입니다."""

    if value in (None, ""):
        return ""
    try:
        number = parse_number(value, label)
    except ValidationError:
        notes.append(f"{label}을(를) 숫자로 읽지 못했습니다. 직접 적어 주세요.")
        return ""
    # 지수 표기가 칸에 들어가면 안 됩니다. (25000000이 "2.5e+07"이 됩니다)
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _place(query, transport_mode: str, role: str, notes: list) -> dict | None:
    """적힌 이름을 우리 항구·공항 목록에서 다시 찾습니다.

    AI가 코드를 지어낼 수 있으므로 목록에 있는 것만 씁니다.
    """

    text = str(query or "").strip()
    if not text:
        return None
    label = LABELS[role]

    # 코드처럼 생겼으면 코드로 먼저 봅니다. (KRPUS, ICN)
    known = location_client.find_location(text.upper())
    kind = planning_service.location_kind(transport_mode)
    if known and known["kind"] == kind:
        return known

    result = planning_service.search_locations(text, transport_mode, role)
    rows = result["data"] if result["success"] else []
    if not rows:
        notes.append(f"{label} '{text}'을(를) 목록에서 찾지 못했습니다. 직접 골라 주세요.")
        return None
    if len(rows) > 1:
        others = ", ".join(row["name"] for row in rows[1:3])
        notes.append(f"{label}는 '{rows[0]['name']}'로 골랐습니다. "
                     f"{others} 같은 곳도 있으니 맞는지 봐 주세요.")
    return rows[0]


def _item(raw: dict, notes: list, no: int) -> dict:
    """품목 한 줄. 숫자 칸은 숫자로 읽힌 것만 채웁니다."""

    if not isinstance(raw, dict):
        return {}
    line = {
        "product_description": optional_text(raw.get("product_description"), max_length=300),
        "hs_code": "".join(ch for ch in str(raw.get("hs_code") or "") if ch.isdigit())[:10],
        "package_type": _pick(raw.get("package_type"), PACKAGE_TYPES, upper=False),
    }
    for key in ITEM_NUMBERS:
        line[key] = _amount(raw.get(key), f"품목 {no} {LABELS[key]}", notes)
    return {key: value for key, value in line.items() if value}


def read(text: str) -> dict:
    """적은 글에서 값을 뽑아 운송 계획 초안을 만듭니다.

    돌려주는 것은 화면이 그대로 쓰는 초안 한 덩어리와, 무엇을 채웠고
    무엇이 비었는지입니다. 비어 있는 칸은 사람이 채워야 합니다.
    """

    written = str(text or "").strip()
    if len(written) < 5:
        raise ValidationError("어떤 화물을 어디로 보내는지 적어 주세요.", "text")
    if len(written) > MAX_TEXT:
        raise ValidationError(f"글이 너무 깁니다. {MAX_TEXT:,}자 아래로 줄여 주세요.", "text")
    if not available():
        raise ServiceError("AI 키(AI_API_KEY)가 없어 글을 읽을 수 없습니다. "
                           "칸을 직접 채워 주세요.")

    prompt = EXTRACT_PROMPT.format(today=date.today().isoformat())
    answer = ai_client.chat([{"role": "system", "content": prompt},
                             {"role": "user", "content": written}], max_tokens=900)
    if not answer["success"]:
        raise ServiceError(answer["message"])

    raw = _json_from(answer["data"])
    notes: list[str] = []

    mode = _pick(raw.get("transport_mode"), {"SEA", "AIR"}) or "SEA"
    draft: dict = {
        "transport_mode": mode,
        "sea_mode": _pick(raw.get("sea_mode"), {"FCL", "LCL"}),
        "departure_date": _date(raw.get("departure_date"), notes, LABELS["departure_date"]),
        "incoterms": _pick(raw.get("incoterms"), INCOTERMS),
        "origin": _place(raw.get("origin"), mode, "origin", notes),
        "destination": _place(raw.get("destination"), mode, "destination", notes),
        "fields": {},
        "cargo_lines": [],
    }

    if raw.get("incoterms") and not draft["incoterms"]:
        notes.append(f"Incoterms '{raw['incoterms']}'는 우리가 아는 조건이 아니라 비워 두었습니다.")

    fields = draft["fields"]
    for key in TEXT_FIELDS:
        fields[key] = optional_text(raw.get(key), max_length=300)
    fields["buyer_country"] = str(raw.get("buyer_country") or "").strip().upper()[:2]
    fields["buyer_required_date"] = _date(
        raw.get("buyer_required_date"), notes, LABELS["buyer_required_date"])
    fields["currency"] = _pick(raw.get("currency"), _currencies()) or "USD"
    fields["invoice_value"] = _amount(raw.get("invoice_value"), LABELS["invoice_value"], notes)

    items = raw.get("items")
    items = items if isinstance(items, list) else []
    if len(items) > MAX_ITEMS:
        notes.append(f"품목이 {len(items)}개라 앞의 {MAX_ITEMS}개만 채웠습니다.")
        items = items[:MAX_ITEMS]
    lines = [_item(item, notes, no) for no, item in enumerate(items, start=1)]
    draft["cargo_lines"] = [line for line in lines if line]

    # 견적명을 안 적었으면 어디로 무엇을 보내는지로 지어 둡니다. 바꿔도 됩니다.
    if not fields["project_name"]:
        fields["project_name"] = _default_name(
            draft, draft["cargo_lines"][0] if draft["cargo_lines"] else {})

    draft["fields"] = {key: value for key, value in fields.items() if value}
    return {"draft": draft, "form": _for_form(draft),
            "filled": _filled(draft), "missing": _missing(draft), "notes": notes}


def _for_form(draft: dict) -> dict:
    """시작 화면의 서류 칸 이름으로 옮겨 줍니다.

    그 화면은 칸 이름이 곧 서식의 칸 이름입니다. 항구는 코드만 쓰고,
    품목은 줄마다 따로 받습니다.
    """

    form = dict(draft["fields"])
    form["transport_mode"] = draft["transport_mode"]
    form["sea_mode"] = draft["sea_mode"]
    form["incoterms"] = draft["incoterms"]
    form["requested_departure_date"] = draft["departure_date"]
    for role in ("origin", "destination"):
        place = draft[role]
        if place:
            form[f"{role}_code"] = place["code"]
            form[f"{role}_name"] = f"{place['name']} ({place['code']})"
    # 견적명은 서버가 다시 짓습니다. 화면에 칸이 없습니다.
    form.pop("project_name", None)
    return {"fields": {key: value for key, value in form.items() if value},
            "items": draft["cargo_lines"]}


def _currencies() -> set:
    from app.collectors import exchange_client

    return {row["code"] for row in exchange_client.list_currencies()}


def _default_name(draft: dict, first_item: dict) -> str:
    """'로스앤젤레스 치약' 같은 이름. 없으면 빈 값입니다."""

    where = (draft["destination"] or {}).get("name", "")
    what = first_item.get("product_description", "")
    return " ".join(part for part in (where, what) if part)[:200]


def _value_of(draft: dict, key: str) -> str:
    """초안에서 칸 하나를 사람이 읽을 글자로 꺼냅니다."""

    if key in ("origin", "destination"):
        place = draft.get(key)
        return f"{place['name']} ({place['code']})" if place else ""
    if key in draft:
        return str(draft[key] or "")
    if key in draft["fields"]:
        return str(draft["fields"][key] or "")
    # 품목 칸은 첫 품목을 기준으로 봅니다.
    first = draft["cargo_lines"][0] if draft["cargo_lines"] else {}
    return str(first.get(key, ""))


def _filled(draft: dict) -> list[dict]:
    rows = []
    for key in list(LABELS):
        value = _value_of(draft, key)
        if value:
            rows.append({"key": key, "label": LABELS[key], "value": value})
    return rows


def _missing(draft: dict) -> list[dict]:
    """아직 비어 있어 사람이 채워야 하는 칸."""

    rows = [{"key": key, "label": LABELS[key], "step": step}
            for key, step in REQUIRED if not _value_of(draft, key)]
    if draft["transport_mode"] == "SEA" and not draft["sea_mode"]:
        rows.insert(0, {"key": "sea_mode", "label": LABELS["sea_mode"], "step": 1})
    return rows
