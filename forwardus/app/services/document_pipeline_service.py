"""올린 서류 → 빠진 정보 묻기 → 채팅으로 받아 합치기 → 고른 서류 만들기.

시작 화면의 대화창에서 이어지는 흐름입니다.

1. start     올린 B/L·견적서에서 읽은 값(document_extract_service)을 초안으로 받습니다.
2. 검증       고른 서류가 요구하는 필수 정보가 다 있는지 **우리 코드가** 봅니다.
             빠진 것이 있으면 서류를 만들지 않고, 무엇이 빠졌는지 짚어 묻습니다.
3. merge     사람이 채팅으로 적은 값을 읽어 초안에 합칩니다. 확인된 값만 넣습니다.
4. generate  고른 서류만 그립니다. 검토 창(미리보기)에서 고치고 PDF로 받습니다.

agent_service와 같은 선을 지킵니다. 무엇이 빠졌는지는 AI가 아니라 서식이
정하고, 값이 맞는지는 우리 검증기가 봅니다. AI는 사람 말에서 값을 뽑는 일만
합니다. 서버는 상태를 갖지 않고, 초안(draft)은 브라우저가 들고 다닙니다.
"""

from __future__ import annotations

import re

from app.collectors import ai_client
from app.collectors.base_client import get_config
from app.services import ServiceError, draft_document_service as drafts
from app.services.document_extract_service import (_amount, _clean, _package_type,
                                                   _payment_terms, _port)
from app.services.intake_service import INCOTERMS, PACKAGE_TYPES, _currencies, _pick
from app.validators import ValidationError

MAX_MESSAGE = 2_000
MAX_ITEMS = 20

# 고를 수 있는 서류. 기본값은 가장 자주 쓰는 상업송장·포장명세서입니다.
KIND_OPTIONS = [
    {"kind": "commercial_invoice", "label": "상업송장 (Commercial Invoice)", "default": True,
     "about": "세관·바이어에 내는 대금 청구 서류"},
    {"kind": "packing_list_std", "label": "포장명세서 (Packing List)", "default": True,
     "about": "포장별 수량·중량·용적"},
    {"kind": "shipping_instruction", "label": "선적의뢰서 (Shipping Request)", "default": False,
     "about": "포워더·선사에 B/L 내용을 알리는 서류"},
    {"kind": "proforma_invoice", "label": "기타 지원 서류 · 견적송장 (Proforma Invoice)",
     "default": False, "about": "계약 전 가격·조건 제시, 바이어 수입허가·송금용"},
]
KINDS = [row["kind"] for row in KIND_OPTIONS]
DEFAULT_KINDS = [row["kind"] for row in KIND_OPTIONS if row["default"]]

# 필수 정보. key는 초안(draft)의 칸 이름이고, "items." 로 시작하면 품목 줄마다 봅니다.
# hint는 빠졌을 때 왜 필요한지 한 줄로 — 주니어 실무자가 되묻지 않아도 되게.
REQUIRED = {
    "exporter_name": {"label": "수출자(Shipper) 상호",
                      "hint": "사업자등록증의 영문 상호와 같아야 통관에서 걸리지 않습니다"},
    "exporter_address": {"label": "수출자(Shipper) 주소",
                         "hint": "송장 ①Seller 칸에 영문 주소로 찍힙니다"},
    "buyer_name": {"label": "바이어(Consignee) 상호",
                   "hint": "수입 통관의 명의인입니다. L/C 거래면 신용장의 Applicant와 맞추세요"},
    "buyer_address": {"label": "바이어(Consignee) 상세 주소",
                      "hint": "도착지 세관과 포워더가 통지·배송에 씁니다"},
    "origin_code": {"label": "선적항(POL)", "hint": "예: 부산(KRPUS), 인천공항(ICN)"},
    "destination_code": {"label": "도착항(POD)", "hint": "예: 로스앤젤레스(USLAX)"},
    "incoterms": {"label": "인코텀즈 조건(FOB, CIF 등)",
                  "hint": "운임·보험을 누가 부담하는지가 갈리고, 과세가격도 달라집니다"},
    "currency": {"label": "결제 통화", "hint": "USD·EUR 등. 송장 금액의 기준입니다"},
    "items.product_description": {"label": "품명", "hint": "세관이 HS부호를 보는 기준입니다"},
    "items.quantity": {"label": "수량(포장 개수)", "hint": "CI·PL의 수량이 서로 같아야 합니다"},
    "items.price": {"label": "단가 또는 품목별 금액",
                    "hint": "모든 품목에 적어야 송장 합계가 맞습니다"},
    "items.weight": {"label": "포장당 총중량(kg)",
                     "hint": "PL의 Gross Weight와 B/L 중량이 여기서 나옵니다"},
    # 서류 그리기가 CBM·컨테이너 수를 계산하려면 치수가 있어야 합니다. 지어내지 않고 묻습니다.
    "items.dims": {"label": "포장 치수(가로×세로×높이 cm)",
                   "hint": "PL의 Measurement(CBM)와 컨테이너 적입 계산에 씁니다. B/L에는 대개 없습니다"},
}

# 서류마다 요구하는 필수 정보. 서식이 정합니다.
REQUIRED_BY_KIND = {
    "commercial_invoice": ["exporter_name", "exporter_address", "buyer_name", "buyer_address",
                           "origin_code", "destination_code", "incoterms", "currency",
                           "items.product_description", "items.quantity", "items.price",
                           "items.dims"],
    "packing_list_std": ["exporter_name", "buyer_name", "origin_code", "destination_code",
                         "items.product_description", "items.quantity", "items.weight",
                         "items.dims"],
    "shipping_instruction": ["exporter_name", "buyer_name", "buyer_address",
                             "origin_code", "destination_code",
                             "items.product_description", "items.quantity", "items.weight",
                             "items.dims"],
    "proforma_invoice": ["exporter_name", "buyer_name", "origin_code", "destination_code",
                         "incoterms", "currency",
                         "items.product_description", "items.quantity", "items.price",
                         "items.dims"],
}

# 사람이 "칸 이름: 값"으로 적을 때 알아볼 이름들. (AI 없이도 읽힙니다)
ALIASES = {
    "exporter_name": ("수출자", "수출자상호", "shipper", "exporter", "seller", "셀러"),
    "exporter_address": ("수출자주소", "shipper주소", "shipperaddress", "exporteraddress",
                         "셀러주소"),
    "buyer_name": ("바이어", "바이어상호", "수입자", "consignee", "buyer", "컨사이니"),
    "buyer_address": ("바이어주소", "수입자주소", "consignee주소", "consigneeaddress",
                      "buyeraddress", "바이어상세주소", "컨사이니주소"),
    "notify_party": ("notify", "notifyparty", "통지처", "노티파이"),
    "origin_code": ("선적항", "pol", "출발항", "출발지", "portofloading"),
    "destination_code": ("도착항", "pod", "양륙항", "도착지", "portofdischarge"),
    "incoterms": ("인코텀즈", "incoterms", "incoterm", "거래조건", "가격조건"),
    "currency": ("통화", "currency", "결제통화"),
    "payment_terms": ("결제조건", "paymentterms", "payment"),
}
DIMS = ("length_cm", "width_cm", "height_cm")
# "40x30x25", "40 × 30 × 25cm", "40*30*25"
DIMS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[x×X*]\s*(\d+(?:\.\d+)?)\s*[x×X*]\s*(\d+(?:\.\d+)?)")
TEXT_KEYS = ("exporter_name", "exporter_address", "buyer_name", "buyer_address", "notify_party")

MERGE_PROMPT = """사용자가 무역 서류에 빠진 정보를 채팅으로 적었습니다.
적힌 글에서 **명시적으로 적힌 값만** 뽑아 주세요. 적히지 않은 칸은 null입니다. 짐작하지 마세요.

- exporter_* 는 수출자(Shipper/Seller), buyer_* 는 수입자(Consignee/Buyer)입니다.
- port_of_loading / port_of_discharge 는 적힌 이름 그대로 ("부산", "LA")
- incoterms 는 EXW FCA FAS FOB CFR CIF CPT CIP DAP DPU DDP 중 하나
- currency 는 USD EUR KRW JPY CNY 같은 세 글자 코드
- 숫자는 단위·쉼표를 떼고 숫자만. 무게는 kg, "1.2톤" -> 1200
- items 는 품목 줄에 대한 값입니다. line 은 1부터 세는 품목 번호입니다.
  품목이 하나뿐이면 line 은 1 입니다. 어느 품목인지 알 수 없으면 그 값은 넣지 마세요.
  length_cm width_cm height_cm 은 한 포장의 가로·세로·높이(cm)입니다. ("40x30x25" -> 40, 30, 25)
  weight_per_package_kg 은 **한 포장** 무게입니다. 줄 전체 무게만 적혔으면 gross_weight_kg 에 넣으세요.

지금 품목 목록:
{items}"""

_STR = {"type": ["string", "null"]}
_NUM = {"type": ["number", "null"]}


def _object(properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}


MERGE_SCHEMA = _object({
    "exporter_name": _STR, "exporter_address": _STR,
    "buyer_name": _STR, "buyer_address": _STR, "notify_party": _STR,
    "port_of_loading": _STR, "port_of_discharge": _STR,
    "incoterms": _STR, "currency": _STR, "payment_terms": _STR,
    "items": {"type": "array", "items": _object({
        "line": {"type": ["integer", "null"]},
        "product_description": _STR, "quantity": _NUM, "package_unit": _STR,
        "unit_price": _NUM, "amount": _NUM,
        "weight_per_package_kg": _NUM, "gross_weight_kg": _NUM, "net_weight_kg": _NUM,
        "length_cm": _NUM, "width_cm": _NUM, "height_cm": _NUM,
    })},
})


# --- 검증 -------------------------------------------------------------------------

def _has(value) -> bool:
    return bool(str(value if value is not None else "").strip())


def _items(draft: dict) -> list[dict]:
    items = draft.get("items")
    return [row for row in items if isinstance(row, dict)] if isinstance(items, list) else []


def _present(draft: dict, key: str) -> bool:
    items = _items(draft)
    if key == "items.product_description":
        return bool(items) and all(_has(row.get("product_description")) for row in items)
    if key == "items.quantity":
        return bool(items) and all(_has(row.get("quantity")) for row in items)
    if key == "items.price":
        return bool(items) and all(_has(row.get("unit_price")) or _has(row.get("amount"))
                                   for row in items)
    if key == "items.dims":
        return bool(items) and all(all(_has(row.get(name)) for name in DIMS) for row in items)
    if key == "items.weight":
        return bool(items) and all(_has(row.get("weight_per_package_kg")) for row in items)
    return _has(draft.get(key))


def clean_kinds(kinds) -> list[str]:
    """고른 서류. 모르는 것은 버리고 순서는 우리 목록 순서로 맞춥니다."""

    picked = set(kinds) if isinstance(kinds, list) else set()
    chosen = [kind for kind in KINDS if kind in picked]
    return chosen


def missing(draft: dict, kinds: list[str] | None = None) -> list[dict]:
    """빠진 필수 정보. kinds를 안 주면 고를 수 있는 모든 서류 기준입니다.

    각 줄에 어느 서류에 필요한지(kinds)를 붙여 둡니다. 화면이 고른 서류에
    맞춰 거를 수 있게 하려는 것입니다. (최종 판단은 generate에서 다시 합니다)
    """

    kinds = kinds or KINDS
    rows = []
    for key, info in REQUIRED.items():
        needed_by = [kind for kind in kinds if key in REQUIRED_BY_KIND[kind]]
        if needed_by and not _present(draft, key):
            rows.append({"key": key, "label": info["label"], "hint": info["hint"],
                         "kinds": needed_by})
    return rows


def _josa(word: str, pair: tuple[str, str]) -> str:
    """받침이 있으면 앞의 것, 없으면 뒤의 것. ("과/와", "이/가")"""

    last = word.rstrip(" )").rstrip()[-1:] if word else ""
    if "가" <= last <= "힣":
        return pair[0] if (ord(last) - 0xAC00) % 28 else pair[1]
    return pair[1]


def _join(labels: list[str]) -> str:
    """'A, B와 C' 꼴로. 마지막 조사는 받침을 봅니다."""

    if len(labels) == 1:
        return labels[0]
    head = ", ".join(labels[:-1])
    return f"{head}{_josa(labels[-2], ('과', '와'))} {labels[-1]}"


# 번호로 답할 때의 예. 묻는 말 아래에 그대로 보여 줍니다.
ANSWER_EXAMPLES = {
    "exporter_name": "SAMPLE COSMETICS CO., LTD.", "exporter_address": "123 Teheran-ro, Seoul, Korea",
    "buyer_name": "SAMPLE BEAUTY INC.", "buyer_address": "1 Test Ave, Los Angeles, CA 90001",
    "origin_code": "부산", "destination_code": "로스앤젤레스", "incoterms": "FOB",
    "currency": "USD", "items.product_description": "LIPSTICK", "items.quantity": "500",
    "items.price": "단가 12.5", "items.weight": "8kg", "items.dims": "40x30x25",
}


def ask_message(rows: list[dict], intro: str = "업로드해주신 서류에서") -> str:
    """빠진 것을 번호로 짚어 묻는 말. 20년 차 사수가 옆에서 알려 주는 말투로.

    intro는 문장 머리입니다. ("업로드해주신 오퍼시트에서", "다만 아직")
    사람은 같은 번호를 붙여 답하면 됩니다. merge가 번호를 이 목록 순서로 읽습니다.
    """

    if not rows:
        return ("필수 정보가 모두 확인됐습니다. 아래에서 **만들 서류를 고르고** "
                "**선택한 서류 생성하기**를 눌러 주세요. 만든 뒤 미리보기에서 한 번 더 "
                "검토하실 수 있습니다.")
    lines = [f"{intro} 아래 {len(rows)}가지 정보가 누락되어 있습니다. 번호에 맞춰 채팅창에 "
             "편하게 입력해 주시면 바로 서류에 반영해 드릴게요!", ""]
    lines += [f"{no}. **{row['label']}** — {row['hint']}" for no, row in enumerate(rows, 1)]
    example = [f"> {no}. {ANSWER_EXAMPLES.get(row['key'], '...')}"
               for no, row in enumerate(rows[:3], 1)]
    lines += ["", "예를 들어 이렇게 적어 주시면 됩니다.", "", "\n".join(example)]
    return "\n".join(lines)


# --- 시작 -------------------------------------------------------------------------

DRAFT_KEYS = ("transport_mode", "exporter_name", "exporter_address", "buyer_name",
              "buyer_address", "buyer_country", "buyer_email", "notify_party", "origin_code",
              "origin_name", "destination_code", "destination_name", "incoterms", "currency",
              "payment_terms", "shipping_marks", "other_references", "container_no", "lc_no",
              "buyer", "remarks")
ITEM_KEYS = ("product_description", "hs_code", "package_type", "quantity", "length_cm",
             "width_cm", "height_cm", "weight_per_package_kg", "net_weight_kg", "unit_price",
             "amount")


def _clean_draft(raw) -> dict:
    """브라우저가 들고 온 초안. 아는 칸만 받고 길이를 자릅니다."""

    raw = raw if isinstance(raw, dict) else {}
    draft = {key: str(raw.get(key) or "").strip()[:500] for key in DRAFT_KEYS
             if _has(raw.get(key))}
    draft["items"] = [{key: str(row.get(key) or "").strip()[:300] for key in ITEM_KEYS
                       if _has(row.get(key))}
                      for row in _items(raw)[:MAX_ITEMS]]
    return draft


def _state(draft: dict, kinds: list[str], reply: str, **extra) -> dict:
    rows = missing(draft, kinds)
    return {"stage": "need_info" if rows else "ready", "reply": reply, "draft": draft,
            "kinds": kinds, "options": KIND_OPTIONS, "missing": rows,
            # 화면이 체크를 바꿀 때마다 서버에 묻지 않고 거를 수 있게 모두 보냅니다.
            "missing_all": missing(draft), **extra}


def start(payload: dict) -> dict:
    """올린 서류에서 읽은 값(form)으로 초안을 만들고 빠진 것을 묻습니다."""

    if not isinstance(payload, dict):
        raise ValidationError("입력을 읽지 못했습니다.", "payload")
    form = payload.get("form") if isinstance(payload.get("form"), dict) else {}
    draft = _clean_draft({**(form.get("fields") or {}), "items": form.get("items") or []})
    requested = clean_kinds(payload.get("kinds"))
    kinds = requested or list(DEFAULT_KINDS)
    label = _clean(payload.get("document_label"), 80) or "서류"
    rows = missing(draft, kinds)
    reply = ask_message(rows, f"업로드해주신 {label}에서")
    if requested:
        # "인보이스 써줘"처럼 서류를 짚어 말했으면 그 서류 기준으로 봤다고 먼저 알립니다.
        titles = ", ".join(_title(kind) for kind in kinds)
        reply = f"요청하신 **{titles}** 기준으로 확인했습니다.\n\n" + reply
    return _state(draft, kinds, reply)


def _title(kind: str) -> str:
    label = next(row["label"] for row in KIND_OPTIONS if row["kind"] == kind)
    return label.replace("기타 지원 서류 · ", "")


# --- 무엇을 해 달라는 말인지 ------------------------------------------------------------

# "프로포마 인보이스"를 상업송장으로 잘못 읽지 않게 먼저 보고 지웁니다.
_KIND_PATTERNS = [
    ("proforma_invoice", re.compile(
        r"(?:프로\s*포마|proforma|pro-forma|견적\s*송장)(?:\s*(?:인보이스|invoice))?"
        r"|(?<![A-Za-z])P/?I(?![A-Za-z])", re.I)),
    ("shipping_instruction", re.compile(
        r"선적\s*의뢰|쉬핑\s*(?:리퀘스트|인스트럭션)|shipping\s*(?:request|instruction)"
        r"|(?<![A-Za-z])S/?[RI](?![A-Za-z])", re.I)),
    ("packing_list_std", re.compile(
        r"패킹|포장\s*명세|packing|(?<![A-Za-z])P/?L(?![A-Za-z])", re.I)),
    ("commercial_invoice", re.compile(
        r"상업\s*송장|커머셜|인보이스|invoice|송장|(?<![A-Za-z])C/?I(?![A-Za-z])", re.I)),
]
# 만들어 달라는 말. "인보이스 작성 방법 알려줘"는 묻는 말이라 여기에 걸리지 않아야 합니다.
_MAKE_PATTERN = re.compile(
    r"(?:만들어|작성해|써|적어|발행해|생성해|뽑아|출력해|준비해|채워)\s*(?:줘|주세요|주시|줄래|주라|봐|달라|드려)"
    r"|(?:만들|작성|생성|발행)\s*(?:해야|할래|하자|합시다|부탁|요청|원해|하고\s*싶)"
    r"|(?:만들기|작성하기|생성하기)|부탁(?:해|드려|드립)"
    r"|(?<![A-Za-z])(?:make|create|draft|write|generate|prepare|issue)(?![A-Za-z])", re.I)


def intent(message: str) -> dict:
    """적은 말이 서류를 만들어 달라는 것인지, 만든다면 어떤 서류인지.

    AI를 쓰지 않습니다. 탭을 옮기는 결정이라 같은 말에는 늘 같게 움직여야 합니다.
    """

    text = str(message or "")[:MAX_MESSAGE]
    kinds, rest = [], text
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(rest):
            kinds.append(kind)
            rest = pattern.sub(" ", rest)
    return {"make": bool(_MAKE_PATTERN.search(text)), "kinds": clean_kinds(kinds)}


# --- 채팅으로 받은 값 합치기 ----------------------------------------------------------

def _key(label: str) -> str:
    return "".join(ch for ch in str(label).lower() if ch.isalnum())


_ALIAS_LOOKUP = {_key(word): key for key, words in ALIASES.items() for word in words}
_ITEM_ALIASES = {
    "unit_price": ("단가", "unitprice", "price", "가격"),
    "amount": ("금액", "amount", "총금액", "품목금액"),
    "quantity": ("수량", "quantity", "qty", "포장개수", "개수"),
    "weight_per_package_kg": ("한상자무게", "포장당무게", "포장당총중량", "한포장무게",
                              "weightperpackage", "상자무게"),
    "product_description": ("품명", "description", "product", "품목명"),
    "dims": ("치수", "크기", "사이즈", "규격", "한상자크기", "포장치수", "상자크기", "dimension",
             "dimensions", "dims", "size"),
}
_ITEM_LOOKUP = {_key(word): key for key, words in _ITEM_ALIASES.items() for word in words}


def _rule_read(message: str, draft: dict) -> dict:
    """"칸 이름: 값" 꼴과 딱 보이는 조건 코드(FOB, USD)는 AI 없이 읽습니다."""

    found: dict = {"items": {}}
    for line in message.splitlines():
        if ":" not in line and "：" not in line:
            continue
        label, _, value = line.replace("：", ":").partition(":")
        # "1. 인코텀즈: FOB" — 묻는 말의 번호를 붙여 칸 이름까지 적은 경우. 번호는 떼고 봅니다.
        label = re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", label)
        value = value.strip()
        if not value:
            continue
        # "품목 2 단가: 5" / "2번 단가: 5" 처럼 품목 번호를 붙일 수 있습니다.
        number = re.search(r"(\d+)\s*(?:번|품목)|품목\s*(\d+)", label)
        bare = _key(re.sub(r"(\d+)\s*(?:번|품목)|품목\s*\d+", "", label))
        if bare in _ALIAS_LOOKUP:
            found[_ALIAS_LOOKUP[bare]] = value
        elif bare in _ITEM_LOOKUP:
            line_no = int(next(g for g in number.groups() if g)) if number else 1
            key = _ITEM_LOOKUP[bare]
            target = found["items"].setdefault(line_no, {})
            if key == "dims":
                match = DIMS_PATTERN.search(value)
                if match:
                    target.update(dict(zip(DIMS, match.groups())))
            else:
                target[key] = value

    # \b는 쓰지 않습니다. 한글도 글자로 쳐서 "CIF로"의 F 뒤에 경계가 없다고 봅니다.
    upper = message.upper()
    if "incoterms" not in found:
        codes = [code for code in INCOTERMS if re.search(rf"(?<![A-Z]){code}(?![A-Z])", upper)]
        if len(codes) == 1:
            found["incoterms"] = codes[0]
    if "currency" not in found:
        codes = [code for code in ("USD", "EUR", "KRW", "JPY", "CNY", "GBP")
                 if re.search(rf"(?<![A-Z]){code}(?![A-Z])", upper)]
        if len(codes) == 1:
            found["currency"] = codes[0]

    return found


NUMBERED_LINE = re.compile(r"^\s*(\d{1,2})\s*(?:[.)]|번\s*[.)]?)\s*(.+?)\s*$")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _asked_keys(asked, draft: dict, kinds: list[str]) -> list[str]:
    """물어본 목록의 순서. 화면이 보여 준 목록(asked)을 돌려받으면 그것을 씁니다.

    묻고 나서 사람이 서류 체크를 바꾸면 missing(draft, kinds)의 순서가 달라집니다.
    번호는 사람이 본 목록을 따라야 합니다. 모르는 칸 이름이 섞여 있으면 버립니다.
    """

    if isinstance(asked, list) and asked and all(key in REQUIRED for key in asked):
        return list(asked)[:len(REQUIRED)]
    return [row["key"] for row in missing(draft, kinds)]


def _numbered_read(message: str, draft: dict, order: list[str], found: dict,
                   notes: list) -> None:
    """"1. 1 Test Ave…" / "2. FOB" — 묻는 말의 번호에 맞춰 적은 답을 그 칸으로 읽습니다.

    번호는 ask_message가 보여 준 순서(order)입니다. 서버가 상태를 갖지 않으므로
    화면이 돌려준 목록을 쓰고, 없으면 같은 초안·같은 서류로 다시 셉니다.
    칸 이름까지 적은 줄("1. 인코텀즈: FOB")은 _rule_read가 읽었으니 건너뜁니다.
    """

    rows = [{"key": key} for key in order]
    items = _items(draft)
    for line in message.splitlines():
        match = NUMBERED_LINE.match(line)
        if not match or re.match(r"^[^:：]{1,20}[:：]", match.group(2)):
            continue
        no, value = int(match.group(1)), match.group(2).strip()
        if not 1 <= no <= len(rows):
            continue
        key = rows[no - 1]["key"]
        if not key.startswith("items."):
            if key in ("incoterms", "currency"):
                # "FOB로 해주세요"에서 조건 코드만. 없으면 적은 그대로 두어 검증에서 걸러지게 합니다.
                codes = INCOTERMS if key == "incoterms" else _currencies()
                code = next((c for c in codes
                             if re.search(rf"(?<![A-Z]){c}(?![A-Z])", value.upper())), "")
                value = code or value
            found.setdefault(key, value)
            continue
        if len(items) > 1:
            notes.append(f"{no}번은 품목이 {len(items)}줄이라 어느 줄인지 알 수 없어 넣지 않았습니다. "
                         f"'2번 단가: 5'처럼 품목 번호를 붙여 적어 주세요.")
            continue
        target = found["items"].setdefault(1, {})
        field = key.split(".", 1)[1]
        if field == "dims":
            dims = DIMS_PATTERN.search(value)
            if dims:
                for name, number in zip(DIMS, dims.groups()):
                    target.setdefault(name, number)
            else:
                notes.append(f"{no}번 포장 치수는 '40x30x25'처럼 가로x세로x높이(cm)로 적어 주세요.")
        elif field == "product_description":
            target.setdefault("product_description", value)
        else:
            number = _NUMBER.search(value)
            if not number:
                notes.append(f"{no}번 '{value[:40]}'에서 숫자를 찾지 못해 넣지 않았습니다.")
                continue
            name = {"quantity": "quantity", "weight": "weight_per_package_kg"}.get(field)
            if field == "price":
                name = "amount" if re.search(r"금액|총|amount|total", value, re.I) else "unit_price"
            target.setdefault(name, number.group(0).replace(",", ""))


def _single_line_guess(message: str, draft: dict, found: dict) -> None:
    """빠진 글자 칸이 하나뿐이고 한 줄로 적었으면 그 칸의 값으로 봅니다. (주소만 적는 경우)

    마지막에 씁니다. AI가 그 칸을 뽑아 왔으면 AI 쪽이 더 정확합니다.
    ("주소는 1 Test Ave…" 전체를 주소로 넣으면 안 됩니다)
    """

    single = message.strip()
    if "\n" in single or ":" in single or len(single) < 3:
        return
    if any(key in found for key in TEXT_KEYS) or any(found.get("items", {}).values()):
        return
    if any(key in found for key in ("incoterms", "currency", "origin_code", "destination_code")):
        return
    text_missing = [key for key in TEXT_KEYS if key in {row["key"] for row in missing(draft)}]
    if len(text_missing) == 1:
        found[text_missing[0]] = single


def _ai_read(message: str, draft: dict) -> dict:
    """글에서 값을 뽑습니다. 키가 없거나 실패하면 빈 값입니다. (규칙으로 읽은 것은 남습니다)"""

    if not ai_client.available():
        return {}
    lines = "\n".join(f"{no}. {row.get('product_description') or '(품명 없음)'}"
                      for no, row in enumerate(_items(draft), 1)) or "(아직 품목이 없습니다)"
    result = ai_client.structured_chat(
        [{"role": "system", "content": MERGE_PROMPT.format(items=lines)},
         {"role": "user", "content": message}],
        MERGE_SCHEMA, name="trade_document_merge", max_tokens=1200,
        model=get_config("AI_DOC_MODEL", ai_client.MODEL), timeout=40)
    if not result["success"]:
        return {}
    raw = result["data"]
    found: dict = {"items": {}}
    for key in TEXT_KEYS + ("incoterms", "currency", "payment_terms"):
        if _has(raw.get(key)):
            found[key] = raw[key]
    if _has(raw.get("port_of_loading")):
        found["origin_code"] = raw["port_of_loading"]
    if _has(raw.get("port_of_discharge")):
        found["destination_code"] = raw["port_of_discharge"]
    count = len(_items(draft))
    for row in raw.get("items") or []:
        if not isinstance(row, dict):
            continue
        line_no = row.get("line") or (1 if count <= 1 else None)
        if not line_no:
            continue
        values = {key: row[key] for key in ("product_description", "quantity", "unit_price",
                                            "amount", "weight_per_package_kg",
                                            "gross_weight_kg", "net_weight_kg", "package_unit",
                                            *DIMS)
                  if row.get(key) is not None}
        if values:
            found["items"].setdefault(int(line_no), {}).update(values)
    return found


def _apply(draft: dict, found: dict, notes: list) -> list[str]:
    """읽은 값을 검증해 초안에 넣습니다. 사람이 적은 값이 서류에서 읽은 값보다 우선입니다.

    돌려주는 것은 반영한 칸의 이름입니다. 무엇이 들어갔는지 사람에게 알려 줍니다.
    """

    applied = []
    mode = draft.get("transport_mode") or "SEA"

    for key in TEXT_KEYS:
        if _has(found.get(key)):
            draft[key] = _clean(str(found[key]), 500)
            applied.append(key)
    if _has(found.get("payment_terms")):
        terms = _payment_terms(str(found["payment_terms"]))
        if terms:
            draft["payment_terms"] = terms
            applied.append("payment_terms")

    if _has(found.get("incoterms")):
        code = _pick(found["incoterms"], INCOTERMS)
        if code:
            draft["incoterms"] = code
            applied.append("incoterms")
        else:
            notes.append(f"'{found['incoterms']}'는 Incoterms 2020 조건이 아니라 넣지 않았습니다. "
                         "FOB·CIF·EXW 같은 세 글자 조건으로 적어 주세요.")
    if _has(found.get("currency")):
        code = _pick(found["currency"], _currencies())
        if code:
            draft["currency"] = code
            applied.append("currency")
        else:
            notes.append(f"통화 '{found['currency']}'는 고를 수 있는 통화가 아닙니다.")

    for role in ("origin", "destination"):
        key = f"{role}_code"
        if _has(found.get(key)):
            place = _port(found[key], mode, role, notes)
            if place:
                draft[key] = place["code"]
                draft[f"{role}_name"] = f"{place['name']} ({place['code']})"
                applied.append(key)

    items = _items(draft)
    for line_no, values in sorted((found.get("items") or {}).items()):
        if line_no < 1 or line_no > MAX_ITEMS:
            continue
        if line_no > len(items):
            if line_no == len(items) + 1 and _has(values.get("product_description")):
                items.append({})
            else:
                notes.append(f"품목 {line_no}은(는) 없는 줄이라 넣지 않았습니다.")
                continue
        _apply_item(items[line_no - 1], values, line_no, notes, applied)
    draft["items"] = items
    return applied


def _apply_item(row: dict, values: dict, no: int, notes: list, applied: list) -> None:
    label = f"품목 {no}"
    if _has(values.get("product_description")):
        row["product_description"] = _clean(str(values["product_description"]), 300)
        applied.append("items.product_description")
    for key, name in (("quantity", "수량"), ("unit_price", "단가"), ("amount", "금액"),
                      ("weight_per_package_kg", "한 포장 무게"), ("net_weight_kg", "순중량"),
                      ("length_cm", "가로"), ("width_cm", "세로"), ("height_cm", "높이")):
        if values.get(key) is not None and _has(values.get(key)):
            number = _amount(values[key], f"{label} {name}", notes)
            if number:
                row[key] = number
                applied.append({"unit_price": "items.price", "amount": "items.price",
                                "weight_per_package_kg": "items.weight",
                                "length_cm": "items.dims", "width_cm": "items.dims",
                                "height_cm": "items.dims"}.get(key, f"items.{key}"))
    if _has(values.get("package_unit")):
        kind = _package_type({"package_unit": values["package_unit"]})
        if kind:
            row["package_type"] = kind
    # 줄 전체 무게만 적었으면 포장 개수로 나눕니다. (document_extract_service와 같은 규칙)
    gross = values.get("gross_weight_kg")
    if gross is not None and not values.get("weight_per_package_kg"):
        total = _amount(gross, f"{label} 총중량", notes)
        if total and _has(row.get("quantity")) and float(row["quantity"]) > 0:
            each = float(total) / float(row["quantity"])
            row["weight_per_package_kg"] = f"{each:.3f}".rstrip("0").rstrip(".")
            applied.append("items.weight")
    # 단가만 있으면 금액은 단가 × 수량입니다. 송장 합계가 맞아야 합니다.
    if _has(row.get("unit_price")) and not _has(row.get("amount")) and _has(row.get("quantity")):
        try:
            total = float(row["unit_price"]) * float(row["quantity"])
        except ValueError:
            return
        row["amount"] = f"{total:.2f}".rstrip("0").rstrip(".")
        notes.append(f"{label} 금액은 단가 × 수량({row['unit_price']} × {row['quantity']})으로 "
                     "계산했습니다. 단가가 개당 가격이면 수량을 개수로 고쳐 주세요.")


def merge(payload: dict) -> dict:
    """채팅으로 적은 값을 초안에 합치고, 아직 빠진 것을 다시 짚습니다."""

    if not isinstance(payload, dict):
        raise ValidationError("입력을 읽지 못했습니다.", "payload")
    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValidationError("빠진 정보를 적어 주세요.", "message")
    if len(message) > MAX_MESSAGE:
        raise ValidationError(f"{MAX_MESSAGE:,}자 아래로 줄여 주세요.", "message")

    draft = _clean_draft(payload.get("draft"))
    kinds = clean_kinds(payload.get("kinds")) or list(DEFAULT_KINDS)
    notes: list[str] = []

    found = _rule_read(message, draft)
    _numbered_read(message, draft, _asked_keys(payload.get("asked"), draft, kinds), found, notes)
    # 규칙으로 못 읽은 것만 AI에게 맡깁니다. 규칙으로 읽은 값이 우선입니다.
    ai = _ai_read(message, draft)
    for key, value in ai.items():
        if key == "items":
            for line_no, values in value.items():
                merged = {**values, **found["items"].get(line_no, {})}
                found["items"][line_no] = merged
        elif key not in found:
            found[key] = value
    _single_line_guess(message, draft, found)

    applied = _apply(draft, found, notes)
    labels = []
    for key in applied:
        label = (REQUIRED.get(key) or {}).get("label") or {
            "notify_party": "통지처(Notify Party)", "payment_terms": "결제 조건"}.get(key, "")
        if label and label not in labels:
            labels.append(label)

    rows = missing(draft, kinds)
    if not labels:
        head = ("적어 주신 내용에서 서류에 넣을 값을 찾지 못했습니다. "
                "**칸 이름: 값** 꼴로 한 줄씩 적어 주시면 정확하게 반영됩니다.")
    else:
        head = f"받았습니다. **{', '.join(labels)}**을(를) 반영했습니다."
    reply = head + "\n\n" + ask_message(rows, "다만 아직")
    return _state(draft, kinds, reply, notes=notes, applied=labels)


# --- 만들기 -----------------------------------------------------------------------

def _render_draft(draft: dict) -> dict:
    """draft_document_service가 읽는 초안 모양으로. 숫자 칸은 숫자로 넘깁니다."""

    rendered = {key: value for key, value in draft.items() if key != "items"}
    rendered["items"] = [dict(row) for row in _items(draft)]
    return rendered


def generate(payload: dict) -> dict:
    """고른 서류만 그립니다. 필수 정보가 빠졌으면 만들지 않고 다시 묻습니다."""

    if not isinstance(payload, dict):
        raise ValidationError("입력을 읽지 못했습니다.", "payload")
    draft = _clean_draft(payload.get("draft"))
    kinds = clean_kinds(payload.get("kinds"))
    if not kinds:
        raise ValidationError("만들 서류를 하나 이상 골라 주세요.", "kinds")

    rows = missing(draft, kinds)
    if rows:
        # 강행하지 않습니다. 빈 칸이 찍힌 송장은 세관·은행에서 되돌아옵니다.
        return _state(draft, kinds, ask_message(rows, "고르신 서류를 만들기 전에 확인해 보니"))

    try:
        documents = [review_document(kind, _render_draft(draft)) for kind in kinds]
    except ValidationError as exc:
        raise ServiceError(str(exc), "VALIDATION_ERROR") from exc

    titles = " · ".join(doc["title"].split(" (")[0] for doc in documents)
    reply = (f"**{titles}** 초안을 만들었습니다. 미리보기 창에서 오탈자와 수량을 "
             "최종 검토하시고, 고칠 곳은 그 자리에서 고친 뒤 **PDF 다운로드**를 눌러 주세요.")
    if any(doc["undecided"] for doc in documents):
        reply += ("\n\n출항일·선박명은 스케줄을 고르기 전이라 **미정**으로 찍혀 있습니다. "
                  "받은 B/L에 적힌 값이 있으면 미리보기에서 바로 적으셔도 됩니다.")
    return {"stage": "made", "reply": reply, "draft": draft, "kinds": kinds,
            "documents": documents}


def review_document(kind: str, draft: dict) -> dict:
    """검토 창(미리보기)이 쓰는 서류 한 장. 칸 값·표·칸 이름·미리보기 그림.

    대화로 만든 초안(agent_service)도 같은 창에서 검토하므로 여기 한 곳에 둡니다.
    """

    result = drafts.render(kind, draft)
    data = drafts.as_text(result["data"])
    return {
        "kind": kind, "title": result["title"], "data": data, "columns": result["columns"],
        "fields": [{"key": name, "label": _label(kind, name)} for name in drafts.fields_for(kind)],
        "missing": result["missing"], "undecided": result["undecided"],
        "preview": drafts.preview_data(kind, data),
    }


def _label(kind: str, name: str) -> str:
    from app.services import document_service

    return document_service.field_label("packing_list" if kind == "packing_list_std" else kind,
                                        name)
