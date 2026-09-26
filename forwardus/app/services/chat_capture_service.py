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

# 항공 용적중량 기준. 가로×세로×높이(cm) ÷ 6,000 = kg (IATA 관행)
AIR_DIVISOR = 6_000

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
# "총 6톤", "전체 3,000kg", "총 중량 6,000kg"
TOTAL_WEIGHT = re.compile(r"(?:총|전체|합쳐서?)\s*(?:중량|무게)?\s*(?:은|는|:)?\s*"
                          r"(\d[\d,]*(?:\.\d+)?)\s*(kg|킬로|t|톤|ton)", re.I)
# "중량 12kg", "무게: 12 kg" — 한 포장 무게로 봅니다. (총 중량은 위에서 먼저 뗍니다)
LABELLED_WEIGHT = re.compile(r"(?:중량|무게)\s*(?:\([^)]*\))?\s*(?:은|는|:|-)?\s*"
                             r"(\d[\d,]*(?:\.\d+)?)\s*(kg|킬로|t|톤|ton)", re.I)
# "품명 치약", "품목: 화장품", "치약 500박스"의 '치약'
PRODUCT_LABELLED = re.compile(r"(?:품명|품목|제품|상품)\s*(?:은|는|:|-)?\s*"
                              r"([가-힣A-Za-z][가-힣A-Za-z0-9 ./-]{0,40}?)\s*(?:[,\n·]|입니다|이고|$)")
PRODUCT_BEFORE_COUNT = re.compile(r"([가-힣][가-힣A-Za-z0-9]{1,15})\s*(?:를|을)?\s*"
                                  r"\d[\d,]*\s*(?:박스|상자|개|팔레트|파렛|카톤)")
# 품명 자리에 들어오면 안 되는 말. (수량·포장 이야기지 물건 이름이 아닙니다)
NOT_PRODUCT = ("총", "전체", "합계", "박스", "상자", "포장", "수량", "중량", "무게", "크기")
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


# 이름 뒤에 붙는 코드와 "항·공항" 같은 꼬리. 다시 찾을 때 떼어 냅니다.
_CODE_TAIL = re.compile(r"\s*\([A-Z]{3,5}\)\s*$")
_KIND_TAIL = re.compile(r"(국제공항|공항|항)$")


def ports_match_mode(fields: dict, mode: str) -> bool:
    """담아 둔 항구가 그 모드의 것인가.

    바다는 UN/LOCODE 다섯 자리(KRPUS), 하늘은 IATA 세 자리(ICN)입니다.
    자릿수만 봐도 어느 쪽 것인지 압니다.
    """

    codes = [str(fields.get(f"{role}_code") or "") for role in ("origin", "destination")]
    codes = [code for code in codes if code]
    if not codes:
        return True
    want = 3 if str(mode or "").upper() == "AIR" else 5
    return all(len(code) == want for code in codes)


def retune_ports(fields: dict, mode: str) -> dict:
    """운송 모드가 바뀌면 **항구도 따라 바꿉니다.**

    왜 필요한가
      "부산에서 로스앤젤레스로 보냅니다"라고 적으면 해상 항구(KRPUS·USLAX)로
      담아 둡니다. 그 뒤에 "항공으로 보내면 얼마나 걸리나요?"라고 물으면
      모드만 AIR로 바뀌고 항구는 해상 그대로였습니다. 머리글에는
      "부산항 → 로스앤젤레스항"이 붙고 본문은 항공 이야기를 했습니다.

    한쪽이라도 그 모드의 항구·공항을 못 찾으면 **구간을 통째로 비웁니다.**
    (부산은 우리 표에 공항이 없습니다) 반쪽짜리 구간은 없는 구간입니다.
    비운 자리는 사람에게 다시 물어보게 됩니다.
    """

    from app.services.document_extract_service import _port

    found, missed = {}, False
    for role in ("origin", "destination"):
        shown = str(fields.get(f"{role}_name") or "")
        if not shown:
            continue
        bare = _KIND_TAIL.sub("", _CODE_TAIL.sub("", shown)).strip()
        place = _port(bare, mode, role, []) if bare else None
        if not place:
            missed = True
            continue
        found[f"{role}_code"] = place["code"]
        found[f"{role}_name"] = f"{place['name']} ({place['code']})"
    if missed:
        return {key: "" for key in ("origin_code", "origin_name",
                                    "destination_code", "destination_name")}
    return found


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
    # 총 중량은 먼저 떼어 냅니다. 안 그러면 "총 중량 6,000kg"의 6,000이
    # 한 포장 무게로 잡힙니다.
    total = TOTAL_WEIGHT.search(rest)
    if total:
        rest = rest[:total.start()] + " " + rest[total.end():]
    per_package = PER_PACKAGE.search(rest) or LABELLED_WEIGHT.search(rest)
    if per_package:
        item["weight_per_package_kg"] = _kg(per_package.group(1), per_package.group(2))
    elif total and item.get("quantity"):
        each = float(_kg(total.group(1), total.group(2))) / float(item["quantity"])
        item["weight_per_package_kg"] = f"{each:.3f}".rstrip("0").rstrip(".")

    # 품명. "품명 치약"처럼 이름표가 붙은 것을 먼저 보고, 없으면 수량 앞의 말을 봅니다.
    if not item.get("product_description"):
        for pattern in (PRODUCT_LABELLED, PRODUCT_BEFORE_COUNT):
            found_name = pattern.search(text)
            name = found_name.group(1).strip() if found_name else ""
            if name and not any(word in name for word in NOT_PRODUCT):
                item["product_description"] = name
                break

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

    # **방금 말한 것이 이깁니다.**
    #
    # 예전에는 "이미 담아 둔 값은 덮지 않습니다"였습니다. 화면에서 고친 값을
    # 지키려던 것인데, 그러면 대화로는 아무것도 **고칠 수가 없습니다.**
    # "부산에서 로스앤젤레스로 보냅니다"라고 적어도 지난 건(대만 가오슝)이
    # 그대로 남아, 다음 질문의 머리글에 "Busan → Kaohsiung"이 붙었습니다.
    # 사람이 방금 적은 말보다 더 새로운 값은 없습니다. (2026-09-26)
    fields = {key: value for key, value in read_values["fields"].items()
              if key in work_draft_service.SHARED_FIELDS and value}
    # 담아 둔 항구가 모드와 안 맞으면 그 모드로 다시 풉니다. (retune_ports 참고)
    # **이번 말에서 읽은 것이 먼저입니다.** 다시 푼 값을 밑에 깔고 그 위에 얹습니다.
    # (순서를 바꿨더니 방금 읽은 공항이 지워졌습니다)
    mode = fields.get("transport_mode") or known_fields.get("transport_mode")
    if mode and not ports_match_mode(known_fields, mode):
        fields = {**retune_ports(known_fields, mode), **fields}
    items = []
    if read_values["items"]:
        item = {key: value for key, value in read_values["items"][0].items()
                if key in work_draft_service.ITEM_FIELDS and value}
        if item:
            # 품목이 바뀌었으면 지난 품목의 치수·무게는 함께 버립니다.
            # 담배 치수에 치약 이름이 붙으면 CBM이 통째로 틀립니다.
            changed = (item.get("product_description")
                       and item["product_description"] != known_item.get("product_description"))
            items = [item if changed else {**known_item, **item}]
    if not fields and not items:
        return []

    work_draft_service.save(viewer, {"fields": fields, "items": items or kept.get("items") or []},
                            "chat")
    labels = [LABELS[key] for key in fields if key in LABELS]
    if items:
        labels += [ITEM_LABELS[key] for key in items[0] if key in ITEM_LABELS
                   and key not in known_item]
    return list(dict.fromkeys(labels))


def cargo_summary(item: dict) -> dict | None:
    """적어 주신 치수·수량으로 CBM과 운임톤을 계산하고 LCL·FCL을 판단합니다.

    "수건 300박스, 한 박스 40x61x70cm에 50kg"이라고 적으면 사람은 그 다음에 꼭
    "그래서 몇 CBM이고 LCL인가요 FCL인가요"를 묻습니다. 그건 계산이라 우리가 바로
    답할 수 있습니다. AI에게 묻지 않습니다. (숫자를 지어내면 안 되는 자리입니다)

    치수나 수량이 하나라도 빠지면 계산하지 않습니다. 반쪽 숫자가 더 위험합니다.
    """

    from app.processors import sea_mode_advisor

    needed = ("length_cm", "width_cm", "height_cm", "quantity")
    if not all(item.get(key) for key in needed):
        return None
    try:
        length, width, height = (float(item[key]) for key in needed[:3])
        count = float(item["quantity"])
        per_package = float(item.get("weight_per_package_kg") or 0)
    except (TypeError, ValueError):
        return None
    if min(length, width, height) <= 0 or count <= 0:
        return None

    one_cbm = length * width * height / 1_000_000       # cm³ → m³
    total_cbm = round(one_cbm * count, 3)
    total_weight = round(per_package * count, 2)
    advice = sea_mode_advisor.recommend(total_cbm, total_weight)

    # 항공은 계산법이 다릅니다. 부피(cm³)를 6,000으로 나눈 용적중량과 실중량 중
    # **큰 값**으로 청구합니다. 해상 R/T와 나란히 보여야 어느 쪽이 나은지 판단합니다.
    volume_weight = round(length * width * height / AIR_DIVISOR * count, 2)
    chargeable = round(max(volume_weight, total_weight), 2)
    return {
        "per_package_cbm": round(one_cbm, 4),
        "total_cbm": total_cbm,
        "total_weight_kg": total_weight,
        "revenue_ton": advice["revenue_ton"],
        "mode": advice["mode"],
        "container_type": advice.get("container_type", ""),
        "containers": advice.get("containers", 0),
        "reason": advice["reason"],
        "confidence": advice["confidence"],
        "air": {
            "volume_weight_kg": volume_weight,
            "chargeable_weight_kg": chargeable,
            # 무엇으로 과금되는지 밝힙니다. 부피로 과금되면 항공이 특히 불리합니다.
            "charged_by": "부피" if volume_weight > total_weight else "실중량",
        },
    }
