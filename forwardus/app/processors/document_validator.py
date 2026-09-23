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

from app.processors.korean import particle

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
}

NUMERIC_TOLERANCE = 0.01


def _normalize(value):
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
        value = _normalize(data[field])
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


def _cross_findings(documents, labels, form_fields, reported) -> list[dict]:
    """서류끼리 맞대어 봅니다. 기준값이 없어도 서로는 같아야 합니다.

    ``reported``는 기준값 대조에서 이미 지적한 (서류, 칸)입니다. 같은 자리를
    두 번 알리지 않습니다. 기준값 쪽이 "무엇과 달라야 하는지"까지 알려 주므로
    더 쓸모 있고, 두 줄이 나란히 뜨면 고칠 곳이 둘인 줄 알게 됩니다.
    """

    findings = []
    for field, field_label in VALIDATION_FIELDS.items():
        written = _written(documents, form_fields, field)
        if len(written) < 2:
            continue
        groups = _group(written)
        if len(groups) < 2:
            continue

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
        expected = _normalize(reference[field])
        for doc_type, data in documents.items():
            shown = form_fields.get(doc_type)
            if field not in data or (shown is not None and field not in shown):
                continue
            actual = _normalize(data[field])
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
    findings.extend(_cross_findings(documents, labels, form_fields, reported))

    return {
        "status": "warning" if findings else "passed",
        "checked_fields": list(VALIDATION_FIELDS.values()),
        "checked_documents": [labels.get(doc, doc) for doc in documents],
        "findings": findings,
    }
