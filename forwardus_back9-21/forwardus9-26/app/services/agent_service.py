"""대화로 서류를 만드는 창구.

"패킹리스트만 만들어줘"처럼 서류 하나만 말해도, **그 서식이 요구하는 칸만**
되묻고 바로 초안을 그려 보여 줍니다. 선박도 스케줄도 없어도 됩니다.

여기서 지키는 선이 하나 있습니다.

    사람 말에서 값을 뽑는 일        AI
    뽑은 값이 맞는지 확인하는 일     우리 코드
    무엇이 아직 비었는지 정하는 일    우리 코드 (서식이 정합니다)
    서류를 그리는 일               우리 코드

AI에게 "다 모였다"를 판단하게 두지 않습니다. 빠진 칸은 서식이 정하는 것이고
그건 우리가 압니다. AI가 없어도(키가 없어도) 칸 목록을 보여 주고 받아
적는 데까지는 그대로 동작합니다.

서버는 상태를 갖지 않습니다. 지금까지 모은 값(draft)은 브라우저가 들고
다니고 매번 같이 보냅니다. 기존 상담 창구와 같은 방식입니다.
"""

from __future__ import annotations

from app.services import ServiceError, draft_document_service as drafts
from app.validators import ValidationError

MAX_MESSAGE = 2_000

# 어떤 말이 어떤 서식을 가리키는지. 규칙을 먼저 봅니다.
# AI가 없어도(키가 없어도) 여기까지는 됩니다.
DOC_WORDS = {
    "packing_list_std": ("패킹리스트", "패킹 리스트", "포장명세서", "포장 명세서",
                         "packing list", "packinglist", "p/l", "pl"),
    "commercial_invoice": ("상업송장", "상업 송장", "커머셜", "인보이스",
                           "commercial invoice", "c/i", "ci", "invoice"),
    "proforma_invoice": ("견적송장", "견적 송장", "프로포마", "프로파마",
                         "proforma", "p/i", "pi"),
    # "sr"·"si"처럼 짧은 것은 다른 낱말 속에 끼어 있어 넣지 않습니다.
    "shipping_instruction": ("선적의뢰서", "선적 의뢰서", "쉬핑리퀘스트", "shipping request",
                             "shipping instruction", "s/r", "s/i"),
}

# "그냥 만들어줘", "없어", "빈칸으로" — 더 안 적고 지금 것으로 그리라는 뜻입니다.
JUST_MAKE = ("그냥", "없어", "없습니다", "없음", "빈칸", "빈 칸", "공백", "모르겠",
             "생략", "건너", "패스", "바로", "지금", "이대로", "그대로", "만들어",
             "보여", "작성")

# 사람이 적어 줄 수 있는 칸.
#
# 세 가지를 같이 들고 다닙니다.
#   ko    우리말 이름 — 무엇을 묻는지
#   en    서식에 인쇄되는 영문 칸 이름 — 종이와 화면을 나란히 놓고 보게
#   note  무엇을 어떻게 적는지, 조심할 것
# group은 표에서 묶어 보여 줄 덩어리입니다.
FIELDS = {
    "exporter_name": {
        "group": "기본 정보", "ko": "보내는 회사 이름", "en": "Shipper / Exporter",
        "note": "수출자 상호. 사업자등록증의 영문 상호와 같아야 합니다"},
    "exporter_address": {
        "group": "기본 정보", "ko": "보내는 회사 주소", "en": "Exporter Address",
        "note": "영문 주소, 담당자명, 연락처"},
    "buyer_name": {
        "group": "기본 정보", "ko": "받는 회사 이름", "en": "Consignee",
        "note": "수입자 상호. 신용장 거래면 To order... 조건을 확인하세요"},
    "buyer_address": {
        "group": "기본 정보", "ko": "받는 회사 주소", "en": "Consignee Address",
        "note": "영문 주소와 연락처"},
    "buyer": {
        "group": "기본 정보", "ko": "Buyer (받는 곳과 다를 때)", "en": "Buyer",
        "note": "받는 곳과 실제 구매자가 다를 때만 적습니다"},
    "notify_party": {
        "group": "기본 정보", "ko": "통지처", "en": "Notify Party",
        "note": "화물 도착을 통지받을 곳. 받는 곳과 같으면 SAME AS CONSIGNEE"},

    "invoice_no": {
        "group": "문서 정보", "ko": "송장 번호", "en": "Invoice No. & Date",
        "note": "송장 고유 관리번호. 비우면 날짜만 찍힙니다"},
    "lc_no": {
        "group": "문서 정보", "ko": "L/C 번호와 날짜", "en": "L/C No. & Date",
        "note": "신용장 번호. 없으면 비워 두세요"},
    "po_no": {
        "group": "문서 정보", "ko": "Buyer 주문번호", "en": "Buyer's P/O No.",
        "note": "구매주문서(PO) 번호"},
    "validity_date": {
        "group": "문서 정보", "ko": "견적 유효기한", "en": "Validity of P/I",
        "note": "이 견적이 언제까지 유효한지"},
    "other_references": {
        "group": "문서 정보", "ko": "기타 참조", "en": "Other references",
        "note": "계약서 번호 등 함께 적을 것"},

    "origin_code": {
        "group": "운송 정보", "ko": "출발지", "en": "Port of Loading (From)",
        "note": "선적항·출발 공항. 부산이면 KRPUS"},
    "destination_code": {
        "group": "운송 정보", "ko": "도착지", "en": "Port of Discharge (To)",
        "note": "양륙항·도착 공항. 로스앤젤레스면 USLAX"},

    "incoterms": {
        "group": "거래 조건", "ko": "거래 조건", "en": "Terms of Delivery",
        "note": "FOB · CIF 같은 Incoterms 2020 조건"},
    "currency": {
        "group": "거래 조건", "ko": "통화", "en": "Currency",
        "note": "USD · EUR 같은 결제 통화"},
    "payment_terms": {
        "group": "거래 조건", "ko": "결제 조건", "en": "Terms of Payment",
        "note": "예: 100% T/T IN ADVANCE BEFORE SHIPMENT"},
    "bank_info": {
        "group": "거래 조건", "ko": "은행 정보", "en": "Bank Information",
        "note": "은행명 · SWIFT · 계좌번호 · 예금주"},

    "shipping_marks": {
        "group": "화물 표시", "ko": "화인", "en": "Shipping Marks",
        "note": "상자에 찍는 표시. 예: ABC / LA / C-NO 1-500 / MADE IN KOREA"},
    "remarks": {
        "group": "화물 표시", "ko": "비고", "en": "Remarks",
        "note": "따로 적어 둘 것"},

    "signed_by": {
        "group": "서명", "ko": "서명 (보내는 쪽)", "en": "Signed by",
        "note": "수출자 상호 또는 담당자명"},
    "accepted_by": {
        "group": "서명", "ko": "서명 (받는 쪽)", "en": "Accepted by (Buyer)",
        "note": "견적송장에서 Buyer가 받아들였다는 표시"},
}

# 영문으로 적어야 하는 이유. 서류는 상대국 세관과 은행이 봅니다.
ENGLISH_NOTE = ("적으실 때 **영문으로** 적어 주세요. 적으신 글자가 그대로 서류에 "
                "인쇄됩니다. 한글로 적으면 서류에도 한글로 나오고, "
                "상대국 세관·은행에서 받아 주지 않습니다.")

# 서식마다 사람에게 물어볼 칸. 순서가 곧 물어보는 순서입니다.
# 기본 정보(보내는 곳·받는 곳의 상호와 주소)는 모두 필수입니다. 주소가 없으면 송장·포장명세서의
# Seller·Consignee 칸이 비어 나가고, 수입 통관에서 되돌아옵니다.
ASK_FOR = {
    "packing_list_std": [
        ("exporter_name", True), ("exporter_address", True),
        ("buyer_name", True), ("buyer_address", True),
        ("origin_code", True), ("destination_code", True),
        ("invoice_no", False), ("buyer", False), ("other_references", False),
        ("signed_by", False),
    ],
    "commercial_invoice": [
        ("exporter_name", True), ("exporter_address", True),
        ("buyer_name", True), ("buyer_address", True),
        ("origin_code", True), ("destination_code", True),
        ("incoterms", True), ("currency", False),
        ("payment_terms", False), ("lc_no", False),
        ("shipping_marks", False), ("remarks", False), ("signed_by", False),
    ],
    "proforma_invoice": [
        ("exporter_name", True), ("exporter_address", True),
        ("buyer_name", True), ("buyer_address", True),
        ("origin_code", True), ("destination_code", True),
        ("incoterms", True), ("currency", False),
        ("validity_date", False), ("po_no", False),
        ("payment_terms", False), ("bank_info", False),
        ("remarks", False), ("signed_by", False), ("accepted_by", False),
    ],
    "shipping_instruction": [
        ("exporter_name", True), ("exporter_address", True),
        ("buyer_name", True), ("buyer_address", True), ("notify_party", False),
        ("origin_code", True), ("destination_code", True),
        ("incoterms", False), ("shipping_marks", False), ("remarks", False),
        ("signed_by", False),
    ],
}

ITEM_NOTE = ("품목은 **품명 · 개수 · 한 상자 크기(가로x세로x높이 cm) · 한 상자 무게(kg)**"
             "가 있어야 부피와 중량이 계산됩니다.")


def detect_kind(text: str) -> str | None:
    """어떤 서류를 말하는지 찾습니다. 못 찾으면 None."""

    lowered = (text or "").lower().replace(" ", "")
    for kind, words in DOC_WORDS.items():
        if any(word.replace(" ", "") in lowered for word in words):
            return kind
    return None


def wants_to_finish(text: str) -> bool:
    """더 안 적고 지금 것으로 그리라는 말인지."""

    written = (text or "").strip()
    if not written:
        return True
    return any(word in written for word in JUST_MAKE)


# 운송 계획 화면에서 정하는 것들. 여기서 적어도 되지만, 운송 계획을 잡으면
# 스케줄과 함께 한 번에 정해집니다. 그렇다고 화면에 적어 둡니다.
FROM_PLANNING = {"origin_code", "destination_code", "incoterms", "currency"}

PLANNING_NOTE = "운송 계획에서 작성합니다"


def ask_list(kind: str, draft: dict | None = None) -> list[dict]:
    """이 서식이 요구하는 칸. 화면이 표로 그립니다.

    세 열로 보여 줍니다. 구분 · 영문 칸 이름 · 기재 내용.
    영문 칸 이름을 같이 두는 이유는, 종이 서식과 화면을 나란히 놓고
    "이 칸이 저 칸이구나"를 바로 알 수 있게 하려는 것입니다.
    """

    draft = draft or {}
    rows = []
    for name, required in ASK_FOR.get(kind, []):
        info = FIELDS.get(name, {})
        rows.append({
            "field": name,
            "group": info.get("group", ""),
            "ko": info.get("ko", name),
            "en": info.get("en", name),
            "note": info.get("note", ""),
            "required": required,
            "from_planning": name in FROM_PLANNING,
            "value": str(draft.get(name) or "").strip(),
        })

    items = draft.get("items") or []
    rows.append({
        "field": "items", "group": "품목", "ko": "품목",
        "en": "Description of Goods",
        "note": "품명 · 개수 · 한 상자 크기(가로x세로x높이 cm) · 한 상자 무게(kg)",
        "required": True, "from_planning": False,
        "value": f"{len(items)}개 적으셨습니다" if items else "",
    })
    return rows


def _ask_message(kind: str, draft: dict) -> str:
    """표 위에 붙는 안내. 칸 목록 자체는 화면이 표로 그립니다.

    {{ }}로 감싼 것은 화면에서 빨간 글씨로 나옵니다.
    """

    title = drafts.FORMS[kind]
    return "\n\n".join([
        f"**{title}**를 만들겠습니다. 아래 내용을 알려 주세요.",
        ENGLISH_NOTE,
        ("{{*}} 는 없으면 서류 모양이 제대로 안 나오는 칸입니다. "
         f"{{{{{PLANNING_NOTE}}}}} 라고 적힌 것은 여기서 적으셔도 되고, "
         "운송 계획을 잡으면 스케줄과 함께 한 번에 정해집니다."),
        ("아는 것만 한 번에 적어 주셔도 됩니다. "
         "**그냥 만들어줘**라고 하시면 지금 있는 것만으로 초안을 그려 드립니다. "
         "빈 칸은 비워 둔 채로 나옵니다."),
    ])


def _pick_message(reason: str = "") -> str:
    lines = []
    if reason:
        lines += [reason, ""]
    lines.append("어떤 서류를 만들까요? 하나만 고르셔도 됩니다.")
    lines.append("")
    for kind, title in drafts.FORMS.items():
        if kind == "packing_list":      # ORDER# 양식은 서류 작성 화면에서 고릅니다.
            continue
        lines.append(f"- {title}")
    lines.append("")
    lines.append('예를 들어 "패킹리스트만 만들어줘"라고 하시면 됩니다.')
    return "\n".join(lines)


def parse_filled(kind: str, text: str) -> dict:
    """"칸 이름: 값" 꼴로 적은 것을 그대로 읽습니다.

    화면에서 표를 누르면 이 꼴로 입력칸에 들어갑니다. 모양이 정해져 있으니
    AI에게 물어볼 이유가 없습니다. 규칙으로 읽으면 빠르고, 공짜이고,
    AI 키가 없어도 되고, 무엇보다 틀리지 않습니다.

    칸 이름은 우리말·영문 어느 쪽으로 적어도 알아봅니다.
    """

    if not text or ":" not in text:
        return {}

    # 이 서식이 쓰는 칸만 봅니다. 이름 -> 칸 짝을 미리 만들어 둡니다.
    lookup = {}
    for name, _ in ASK_FOR.get(kind, []):
        info = FIELDS.get(name, {})
        for label in (info.get("ko", ""), info.get("en", ""), name):
            if label:
                lookup[_key(label)] = name

    found = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        name = lookup.get(_key(label))
        value = value.strip()
        if name and value:
            found[name] = value[:500]
    return found


def _key(label: str) -> str:
    """이름을 견주기 좋게 다듬습니다. 띄어쓰기·기호·대소문자를 무시합니다."""

    return "".join(ch for ch in str(label).lower() if ch.isalnum())


def _read_message(kind: str, message: str, draft: dict) -> list[str]:
    """적어 주신 글에서 값을 뽑아 draft에 넣습니다. 확인된 것만 넣습니다.

    두 단계로 읽습니다.
      1. "칸 이름: 값" 꼴은 규칙으로 그대로 읽습니다. (표를 눌러 넣은 틀)
      2. 그러고도 안 채워진 것이 있으면 AI에게 글을 읽힙니다.

    규칙을 먼저 두는 이유는, 모양이 정해진 것을 굳이 AI에게 물어볼 이유가
    없기 때문입니다. 빠르고 공짜이고 틀리지 않습니다.

    돌려주는 것은 "이건 확인 못 했다"는 메모입니다.
    """

    from app.services import intake_service

    if not message.strip():
        return []

    # 1) 틀에 맞춰 적은 것부터.
    for name, value in parse_filled(kind, message).items():
        draft[name] = value

    if not intake_service.available():
        return []

    # 2) 남은 것은 AI가 글에서 찾아봅니다.
    try:
        read = intake_service.read(message)
    except (ValidationError, ServiceError):
        return []

    form = read["form"]["fields"]
    # 서식이 쓰는 칸만 받습니다. 나머지는 이 서류와 상관이 없습니다.
    wanted = {name for name, _ in ASK_FOR.get(kind, [])}
    for name, value in form.items():
        if name in wanted and value and not str(draft.get(name) or "").strip():
            draft[name] = value
    if read["form"]["items"]:
        draft["items"] = read["form"]["items"]
    return list(read["notes"])


def turn(payload: dict) -> dict:
    """대화 한 번. 무엇을 물을지, 또는 무엇을 그렸는지 돌려줍니다."""

    if not isinstance(payload, dict):
        raise ValidationError("입력을 읽지 못했습니다.", "payload")

    message = str(payload.get("message") or "").strip()
    if len(message) > MAX_MESSAGE:
        raise ValidationError(f"{MAX_MESSAGE:,}자 아래로 줄여 주세요.", "message")

    draft = dict(payload.get("draft") or {})
    kind = draft.get("kind") or detect_kind(message)

    # 1) 어떤 서류인지 아직 모릅니다.
    if not kind:
        return {"reply": _pick_message(), "draft": draft, "stage": "pick"}

    first_time = draft.get("kind") != kind
    draft["kind"] = kind

    # 2) 방금 서류를 고르셨습니다. 무엇이 필요한지 먼저 보여 줍니다.
    if first_time:
        notes = _read_message(kind, message, draft)
        return {"reply": _ask_message(kind, draft), "draft": draft,
                "stage": "ask", "fields": ask_list(kind, draft), "notes": notes}

    # 3) 답을 주셨습니다. 읽어서 채웁니다.
    notes = _read_message(kind, message, draft)

    # 4) 그릴까요, 더 물을까요.
    if not wants_to_finish(message):
        return {"reply": _ask_message(kind, draft), "draft": draft,
                "stage": "ask", "fields": ask_list(kind, draft), "notes": notes}

    return {**make(kind, draft), "draft": draft, "notes": notes}


# 수출에 반드시 내야 하는 서류 두 장입니다. 칸의 대부분을 함께 씁니다
# (보내는 쪽·받는 쪽·출발지·도착지·품목). 그래서 하나만 말씀하셔도 둘을
# 같이 만들어 둡니다. 어차피 둘 다 필요하고, 값은 이미 다 모였습니다.
TOGETHER = {
    "packing_list_std": ["packing_list_std", "commercial_invoice"],
    "commercial_invoice": ["commercial_invoice", "packing_list_std"],
    "proforma_invoice": ["proforma_invoice"],
    "shipping_instruction": ["shipping_instruction"],
}


def make(kind: str, draft: dict) -> dict:
    """초안을 그립니다. 품목이 없으면 서류가 안 되니 되묻습니다."""

    if not (draft.get("items") or []):
        return {"reply": "품목을 알려 주셔야 서류가 나옵니다.\n\n" + ITEM_NOTE,
                "stage": "ask", "fields": ask_list(kind, draft)}

    made = []
    for one in TOGETHER.get(kind, [kind]):
        rendered = drafts.render(one, draft)
        made.append({"kind": one, "title": rendered["title"],
                     "missing": rendered["missing"],
                     "undecided": rendered["undecided"]})

    first = made[0]
    return {"reply": _done_message(made), "stage": "made",
            "documents": made,
            # 처음 말씀하신 서류를 대표로 둡니다.
            "kind": first["kind"], "title": first["title"],
            "missing": first["missing"], "undecided": first["undecided"]}


def _done_message(made: list[dict]) -> str:
    """다 만든 뒤에 건네는 말. 무엇이 비었는지 숨기지 않습니다."""

    def short(title):
        return title.split(" (")[0]

    lines = [f"**{' · '.join(short(row['title']) for row in made)}** 초안입니다.", ""]

    if len(made) > 1:
        lines.append("수출에는 이 둘을 함께 냅니다. 칸의 대부분을 같이 쓰기 때문에 "
                     "한 번 적으신 것으로 둘 다 만들었습니다.")
        lines.append("")

    if any(row["undecided"] for row in made):
        lines.append("운송 일정이 없어서 아직 못 채운 칸이 있습니다. "
                     "출항일·선박명은 스케줄을 고르면 채워집니다.")
        lines.append("")

    for row in made:
        if not row["missing"]:
            continue
        names = ", ".join(item["label"] for item in row["missing"][:5])
        more = f" 외 {len(row['missing']) - 5}개" if len(row["missing"]) > 5 else ""
        lines.append(f"- {short(row['title'])} 빈 칸: {names}{more}")
    if any(row["missing"] for row in made):
        lines.append("")

    lines.append("**PDF로 받기**로 지금 내려받으실 수 있습니다. "
                 "적으신 내용은 **임시로 저장해 두었습니다.**")
    lines.append("")
    lines.append("이제 **운송 일정**을 넣으시면, 저장해 둔 내용에 출항일·선박명까지 "
                 "채워서 정식 서류로 만듭니다.")
    return "\n".join(lines)
