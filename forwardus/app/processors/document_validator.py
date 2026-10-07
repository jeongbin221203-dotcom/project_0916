"""Cross-document consistency checks.

두 가지를 봅니다.

1. 기준값 대조 — 서류마다 Shipment 기록과 같은지.
2. 서류끼리 맞대기 — 서류들끼리 같은 값을 적고 있는지.

2가 따로 필요한 이유는 1이 기준값이 있을 때만 돌기 때문입니다. Shipment에
순중량을 적지 않았으면 그 칸은 검사에서 통째로 빠지는데, 그래도 상업송장과
패킹리스트의 순중량은 서로 같아야 합니다. 예전에는 서류 다섯 장에 서로 다른
순중량이 적혀 있어도 전부 통과였습니다.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

from app.processors.cost_calculator import INCOTERMS_INFO
from app.processors.korean import particle

_INCOTERM_CODES = {row["code"] for row in INCOTERMS_INFO}

# Fields compared across documents, with the document types that carry them.
VALIDATION_FIELDS = {
    "quantity": "Quantity",
    "gross_weight_kg": "Gross Weight",
    "net_weight_kg": "Net Weight",
    "invoice_value": "Invoice Value",
    "currency": "Currency",
    "incoterms": "Incoterms",
    "hs_code": "HS CODE",
    "consignee": "Consignee",
    "pol": "POL",
    "pod": "POD",

    # 아래는 2026-09-26에 넣었습니다.
    #
    # 그 전에는 위 열 칸만 봤습니다. 서식 칸은 64개인데 10개만 본 것입니다.
    # 적합성 검사를 100회 돌려 보니 **수출자명·품명·선박명이 서류마다 달라도
    # 전부 통과**였습니다. 이것들은 실제로 가장 자주 사고가 나는 칸입니다.
    #   - 수출자명이 L/C와 한 글자 다르면 은행에서 서류가 돌아옵니다.
    #   - 품명이 송장과 패킹리스트에서 다르면 통관이 보류됩니다.
    #   - B/L의 선박명이 송장과 다르면 바이어가 물건을 못 찾습니다.
    "exporter": "Shipper / Exporter",
    "exporter_address": "Shipper 주소",
    "consignee_address": "Consignee 주소",
    "notify_party": "Notify Party",
    "product_description": "품명",
    "package_type": "포장 종류",
    "shipping_marks": "화인 (Shipping Marks)",
    "total_cbm": "Total CBM",
    "etd": "출항일 (ETD)",
    "vessel_or_flight": "선박·항공편",
    "carrier": "선사·항공사",
    "payment_terms": "결제 조건",
    "freight_term": "운임 조건",
    "dangerous_goods": "위험물 표시",
}

# 일부러 검사하지 않는 칸. 서류마다 **달라도 되는** 것들입니다.
#   doc_no      서류마다 자기 번호를 씁니다 (CI-… / PL-…)
#   doc_date    송장 작성일과 포장일은 다를 수 있습니다
#   remarks     자유롭게 적는 칸입니다
#   signed_by   서류마다 서명자가 다를 수 있습니다
#   unit_price  견적송장(PI)은 제안가, 상업송장(CI)은 확정가라 다를 수 있습니다
# 이 목록을 줄이려면 "정말 달라도 되는가"를 먼저 따져 보세요. 잘못 넣으면
# 멀쩡한 서류에 경고가 떠서, 사람이 경고를 안 믿게 됩니다.
NOT_COMPARED = ("doc_no", "doc_date", "remarks", "signed_by", "unit_price")

NUMERIC_TOLERANCE = 0.01


# 숫자로 읽어야 하는 칸. 이 칸만 "3,000.00"과 3000.0을 같게 봅니다.
#
# 왜 칸을 정해 두나
#   전부 숫자로 읽으려 하면 HS부호가 망가집니다. "0303890000"을 숫자로 바꾸면
#   303890000.0이 되어 앞의 0이 사라지고, 다른 부호와 같아져 버립니다.
#   숫자인 칸만 숫자로 읽습니다.
NUMERIC_FIELDS = ("quantity", "gross_weight_kg", "net_weight_kg",
                  "invoice_value", "total_cbm", "unit_price", "amount")

# 금액 칸에 붙는 기호. 떼고 숫자만 봅니다. ("USD 3,000.00" · "$3,000")
_MONEY_MARKS = ("USD", "EUR", "JPY", "CNY", "KRW", "$", "€", "¥", "₩", ",", " ")


def _as_number(value):
    """숫자로 읽어 봅니다. 숫자가 아니면 None."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    for mark in _MONEY_MARKS:
        text = text.replace(mark, "")
    try:
        return float(text)
    except ValueError:
        return None


def _normalize(value, field: str = ""):
    """견줄 수 있는 모양으로 고칩니다.

    글자는 앞뒤·가운데 공백을 하나로 줄이고 대문자로 맞춥니다. 대소문자는
    일부러 무시합니다 — 은행도 대소문자만 다른 것은 불일치로 보지 않습니다.

    숫자 칸(NUMERIC_FIELDS)은 숫자로 읽습니다. 그래야 송장에 "3,000.00"으로
    적고 기록에 3000.0으로 있는 것이 같은 값이 됩니다. 예전에는 이것이
    "값이 다릅니다" 경고로 떴습니다. 쉼표를 넣어 적는 것이 오히려 흔한데,
    멀쩡한 서류에 경고가 뜨면 사람이 경고를 안 믿게 됩니다. (2026-09-26)
    """

    # **HS부호는 6자리까지만 맞댑니다.**
    #
    # 바이어에게 나가는 송장에는 6자리를 찍고(6601.91), 기록에는 10자리가
    # 있습니다(6601910000). 6자리까지는 세계 공통이고 그 아래는 나라마다
    # 다르므로, 앞 6자리가 같으면 같은 분류입니다. 자릿수가 다르다고
    # "값이 다릅니다"를 띄우면 멀쩡한 서류에 경고가 붙습니다. (2026-09-28)
    if field == "hs_code":
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return digits[:6] if len(digits) >= 6 else " ".join(str(value or "").split()).upper()
    # **Incoterms 는 앞 세 글자(코드)만 맞댑니다.** Incoterms 2020 은 지정 장소를 요구하고 L/C 도
    # "CIF LOS ANGELES" 처럼 적는데, 완전 일치로 보니 서류를 그렇게 고치면 네 장 모두 "기준값과 다릅니다"가
    # 되어 영영 확정할 수 없었습니다(전수 점검 1회차).
    if field == "incoterms":
        text = " ".join(str(value or "").split()).upper()
        match = re.match(r"([A-Z]{3})\b", text)
        return match.group(1) if match and match.group(1) in _INCOTERM_CODES else text
    # 항구는 "BUSAN, KOREA"·"Busan (KRPUS)" 가 같은 곳입니다 — 쉼표·괄호 앞의 이름만 맞댑니다.
    if field in ("pol", "pod"):
        text = " ".join(str(value or "").split())
        return re.split(r"[,(]", text)[0].strip().upper() if text else ""
    if field in NUMERIC_FIELDS:
        number = _as_number(value)
        if number is not None:
            return number
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return ""
    return " ".join(str(value).split()).upper()


def _equal(expected, actual) -> bool:
    if isinstance(expected, float) and isinstance(actual, float):
        return math.isclose(expected, actual, abs_tol=NUMERIC_TOLERANCE)
    return expected == actual


def _written(documents, form_fields, field) -> dict[str, object]:
    """그 칸을 실제로 보여 주고, 값이 적혀 있는 서류만 골라 옵니다.

    지금 서식에 없는 칸(예전 문서에 남은 것)은 고칠 수 없으니 뺍니다.
    비어 있는 칸은 "다르다"가 아니라 "아직 안 적었다"라서 1번이 따로 봅니다.
    """

    written = {}
    for doc_type, data in documents.items():
        shown = form_fields.get(doc_type)
        if field not in data or (shown is not None and field not in shown):
            continue
        value = _normalize(data[field], field)
        if value != "":
            written[doc_type] = value
    return written


def _group(written: dict[str, object]) -> list[list]:
    """같은 값을 적은 서류끼리 묶습니다. 서식 차례를 그대로 지킵니다."""

    groups: list[list] = []
    for doc_type, value in written.items():
        for group in groups:
            if _equal(group[0], value):
                group[1].append(doc_type)
                break
        else:
            groups.append([value, [doc_type]])
    return groups


def _raw(documents, doc_type, field):
    """화면에 보여 줄 때는 정규화 전 값이 낫습니다. (대문자로 바꾸기 전)"""

    return documents[doc_type].get(field)


def _cross_findings(documents, labels, form_fields, reported, reference=None) -> list[dict]:
    """서류끼리 맞대어 봅니다. 기준값이 없어도 서로는 같아야 합니다.

    ``reported``는 기준값 대조에서 이미 지적한 (서류, 칸)입니다. 같은 자리를
    두 번 알리지 않습니다. 기준값 쪽이 "무엇과 달라야 하는지"까지 알려 주므로
    더 쓸모 있고, 두 줄이 나란히 뜨면 고칠 곳이 둘인 줄 알게 됩니다.

    ``reference``가 있으면 **기준값과 같은 서류는 지적하지 않습니다.**

    왜 그렇게 하는가
      서류가 둘뿐이고 서로 다르면 어느 쪽을 기준으로 삼을지 정해지지 않아,
      **값이 맞는 쪽**이 지적당하는 일이 있었습니다. 고치라고 해서 가 보면
      값이 맞아서 무엇이 문제인지 알 수가 없습니다. 기준값이 있으면 답은
      정해져 있습니다 — 기준값과 같은 쪽이 맞고, 다른 쪽을 고치면 됩니다.
      (2026-09-27)
    """

    reference = reference or {}
    findings = []
    for field, field_label in VALIDATION_FIELDS.items():
        written = _written(documents, form_fields, field)
        if len(written) < 2:
            continue
        groups = _group(written)
        if len(groups) < 2:
            continue

        # 기준값과 같은 묶음을 맨 앞으로. 그 묶음의 서류는 고칠 것이 없습니다.
        if reference.get(field) not in (None, ""):
            wanted = _normalize(reference[field], field)
            right = [group for group in groups if _equal(group[0], wanted)]
            if right:
                groups = right + [group for group in groups if group not in right]
                for _value, docs in right:
                    for doc_type in docs:
                        reported.add((doc_type, field))

        def entry(doc_type, other, message):
            return {
                "status": "warning",
                "kind": "cross",
                "field": field,
                "field_label": field_label,
                "document": doc_type,
                "document_label": labels.get(doc_type, doc_type),
                "other_document": other,
                "other_document_label": labels.get(other, other) if other else "",
                "expected": _raw(documents, other, field) if other else None,
                "actual": _raw(documents, doc_type, field),
                "message": message,
            }

        alone = [group for group in groups if len(group[1]) == 1]
        crowd = [group for group in groups if len(group[1]) > 1]
        # 한 서류만 나머지와 다른 경우. "나머지"가 되려면 둘 이상이 같아야 합니다.
        if len(groups) == 2 and len(alone) == 1 and len(crowd) == 1:
            odd = alone[0][1][0]
            if (odd, field) in reported:
                continue
            name = labels.get(odd, odd)
            findings.append(entry(
                odd, crowd[0][1][0],
                f"{name}의 {field_label}{particle(field_label, '이')}"
                " 나머지 서류와 일치하지 않습니다."))
            continue

        # 그 밖에는 둘씩 맞대어 알립니다. (서식에서 앞선 서류를 기준으로)
        base = groups[0][1][0]
        base_name = labels.get(base, base)
        for _value, docs in groups[1:]:
            for doc_type in docs:
                if (doc_type, field) in reported:
                    continue
                name = labels.get(doc_type, doc_type)
                findings.append(entry(
                    doc_type, base,
                    f"{base_name}{particle(base_name, '와')} {name}의 "
                    f"{field_label}{particle(field_label, '이')}"
                    " 일치하지 않습니다. 다시 확인해주세요."))
    return findings


# 비어 있으면 서류가 제 구실을 못 하는 칸. 서류 종류마다 다릅니다.
#
# 왜 따로 두나
#   위의 기준값 대조는 **기준값이 있을 때만** 돕니다. Shipment에 순중량을 안
#   적었으면 그 칸은 검사에서 통째로 빠지고, 서류끼리 맞대기도 양쪽이 다 비어
#   있으면 "같다"로 지나갑니다. 그래서 순중량이 빈 포장명세서가 "검증 통과"로
#   나왔습니다. 수입국 세관이 순중량을 요구하면 그 자리에서 막힙니다.
#
# 여기에 넣지 않은 것
#   컨테이너 번호·주문번호·연락받을 사람처럼 **아직 모를 수 있는** 칸은 넣지
#   않습니다. 부킹 전에는 컨테이너 번호가 없는 것이 정상인데 그것을 빨갛게
#   띄우면, 늘 떠 있는 경고가 되어 아무도 안 봅니다.
REQUIRED_BLANKS = {
    "packing_list": ("net_weight_kg", "gross_weight_kg", "quantity",
                     "consignee", "product_description"),
    "commercial_invoice": ("invoice_value", "currency", "quantity", "incoterms",
                           "consignee", "product_description"),
}


def _missing_findings(documents, labels, form_fields, reported) -> list[dict]:
    """꼭 있어야 하는데 비어 있는 칸. "없다"와 "다르다"는 다른 문제입니다."""

    findings = []
    for doc_type, fields in REQUIRED_BLANKS.items():
        data = documents.get(doc_type)
        if not data:
            continue
        shown = form_fields.get(doc_type)
        for field in fields:
            if field not in data or (shown is not None and field not in shown):
                continue
            if (doc_type, field) in reported:
                continue
            if _normalize(data[field], field) != "":
                continue
            label = VALIDATION_FIELDS.get(field, field)
            name = labels.get(doc_type, doc_type)
            findings.append({
                "status": "warning",
                "kind": "missing",
                "field": field,
                "field_label": label,
                "document": doc_type,
                "document_label": name,
                "expected": None,
                "actual": None,
                "message": f"{name}에 {label}{particle(label, '이')} 비어 있습니다. "
                           "이 칸이 비면 통관에서 되돌아올 수 있습니다.",
            })
    return findings


_QTY_WITH_UNIT = re.compile(r"^\s*([\d,]+(?:\.\d+)?)\s*[A-Za-z./]{0,12}\s*$")


def _qty_number(value):
    """수량 칸은 "2,000 PCS" 처럼 단위가 붙어 나옵니다. 숫자만 읽습니다(없으면 None).

    단위가 붙은 줄은 qty × price 검산을 통째로 건너뛰어, 6,400 이어야 할 금액이 5,000 이어도 통과했습니다
    (전수 점검 4회차).
    """

    number = _as_number(value)
    if number is not None:
        return number
    match = _QTY_WITH_UNIT.match(str(value or ""))
    return float(match.group(1).replace(",", "")) if match else None


def _item_findings(documents, labels) -> list[dict]:
    """품목 표의 셈. 은행은 신용장 서류에서 단가 × 수량 = 금액, 줄 합계 = 송장 금액을 다시 셉니다.

    CI 품목을 `item-0-amount = 1.00` 으로 고쳐도 검증을 통과해 확정됐습니다(전수 점검 1회차).
    값이 하나라도 비면(아직 안 적음) 그 줄은 건너뜁니다 — 없는 것은 '다르다'가 아닙니다.
    """

    findings = []
    for doc_type, data in documents.items():
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            continue
        name = labels.get(doc_type, doc_type)
        amounts = []
        for number, row in enumerate(items, start=1):
            if not isinstance(row, dict):
                continue
            qty, price, amount = (_qty_number(row.get("quantity")), _as_number(row.get("unit_price")),
                                  _as_number(row.get("amount")))
            amounts.append(amount)
            if None in (qty, price, amount) or qty <= 0:
                continue
            if abs(qty * price - amount) > 0.01 + qty * 0.00005:
                findings.append({
                    "status": "warning", "kind": "items", "field": "items", "field_label": "품목 표",
                    "document": doc_type, "document_label": name, "expected": round(qty * price, 2),
                    "actual": row.get("amount"),
                    "message": f"{name} 품목 {number}줄의 수량 × 단가({qty:g} × {price:g} = {qty * price:,.2f})가 "
                               f"금액({amount:,.2f})과 맞지 않습니다."})
        total = _as_number(data.get("invoice_value"))
        if amounts and None not in amounts and total is not None and abs(sum(amounts) - total) > 0.01:
            findings.append({
                "status": "warning", "kind": "items", "field": "invoice_value", "field_label": "Invoice Value",
                "document": doc_type, "document_label": name, "expected": round(sum(amounts), 2),
                "actual": data.get("invoice_value"),
                "message": f"{name}의 품목 금액 합계({sum(amounts):,.2f})가 Invoice Value({total:,.2f})와 "
                           "다릅니다."})
    return findings


# 날짜로 읽혀야 하는 칸. 송장 작성일에 "zzz" 를 적어도 검증을 통과해 확정됐습니다(전수 점검 1회차).
DATE_FIELDS = {"doc_date": "작성일", "etd": "출항일 (ETD)", "eta": "도착일 (ETA)", "validity_date": "유효기간",
               "date_ordered": "주문일", "date_shipped": "선적일"}
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y",
                 "%B %d, %Y", "%d-%b-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y")


def _is_date(value) -> bool:
    text = " ".join(str(value or "").replace(",", ", ").split()).replace(" ,", ",").strip()
    if not text:
        return True                                  # 비어 있는 것은 여기서 따지지 않습니다
    for pattern in _DATE_FORMATS:
        try:
            datetime.strptime(text.title() if "%b" in pattern or "%B" in pattern else text, pattern)
            return True
        except ValueError:
            continue
    return False


def _date_findings(documents, labels, form_fields) -> list[dict]:
    findings = []
    for doc_type, data in documents.items():
        shown = form_fields.get(doc_type)
        for field, label in DATE_FIELDS.items():
            if field not in data or (shown is not None and field not in shown):
                continue
            if _is_date(data[field]):
                continue
            name = labels.get(doc_type, doc_type)
            findings.append({
                "status": "warning", "kind": "format", "field": field, "field_label": label,
                "document": doc_type, "document_label": name,
                "expected": None, "actual": data[field],
                "message": f"{name}의 {label}{particle(label, '이')} 날짜로 읽히지 않습니다"
                           f" ('{str(data[field])[:30]}'). 2026-10-21 처럼 적어 주세요.",
            })
    return findings


# 영문으로 적어야 하는 칸. 세관·은행·바이어는 한글 서류를 받아 주지 않습니다. 채팅은 이를 안내하는데 서류 작성·검증은
# 한글 서류도 "모든 문서의 주요 필드가 일치합니다"로 통과시켰습니다(전수 점검 4회차).
ENGLISH_ONLY_FIELDS = {"exporter": "Exporter", "exporter_address": "Exporter 주소", "consignee": "Consignee",
                       "consignee_address": "Consignee 주소", "notify_party": "Notify Party",
                       "product_description": "품명(Description)", "shipper": "Shipper"}
_HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")


def _language_findings(documents, labels, form_fields) -> list[dict]:
    findings = []
    for doc_type, data in documents.items():
        shown = form_fields.get(doc_type)
        name = labels.get(doc_type, doc_type)
        rows = [("", data)] + [(f" 품목 {n}줄", row) for n, row in enumerate(data.get("items") or [], start=1)
                              if isinstance(row, dict)]
        for where, row in rows:
            for field, label in ENGLISH_ONLY_FIELDS.items():
                value = row.get(field)
                if not isinstance(value, str) or not _HANGUL.search(value):
                    continue
                if not where and shown is not None and field not in shown:
                    continue
                findings.append({
                    "status": "warning", "kind": "language", "field": field, "field_label": label,
                    "document": doc_type, "document_label": name, "expected": None, "actual": value[:60],
                    "message": f"{name}{where}의 {label}에 한글이 있습니다. 세관·은행은 영문 서류를 요구하므로 "
                               "영문(로마자)으로 바꿔 주세요."})
    return findings


def validate_documents(documents: dict[str, dict], reference: dict,
                       labels: dict[str, str] | None = None,
                       form_fields: dict[str, list] | None = None) -> dict:
    """Compare each document's fields against the shipment reference values.

    ``documents`` maps doc_type → field data. ``reference`` holds the expected
    values taken from the Shipment record (the single source of truth).
    ``form_fields`` is the current서식 definition; a document made before the
    서식 changed can still hold keys the form no longer has, and comparing those
    reports mismatches for boxes nobody can see or fix. So we only compare what
    the current 서식 actually shows.

    기준값 대조가 끝나면 서류끼리도 맞대어 봅니다(_cross_findings). 기준값이
    비어 있으면 그 칸은 위 순회에서 통째로 빠지는데, 그래도 서류끼리는 같아야
    하기 때문입니다. 같은 (서류, 칸)을 두 번 알리지는 않습니다.

    Returns an overall status and a list of findings.
    각 finding의 ``kind``는 ``"reference"``(기준값과 다름) 또는
    ``"cross"``(서류끼리 다름)입니다. 화면은 ``message``를 그대로 보여 줍니다.
    """

    labels = labels or {}
    form_fields = form_fields or {}
    findings = []
    for field, field_label in VALIDATION_FIELDS.items():
        if field not in reference or reference[field] in (None, ""):
            continue
        expected = _normalize(reference[field], field)
        for doc_type, data in documents.items():
            shown = form_fields.get(doc_type)
            if field not in data or (shown is not None and field not in shown):
                continue
            actual = _normalize(data[field], field)
            if actual == "":
                findings.append({
                    "status": "warning",
                    "kind": "reference",
                    "field": field,
                    "field_label": field_label,
                    "document": doc_type,
                    "document_label": labels.get(doc_type, doc_type),
                    "expected": reference[field],
                    "actual": None,
                    "message": f"{labels.get(doc_type, doc_type)}에 {field_label} 값이 비어 있습니다.",
                })
            elif not _equal(expected, actual):
                findings.append({
                    "status": "warning",
                    "kind": "reference",
                    "field": field,
                    "field_label": field_label,
                    "document": doc_type,
                    "document_label": labels.get(doc_type, doc_type),
                    "expected": reference[field],
                    "actual": data[field],
                    "message": f"{labels.get(doc_type, doc_type)}의 {field_label}"
                               f"{particle(field_label, '이')} Shipment 기준값과 다릅니다.",
                })

    # 기준값이 없어 위에서 건너뛴 칸도 서류끼리는 같아야 합니다.
    reported = {(row["document"], row["field"]) for row in findings}
    findings.extend(_cross_findings(documents, labels, form_fields, reported,
                                    reference))
    findings.extend(_missing_findings(documents, labels, form_fields, reported))
    findings.extend(_date_findings(documents, labels, form_fields))
    findings.extend(_language_findings(documents, labels, form_fields))
    findings.extend(_item_findings(documents, labels))

    return {
        "status": "warning" if findings else "passed",
        "checked_fields": list(VALIDATION_FIELDS.values()),
        "checked_documents": [labels.get(doc, doc) for doc in documents],
        "findings": findings,
    }
