"""Home screen."""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, render_template, request, url_for

from app.routes import error_response
from app.routes.auth import current_user
from app.services import (ServiceError, agent_service, attachment_service,
                          chat_capture_service, chat_memory_service,
                          document_extract_service, document_pipeline_service,
                          intake_service, support_chat_service, work_draft_service)
from app.validators import ValidationError

home_bp = Blueprint("home", __name__)


def quick_actions() -> list[dict]:
    """적는 칸 바로 위의 세 단추. 순서: 무역 상담 → 서류 작성 → 운송 계획 (그 뒤에 HS CODE 조회)

    서류 작성이 운송 계획보다 앞입니다. 서류에 적은 값이 운송 계획 칸을 미리 채웁니다.

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
         # 원산지증명서는 답이 길어 맨 뒤에 둡니다. 앞의 짧은 것부터 보이게.
         "examples": ["수출할 때 꼭 필요한 서류가 뭔가요?",
                      "FOB랑 CIF는 어떻게 다른가요?",
                      "인코텀즈는 어떻게 고르나요?",
                      "적재의무기한이 뭔가요?",
                      "원산지증명서는 어디서 받나요?"]},
        {"key": "documents", "icon": "📄", "label": "서류 작성",
         "placeholder": "어떤 서류가 필요하신가요",
         "hint": "필요한 서류만 골라 그 서류에 들어가는 것만 여쭤봅니다.",
         "opener": "어떤 서류가 필요하신가요? 상업송장·포장명세서 중에 고르셔도 되고, "
                   "둘 다 필요하시면 그렇게 말씀해 주세요.\n\n"
                   "보내실 화물을 한 번에 적어 주시면 서류 칸을 채워 드립니다. "
                   "적으신 뒤 **적은 내용으로 칸 채우기**를 눌러 주세요.\n\n"
                   "받아 두신 B/L·Offer Sheet·견적서가 있으면 적는 칸 왼쪽 아래 **+**로 "
                   "올려 주세요. 읽은 값으로 서류를 만들고, 빠진 것만 여쭤봅니다.",
         # 적은 글에서 값을 뽑아 서류 작성 화면의 칸을 채웁니다.
         # (서류 올리기는 칩이 아니라 세 탭이 같이 쓰는 적는 칸의 + 단추입니다)
         "fill_label": "✨ 서류 칸 자동 입력",
         "examples": ["패킹리스트만 만들어줘", "상업송장만 작성해줘"],
         # 빈 서식 PDF를 그대로 내려받는 자리. 대화를 시작하는 칩과 성격이
         # 달라 따로 둡니다. (/documents/blank/<kind>.pdf)
         "downloads": [{"label": "패킹리스트(PDF)", "kind": "packing_list_std"},
                       {"label": "상업송장(PDF)", "kind": "commercial_invoice"}]},
        {"key": "planning", "icon": "📦", "label": "운송 예상 견적",
         "placeholder": "어디서 어디로, 무엇을 언제 보내시나요",
         "hint": "출발·도착지와 화물을 알려 주시면 스케줄과 물류비를 찾아 드립니다.",
         "opener": "어디서 어디로 보내시나요? 출발지와 도착지를 알려 주세요.",
         "examples": ["부산에서 로스앤젤레스로 11월 초에 보냅니다",
                      "치약 500박스, 한 박스 40x30x25cm에 12kg입니다",
                      "항공으로 보내면 얼마나 걸리나요?"]},
    ]


@home_bp.get("/")
def index():
    # 서식 칸은 사이드바의 "서류 작성" 화면(/documents/new)에 있습니다. 홈은 대화하는 자리입니다.
    # 사이드바(최근 Shipment 포함)는 모든 화면에 붙어 base.html이 그립니다. (routes/sidebar.py)
    return render_template("home/index.html", actions=quick_actions())


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
    # 서류가 둘이면 둘 다 그립니다. 수출에는 함께 내는 것이라 따로 볼 이유가 없습니다.
    # 검토 창(미리보기·고치기)이 쓰는 칸 값도 함께 넣습니다.
    if result.get("stage") == "made":
        for row in result.get("documents", []):
            row.update(document_pipeline_service.review_document(row["kind"], result["draft"]))
            row["file_url"] = url_for("document.draft_file", kind=row["kind"])
    return jsonify({"success": True, "data": result})


@home_bp.get("/api/chat-memory")
def api_chat_memory():
    """이 회원의 지난 상담. 로그인 전이면 비어 있습니다. (Entity)"""

    viewer = current_user()
    rows = chat_memory_service.messages(viewer)
    kept = chat_memory_service.context(viewer)
    return jsonify({"success": True, "data": {
        "summary": kept["summary"],
        "messages": [{"role": row.role, "text": row.text, "source": row.source,
                      "at": row.created_at.isoformat()} for row in rows],
    }})


@home_bp.delete("/api/chat-memory")
def api_forget_chat():
    """새 대화. 이 회원의 상담 기억을 지웁니다."""

    chat_memory_service.forget(current_user())
    return jsonify({"success": True})


@home_bp.post("/api/doc-pipeline/<step>")
def api_doc_pipeline(step: str):
    """올린 서류 → 빠진 정보 묻기 → 채팅으로 합치기 → 고른 서류 만들기.

    서버는 상태를 갖지 않습니다. 초안(draft)은 브라우저가 들고 다닙니다.
    """

    handlers = {"start": document_pipeline_service.start,
                "merge": document_pipeline_service.merge,
                "generate": document_pipeline_service.generate,
                # 앞서 올린 서류가 있을 때, 상담 탭에서 적은 말이 서류를 만들어 달라는 것인지.
                "intent": lambda payload: document_pipeline_service.intent(
                    payload.get("message", ""))}
    if step not in handlers:
        return error_response(ServiceError("없는 단계입니다.", "NOT_FOUND", 404))
    try:
        result = handlers[step](request.get_json(silent=True) or {})
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": result})


@home_bp.post("/api/attach")
def api_attach():
    """적는 칸의 `+`로 붙인 파일과 같이 적은 말. 세 탭이 같이 씁니다.

    서류 종류를 알아보고, 서류를 만들어 달라는 말이면 서류 작성 흐름으로 보냅니다.
    올린 파일은 남기지 않습니다.
    """

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return error_response(ServiceError("올릴 파일을 골라 주세요.", "VALIDATION_ERROR"))
    data = upload.stream.read(document_extract_service.MAX_UPLOAD_BYTES + 1)
    try:
        history = json.loads(request.form.get("history") or "[]")
    except ValueError:
        history = []
    history = [turn for turn in history if isinstance(turn, dict)] if isinstance(history, list) else []
    try:
        result = attachment_service.handle(upload.filename, data,
                                           message=request.form.get("message", ""),
                                           mode=request.form.get("mode", "consult"),
                                           history=history)
    except (ValidationError, ServiceError) as exc:
        return error_response(exc)
    return jsonify({"success": True, "data": result})


@home_bp.post("/api/support-chat")
def api_support_chat():
    """어느 화면에서나 열 수 있는 고객상담 창구."""

    payload = request.get_json(silent=True) or {}
    question = payload.get("question", "")
    # 로그인한 회원의 상담은 대화 전체를 DB에 남기고 이어 갑니다. (Entity)
    # 로그인 전에는 남기지 않고, 브라우저가 들고 온 최근 대화만 씁니다.
    viewer = current_user()
    kept = chat_memory_service.context(viewer)
    history = kept["history"] or payload.get("history") or []
    # 지금 작성 중인 건을 AI에게 함께 넘깁니다. 화면 머리글("Busan -> Istanbul
    # 기준으로 답했습니다")과 같은 값입니다. 안 넘기면 AI는 지난 대화 요약만 보고,
    # 머리글은 이스탄불인데 본문은 로스앤젤레스라고 답하는 일이 생깁니다.
    #
    # **이번 대화에서 말한 것이 먼저입니다.**
    #   "부산에서 로스앤젤레스로 보냅니다" 라고 적은 뒤 "치약 500박스…"를
    #   물었더니, 머리글에 엉뚱하게 "Busan → Kaohsiung · 담배"가 붙었습니다.
    #   저장해 둔 지난 건(대만 담배)을 보고 있었기 때문입니다. 이번 말에서 읽은
    #   값을 저장분 위에 덮어씁니다. 저장분은 **빈 자리를 메우는 데만** 씁니다.
    #   (대화에서 읽은 값을 저장하는 일(capture)은 답을 만든 **뒤**에 일어나서,
    #    바로 그 말을 한 차례에는 저장분이 아직 옛것입니다) (2026-09-26)
    at, goods = {}, {}
    if viewer is not None:
        draft = work_draft_service.load(viewer) or {}
        at = dict(draft.get("fields") or {})
        goods = dict((draft.get("items") or [{}])[0] if draft.get("items") else {})
    said = chat_capture_service.read(question) or {}
    said_fields = {key: value for key, value in (said.get("fields") or {}).items() if value}
    said_item = (said.get("items") or [{}])[0] if said.get("items") else {}
    # **말한 쪽만** 바꿉니다. 한 짝으로 통째로 지우면, "부산에서 로스앤젤레스로"
    # 에서 도착지만 읽힌 경우 출발지가 통째로 날아갑니다. 새로 말한 곳은 덮고
    # 말하지 않은 곳은 그대로 둡니다 — 출발항은 대개 그대로이고, 위험한 것은
    # **묵은 도착지**입니다.
    at.update(said_fields)
    if said_item.get("product_description"):
        goods = dict(said_item)

    current = {}
    if at.get("origin_name") and at.get("destination_name"):
        current["구간"] = f"{at['origin_name']} -> {at['destination_name']}"
    if at.get("destination_country"):
        current["도착국"] = at["destination_country"]
    if goods.get("product_description"):
        current["품목"] = goods["product_description"]
    if at.get("transport_mode"):
        current["운송"] = "항공" if at["transport_mode"] == "AIR" else "해상"
    try:
        result = support_chat_service.ask(question, history,
                                          brief=payload.get("style") == "brief",
                                          memory=kept["summary"],
                                          current=current or None)
    except ServiceError as error:
        return jsonify({"success": False, "message": str(error),
                        "error_code": error.error_code, "source": "api"}), error.status
    if viewer is not None and result.get("success"):
        source = "support" if payload.get("style") == "brief" else "consult"
        chat_memory_service.remember(viewer, "user", question, source)
        chat_memory_service.remember(viewer, "assistant", result["data"]["answer"], source)
        chat_memory_service.summarize(viewer)
        # 대화에 적은 화물 정보(출발·도착지·품목·수량·치수·무게 등)를 담아 둡니다. (State)
        # 서류 작성·운송 계획 화면이 이 값으로 칸을 미리 채웁니다.
        kept_fields = chat_capture_service.capture(viewer, question)
        if kept_fields:
            result["data"]["captured"] = kept_fields
    # CBM·운임톤과 LCL/FCL은 계산입니다. 로그인하지 않아도 바로 알려 드립니다.
    # (적어 주신 치수·수량이 다 있을 때만. 반쪽 숫자는 더 위험합니다)
    if result.get("success"):
        read_values = chat_capture_service.read(question)
        first = (read_values.get("items") or [{}])[0] if read_values else {}
        summary = chat_capture_service.cargo_summary(first) if first else None
        if summary:
            result["data"]["cargo"] = summary
        # 이번 말에 없는 것은 앞서 알려 주신 값으로 답합니다. 그때는 **무엇을 기준으로
        # 답했는지 밝힙니다.** 밝히지 않으면 엉뚱한 구간·품목의 기간과 운임을 그대로
        # 믿게 됩니다. ("치약 기준인데 수건인 줄 알고 보는" 일이 생깁니다)
        told = read_values.get("fields") or {}
        told_item = (read_values.get("items") or [{}])[0] if read_values else {}
        # 구간·품목을 **실제로 쓴 답**에만 붙입니다.
        #
        # "FOB랑 CIF는 어떻게 다른가요?"는 저장해 둔 설명(knowledge)으로 답합니다.
        # 그 답은 어느 구간이든 똑같은데도 "부산 → 이스탄불 기준으로 답했습니다"가
        # 붙었습니다. 맞춰서 답한 것처럼 보이게 하는 거짓말입니다. 그런 줄이 섞이면
        # 정작 구간이 걸린 답에서도 이 줄을 안 믿게 됩니다.
        #
        # 구간·품목을 넘기는 곳은 AI로 답하는 길(api)과 우리가 계산하는 길(calculated)
        # 둘뿐입니다. 나머지(knowledge·faq·cache·clarification)는 보지도 않습니다.
        uses_context = result.get("source") in ("api", "calculated")
        if viewer is not None and uses_context:
            # 위에서 만든 값(이번 말 > 저장분)을 그대로 씁니다. 여기서 저장분을
            # 다시 읽으면, AI에게 넘긴 기준과 머리글이 서로 달라집니다.
            fields, item = at, goods
            assumed = {}
            if not (told.get("origin_code") and told.get("destination_code")):
                if fields.get("origin_name") and fields.get("destination_name"):
                    assumed["route"] = f"{fields['origin_name']} → {fields['destination_name']}"
            if not told_item.get("product_description") and item.get("product_description"):
                assumed["item"] = item["product_description"]
            if not told.get("transport_mode") and fields.get("transport_mode"):
                assumed["mode"] = "항공" if fields["transport_mode"] == "AIR" else "해상"
            if assumed:
                result["data"]["assumed"] = assumed
    return jsonify(result), (200 if result["success"] else 502)
