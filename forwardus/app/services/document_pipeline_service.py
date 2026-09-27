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

from app.collectors import ai_client, location_client
from app.collectors.base_client import get_config
from app.processors import bank_redaction, document_defaults
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
    "packing_list_std": ["exporter_name", "exporter_address", "buyer_name", "buyer_address",
                         "origin_code", "destination_code",
                         "items.product_description", "items.quantity", "items.weight",
                         "items.dims"],
    "shipping_instruction": ["exporter_name", "exporter_address", "buyer_name", "buyer_address",
                             "origin_code", "destination_code",
                             "items.product_description", "items.quantity", "items.weight",
                             "items.dims"],
    "proforma_invoice": ["exporter_name", "exporter_address", "buyer_name", "buyer_address",
                         "origin_code", "destination_code",
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
    # 서식에만 있는 칸. 파일에 없어도 채팅으로 적으면 서류 작성 화면까지 그대로 갑니다.
    "buyer_country": ("바이어국가", "수입국", "도착국가", "buyercountry", "국가코드"),
    "buyer_email": ("바이어이메일", "이메일", "buyeremail", "email"),
    "buyer": ("실제바이어", "대금지급처", "otherbuyer", "buyerifotherthanconsignee"),
    "incoterms_place": ("인코텀즈장소", "가격조건장소", "인도장소", "incotermsplace"),
    "shipping_marks": ("화인", "쉬핑마크", "shippingmarks", "marks"),
    "lc_no": ("lc번호", "신용장번호", "lcno", "신용장"),
    "other_references": ("기타참조", "참조", "otherreferences", "reference"),
    "container_no": ("컨테이너번호", "컨테이너", "containerno", "container"),
    "remarks": ("비고", "remarks", "특이사항"),
    "comments": ("포장명세서비고", "코멘트", "comments"),
    "consignee_city_zip": ("도시주우편번호", "우편번호", "citystatezip", "zip", "citzip"),
    "attention": ("담당자", "attention", "attn", "수신담당자"),
    "customer_order_no": ("주문번호", "po번호", "pono", "customerorderno", "orderno"),
    "project_name": ("견적명", "문서명", "프로젝트명", "건명", "서류명",
                     "projectname", "quotename", "quotetitle", "documentname"),
}
DIMS = ("length_cm", "width_cm", "height_cm")
# "40x30x25", "40 × 30 × 25cm", "40*30*25", "40cm x 30cm x 25cm"
# 숫자마다 단위가 붙어 있어도 읽습니다. 사람은 보통 "40cm x 30cm x 25cm"라고 적습니다.
DIMS_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:cm|센티|mm)?\s*[x×X*]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:cm|센티|mm)?\s*[x×X*]\s*"
    r"(\d+(?:\.\d+)?)", re.I)
TEXT_KEYS = ("exporter_name", "exporter_address", "buyer_name", "buyer_address", "notify_party")
# 채팅으로 받아 초안에 그대로 넣는 나머지 글자 칸. 이름이 서류 작성 화면의 input name과
# 같아서(FORWARDUS_DOC_FILL) 합친 값이 그 화면의 칸까지 빈칸 없이 이어집니다.
EXTRA_TEXT_KEYS = ("buyer", "shipping_marks", "lc_no", "other_references", "container_no",
                   "remarks", "incoterms_place", "project_name", "buyer_email",
                   "comments", "consignee_city_zip", "attention", "customer_order_no")

MERGE_PROMPT = """사용자가 무역 서류의 내용을 채팅으로 적었습니다.
올린 파일에서 이미 읽어 둔 값이 아래에 있습니다. 사용자가 **고쳐 달라고 하거나
새로 알려 준 값**을 적힌 글에서 뽑아 주세요.

지켜야 할 것
- 글에 **명시적으로 적힌 값만** 뽑습니다. 적히지 않은 칸은 null입니다. 짐작하지 마세요.
- 이미 읽어 둔 값을 그대로 다시 적지 마세요. 사용자가 말한 것만 돌려주면 됩니다.
- exporter_* 는 수출자(Shipper/Seller), buyer_* 는 수입자(Consignee/Buyer)입니다.
- port_of_loading / port_of_discharge 는 적힌 이름 그대로 ("부산", "LA")
- incoterms 는 EXW FCA FAS FOB CFR CIF CPT CIP DAP DPU DDP 중 하나입니다.
  "CIF 마이애미", "FOB 부산"처럼 장소가 붙어 있으면 조건은 incoterms 에,
  장소는 incoterms_place 에 따로 넣으세요. ("CIF 마이애미" -> "CIF", "마이애미")
- currency 는 USD EUR KRW JPY CNY 같은 세 글자 코드
- buyer 는 대금을 내는 곳이 받는 곳(Consignee)과 **다를 때만** 적습니다.
  같다고 했거나 언급이 없으면 null 입니다. "SAME AS CONSIGNEE"라고 적지 마세요.
- project_name 은 사용자가 이 건을 부르겠다고 말한 이름입니다.
  ("견적명은 ABC사 의류 수출 건으로 해줘" -> "ABC사 의류 수출 건")
- 숫자는 단위·쉼표를 떼고 숫자만. 무게는 kg, "1.2톤" -> 1200
- items 는 품목 줄에 대한 값입니다. line 은 1부터 세는 품목 번호입니다.
  품목이 하나뿐이면 line 은 1 입니다. 어느 품목인지 알 수 없으면 그 값은 넣지 마세요.
  length_cm width_cm height_cm 은 한 포장의 가로·세로·높이(cm)입니다. ("40x30x25" -> 40, 30, 25)
  weight_per_package_kg 은 **한 포장** 무게입니다. 줄 전체 무게만 적혔으면 gross_weight_kg 에 넣으세요.

지금 품목 목록:
{items}

파일에서 이미 읽어 둔 값:
{known}"""

_STR = {"type": ["string", "null"]}
_NUM = {"type": ["number", "null"]}


def _object(properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}


MERGE_SCHEMA = _object({
    "exporter_name": _STR, "exporter_address": _STR,
    "buyer_name": _STR, "buyer_address": _STR, "notify_party": _STR,
    "buyer_country": _STR, "buyer_email": _STR, "buyer": _STR,
    "port_of_loading": _STR, "port_of_discharge": _STR,
    "incoterms": _STR, "incoterms_place": _STR, "currency": _STR, "payment_terms": _STR,
    # 서식에만 있는 칸. 파일에 없어도 채팅으로 적으면 서류에 그대로 들어갑니다.
    "shipping_marks": _STR, "lc_no": _STR, "other_references": _STR,
    "container_no": _STR, "remarks": _STR, "comments": _STR,
    "consignee_city_zip": _STR, "attention": _STR, "customer_order_no": _STR,
    # 대시보드에서 이 건을 부를 이름. 서류에는 찍히지 않습니다.
    "project_name": _STR,
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


# 패킹리스트의 중량·포장 수·치수. 품목이 여러 개이면 품목마다 따로 받아야 해서 한 덩어리로 묻습니다.
PACKING_KEYS = ("items.weight", "items.dims", "items.quantity")


def packing_gaps(draft: dict) -> list[dict]:
    """품목마다 비어 있는 패킹 정보. [{"no": 1, "name": "LIPSTICK", "missing": ["총중량", …]}]"""

    gaps = []
    for no, row in enumerate(_items(draft), 1):
        missing_labels = []
        if not _has(row.get("net_weight_kg")):
            missing_labels.append("순중량")
        if not _has(row.get("weight_per_package_kg")):
            missing_labels.append("총중량")
        if not all(_has(row.get(name)) for name in DIMS):
            missing_labels.append("박스 규격")
        if not _has(row.get("quantity")):
            missing_labels.append("박스 수")
        # 순중량만 빠진 줄은 서류가 막히지 않으므로 묻는 대상에서 뺍니다.
        if missing_labels and missing_labels != ["순중량"]:
            gaps.append({"no": no, "name": row.get("product_description") or "(품명 없음)",
                         "missing": missing_labels})
    return gaps


def _uses_packing_block(rows: list[dict], draft: dict | None) -> bool:
    return (draft is not None and len(_items(draft)) >= 2
            and any(row["key"] in PACKING_KEYS for row in rows) and bool(packing_gaps(draft)))


def order_rows(rows: list[dict], draft: dict | None) -> list[dict]:
    """묻는 순서. 패킹 덩어리를 쓰면 패킹 칸은 맨 뒤로 보냅니다. (번호를 맞추려고)"""

    if not _uses_packing_block(rows, draft):
        return rows
    rank = {key: index for index, key in enumerate(PACKING_KEYS)}
    return ([row for row in rows if row["key"] not in rank]
            + sorted((row for row in rows if row["key"] in rank), key=lambda row: rank[row["key"]]))


def _packing_block(draft: dict, intro: str, start_no: int) -> list[str]:
    gaps = packing_gaps(draft)
    count = len(gaps)
    lines = [f"{intro} 품목 {count}종의 세부 패킹 데이터가 확인되지 않습니다. "
             "정확한 패킹리스트 생성을 위해 아래 정보를 채팅창에 적어주세요!",
             f"{start_no}. 품목 {count}개의 각각의 순중량(Net Weight) 및 총중량(Gross Weight)",
             f"{start_no + 1}. 포장 박스 규격(가로 x 세로 x 높이 cm) 및 총 박스(Carton) 수", "",
             "품목별로 비어 있는 것:"]
    lines += [f"- {gap['no']}번 {gap['name']}: {', '.join(gap['missing'])}" for gap in gaps[:MAX_ITEMS]]
    lines += ["", "품목 번호를 앞에 붙여 한 줄씩 적어 주시면 그 품목에 넣습니다. 예:", ""]
    lines += [f"> {gap['no']}번 품목: 순중량 6.5kg, 총중량 8kg, 40x30x25cm, 500박스"
              for gap in gaps[:2]]
    return lines


def ask_message(rows: list[dict], intro: str = "업로드해주신 서류에서",
                draft: dict | None = None) -> str:
    """빠진 것을 번호로 짚어 묻는 말. 20년 차 사수가 옆에서 알려 주는 말투로.

    intro는 문장 머리입니다. ("업로드해주신 오퍼시트에서", "다만 아직")
    사람은 같은 번호를 붙여 답하면 됩니다. merge가 번호를 이 목록 순서로 읽습니다.
    draft를 주면, 품목이 여러 개이고 패킹 정보(중량·박스 수·규격)가 빠졌을 때
    품목 수를 짚어 따로 묻습니다. 품목마다 값이 달라 "3. 8kg"처럼은 답할 수 없습니다.
    """

    if _uses_packing_block(rows, draft):
        other = [row for row in order_rows(rows, draft) if row["key"] not in PACKING_KEYS]
        lines = []
        if other:
            lines = [f"{intro} 아래 {len(other)}가지 정보가 누락되어 있습니다. 번호에 맞춰 "
                     "채팅창에 편하게 입력해 주시면 바로 서류에 반영해 드릴게요!", ""]
            lines += [f"{no}. **{row['label']}** — {row['hint']}" for no, row in enumerate(other, 1)]
            lines.append("")
        lines += _packing_block(draft, "또한" if other else intro, len(other) + 1)
        return "\n".join(lines)

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
              # project_name은 서식의 칸이 아니라 대시보드에서 이 건을 부르는 이름입니다.
              # 챗봇이 서류를 만들기 직전에 한 번 묻고, 초안에 담아 다닙니다.
              "buyer", "remarks", "project_name", "requested_departure_date",
              # "CIF 마이애미"의 장소. 가격 조건은 장소와 함께 적는 것이 맞습니다.
              "incoterms_place",
              # 포장명세서 쪽 칸. 서류 작성 화면의 input name과 이름이 같습니다.
              "comments", "consignee_city_zip", "attention", "customer_order_no")
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
    # 받는 곳(Consignee)과 대금을 내는 곳(Buyer) 가운데 한쪽만 적혀 있으면 서로 메웁니다.
    # 여기서 메워야 "무엇이 빠졌나" 목록에도 빠진 것으로 잡히지 않습니다.
    consignee, buyer = document_defaults.pair_parties(draft.get("buyer_name"),
                                                      draft.get("buyer"))
    if consignee:
        draft["buyer_name"] = consignee
    if buyer:
        draft["buyer"] = buyer
    return draft


def suggest_project_name(draft: dict) -> str:
    """대시보드에서 이 건을 부를 이름. `미국_의류_20260923`.

    서류 작성 화면(document_start_service.suggest_project_name)과 같은 규칙을
    씁니다. 대화로 만들든 칸을 채워 만들든 이름 모양이 같아야 합니다.
    """

    code = str(draft.get("destination_code") or "").strip().upper()
    where = location_client.country_name(code[:2]) if len(code) >= 2 else ""
    items = _items(draft)
    what = str(items[0].get("product_description") or "").strip() if items else ""
    return document_defaults.project_name(where or code, what,
                                          draft.get("requested_departure_date"))


# 서류를 만들기 직전에 챗봇이 묻는 말. 대시보드에서 이 건을 알아보기 위한 이름입니다.
NAME_QUESTION = (
    "마지막으로, 이번 건을 대시보드에서 쉽게 구분하실 수 있도록 **견적명**을 지정해 주세요.\n"
    "(예: `2026-10 멕시코 화장품 1차`, `ABC사 의류 수출 건`)\n\n"
    "채팅창에 원하시는 이름을 적어 주시면 그대로 저장합니다. "
    "그냥 **넘어가기**라고 적으시면 `{suggestion}`(으)로 자동 지정해 드릴게요.")


def name_question(draft: dict) -> str:
    return NAME_QUESTION.format(suggestion=suggest_project_name(draft) or "자동 생성된 이름")


def _state(draft: dict, kinds: list[str], reply: str, ask_name: bool = True, **extra) -> dict:
    rows = order_rows(missing(draft, kinds), draft)
    named = bool(str(draft.get("project_name") or "").strip())
    # 필수 정보가 다 모였고 이름을 아직 안 정했으면, 만들기 전에 한 번 묻습니다.
    # 빠진 정보가 남아 있을 때 같이 물으면 답해야 할 것이 뒤섞입니다.
    awaiting_name = not rows and not named
    if awaiting_name and ask_name:
        reply = f"{reply}\n\n{name_question(draft)}"
    return {"stage": "need_info" if rows else "ready", "reply": reply, "draft": draft,
            "kinds": kinds, "options": KIND_OPTIONS, "missing": rows,
            # 서류를 만들기 직전에 묻는 견적명. 안 적고 넘어가면 이 이름을 씁니다.
            "project_name": str(draft.get("project_name") or ""),
            "project_name_suggestion": suggest_project_name(draft),
            # 화면은 이 값을 보고 다음 채팅을 "견적명 답"으로 보내 줍니다. (home.js)
            "awaiting_name": awaiting_name,
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
    reply = ask_message(rows, f"업로드해주신 {label}에서", draft)
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


# "CIF 마이애미로", "FOB Busan", "CIF 마이애미 조건으로" — 조건 뒤에 붙는 지명.
# 조사와 흔한 뒷말은 이름에서 뗍니다. ("~로 변경해줘")
_PLACE_TAIL = re.compile(r"(?:으?로|에서|조건|기준|변경|바꿔|해\s*줘|해\s*주세요|입니다|이야|야)+$")


def _incoterms_place(message: str, code: str) -> str:
    """가격 조건 코드 바로 뒤에 적힌 장소. 없으면 빈 문자열."""

    match = re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])[\s,]*([^\s,.\n]{{2,30}})",
                      message, re.I)
    if not match:
        return ""
    place = _PLACE_TAIL.sub("", match.group(1)).strip(" ,.-")
    # "CIF 조건으로"처럼 지명이 아닌 말만 남으면 넣지 않습니다.
    return place if len(place) >= 2 and not _PLACE_TAIL.fullmatch(place) else ""


# 품목 줄의 숫자 칸. "500개로 해줘"처럼 뒤에 말이 붙어도 숫자만 떼어 씁니다.
_ITEM_NUMBER_KEYS = ("quantity", "unit_price", "amount", "weight_per_package_kg")
# "…는 15달러야", "…는 부산입니다" — 값 끝에 붙는 서술어. 값에서 뗍니다.
_VALUE_TAIL = re.compile(r"\s*(?:입니다|이에요|예요|에요|이야|야|랍니다|로\s*해\s*줘|"
                         r"로\s*변경(?:해\s*줘)?|으로\s*해\s*줘)\s*[.!~]*\s*$")


def _assign(found: dict, label: str, value: str, line_no: int = 1) -> bool:
    """읽은 "칸 이름 → 값"을 자리에 넣습니다. 아는 칸이면 True."""

    bare = _key(label)
    if bare in _ALIAS_LOOKUP:
        found[_ALIAS_LOOKUP[bare]] = value
        return True
    if bare not in _ITEM_LOOKUP:
        return False
    key = _ITEM_LOOKUP[bare]
    target = found["items"].setdefault(line_no, {})
    if key == "dims":
        match = DIMS_PATTERN.search(value)
        if match:
            target.update(dict(zip(DIMS, match.groups())))
        return True
    if key in _ITEM_NUMBER_KEYS:
        # 숫자 칸은 숫자만 남깁니다. "15달러"를 그대로 넘기면 읽지 못했다고 되묻습니다.
        number = _NUMBER.search(value)
        if not number:
            return True
        value = number.group(0).replace(",", "")
    target[key] = value
    return True


# "수량은", "단가는" — 칸 이름 뒤에 붙는 조사. 여기서 값이 시작합니다.
_PARTICLE = re.compile(r"(?:은|는|이|가)\s+")


def _phrase_read(message: str, found: dict) -> None:
    """ "수량은 500개로 해줘", "단가는 15달러야" 처럼 문장으로 적은 값.

    사람은 "칸 이름: 값" 꼴로만 적지 않습니다. 조사(은/는/이/가) 앞에 우리가 아는
    칸 이름이 있으면 그 뒤를 값으로 봅니다. 아는 이름이 아니면 건드리지 않습니다.
    ("이 건은 급합니다"의 "건"은 아는 칸이 아니라 지나갑니다)

    한 줄에 여러 개를 적었으면 다음 칸 이름 앞에서 끊습니다. 그래야
    "바이어 주소는 1 Ocean Dr, Miami, FL"의 쉼표는 주소 안에 남고,
    "수량은 500개, 단가는 15달러"는 두 값으로 갈립니다.
    """

    for line in message.splitlines():
        if ":" in line or "：" in line:
            continue                 # "칸 이름: 값" 꼴은 위에서 이미 읽었습니다.
        spots = []
        for particle in _PARTICLE.finditer(line):
            head = line[:particle.start()]
            # 긴 이름부터 봅니다. "바이어 주소"를 "주소"로 읽으면 안 됩니다.
            for size in range(12, 1, -1):
                label = head[-size:]
                if _key(label) in _ALIAS_LOOKUP or _key(label) in _ITEM_LOOKUP:
                    spots.append((particle.start() - len(label), particle.end(), label))
                    break
        for index, (_, value_start, label) in enumerate(spots):
            end = spots[index + 1][0] if index + 1 < len(spots) else len(line)
            # 마침표는 떼지 않습니다. "Forward Cosmetics Co., Ltd."의 일부입니다.
            value = _VALUE_TAIL.sub("", line[value_start:end].strip()).strip(" ,-")
            # "칸 이름: 값"으로 또렷하게 적은 값이 있으면 그쪽이 맞습니다. 덮지 않습니다.
            if value and _ALIAS_LOOKUP.get(_key(label)) not in found:
                _assign(found, label, value)


def _rule_read(message: str, draft: dict) -> dict:
    """ "칸 이름: 값" 꼴, 문장 꼴, 딱 보이는 조건 코드(FOB, USD)를 AI 없이 읽습니다."""

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
        line_no = int(next(g for g in number.groups() if g)) if number else 1
        _assign(found, re.sub(r"(\d+)\s*(?:번|품목)|품목\s*\d+", "", label), value, line_no)

    _phrase_read(message, found)

    # \b는 쓰지 않습니다. 한글도 글자로 쳐서 "CIF로"의 F 뒤에 경계가 없다고 봅니다.
    upper = message.upper()
    if "incoterms" not in found:
        codes = [code for code in INCOTERMS if re.search(rf"(?<![A-Z]){code}(?![A-Z])", upper)]
        if len(codes) == 1:
            found["incoterms"] = codes[0]
    # 가격 조건은 장소와 함께 적는 것이 맞습니다. "CIF"가 아니라 "CIF MIAMI".
    # "CIF 마이애미로 변경해줘"에서 뒤따르는 지명만 떼어 냅니다.
    if "incoterms_place" not in found and _has(found.get("incoterms")):
        place = _incoterms_place(message, found["incoterms"])
        if place:
            found["incoterms_place"] = place
    if "currency" not in found:
        codes = [code for code in ("USD", "EUR", "KRW", "JPY", "CNY", "GBP")
                 if re.search(rf"(?<![A-Z]){code}(?![A-Z])", upper)]
        if len(codes) == 1:
            found["currency"] = codes[0]

    return found


# "1번 품목: …" / "품목 2 - …" / "#3 …" — 품목 번호를 앞에 붙인 패킹 답
ITEM_LINE = re.compile(r"^\s*(?:(?:품목|item)\s*#?\s*(\d{1,2})|#?(\d{1,2})\s*번(?:\s*품목)?)"
                       r"\s*[:：\-–)]?\s*(.+?)\s*$", re.I)
_WEIGHT = r"(\d[\d,]*(?:\.\d+)?)\s*(kg|킬로|톤|ton|t|g)?"
_NET = re.compile(r"(?:순\s*중량|net\s*(?:weight|wt)?|n\.\s*w\.?)\s*[:=]?\s*" + _WEIGHT, re.I)
_GROSS = re.compile(r"(?:총\s*중량|gross\s*(?:weight|wt)?|g\.\s*w\.?)\s*[:=]?\s*"
                    r"(박스당|상자당|포장당|per\s*(?:box|carton|ctn|pkg))?\s*" + _WEIGHT, re.I)
_PER_PACKAGE = re.compile(r"(?:박스당|상자당|포장당|한\s*(?:박스|상자|포장)|per\s*(?:box|carton|ctn|pkg))"
                          r"\s*(?:무게)?\s*[:=]?\s*" + _WEIGHT, re.I)
_CARTONS = re.compile(r"(\d[\d,]*)\s*(박스|상자|boxes|box|ctns|ctn|cartons|carton|c/t|pkgs|pkg|packages)"
                      r"(?![a-z])", re.I)


def _kg(number: str, unit: str | None) -> str:
    value = float(number.replace(",", ""))
    unit = (unit or "kg").lower()
    if unit in ("톤", "ton", "t"):
        value *= 1000
    elif unit == "g":
        value /= 1000
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _packing_read(message: str, draft: dict, found: dict) -> None:
    """품목 번호를 붙여 적은 패킹 값(순중량·총중량·박스 규격·박스 수)을 그 품목에 넣습니다.

    총중량은 그 품목 줄 전체의 무게로 봅니다. ("박스당 8kg"처럼 적으면 한 박스 무게)
    줄 전체 무게는 합칠 때 박스 수로 나눠 한 박스 무게로 바꿉니다. (_apply_item)
    """

    count = len(_items(draft))
    for line in message.splitlines():
        match = ITEM_LINE.match(line)
        if not match:
            continue
        no = int(match.group(1) or match.group(2))
        text = match.group(3)
        if not 1 <= no <= max(count, 1):
            continue
        values: dict = {}
        dims = DIMS_PATTERN.search(text)
        if dims:
            values.update(dict(zip(DIMS, dims.groups())))
            text = text[:dims.start()] + " " + text[dims.end():]
        net = _NET.search(text)
        if net:
            values["net_weight_kg"] = _kg(net.group(1), net.group(2))
        gross = _GROSS.search(text)
        if gross:
            key = "weight_per_package_kg" if gross.group(1) else "gross_weight_kg"
            values[key] = _kg(gross.group(2), gross.group(3))
        per_package = _PER_PACKAGE.search(text)
        if per_package and "weight_per_package_kg" not in values:
            values["weight_per_package_kg"] = _kg(per_package.group(1), per_package.group(2))
        cartons = _CARTONS.search(text)
        if cartons:
            values["quantity"] = cartons.group(1).replace(",", "")
            values["package_unit"] = "CTN" if cartons.group(2) in ("박스", "상자") else cartons.group(2)
        if values:
            found["items"].setdefault(no, {}).update(values)
            # 번호 답 읽기(_numbered_read)가 "3번 …"을 묻는 말의 3번으로 또 읽지 않게 표시합니다.
            found.setdefault("_packing_lines", set()).add(line)


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
    consumed = found.get("_packing_lines") or set()
    for line in message.splitlines():
        if line in consumed:
            continue
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


def _known_values(draft: dict) -> str:
    """파일에서 이미 읽어 둔 값. AI가 같은 값을 다시 적지 않게 보여 줍니다.

    이 자리가 "하이브리드 병합"의 한쪽입니다. 파일에서 읽은 값과 사람이 채팅으로
    적은 값을 한 덩어리로 놓고 보아야, 사람이 "수량은 500개로 해줘"라고 했을 때
    그것이 새 값인지 고치는 값인지 AI가 압니다.
    계좌번호·SWIFT는 여기에 넣지 않습니다. (bank_redaction)
    """

    shown = []
    for key in ("exporter_name", "exporter_address", "buyer_name", "buyer_address",
                "buyer_country", "notify_party", "origin_name", "destination_name",
                "incoterms", "currency", "payment_terms"):
        if _has(draft.get(key)):
            shown.append(f"- {key}: {bank_redaction.strip_bank_numbers(str(draft[key]))[0]}")
    for no, row in enumerate(_items(draft), 1):
        values = ", ".join(f"{key}={row[key]}" for key in ITEM_KEYS if _has(row.get(key)))
        if values:
            shown.append(f"- items[{no}]: {values}")
    return "\n".join(shown) or "(아직 읽어 둔 값이 없습니다)"


def _ai_read(message: str, draft: dict) -> dict:
    """글에서 값을 뽑습니다. 키가 없거나 실패하면 빈 값입니다. (규칙으로 읽은 것은 남습니다)"""

    if not ai_client.available():
        return {}
    lines = "\n".join(f"{no}. {row.get('product_description') or '(품명 없음)'}"
                      for no, row in enumerate(_items(draft), 1)) or "(아직 품목이 없습니다)"
    result = ai_client.structured_chat(
        [{"role": "system", "content": MERGE_PROMPT.format(items=lines,
                                                           known=_known_values(draft))},
         # 계좌번호·SWIFT는 AI로 보내지 않습니다.
         {"role": "user", "content": bank_redaction.strip_bank_numbers(message)[0]}],
        MERGE_SCHEMA, name="trade_document_merge", max_tokens=1200,
        model=ai_client.model_name(get_config("AI_DOC_MODEL", "")), timeout=40)
    if not result["success"]:
        return {}
    raw = result["data"]
    found: dict = {"items": {}}
    for key in TEXT_KEYS + EXTRA_TEXT_KEYS + ("incoterms", "currency", "payment_terms",
                                              "buyer_country"):
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

    for key in TEXT_KEYS + EXTRA_TEXT_KEYS:
        if _has(found.get(key)):
            draft[key] = _clean(str(found[key]), 500)
            applied.append(key)
    # 나라 코드는 두 글자입니다. "미국"이라고 적으면 넣지 않고 그대로 둡니다.
    if _has(found.get("buyer_country")):
        code = str(found["buyer_country"]).strip().upper()[:2]
        if code.isalpha():
            draft["buyer_country"] = code
            applied.append("buyer_country")
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


# 반영했다고 알려 줄 때 쓰는 이름. REQUIRED에 없는(=필수가 아닌) 칸들입니다.
# 여기에 없으면 조용히 들어갑니다. 무엇이 반영됐는지 말해 주지 않으면 사람이
# 확인하지 않고 넘어갑니다.
APPLIED_LABELS = {
    "notify_party": "통지처(Notify Party)", "payment_terms": "결제 조건",
    "items.net_weight_kg": "순중량", "buyer_country": "Buyer 국가",
    "buyer_email": "Buyer 이메일", "buyer": "Buyer(Consignee와 다를 때)",
    "incoterms_place": "인코텀즈 장소", "shipping_marks": "화인(Shipping Marks)",
    "lc_no": "L/C 번호", "other_references": "기타 참조",
    "container_no": "컨테이너 번호", "remarks": "비고(송장)",
    "comments": "비고(포장명세서)", "consignee_city_zip": "도시·주·우편번호",
    "attention": "담당자(ATTENTION)", "customer_order_no": "Buyer 주문번호",
    "project_name": "견적명",
}

# 견적명을 물었을 때 "그냥 알아서 해 주세요"에 해당하는 답들.
#
# "넘어가"로 시작하면 다 넘어가기로 보지 않습니다. 그렇게 하면
# "자동차 부품 수출 건"이 "자동"으로 시작한다는 이유로 이름이 아니라
# 넘어가겠다는 말이 됩니다. 통째로 맞는 말만 넘어가기로 봅니다.
_SKIP_FILLER = re.compile(r"^(?:그냥|일단|그럼|그러면|아뇨|아니요|아니)\s*")
_SKIP_ANSWERS = frozenset("""
넘어가기 넘어갈게 넘어갈게요 넘어갑니다 넘어가줘 넘어가주세요 넘어감 넘어갈래요
건너뛰기 건너뛸게 건너뛸게요 건너뛰어줘 건너뜀 스킵 패스 생략 생략할게요 생략해줘
없음 없어 없어요 없습니다 괜찮아 괜찮아요 괜찮습니다 괜찮어요
알아서 알아서해줘 알아서해주세요 알아서정해줘 알아서해 맡길게요
자동 자동으로 자동생성 자동으로해줘 자동으로부탁 기본 기본값 기본값으로 기본으로
skip pass no none auto default
""".split())


def _is_skip_answer(text: str) -> bool:
    plain = re.sub(r"[\s.!~,·]", "", _SKIP_FILLER.sub("", text)).lower()
    return plain in _SKIP_ANSWERS


def _found_anything(found: dict) -> bool:
    """읽기에서 값이 하나라도 나왔는지."""

    return any(value for key, value in found.items() if key != "items") \
        or any(found.get("items", {}).values())


def _name_reply(message: str, found: dict) -> str | None:
    """견적명을 물은 다음 줄의 답. 이름이면 그 이름, 넘어가겠다는 말이면 빈 문자열.

    None은 "이건 이름 답이 아니다"입니다. 이름을 물었다고 해서 다음 말이 늘
    이름인 것은 아닙니다. 아래는 이름으로 보지 않고 평소대로 읽습니다.

    - 여러 줄이거나 "칸 이름: 값" 꼴          (빠진 값을 마저 적는 말)
    - 읽기에서 값이 나온 말 ("수량은 500개")   (값을 고치는 말)
    - 서류를 짚어 만들어 달라는 말             ("패킹리스트도 만들어줘")

    이름으로 잘못 읽으면 대시보드 목록에 "수량은 500개"가 건 이름으로 남습니다.
    """

    text = str(message or "").strip()
    if not text or "\n" in text or ":" in text or "：" in text:
        return None
    if _found_anything(found):
        return None
    if _is_skip_answer(text):
        return ""
    wanted = intent(text)
    if wanted["make"] or wanted["kinds"]:
        return None
    return _clean(text, 200)


def _named(draft: dict, kinds: list[str], answer: str) -> dict:
    """견적명을 정했습니다. 무엇으로 저장되는지 알려 주고 만들기로 넘깁니다.

    answer가 빈 문자열이면 "넘어가기"입니다. 지어 둔 이름을 그대로 씁니다.
    이름이 정해지면 _state가 더는 묻지 않습니다.
    """

    chosen = answer or suggest_project_name(draft)
    draft["project_name"] = chosen
    head = (f"견적명을 **{chosen}**(으)로 지정했습니다." if answer
            else f"견적명을 **{chosen}**(으)로 자동 지정했습니다.")
    reply = (f"{head} 대시보드 서류 목록에 이 이름으로 표시됩니다.\n\n"
             "아래에서 만들 서류를 확인하시고 **선택한 서류 생성하기**를 눌러 주세요. "
             "이름은 그 칸에서 언제든 고치실 수 있습니다.")
    return _state(draft, kinds, reply)


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
    # 바로 앞에서 견적명을 물었으면, 이 말은 그 답일 수 있습니다. 규칙으로 읽어
    # 아무 값도 안 나왔을 때만 이름으로 봅니다. ("수량은 500개"는 값입니다)
    if payload.get("awaiting") == "project_name":
        answer = _name_reply(message, found)
        if answer is not None:
            return _named(draft, kinds, answer)

    # "1번 품목: 순중량 …" 꼴. 규칙으로 읽은 품목 값이라 AI보다 먼저입니다.
    _packing_read(message, draft, found)
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
        label = (REQUIRED.get(key) or {}).get("label") or APPLIED_LABELS.get(key, "")
        if label and label not in labels:
            labels.append(label)

    rows = missing(draft, kinds)
    if not labels:
        head = ("적어 주신 내용에서 서류에 넣을 값을 찾지 못했습니다. "
                "**칸 이름: 값** 꼴로 한 줄씩 적어 주시면 정확하게 반영됩니다.")
    else:
        head = f"받았습니다. **{', '.join(labels)}**을(를) 반영했습니다."
    reply = head + "\n\n" + ask_message(rows, "다만 아직", draft)
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
        return _state(draft, kinds, ask_message(rows, "고르신 서류를 만들기 전에 확인해 보니", draft))

    # 이름 없이 만들면 대시보드 목록에서 이 건을 알아볼 수 없습니다.
    # 묻는 단계를 건너뛰고 바로 눌렀더라도 지어 둔 이름을 붙입니다.
    if not str(draft.get("project_name") or "").strip():
        draft["project_name"] = suggest_project_name(draft)

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
    reply += (f"\n\n이 건은 대시보드에 **{draft['project_name']}**(으)로 저장됩니다.")
    return {"stage": "made", "reply": reply, "draft": draft, "kinds": kinds,
            "project_name": draft["project_name"], "documents": documents}


def review_document(kind: str, draft: dict) -> dict:
    """검토 창(미리보기)이 쓰는 서류 한 장. 칸 값·표·칸 이름·미리보기 그림.

    대화로 만든 초안(agent_service)도 같은 창에서 검토하므로 여기 한 곳에 둡니다.
    """

    from app.processors.document_form import MONEY_KEYS

    result = drafts.render(kind, draft)
    data = drafts.as_text(result["data"])
    # 금액 칸 머리에 통화를 붙입니다. ("Amount (USD)") 통화를 모르면 그대로 둡니다.
    currency = str(draft.get("currency") or "").strip().upper()[:3]

    def money(key: str, label: str) -> str:
        return f"{label} ({currency})" if currency and key in MONEY_KEYS else label

    return {
        "kind": kind, "title": result["title"], "data": data, "currency": currency,
        "columns": [{**column, "label": money(column["key"], column["label"])}
                    for column in result["columns"]],
        "fields": [{"key": name, "label": money(name, _label(kind, name))}
                   for name in drafts.fields_for(kind)],
        "missing": result["missing"], "undecided": result["undecided"],
        "preview": drafts.preview_data(kind, data),
    }


def _label(kind: str, name: str) -> str:
    from app.services import document_service

    return document_service.field_label("packing_list" if kind == "packing_list_std" else kind,
                                        name)
