"""Home screen."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, url_for

from app.routes import error_response
from app.services import (ServiceError, document_start_service, intake_service,
                          shipment_service, support_chat_service)
from app.validators import ValidationError

home_bp = Blueprint("home", __name__)


def _tabs() -> list[dict]:
    """시작 화면의 다섯 갈래.

    상담만 적는 칸 하나로 끝나고, 나머지 넷은 서식 칸을 펼칩니다.
    넷은 **같은 초안 하나**를 나눠 씁니다. 일정에서 고른 날짜가 운송계획의
    스케줄 조회에 쓰이고, 그 결과가 서류의 출항일이 되는 식입니다.
    """

    return [
        # 여기 적은 글로 두 가지를 합니다. 물어보거나, 서류 초안을 채우거나.
        {"key": "chat", "icon": "💬", "label": "상담", "go": "", "form": False,
         "placeholder": ("궁금한 것을 물어보세요. 보내실 화물을 적으면 서류 칸을 채워 드립니다.\n"
                         "예) 부산에서 LA로 11월 초에 치약 500박스, 한 박스 40x30x25cm에 "
                         "12kg, 전부 25,000달러 FOB로 보냅니다"),
         "hint": ("관세율·운임 같은 숫자는 짐작해서 답하지 않고 조회 화면으로 안내합니다. "
                  "화물을 적으셨다면 <b>서류 초안 채우기</b>를 눌러 주세요."),
         "fill_label": "📄 서류 초안 채우기",
         "examples": ["수출할 때 꼭 필요한 서류가 뭔가요?",
                      "FOB랑 CIF는 어떻게 다른가요?",
                      "원산지증명서는 어디서 받나요?",
                      "인코텀즈는 어떻게 고르나요?",
                      "적재의무기한이 뭔가요?"]},
        {"key": "doc", "icon": "📄", "label": "서류작성", "go": "", "form": True,
         "placeholder": "", "hint": "", "examples": []},
        {"key": "origin", "icon": "🏅", "label": "원산지증명서", "go": "", "form": True,
         "placeholder": "", "hint": "", "examples": []},
        {"key": "plan", "icon": "📦", "label": "운송계획", "go": "", "form": True,
         "placeholder": "", "hint": "", "examples": []},
        {"key": "when", "icon": "🗓", "label": "일정선택", "go": "", "form": True,
         "placeholder": "", "hint": "", "examples": []},
    ]


# 왼쪽 세로 줄. 가운데는 적는 칸 하나만 남기고 나머지는 전부 이리로 옮겼습니다.
RAIL = [
    {"key": "planning", "icon": "📦", "tone": "blue", "label": "운송 계획",
     "note": "출발·도착지와 화물을 넣으면 스케줄과 물류비를 봅니다"},
    {"key": "shipment", "icon": "📄", "tone": "green", "label": "서류 작성",
     "note": "상업송장·포장명세서를 Shipment 데이터로 자동 작성합니다"},
    {"key": "reverse", "icon": "📅", "tone": "amber", "label": "일정 역산",
     "note": "Buyer 납기일에서 거꾸로 언제 보내야 하는지 계산합니다"},
]

RAIL_URLS = {"planning": "planning.new", "shipment": "shipment.index",
             "reverse": "planning.index"}


@home_bp.get("/")
def index():
    rail = [{**item, "url": url_for(RAIL_URLS[item["key"]])} for item in RAIL]
    # 통화 목록은 여기서 채우지 않습니다. 관세청에서 받아오는 값이라 기관이
    # 멈추면 시작 화면이 통째로 기다리게 됩니다. 환율 계산기를 펼칠 때
    # 따로 받아 옵니다.
    return render_template("home/index.html", recent=shipment_service.list_shipments()[:3],
                           tabs=_tabs(), rail=rail,
                           checklist=document_start_service.checklist())


@home_bp.post("/api/intake")
def api_intake():
    """대화창에 적은 수출 내용을 읽어 서류 칸을 채울 초안을 돌려줍니다.

    Shipment를 만들지는 않습니다. 사람이 화면에서 확인하고 만듭니다.
    """

    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"success": True, "data": intake_service.read(payload.get("text", ""))})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)


@home_bp.post("/api/support-chat")
def api_support_chat():
    """어느 화면에서나 열 수 있는 고객상담 창구."""

    payload = request.get_json(silent=True) or {}
    try:
        result = support_chat_service.ask(payload.get("question", ""),
                                          payload.get("history") or [])
    except ServiceError as error:
        return jsonify({"success": False, "message": str(error),
                        "error_code": error.error_code, "source": "api"}), error.status
    return jsonify(result), (200 if result["success"] else 502)
