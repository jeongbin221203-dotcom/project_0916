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

from functools import lru_cache

import json
import re
from datetime import date

from app.collectors import ai_client, location_client
from app.processors import bank_redaction, document_defaults
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


# 달 이름. 서류에는 SEP · Sept · September 가 섞여 나옵니다.
MONTH_WORDS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# 숫자만으로 적어 뜻이 두 가지인 날짜. 이런 모양이면 비워 둡니다.
AMBIGUOUS_DATE = re.compile(r"^\s*\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{2,4}\s*$")


def _as_iso(text: str) -> str:
    """서류에 적힌 날짜를 ISO 로 바꿉니다. 뜻이 하나로 정해질 때만 바꿉니다.

    못 바꾸면 받은 글을 그대로 돌려줍니다 (parse_date 가 다시 봅니다).
    """

    raw = str(text or "").strip()
    if not raw:
        return raw

    # 연도가 앞: 2027.04.28 · 2027/04/28 · 2027-04-28
    head = re.match(r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})$", raw)
    if head:
        year, month, day = (int(part) for part in head.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"

    # 여덟 자리 숫자: 20270428
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"

    # 달이 글자: 29-SEP-2027 · 29 Sep 2027 · September 29, 2027 · 29 September 2027
    words = re.findall(r"[A-Za-z]+|\d+", raw)
    month = next((MONTH_WORDS[word[:3].lower()] for word in words
                  if word[:3].lower() in MONTH_WORDS and word.isalpha()), 0)
    if month:
        numbers = [int(word) for word in words if word.isdigit()]
        years = [n for n in numbers if n >= 1000]
        days = [n for n in numbers if 1 <= n <= 31]
        if len(years) == 1 and days:
            return f"{years[0]:04d}-{month:02d}-{days[0]:02d}"
    return raw


def _incoterms_word(value) -> str:
    """가격조건 칸에 붙어 오는 군더더기를 떼어 냅니다.

    서류에는 이렇게 적혀 옵니다.
        C.I.F.               점을 찍습니다
        FOB Incoterms 2020   규칙 이름을 붙입니다
        FOB Busan            지명을 붙입니다 (지명은 incoterms_place 가 따로 받습니다)
    맨 앞 낱말만 보고, 그것이 우리가 아는 조건일 때만 씁니다.
    """

    raw = str(value or "").replace(".", " ").strip()
    if not raw:
        return ""
    if raw.upper() in INCOTERMS:
        return raw.upper()
    # 점을 떼면 "C I F" 가 되므로 한 글자씩인 경우를 먼저 붙여 봅니다.
    letters = "".join(raw.split())
    if letters.upper() in INCOTERMS:
        return letters.upper()
    first = raw.split()[0].upper()
    return first if first in INCOTERMS else ""


def _date(value, notes: list, label: str) -> str:
    """날짜로 읽히고 지난 날이 아닐 때만 씁니다."""

    if not value:
        return ""
    if AMBIGUOUS_DATE.match(str(value)):
        # 02/06/2027 은 영국식이면 6월 2일, 미국식이면 2월 6일입니다.
        # 서류만 보고는 알 수 없습니다. 넉 달을 잘못 잡으면 선적이 어긋납니다.
        notes.append(f"{label} '{str(value).strip()}'은(는) 일/월 차례를 알 수 없어 "
                     "비워 두었습니다. (2월 6일인지 6월 2일인지 서류만으로는 "
                     "가릴 수 없습니다) 달력에서 직접 골라 주세요.")
        return ""
    try:
        parsed = parse_date(_as_iso(value), label)
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


# 도시 이름으로 부르는 국내 공항. 자료에는 공항 이름만 있어 도시로는 안 찾힙니다.
# ("부산"으로 항공을 적으면 자료의 "김해국제공항"을 못 찾습니다)
KR_CITY_AIRPORT = {
    "부산": "PUS", "김해": "PUS",
    "서울": "ICN", "인천": "ICN", "김포": "GMP",
    "대구": "TAE", "청주": "CJJ", "제주": "CJU",
}


# 2000년 로마자 표기법이 바뀌기 전 이름. 바깥 바이어가 만든 서류에는 아직
# 옛 표기가 나옵니다. **표기법이 바뀐 것만** 넣습니다 — 짐작으로 별명을 더하면
# 그만큼 잘못 잡을 자리가 늘어납니다. (2026-09-27)
OLD_ROMAN = {
    "pusan": "Busan",
    "inchon": "Incheon",
    "kwangyang": "Gwangyang",
    "ulsan": "Ulsan",          # 표기가 그대로인 곳. 찾기 쉬우라고 함께 둡니다.
}


# 항구 이름에 곁들여 적히는 낱말. 이것만 떼어 냅니다.
# city · terminal · new 는 넣지 않습니다 — 지명의 일부일 수 있습니다
# (Ho Chi Minh City, Angeles City, New York).
PORT_WORDS = {"port", "ports", "of", "seaport", "harbour", "harbor", "항", "항구"}

# 나라를 줄여 적는 말. 항구표의 나라 이름에는 없는 표기입니다.
COUNTRY_SHORT = {"usa", "u.s.a.", "u.s.", "us", "uk", "u.k.", "prc", "rok", "rok.",
                 "korea", "vietnam", "america"}


def _drop_words(text: str, known: frozenset[str] | set[str]) -> str:
    """주어진 낱말만 떼어 냅니다. 뗄 것이 없거나 남는 것이 없으면 그대로 둡니다."""

    pieces = [piece for piece in str(text or "").replace(",", " ").split() if piece]
    kept = [piece for piece in pieces if piece.strip(".").casefold() not in known]
    if not kept or len(kept) == len(pieces):
        return str(text or "")
    return " ".join(kept)


@lru_cache(maxsize=1)
def _country_words() -> frozenset[str]:
    """항구표에 실제로 들어 있는 나라 이름을 낱말로 풀어 모읍니다.

    표를 그대로 쓰므로 나라가 늘어도 따로 손볼 것이 없습니다.
    '대한민국' · 'Korea, Republic of' · '미국' · 'United States of America' ...
    """

    words: set[str] = set(COUNTRY_SHORT) | set(PORT_WORDS)
    for kind in ("port", "airport"):
        result = location_client.search_locations("", kind, None, None)
        for row in (result.get("data") or []):
            for key in ("country", "country_en"):
                name = str(row.get(key) or "")
                for piece in name.replace(",", " ").split():
                    piece = piece.strip().casefold()
                    if len(piece) >= 2:
                        words.add(piece)
    return frozenset(words)


def _collapse_repeats(text: str) -> str:
    """같은 낱말이 잇따르면 한 번만 남깁니다.

    싱가포르·모나코·파나마처럼 **항구 이름과 나라 이름이 같은 곳**은
    "Singapore Singapore" 로 적혀 옵니다. 쉼표가 있으면 앞만 잘라 쓰면 되지만,
    쉼표 없이 붙여 적는 서류도 있습니다. (2026-09-27)
    """

    pieces = str(text or "").split()
    kept = [piece for no, piece in enumerate(pieces)
            if no == 0 or piece.casefold() != pieces[no - 1].casefold()]
    return " ".join(kept)


def _shorter_names(text: str) -> list[str]:
    """해 볼 만한 짧은 이름들. 찾을 때까지 차례로 써 봅니다.

    한 가지만 고르면 안 됩니다. 곁말과 나라 이름은 서로 겹칩니다 —
    'of' 는 곁말("Port of Busan")이면서 나라 이름의 일부("Republic of Korea")
    입니다. 곁말만 떼고 멈추면 "Busan Republic Korea" 가 되어 어디에도
    없습니다. 그래서 셋을 다 내놓습니다. (2026-09-27)

    셋 다 **글자를 덜어내기만** 합니다. 새로 짓지 않으므로 엉뚱한 곳에
    들어맞는 길이 늘어나지 않습니다.

    싱가포르·모나코·파나마처럼 나라와 항구 이름이 같은 곳은 나라 이름을
    떼면 남는 글자가 없어, _drop_words 가 원래 글을 그대로 돌려줍니다.
    """

    original = str(text or "")
    tries = [
        _drop_words(original, PORT_WORDS),                   # "Port of Singapore" -> "Singapore"
        _drop_words(original, _country_words()),             # "Los Angeles USA"   -> "Los Angeles"
        _drop_words(_drop_words(original, PORT_WORDS),
                    _country_words()),                       # "Busan Republic of Korea" -> "Busan"
        _collapse_repeats(original),                         # "Singapore Singapore" -> "Singapore"
    ]
    found: list[str] = []
    for name in tries:
        if name and name.casefold() != original.casefold() and name not in found:
            found.append(name)
    return found


def _drop_country_words(text: str) -> str:
    """가장 짧게 줄인 이름 하나. (띄어쓰기를 지워 견줄 때 씁니다)"""

    tries = _shorter_names(text)
    return min(tries, key=len) if tries else str(text or "")


@lru_cache(maxsize=2)
def _squashed_index(kind: str) -> dict:
    """띄어쓰기를 지운 이름 -> 그 곳. 서류마다 띄어쓰기가 달라서 필요합니다.

    "Los Angeles" 와 "LosAngeles", "Hai Phong" 과 "Haiphong" 을 같은 곳으로
    봅니다. 글자는 그대로라 엉뚱한 곳에 들어맞지 않습니다.
    먼저 들어온 것을 남깁니다 (표가 물동량 순서라 큰 항구가 앞에 옵니다).
    """

    found: dict = {}
    result = location_client.search_locations("", kind, None, None)
    for row in (result.get("data") or []):
        for key in ("name", "name_en", "city", "city_en"):
            name = "".join(str(row.get(key) or "").split()).casefold()
            if len(name) >= 3:
                found.setdefault(name, row)
    return found


def _fits_role(row: dict, role: str) -> bool:
    """수출이라 출발은 국내, 도착은 바깥입니다. (planning_service 와 같은 규칙)"""

    korean = str(row.get("country_code") or "") == "KR"
    return korean if role == "origin" else not korean


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
    # 서류에는 "Busan, Korea"처럼 나라가 붙어 옵니다. 그대로는 목록에 없으니
    # 쉼표 앞("Busan")만 다시 찾습니다.
    if not rows and "," in text:
        head = text.split(",")[0].strip()
        if head:
            again = planning_service.search_locations(head, transport_mode, role)
            rows = again["data"] if again["success"] else []
    # "미국 로스앤젤레스", "Los Angeles USA", "Port of Busan"처럼 나라 이름이나
    # 항구를 뜻하는 곁말이 붙은 경우. **그 낱말만** 떼고 한 번 더 찾습니다.
    #
    # 예전에는 앞 낱말·뒤 낱말을 가리지 않고 떼었습니다. 남은 한 낱말이 짧으면
    # 아무 데나 들어맞아, 엉뚱한 나라의 항구가 조용히 채워졌습니다. (2026-09-27)
    #     "Phong Nha, Vietnam"        -> 'Nha'  -> 나바셰바항(인도)
    #     "Hai Duong, Vietnam"        -> 'Hai'  -> 하이퐁항
    #     "Angeles City, Philippines" -> 'City' -> 호찌민항
    # 뗄 것이 없으면 더 짐작하지 않고 빈 칸으로 둡니다.
    if not rows:
        for shorter in _shorter_names(text):
            again = planning_service.search_locations(shorter, transport_mode, role)
            rows = again["data"] if again["success"] else []
            if rows:
                notes.append(f"{label} '{text}'을(를) '{shorter}'(으)로 찾았습니다. 맞는지 봐 주세요.")
                break
    # 옛 로마자 표기(Pusan · Inchon)를 지금 이름으로 바꿔 한 번 더 봅니다.
    if not rows:
        renamed = OLD_ROMAN.get("".join(_drop_country_words(text).split()).casefold())
        if renamed:
            again = planning_service.search_locations(renamed, transport_mode, role)
            rows = again["data"] if again["success"] else []
            if rows:
                notes.append(f"{label} '{text}'은(는) 옛 표기로 보고 "
                             f"{rows[0]['name']}({rows[0]['code']})로 넣었습니다. 맞는지 봐 주세요.")

    # 띄어쓰기만 다른 경우. 항구표는 VNHPH 를 'Haiphong' 한 낱말로 담고 있는데,
    # 서류에는 'Hai Phong' 으로 적혀 옵니다(표본 다섯 장이 그렇습니다).
    # 띄어쓰기를 지우고 한 번 더 봅니다. 낱말을 떼는 것과 달리 **글자가 하나도
    # 줄지 않아** 엉뚱한 곳에 들어맞지 않습니다. (2026-09-27)
    if not rows:
        squashed = "".join(_drop_country_words(text).split())
        if len(squashed) >= 3 and squashed.casefold() != text.casefold():
            again = planning_service.search_locations(squashed, transport_mode, role)
            rows = again["data"] if again["success"] else []
        # 표 쪽 띄어쓰기도 지우고 견줍니다. 서류가 "LosAngeles" 라고 붙여 쓰면
        # 표의 'Los Angeles' 와 안 맞기 때문입니다. 위와 반대 방향입니다.
        if not rows and len(squashed) >= 3:
            hit = _squashed_index(kind).get(squashed.casefold())
            if hit and _fits_role(hit, role):
                rows = [hit]

    # 공항은 **도시 이름으로 부르는데 자료에는 공항 이름만** 있습니다.
    # 부산 공항은 자료에 "김해국제공항"이라 "부산"으로는 안 나옵니다. 그래서
    # "부산에서 항공으로"라고 적으면 출발 공항이 통째로 비었습니다. (2026-09-26)
    if not rows and kind == "airport":
        code = KR_CITY_AIRPORT.get(text.replace(" ", ""))
        found = location_client.find_location(code) if code else None
        if found and found["kind"] == "airport":
            notes.append(f"{label} '{text}'은(는) {found['name']}({found['code']})으로 봤습니다. "
                         "다른 공항이면 알려 주세요.")
            return found
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
        # 키 이름은 운영하는 사람의 말입니다. 이용자에게는 할 일만 알려 줍니다.
        raise ServiceError("지금은 붙여 넣으신 글을 자동으로 읽어 드릴 수 없습니다. "
                           "칸을 직접 채워 주시면 나머지는 그대로 만들어 드립니다.")

    prompt = EXTRACT_PROMPT.format(today=date.today().isoformat())
    # 계좌번호·SWIFT는 AI로 보내지 않습니다. (붙여 넣은 오퍼 글에 섞여 오는 일이 흔합니다)
    sent = bank_redaction.strip_bank_numbers(written)[0]
    answer = ai_client.chat([{"role": "system", "content": prompt},
                             {"role": "user", "content": sent}], max_tokens=900)
    if not answer["success"]:
        raise ServiceError(answer["message"])

    raw = _json_from(answer["data"])
    notes: list[str] = []

    mode = _pick(raw.get("transport_mode"), {"SEA", "AIR"}) or "SEA"
    draft: dict = {
        "transport_mode": mode,
        "sea_mode": _pick(raw.get("sea_mode"), {"FCL", "LCL"}),
        "departure_date": _date(raw.get("departure_date"), notes, LABELS["departure_date"]),
        "incoterms": _incoterms_word(raw.get("incoterms")),
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
    # 견적명은 서류 작성 화면에 칸이 있습니다. 지어 둔 이름을 그대로 넘겨
    # 자리표시가 아니라 채워진 값으로 보여 주고, 사람이 고쳐 쓸 수 있게 합니다.
    return {"fields": {key: value for key, value in form.items() if value},
            "items": draft["cargo_lines"]}


def _currencies() -> set:
    from app.collectors import exchange_client

    return {row["code"] for row in exchange_client.list_currencies()}


def _default_name(draft: dict, first_item: dict) -> str:
    """`미국_치약_20261105`. 없으면 빈 값입니다.

    이름 모양은 서류 작성 화면과 같아야 합니다. 같은 건을 어디서 만들었느냐에
    따라 목록의 이름 모양이 달라지면 대시보드에서 줄을 훑기 어렵습니다.
    (processors/document_defaults.project_name)
    """

    place = draft["destination"] or {}
    where = location_client.country_name(place.get("country_code", "")) or place.get("name", "")
    what = first_item.get("product_description", "")
    if not where and not what:
        return ""
    return document_defaults.project_name(where, what, draft.get("departure_date"))


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
