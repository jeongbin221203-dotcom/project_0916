"""서류의 "합계" 칸은 **모든 품목을 더한 값**입니다. (2026-09-28)

무엇이 났나
  배포된 화면에서 우산 오퍼시트(품목 2줄)로 서류를 만들어 원본과 맞췄더니
  품목 줄은 완벽한데 합계가 틀렸습니다.

      포장명세서 NET 360.00 · GROSS 408.00 · CBM 2.016 · QUANTITY 24
      원본 합계   NET 720    · GROSS 808    · CBM 3.612 · 40상자

  build_reference 가 shipment.cargo(=cargos[0], **첫 품목**)를 썼습니다.
  품목이 하나면 합계와 같아서 지금껏 안 보였습니다.

왜 큰일인가
  포장명세서의 중량·용적은 그대로 **B/L 과 통관 신고**로 갑니다.
  808kg 짐을 408kg 로 신고하면 선사 청구가 어긋나고 세관이 되묻습니다.
"""

from __future__ import annotations

import pytest

from app.services.document_service import _headline, _summed


class Line:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


UMBRELLA = [
    Line(total_weight_kg=408.0, net_weight_kg=360.0, total_cbm=2.016, quantity=24,
         product_description="3-fold manual umbrella", hs_code="6601910000"),
    Line(total_weight_kg=400.0, net_weight_kg=360.0, total_cbm=1.596, quantity=16,
         product_description="Straight automatic-open umbrella", hs_code="6601992000"),
]


@pytest.mark.parametrize("attribute,want", [
    ("total_weight_kg", 808),      # 서류: gross weight 808 kg
    ("net_weight_kg", 720),        # 서류: net weight 720 kg
    ("total_cbm", 3.612),          # 서류: volume 3.612 CBM
    ("quantity", 40),              # 서류: 40 cartons
])
def test_모든_품목을_더한다(attribute, want):
    assert _summed(UMBRELLA, attribute) == pytest.approx(want)


def test_한_줄이라도_비면_합계를_내지_않는다():
    """**반쪽 합계가 가장 위험합니다.**

    세 줄 중 두 줄만 더한 중량이 B/L 에 찍히면 아무도 못 알아챕니다.
    모르면 비워 두고 사람이 채우게 합니다.
    """

    half = [UMBRELLA[0], Line(total_weight_kg=400.0, net_weight_kg=None,
                              total_cbm=1.596, quantity=16,
                              product_description="x", hs_code="y")]
    assert _summed(half, "net_weight_kg") is None
    assert _summed(half, "total_weight_kg") == pytest.approx(808)   # 이건 다 있습니다


def test_품목이_하나면_지금까지와_같다():
    """고치다가 흔한 경우를 바꾸면 안 됩니다."""

    assert _summed(UMBRELLA[:1], "total_weight_kg") == pytest.approx(408)
    assert _headline(UMBRELLA[:1], "product_description") == "3-fold manual umbrella"


def test_더할_수_없는_값은_대표에_외_N건을_붙인다():
    """"합계" 라는 이름 아래 첫 줄만 적으면 그것이 전부인 줄 압니다."""

    assert _headline(UMBRELLA, "product_description") == "3-fold manual umbrella 외 1건"
    assert _headline(UMBRELLA, "hs_code") == "6601910000 외 1건"


def test_품목이_없으면_빈_값이다():
    assert _summed([], "total_weight_kg") is None
    assert _headline([], "product_description") == ""


def test_실제_서류가_합계를_쓴다(app, create_shipment):
    """함수가 아니라 **build_reference 가 그 값을 쓰는지**를 봅니다.

    이 테스트가 없으면 _summed 를 build_reference 에서 빼도 울지 않습니다.
    (2026-09-28 되돌림 검사에서 배운 것 — 함수만 보면 배선을 못 봅니다)
    """

    from sqlalchemy import inspect

    from app.extensions import db
    from app.models import Cargo
    from app.services.document_service import build_reference

    shipment = create_shipment()
    first = shipment.cargos[0]

    # 첫 품목의 칸을 그대로 복사합니다. 합계가 정확히 두 배가 되어야 합니다.
    copied = {column.key: getattr(first, column.key)
              for column in inspect(Cargo).mapper.column_attrs
              if column.key not in ("id",)}
    copied["product_description"] = "둘째 품목"
    db.session.add(Cargo(**copied))
    db.session.commit()

    reference = build_reference(shipment)
    assert reference["gross_weight_kg"] == pytest.approx(first.total_weight_kg * 2)
    assert reference["total_cbm"] == pytest.approx(first.total_cbm * 2)
    assert reference["quantity"] == pytest.approx(first.quantity * 2)
    assert "외 1건" in reference["product_description"]
