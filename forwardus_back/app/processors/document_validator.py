"""Cross-document consistency checks."""

from __future__ import annotations

import math

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


def validate_documents(documents: dict[str, dict], reference: dict, labels: dict[str, str] | None = None) -> dict:
    """Compare each document's fields against the shipment reference values.

    ``documents`` maps doc_type → field data. ``reference`` holds the expected
    values taken from the Shipment record (the single source of truth).
    Returns an overall status and a list of findings.
    """

    labels = labels or {}
    findings = []
    for field, field_label in VALIDATION_FIELDS.items():
        if field not in reference or reference[field] in (None, ""):
            continue
        expected = _normalize(reference[field])
        for doc_type, data in documents.items():
            if field not in data:
                continue
            actual = _normalize(data[field])
            if actual == "":
                findings.append({
                    "status": "warning",
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
                    "field": field,
                    "field_label": field_label,
                    "document": doc_type,
                    "document_label": labels.get(doc_type, doc_type),
                    "expected": reference[field],
                    "actual": data[field],
                    "message": f"{labels.get(doc_type, doc_type)}의 {field_label}이(가) Shipment 기준값과 다릅니다.",
                })

    return {
        "status": "warning" if findings else "passed",
        "checked_fields": list(VALIDATION_FIELDS.values()),
        "checked_documents": [labels.get(doc, doc) for doc in documents],
        "findings": findings,
    }
