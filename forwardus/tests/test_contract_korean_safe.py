"""국문 계약서 — 새 독소조항이 정상 문장을 짚지 않는가 (2026-10-03).

왜 이 파일이 있나
  실제 계약서 검증(SEC EDGAR · CUAD 1,310 건)은 전부 영문이라, 실제 분쟁 문구로
  넣은 조항들의 **국문 규칙**은 걸리면 안 되는 문장으로 재 본 적이 없습니다.
  수출자에게 유리하거나 흔한 정상 국문 조항을 먼저 적어 둡니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

SAFE = [
    # battle_of_forms — 본 계약이 우선하는 꼴
    ("battle_of_forms", "제2조 본 계약은 매수인의 발주서보다 우선하여 적용된다."),
    ("battle_of_forms", "제2조 매수인의 발주서에 본 계약과 다른 조건이 있으면 그 조건은 효력이 없다."),
    # foreign_language_prevails — 국문·영문 우선, 참고용 번역
    ("foreign_language_prevails", "제30조 본 계약은 국문과 영문으로 작성하며, 다툼이 있으면 국문을 우선한다."),
    ("foreign_language_prevails", "제30조 중문 번역본은 참고용이며 영문본을 정본으로 한다."),
    ("foreign_language_prevails", "제30조 중문본은 영문본에 우선하지 아니한다."),
    # acceptance_signature_payment — 매도인이 확인서에 서명, 간주 인수
    ("acceptance_signature_payment", "제7조 잔금은 매도인이 설치 완료 확인서를 발급한 날부터 30일 이내에 지급한다."),
    ("acceptance_signature_payment", "제7조 잔금은 시운전 완료 확인서 서명일부터 30일 이내에 지급하되, 매수인이 10일 "
                                     "이내에 서명하지 아니하면 서명한 것으로 간주한다."),
    # on_demand_bond — 바이어가 내는 보증, 중재판정이 있어야 청구
    ("on_demand_bond", "제8조 매수인은 매도인을 수익자로 하는 지급보증서를 은행으로부터 발급받아 제출한다."),
    ("on_demand_bond", "제8조 이행보증금은 중재판정이 확정된 경우에만 청구할 수 있다."),
    # time_essence_cancel — 최고·유예기간·불가항력
    ("time_essence_cancel", "제10조 선적이 지연되면 매수인은 15일의 유예기간을 정하여 최고한 후 그 기간 내에 "
                            "선적되지 아니한 분에 한하여 해제할 수 있다."),
    ("time_essence_cancel", "제10조 불가항력으로 선적이 60일 넘게 지연되면 각 당사자는 계약을 해제할 수 있다."),
    # cover_purchase — 상한, 매도인이 재판매
    ("cover_purchase", "제11조 매수인이 제3자로부터 구매한 경우 그 차액은 매도인이 부담하되, 지연 물품 "
                       "대금의 10%를 한도로 한다."),
    ("cover_purchase", "제11조 매수인이 인수를 거절하면 매도인은 물품을 재판매하고 그 차액을 매수인에게 청구할 수 있다."),
    # one_way_force_majeure — 양쪽 모두
    ("one_way_force_majeure", "제12조 불가항력 조항은 양 당사자에게 동일하게 적용된다."),
    ("one_way_force_majeure", "제12조 어느 당사자도 불가항력으로 인한 이행 지체에 대하여 책임을 지지 아니한다."),
    # unilateral_amendment — 서면 합의로만
    ("unilateral_amendment", "제13조 본 계약은 양 당사자의 서면 합의로만 변경할 수 있다."),
    ("unilateral_amendment", "제13조 매수인은 선적 30일 전까지 서면 통지로 인도 장소를 변경할 수 있다."),
    # unlimited_damages — 간접손해 배제·한도
    ("unlimited_damages", "제14조 매도인의 배상책임은 해당 물품 대금을 한도로 하며, 간접손해는 배상하지 아니한다."),
    ("unlimited_damages", "제14조 매수인은 매도인이 입은 모든 손해를 배상한다."),
]


@pytest.mark.parametrize("key,line", SAFE, ids=[f"{k}:{s[:24]}" for k, s in SAFE])
def test_국문_정상_조항은_짚지_않는다(key, line):
    assert key not in contract_clauses.find_in("수출 매매계약서\n" + line)


TOXIC = [
    ("battle_of_forms", "제2조 본 거래에는 매수인의 구매약관이 우선하여 적용된다."),
    ("foreign_language_prevails", "제30조 국문과 중문이 다를 때에는 중문을 우선한다."),
    ("acceptance_signature_payment", "제7조 잔금은 매수인이 시운전 완료 확인서에 서명한 날부터 30일 이내에 지급한다."),
    ("on_demand_bond", "제8조 매도인은 매수인의 서면 청구만으로 조건 없이 지급되는 이행보증서를 제출한다."),
    ("time_essence_cancel", "제10조 선적이 3일 이상 지연되면 매수인은 즉시 계약을 해제할 수 있다."),
    ("cover_purchase", "제11조 매도인이 납기를 어기면 매수인은 제3자로부터 구매하고 그 차액을 매도인이 부담한다."),
    ("one_way_force_majeure", "제12조 불가항력 조항은 매수인에게만 적용된다."),
    ("unilateral_amendment", "제13조 매수인은 통지만으로 본 계약의 조건을 변경할 수 있다."),
]


@pytest.mark.parametrize("key,line", TOXIC, ids=[f"{k}:{s[:24]}" for k, s in TOXIC])
def test_국문_독소_조항은_짚는다(key, line):
    assert key in contract_clauses.find_in("수출 매매계약서\n" + line)
