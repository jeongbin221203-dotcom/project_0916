"""메인 챗봇으로 서류를 만드는 흐름에서 지키려는 세 가지.

1. 견적명을 **말로 물어보고** 말로 받습니다. 안 정하면 지어 줍니다.
2. 파일에 없던 값도 채팅에 적으면 서류 작성 화면의 칸까지 그대로 갑니다.
3. 상업송장 Buyer를 비우면 정확히 `SAME AS CONSIGNEE`가 찍힙니다.

AI 키 없이 돕니다. 규칙만으로도 읽혀야, 키가 없거나 응답이 실패해도
사람이 적은 값이 사라지지 않습니다.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.processors import document_defaults
from app.services import document_pipeline_service as pipe
from app.services import draft_document_service as drafts

STATIC = Path(__file__).parent.parent / "app" / "static"


@pytest.fixture(autouse=True)
def _no_ai():
    with patch.object(pipe.ai_client, "available", return_value=False):
        yield


def _form(**fields) -> dict:
    """올린 파일에서 읽어 온 값. 일부러 여러 칸을 비워 둡니다."""

    base = {"transport_mode": "SEA", "exporter_name": "SAMPLE COSMETICS",
            "exporter_address": "Seoul, Korea", "buyer_name": "SAMPLE BEAUTY INC.",
            "origin_code": "KRPUS", "destination_code": "USLAX", "currency": "USD"}
    base.update(fields)
    return {"fields": {key: value for key, value in base.items() if value},
            "items": [{"product_description": "LIPSTICK", "package_type": "carton",
                       "quantity": "100", "weight_per_package_kg": "5"}]}


def _ready(**fields) -> dict:
    """필수 정보가 다 모인 초안. 견적명은 아직 없습니다."""

    state = pipe.start({"form": _form(**fields)})
    return pipe.merge({"draft": state["draft"], "kinds": state["kinds"], "message":
                       "인코텀즈: FOB\n바이어 주소: 1 Test Ave, Los Angeles\n단가: 12.5\n"
                       "한 상자 크기: 40x30x25"})


# --- 1. 말로 묻고 말로 받는 견적명 ---------------------------------------------------

def test_필수_정보가_다_모이면_견적명을_물어본다(app):
    state = _ready()

    assert state["stage"] == "ready"
    assert state["awaiting_name"] is True
    assert "견적명" in state["reply"]
    # 무엇을 적으면 되는지 예를 들어 줍니다. 빈칸만 내밀면 무엇을 적을지 모릅니다.
    assert "2026-10 멕시코 화장품 1차" in state["reply"]
    # 안 적고 넘어가면 무엇으로 저장되는지 미리 보여 줍니다.
    assert state["project_name_suggestion"] in state["reply"]
    assert "넘어가기" in state["reply"]


def test_빠진_정보가_남아_있으면_견적명을_먼저_묻지_않는다(app):
    """답해야 할 것이 뒤섞이면 사람이 무엇을 적어야 할지 모릅니다."""

    state = pipe.start({"form": _form()})

    assert state["stage"] == "need_info"
    assert state["awaiting_name"] is False
    assert "견적명" not in state["reply"]


def test_채팅으로_적은_이름을_그대로_저장한다(app):
    ready = _ready()

    state = pipe.merge({"draft": ready["draft"], "kinds": ready["kinds"],
                        "awaiting": "project_name", "message": "ABC사 의류 수출 건"})

    assert state["project_name"] == "ABC사 의류 수출 건"
    assert state["draft"]["project_name"] == "ABC사 의류 수출 건"
    assert state["awaiting_name"] is False          # 두 번 묻지 않습니다.
    assert "ABC사 의류 수출 건" in state["reply"]


@pytest.mark.parametrize("skip", ["넘어가기", "그냥 넘어갈게요", "알아서 해줘", "없음",
                                  "자동으로", "기본값", "skip"])
def test_넘어가겠다고_하면_지어_붙인다(app, skip):
    ready = _ready()

    state = pipe.merge({"draft": ready["draft"], "kinds": ready["kinds"],
                        "awaiting": "project_name", "message": skip})

    # 도착국가_대표품목_날짜. 서류 작성 화면이 짓는 이름과 같은 모양입니다.
    assert re.fullmatch(r"미국_LIPSTICK_\d{8}", state["project_name"]), state["project_name"]
    assert state["awaiting_name"] is False


def test_이름을_물었는데_다른_값을_적으면_그_값으로_읽는다(app):
    """"칸 이름: 값" 꼴이면 이름이 아니라 고치려는 값입니다."""

    ready = _ready()

    state = pipe.merge({"draft": ready["draft"], "kinds": ready["kinds"],
                        "awaiting": "project_name", "message": "결제조건: L/C at sight"})

    assert state["draft"]["payment_terms"] == "L/C at sight"
    assert not state["project_name"]
    assert state["awaiting_name"] is True           # 이름은 아직 안 정했습니다.


def test_이름을_물었는데_값을_문장으로_적어도_값으로_읽는다(app):
    """"수량은 500개"가 건 이름으로 목록에 남으면 안 됩니다."""

    ready = _ready()

    state = pipe.merge({"draft": ready["draft"], "kinds": ready["kinds"],
                        "awaiting": "project_name", "message": "수량은 500개로 해줘"})

    assert state["draft"]["items"][0]["quantity"] == "500"
    assert not state["project_name"]


def test_이름을_물었는데_서류를_더_만들어_달라고_하면_이름이_아니다(app):
    ready = _ready()

    state = pipe.merge({"draft": ready["draft"], "kinds": ready["kinds"],
                        "awaiting": "project_name", "message": "선적의뢰서도 만들어줘"})

    assert not state["project_name"]
    assert state["awaiting_name"] is True


@pytest.mark.parametrize("name", ["자동차 부품 수출 건", "없어도 되는 물량 1차",
                                  "패스트푸드 수출", "그냥커피 수출건"])
def test_넘어가기처럼_시작하는_이름도_이름으로_받는다(app, name):
    """"자동차 부품 수출 건"이 "자동"으로 시작한다고 넘어가기가 되면 안 됩니다."""

    ready = _ready()

    state = pipe.merge({"draft": ready["draft"], "kinds": ready["kinds"],
                        "awaiting": "project_name", "message": name})

    assert state["project_name"] == name


def test_이름을_안_정하고_만들면_지어_붙인다(app):
    """이름 없는 건이 대시보드 목록에 쌓이지 않게 합니다."""

    ready = _ready()

    made = pipe.generate({"draft": ready["draft"], "kinds": ["commercial_invoice"]})

    assert made["stage"] == "made"
    assert re.fullmatch(r"미국_LIPSTICK_\d{8}", made["project_name"])
    assert made["project_name"] in made["reply"]


# --- 2. 파일 + 채팅 하이브리드 병합 --------------------------------------------------

CHAT = ("수량은 500개로 해줘\n"
        "단가는 15달러야\n"
        "인코텀즈 CIF 마이애미로 변경해줘\n"
        "바이어 주소는 1 Ocean Dr, Miami, FL 33101\n"
        "결제조건: T/T 30 days after B/L date\n"
        "화인: ABC / MIA / C-NO 1-500\n"
        "LC번호: LC-2026-77\n"
        "컨테이너번호: TEMU1234567\n"
        "담당자: Mr. Lee\n"
        "주문번호: PO-9912\n"
        "비고: Fragile")


def _merged(app_unused=None) -> dict:
    state = pipe.start({"form": _form()})
    return pipe.merge({"draft": state["draft"], "kinds": state["kinds"],
                       "message": CHAT + "\n한 상자 크기: 40x30x25"})["draft"]


def test_채팅에만_적은_값이_초안에_모두_들어간다(app):
    """파일에 없던 조건도 말로 적으면 서류에 들어가야 합니다."""

    draft = _merged()

    assert draft["incoterms"] == "CIF"
    assert draft["incoterms_place"] == "마이애미"
    assert draft["buyer_address"] == "1 Ocean Dr, Miami, FL 33101"
    assert draft["payment_terms"] == "T/T 30 days after B/L date"
    assert draft["shipping_marks"] == "ABC / MIA / C-NO 1-500"
    assert draft["lc_no"] == "LC-2026-77"
    assert draft["container_no"] == "TEMU1234567"
    assert draft["attention"] == "Mr. Lee"
    assert draft["customer_order_no"] == "PO-9912"
    assert draft["remarks"] == "Fragile"
    # 파일에 100개로 적혀 있어도, 말로 500개라고 하면 말이 이깁니다.
    assert draft["items"][0]["quantity"] == "500"
    assert draft["items"][0]["unit_price"] == "15"


def test_합친_초안의_칸_이름이_서류_작성_화면의_칸과_같다(app, client):
    """이 시험이 "빈칸 없이 프리필"을 지킵니다.

    대화창이 모은 초안은 sessionStorage를 거쳐 서류 작성 화면이 그대로 꽂습니다
    (home.js stashForDocForm → doc_form.js FORWARDUS_DOC_FILL). 칸 이름이 어긋나면
    조용히 빈칸으로 남습니다. 그래서 이름이 같은지 여기서 봅니다.
    """

    draft = _merged()
    html = client.get("/documents/new").get_data(as_text=True)
    names = set(re.findall(r'name="([a-z_]+)"', html))

    # 화면에 칸이 없는 것은 incoterms_place 하나뿐입니다. 그 값은 서식에서
    # 가격 조건에 붙여 인쇄됩니다("CIF MIAMI"). 화면에는 따로 칸이 없습니다.
    absent = {key for key in draft if key != "items" and key not in names}
    assert absent == {"incoterms_place"}, absent
    assert all(f"item_{key}" in names for key in draft["items"][0])


def test_대화창이_모은_값을_서류_작성_화면이_집어_간다(app):
    """두 화면은 sessionStorage 한 자리를 통해 이어집니다.

    자리 이름이 어긋나면 아무 말 없이 빈 화면이 됩니다. 눈으로는 알 수 없어
    여기서 봅니다. 값의 모양(칸 이름)은 바로 위 시험이 봅니다.
    """

    home = (STATIC / "js/home.js").read_text(encoding="utf-8")
    form = (STATIC / "js/doc_form.js").read_text(encoding="utf-8")

    assert 'setItem("forwardus:doc-draft"' in home
    assert 'getItem("forwardus:doc-draft")' in form
    # 채팅으로 값을 합칠 때마다, 그리고 그 화면으로 넘어가기 직전에 놓아 둡니다.
    assert home.count("stashForDocForm") >= 3
    # 견적명 답인지 아닌지를 서버가 알 수 있게 같이 보냅니다.
    assert 'awaiting: pipe.awaiting_name ? "project_name" : ""' in home


def test_채팅으로_고친_값이_서류에_그대로_찍힌다(app):
    draft = _merged()

    invoice = pipe.review_document("commercial_invoice", drafts.as_text(draft))

    assert invoice["data"]["incoterms"] == "CIF 마이애미"      # 조건은 장소와 함께
    assert invoice["data"]["payment_terms"] == "T/T 30 days after B/L date"
    assert invoice["data"]["shipping_marks"] == "ABC / MIA / C-NO 1-500"
    assert invoice["data"]["lc_no"] == "LC-2026-77"
    assert invoice["data"]["consignee_address"] == "1 Ocean Dr, Miami, FL 33101"


def test_문장으로_적어도_읽는다(app):
    """사람은 "칸 이름: 값" 꼴로만 적지 않습니다."""

    found = pipe._rule_read("수출자는 Forward Cosmetics Co., Ltd.", {})

    # 상호 끝의 마침표는 이름의 일부입니다. 떼면 다른 회사가 됩니다.
    assert found["exporter_name"] == "Forward Cosmetics Co., Ltd."


def test_아는_칸_이름이_아니면_건드리지_않는다(app):
    """"이 건은 급합니다"의 "건"을 칸 이름으로 읽으면 엉뚱한 값이 들어갑니다."""

    assert not [value for key, value in pipe._rule_read("이 건은 급합니다", {}).items() if value]


# --- 3. Buyer 공란 → SAME AS CONSIGNEE -----------------------------------------------

def test_Buyer를_비우면_정확히_SAME_AS_CONSIGNEE가_찍힌다(app):
    draft = _merged()

    invoice = pipe.review_document("commercial_invoice", drafts.as_text(draft))

    assert invoice["data"]["consignee"] == "SAMPLE BEAUTY INC."
    assert invoice["data"]["buyer"] == "SAME AS CONSIGNEE"


def test_SAME_AS_BUYER는_어디에도_넣지_않는다(app):
    """받는 곳을 모르는 상태에서 문구를 상호 자리에 옮기면 안 됩니다.

    그 서류는 받는 곳 이름이 "SAME AS CONSIGNEE"인 채로 나갑니다.
    비워 두고 필수 항목으로 다시 묻는 편이 맞습니다.
    """

    assert not hasattr(document_defaults, "SAME_AS_BUYER")
    assert document_defaults.pair_parties("", "SAME AS CONSIGNEE") == ("", "SAME AS CONSIGNEE")

    state = pipe.start({"form": _form(buyer_name="", buyer="SAME AS CONSIGNEE")})
    assert "buyer_name" in {row["key"] for row in state["missing"]}


def test_Buyer를_직접_적으면_그_값이_남는다(app):
    """대금을 내는 곳이 받는 곳과 다르면 적은 대로 찍혀야 합니다."""

    state = pipe.start({"form": _form()})
    merged = pipe.merge({"draft": state["draft"], "kinds": state["kinds"], "message":
                         "인코텀즈: FOB\n바이어 주소: 1 Test Ave\n단가: 12.5\n"
                         "한 상자 크기: 40x30x25\n실제바이어: ABC Trading Ltd."})

    invoice = pipe.review_document("commercial_invoice", drafts.as_text(merged["draft"]))
    assert invoice["data"]["buyer"] == "ABC Trading Ltd."
    assert invoice["data"]["consignee"] == "SAMPLE BEAUTY INC."
