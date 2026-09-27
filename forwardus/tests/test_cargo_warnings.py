"""앞뒤가 안 맞는 화물을 **화면에서 볼 수 있는가.**

서버는 진작 이런 말을 만들어 보내고 있었습니다.
  "1CBM당 26,667kg입니다. 오스뮴(22,590kg)보다 무거운 화물은 없으니 값이
   잘못 적혔습니다. 포장당 중량 칸에 전체 중량을 적었거나…"
그런데 화면 어디에도 붙지 않아 **아무도 못 봤습니다.** 계산은 멀쩡히 되고
숫자도 그럴듯해서, 견적을 받고 나서야 압니다. 포장당 중량 칸에 전체 중량을
적으면 운임 기준이 100배 틀립니다. (2026-09-26)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

NORMAL = {"product_description": "치약", "package_type": "carton", "quantity": "100",
          "length_cm": "40", "width_cm": "30", "height_cm": "25",
          "weight_per_package_kg": "8"}


def _cargo(client, **overrides):
    item = {**NORMAL, **overrides}
    response = client.post("/planning/api/cargo",
                           json={"items": [item], "transport_mode": "SEA", "sea_mode": "LCL"})
    assert response.status_code == 200, response.get_data(as_text=True)[:200]
    return response.get_json()["data"]


def test_정상_화물에는_경고가_없다(client):
    assert not (_cargo(client).get("warnings") or [])


def test_포장당_중량에_전체_중량을_적으면_알려_준다(client):
    """가장 흔한 실수입니다. 운임 기준이 100배 틀립니다."""

    data = _cargo(client, weight_per_package_kg="800")
    messages = " ".join(row["message"] for row in data["warnings"])
    assert "포장당 중량" in messages
    assert "오스뮴" in messages, "왜 있을 수 없는 값인지까지 말해 주어야 합니다"


def test_금보다_무거우면_알려_준다(client):
    data = _cargo(client, quantity="10", length_cm="10", width_cm="10",
                  height_cm="10", weight_per_package_kg="20")
    messages = " ".join(row["message"] for row in data["warnings"])
    assert "1CBM당" in messages


def test_경고에_품목_번호가_붙는다(client):
    """품목이 여럿이면 어느 줄이 이상한지 알아야 고칩니다."""

    response = client.post("/planning/api/cargo", json={
        "items": [NORMAL, {**NORMAL, "weight_per_package_kg": "800"}],
        "transport_mode": "SEA", "sea_mode": "LCL"})
    warnings = response.get_json()["data"]["warnings"]
    assert warnings and all(row["line_no"] == 2 for row in warnings)


@pytest.mark.parametrize("where,hook", [
    ("app/templates/planning/new.html", "data-calc-warnings"),
    ("app/templates/document/_form.html", "data-doc-warnings"),
])
def test_두_화면_모두_경고를_붙일_자리가_있다(where, hook):
    assert hook in (ROOT / where).read_text(encoding="utf-8")


@pytest.mark.parametrize("where,hook", [
    ("app/static/js/planning.js", "data-calc-warnings"),
    ("app/static/js/doc_form.js", "data-doc-warnings"),
])
def test_두_화면_모두_경고를_그려_넣는다(where, hook):
    text = (ROOT / where).read_text(encoding="utf-8")
    assert hook in text
    assert re.search(r"data\.warnings|response\.data\.warnings", text), \
        "서버가 보낸 warnings 를 읽어야 합니다"


def test_경고_상자에_CSS가_있다():
    """규칙이 없으면 글자가 그냥 흘러 나와 지나칩니다."""

    css = "\n".join(p.read_text(encoding="utf-8")
                    for p in (ROOT / "app/static/css").glob("*.css"))
    assert ".calc_warnings" in css
