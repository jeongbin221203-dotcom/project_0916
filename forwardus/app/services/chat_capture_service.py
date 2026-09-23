"""대화에 적은 화물 정보를 담아 둡니다. (State — 값만, 원문은 아닙니다)

무역 상담이나 운송 계획 이야기를 하다 보면 값이 그냥 지나갑니다.

    "부산에서 로스앤젤레스로 화장품 500박스 보냅니다. 한 박스 40x30x25cm에 12kg이고
     FOB, USD 결제입니다."

그 다음에 서류 작성 화면으로 가면 칸이 비어 있어 같은 말을 또 적어야 했습니다.
여기서는 **적혀 있는 값만** 뽑아 "작성 중인 수출 건"(work_drafts)에 담아 둡니다. 그러면
서류 작성과 운송 계획이 그 값으로 칸을 미리 채웁니다.

지키는 것
  - AI를 따로 부르지 않습니다. 규칙으로 읽을 수 있는 것만 담습니다. (대화마다 돈이 들면 안 됩니다)
  - 짐작하지 않습니다. "보통 40피트면…" 같은 추정은 담지 않습니다.
  - 이미 담아 둔 값은 덮지 않습니다. 사람이 화면에서 고친 값이 우선입니다.
  - 계좌번호·바이어 주소·연락처는 담지 않습니다. (work_draft_service가 한 번 더 거릅니다)
"""

from __future__ import annotations

import re

from app.services import document_pipeline_service as pipeline
from app.services import work_draft_service

# "부산에서 로스앤젤레스로", "인천 → LA", "부산발 LA착"
ROUTE_PATTERNS = (
    re.compile(r"([가-힣A-Za-z][가-힣A-Za-z .]{1,24}?)\s*(?:에서|서|발)\s*"
               r"([가-힣A-Za-z][가-힣A-Za-z .]{1,24}?)\s*(?:으로|로|까지|행|착)"),
    re.compile(r"([가-힣A-Za-z][가-힣A-Za-z .]{1,24}?)\s*(?:→|->|~)\s*"
               r"([가-힣A-Za-z][가-힣A-Za-z .]{1,24})"),
)
# "500박스", "500 CTN", "300개"
COUNT = re.compile(r"(\d[\d,]*)\s*(박스|상자|개|팔레트|파렛|카톤|ctns?|cartons?|boxes|box|plts?|pallets?)",
                   re.I)
# "한 박스 12kg", "박스당 12kg", "개당 0.5t"
PER_PACKAGE = re.compile(r"(?:한|1)?\s*(?:박스|상자|개|팔레트|파렛|carton|ctn|box|plt)\s*(?:당|에|은|는)?\s*"
                         r"(\d[\d,]*(?:\.\d+)?)\s*(kg|킬로|t|톤|ton)", re.I)
# "총 6톤", "전체 3,000kg"
TOTAL_WEIGHT = re.compile(r"(?:총|전체|합쳐서?)\s*(\d[\d,]*(?:\.\d+)?)\s*(kg|킬로|t|톤|ton)", re.I)
# 항공 · 해상
AIR_WORDS = ("항공", "비행기", "air", "awb")
SEA_WORDS = ("해상", "배로", "선박", "컨테이너", "fcl", "lcl", "ocean", "sea")
# 이 글자 수보다 짧으면 값이 들어 있을 리 없습니다.
MIN_LENGTH = 6
LABELS = {
    "origin_code": "출발지", "destination_code": "도착지", "incoterms": "Incoterms",
    "currency": "통화", "transport_mode": "운송 모드", "exporter_name": "수출자",
    "buyer_name": "바이어",
}
ITEM_LABELS = {"product_description": "품명", "quantity": "수량",
               "weight_per_package_kg": "한 포장 무게", "length_cm": "포장 치수"}


def _kg(number: str, unit: str) -> str:
    value = float(number.replace(",", ""))
    if unit.lower() in ("t", "톤", "ton"):
        value *= 1000
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _mode(text: str) -> str:
    low = text.lower()
    if any(word in low for word in AIR_WORDS):
        return "AIR"
    return "SEA" if any(word in low for word in SEA_WORDS) else ""


def _ports(text: str, mode: str) -> dict:
    """"A에서 B로"에서 두 곳을 찾아 우리 항구·공항 목록의 코드로 바꿉니다."""

    from app.services.document_extract_service import _port

    for pattern in ROUTE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        found = {}
        for role, written in (("origin", match.group(1)), ("destination", match.group(2))):
            place = _port(written.strip(), mode or "SEA", role, [])
            if place:
                found[f"{role}_code"] = place["code"]
                found[f"{role}_name"] = f"{place['name']} ({place['code']})"
        if found:
            return found
    return {}


def read(message: str) -> dict:
    """적힌 값만 뽑습니다. {"fields": {...}, "items": [{...}]} (없으면 빈 dict)"""

    text = str(message or "").strip()
    if len(text) < MIN_LENGTH:
        return {}

    # "칸 이름: 값"과 조건 코드(FOB·USD)는 이미 읽는 코드가 있습니다.
    # 담아 둘 수 있는 칸만 받습니다. (그 밖의 키는 여기서 버립니다)
    found = pipeline._rule_read(text, {"items": []})
    fields = {key: value for key, value in found.items()
              if key in work_draft_service.SHARED_FIELDS and value}
    item: dict = {}
    for line_no, values in (found.get("items") or {}).items():
        if line_no == 1:
            item.update({key: value for key, value in values.items() if value})

    mode = _mode(text)
    if mode:
        fields["transport_mode"] = mode
    fields.update(_ports(text, mode))

    # 치수를 먼저 떼어 냅니다. "한 박스 40x30x25cm에 12kg"에서 12kg을 찾으려면
    # 사이에 낀 치수를 치워야 "박스 … 12kg"이 이어집니다.
    dims = pipeline.DIMS_PATTERN.search(text)
    rest = text
    if dims:
        item.update(dict(zip(pipeline.DIMS, dims.groups())))
        rest = (text[:dims.start()] + " " + text[dims.end():]).replace("cm", " ")
    count = COUNT.search(text)
    if count:
        item["quantity"] = count.group(1).replace(",", "")
    per_package = PER_PACKAGE.search(rest)
    if per_package:
        item["weight_per_package_kg"] = _kg(per_package.group(1), per_package.group(2))
    elif TOTAL_WEIGHT.search(rest) and item.get("quantity"):
        total = TOTAL_WEIGHT.search(rest)
        each = float(_kg(total.group(1), total.group(2))) / float(item["quantity"])
        item["weight_per_package_kg"] = f"{each:.3f}".rstrip("0").rstrip(".")

    if not fields and not item:
        return {}
    return {"fields": fields, "items": [item] if item else []}


def capture(viewer, message: str) -> list[str]:
    """대화에서 읽은 값을 담아 두고, 무엇을 담았는지 한국어 이름으로 돌려줍니다.

    로그인하지 않았으면 담지 않습니다. (담아 둘 자리가 사람마다 하나입니다)
    """

    if viewer is None:
        return []
    read_values = read(message)
    if not read_values:
        return []

    kept = work_draft_service.load(viewer)
    known_fields = (kept.get("fields") or {})
    known_item = (kept.get("items") or [{}])[0] if kept.get("items") else {}

    # 이미 담아 둔 값은 덮지 않습니다. 화면에서 고친 값이 우선입니다.
    fields = {key: value for key, value in read_values["fields"].items()
              if key in work_draft_service.SHARED_FIELDS and not known_fields.get(key)}
    items = []
    if read_values["items"]:
        item = {key: value for key, value in read_values["items"][0].items()
                if key in work_draft_service.ITEM_FIELDS and not known_item.get(key)}
        if item:
            items = [{**known_item, **item}]
    if not fields and not items:
        return []

    work_draft_service.save(viewer, {"fields": fields, "items": items or kept.get("items") or []},
                            "chat")
    labels = [LABELS[key] for key in fields if key in LABELS]
    if items:
        labels += [ITEM_LABELS[key] for key in items[0] if key in ITEM_LABELS
                   and key not in known_item]
    return list(dict.fromkeys(labels))
