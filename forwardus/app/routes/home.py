"""Home screen."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, url_for

from app.routes import error_response
from app.services import (ServiceError, agent_service, draft_document_service,
                          intake_service, shipment_service, support_chat_service)
from app.validators import ValidationError

home_bp = Blueprint("home", __name__)


def quick_actions() -> list[dict]:
    """적는 칸 바로 위의 세 단추.

    누르면 그 모드로 대화가 시작됩니다. 칸을 펼치지 않습니다 — 칸은
    사이드바의 화면에 있고, 여기는 말로 하는 자리입니다.

    `opener`는 눌렀을 때 AI가 먼저 건네는 말입니다. 사람이 무엇부터 적어야
    할지 모르는 것이 가장 흔한 막힘이라, 첫 질문을 우리가 던집니다.
    """

    return [
        {"key": "consult", "icon": "💬", "label": "무역 상담",
         "placeholder": "수출하면서 막히는 것을 물어보세요",
         "hint": "관세율·운임 같은 숫자는 짐작해서 답하지 않고 조회 화면으로 안내합니다.",
         "opener": "수출 절차에서 막히는 것을 물어보세요. 어떤 것이든 좋습니다.",
         "examples": ["수출할 때 꼭 필요한 서류가 뭔가요?",
                      "FOB랑 CIF는 어떻게 다른가요?",
                      "원산지증명서는 어디서 받나요?",
                      "인코텀즈는 어떻게 고르나요?",
                      "적재의무기한이 뭔가요?"]},
        {"key": "planning", "icon": "📦", "label": "운송 계획",
         "placeholder": "어디서 어디로, 무엇을 언제 보내시나요",
         "hint": "출발·도착지와 화물을 알려 주시면 스케줄과 물류비를 찾아 드립니다.",
         "opener": "어디서 어디로 보내시나요? 출발지와 도착지를 알려 주세요.",
         "examples": ["부산에서 로스앤젤레스로 11월 초에 보냅니다",
                      "치약 500박스, 한 박스 40x30x25cm에 12kg입니다",
                      "항공으로 보내면 얼마나 걸리나요?"]},
        {"key": "documents", "icon": "📄", "label": "서류 작성",
         "placeholder": "어떤 서류가 필요하신가요",
         "hint": "필요한 서류만 골라 그 서류에 들어가는 것만 여쭤봅니다.",
         "opener": "어떤 서류가 필요하신가요? 상업송장·포장명세서 중에 고르셔도 되고, "
                   "둘 다 필요하시면 그렇게 말씀해 주세요.\n\n"
                   "보내실 화물을 한 번에 적어 주시면 서류 칸을 채워 드립니다. "
                   "적으신 뒤 **적은 내용으로 칸 채우기**를 눌러 주세요.",
         # 적은 글에서 값을 뽑아 서류 작성 화면의 칸을 채웁니다.
         "fill_label": "📄 적은 내용으로 칸 채우기",
         "examples": ["패킹리스트만 만들어줘",
                      "상업송장만 작성해줘",
                      "부산에서 LA로 치약 500박스, 한 박스 40x30x25cm에 12kg",
                      "마시는 수액 HS코드 알려줘"]},
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

RAIL_URLS = {"planning": "planning.new", "shipment": "document.new",
             "reverse": "planning.index"}


@home_bp.get("/")
def index():
    rail = [{**item, "url": url_for(RAIL_URLS[item["key"]])} for item in RAIL]
    # 서식 칸은 더 이상 여기서 만들지 않습니다. 사이드바의 "서류 작성"
    # 화면(/documents/new)으로 옮겼습니다. 홈은 대화하는 자리입니다.
    return render_template("home/index.html", recent=shipment_service.list_shipments()[:3],
                           actions=quick_actions(), rail=rail)


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


@home_bp.post("/api/agent")
def api_agent():
    """대화로 서류를 만드는 창구.

    서버는 상태를 갖지 않습니다. 지금까지 모은 값(draft)은 브라우저가
    들고 다니고 매번 같이 보냅니다.
    """

    payload = request.get_json(silent=True) or {}
    try:
        result = agent_service.turn(payload)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)

    # 다 그렸으면 그림까지 함께 보냅니다. 대화창에 바로 붙습니다.
    if result.get("stage") == "made":
        result["preview"] = draft_document_service.preview(
            result["kind"], result["draft"])
        result["file_url"] = url_for("document.draft_file", kind=result["kind"])
    return jsonify({"success": True, "data": result})


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
