"""영어 계약서 독소 문장 보강(무역 실무 팀장 점검) — 걸리면 안 되는 문장부터."""

import pytest

from app.processors import contract_clauses as cc


def _keys(text):
    return {k for k, v in cc.analyze(text)["clauses"].items() if v["status"] == "present"}


@pytest.mark.parametrize("text, key", [
    ("The delivery term is FOB Busan. Seller shall bear all customs duties and clearance costs at the port of destination.", "term_conflict"),
    ("Price is FOB Incheon, and Seller shall pay the import duties and VAT in the destination country.", "term_conflict"),
    ("Seller hereby assigns to Buyer all of its intellectual property rights in the Goods.", "ip_assignment"),
    ("Seller shall be liable for all direct, indirect, incidental and consequential damages without limitation.", "unlimited_damages"),
    ("Seller's warranty obligations apply for ten (10) years and Seller is liable for indirect and consequential damages.", "unlimited_damages"),
    ("Buyer may return any goods for a full refund within five (5) years of delivery.", "full_return"),
    ("Buyer has the right to return the goods at any time within 5 years.", "full_return"),
])
def test_영어_독소_문장을_잡는다(text, key):
    assert key in _keys(text)


@pytest.mark.parametrize("text, key", [
    ("The delivery term is FOB Busan. Buyer shall bear all customs duties and VAT at the port of destination.", "term_conflict"),
    ("The delivery term is DDP Hamburg (Delivered Duty Paid). Seller shall pay the import duties at destination.", "term_conflict"),
    ("Seller shall not be liable for indirect or consequential damages.", "unlimited_damages"),
    ("Seller shall be liable for direct damages up to the contract price.", "unlimited_damages"),
    ("Seller shall be liable for direct damages only, and in no event for consequential damages.", "unlimited_damages"),
    ("Buyer may return defective goods within 30 days for replacement.", "full_return"),
    ("Buyer hereby assigns to Seller all intellectual property rights in the improvements.", "ip_assignment"),
    ("Seller hereby assigns to Buyer all of its rights to receive payment under the invoice.", "ip_assignment"),
])
def test_정상_문장은_독소로_잡지_않는다(text, key):
    assert key not in _keys(text)
