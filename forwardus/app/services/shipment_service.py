"""Shipment lookup, summary, and status transitions."""

from __future__ import annotations

import re
from collections import OrderedDict

from app.models.document import DOCUMENT_TYPES
from app.processors.schedule_calculator import check_buyer_deadline
from app.repositories import document_repository, shipment_repository, tracking_repository
from app.services import ServiceError

# Allowed manual transitions (tracking events move the in-transit states).
MANUAL_TRANSITIONS = {
    "book": ({"quoted"}, "booked"),
    "close": ({"delivered"}, "closed"),
    "cancel": ({"draft", "quoted", "booked"}, "cancelled"),
}


def can_view(viewer, shipment) -> bool:
    """마스터는 모든 Shipment를, 일반 회원은 자기가 만든 것만 봅니다."""

    if viewer is None:
        return False
    return bool(viewer.is_master) or shipment.user_id == viewer.id


def get_or_404(shipment_id: str, viewer=None):
    shipment = shipment_repository.get_by_shipment_id(shipment_id)
    # 남의 Shipment는 있는지조차 알리지 않습니다. 없는 것과 똑같이 답합니다.
    if shipment is None or not can_view(viewer, shipment):
        raise ServiceError("Shipment를 찾을 수 없습니다.", "SHIPMENT_NOT_FOUND", 404)
    return shipment


def list_shipments(status: str | None = None, viewer=None):
    """보는 사람이 볼 수 있는 Shipment만 돌려줍니다. 로그인 전이면 비어 있습니다."""

    if viewer is None:
        return []
    return shipment_repository.list_shipments(
        status or None, user_id=None if viewer.is_master else viewer.id)


def cost_groups(shipment) -> list[dict]:
    """비용을 묶음별로. 각 줄에 **누가 내는지**(수출자/바이어)를 붙입니다.

    FOB 건의 "Total Logistics Cost"에 운임·보험·도착지 비용이 모두 합산돼, 그대로 보고하면 수출자 원가가 과대하게 읽혔습니다
    (무역 실무 팀장 점검). 부담 주체는 Incoterms 규칙표(cost_calculator.EXPORTER_PAYS) 한 곳을 따릅니다.
    """

    from app.services.assistant_service import _exporter_pays

    groups: "OrderedDict[str, dict]" = OrderedDict()
    for cost in shipment.costs:
        group = groups.setdefault(cost.category, {"category": cost.category, "total_krw": 0, "exporter_krw": 0,
                                                  "lines": []})
        exporter = _exporter_pays(shipment.incoterms, cost.category)
        cost.payer = "수출자" if exporter else "바이어"
        group["total_krw"] += cost.krw_amount
        if exporter:
            group["exporter_krw"] += cost.krw_amount
        group["lines"].append(cost)
    return list(groups.values())


def build_summary(shipment) -> dict:
    """Everything the Shipment Detail screen shows, gathered in one place."""

    documents = {doc.doc_type: doc for doc in document_repository.list_for_shipment(shipment)}
    events = tracking_repository.list_events(shipment)
    progress_events = [event for event in events if event.event_code != "eta_changed"]
    return {
        "shipment": shipment,
        "cost_groups": cost_groups(shipment),
        "exporter_total_krw": sum(group["exporter_krw"] for group in cost_groups(shipment)),
        "deadline": check_buyer_deadline(shipment.eta, shipment.buyer_required_date, shipment.transport_mode)
        if shipment.eta else None,
        "documents": [
            {"doc_type": doc_type, "title": title, "document": documents.get(doc_type)}
            for doc_type, title in DOCUMENT_TYPES.items()
        ],
        "latest_event": progress_events[-1] if progress_events else None,
        "exceptions": [event for event in events if event.is_exception],
    }


def transition(shipment, action: str):
    if action not in MANUAL_TRANSITIONS:
        raise ServiceError("지원하지 않는 작업입니다.", "INVALID_ACTION")
    allowed_from, target = MANUAL_TRANSITIONS[action]
    if shipment.status not in allowed_from:
        raise ServiceError(f"현재 상태({shipment.status_label})에서는 이 작업을 할 수 없습니다.", "INVALID_TRANSITION")
    shipment.status = target
    shipment_repository.commit()
    return shipment


# --- 수정 · 삭제 ----------------------------------------------------------------------
#
# 무역 실무 점검: Shipment 를 고치거나 지울 길이 없어, 마법사에서 바이어·수출자를 잘못 넣으면 서류 5개를 각각 고치거나 건을
# 새로 만들어야 했습니다. 수정은 **당사자 정보**(견적명·수출자·Notify·바이어)만 받습니다 — 운임·일정·화물 치수는 견적 계산의
# 입력이라 바꾸면 견적을 다시 해야 하므로 새 건으로 만드는 편이 안전합니다.

LOCKED_STATUSES = ("closed", "cancelled")
# Shipment 값이 서류의 어느 칸으로 가는지
PARTY_DOCUMENT_FIELDS = {
    "exporter_name": ("exporter", "signed_by", "packed_by"),
    "exporter_address": ("exporter_address",),
    "notify_party": ("notify_party",),
    "buyer_name": ("consignee", "buyer"),
    "buyer_address": ("consignee_address",),
}


def _party_snapshot(shipment) -> dict:
    buyer = shipment.buyer
    return {"project_name": shipment.project_name, "exporter_name": shipment.exporter_name,
            "exporter_address": shipment.exporter_address, "notify_party": shipment.notify_party,
            "buyer_name": buyer.name if buyer else "", "buyer_country": buyer.country if buyer else "",
            "buyer_address": buyer.address if buyer else "", "buyer_email": buyer.contact_email if buyer else ""}


def update_shipment(shipment, form: dict, *, propagate: bool = True) -> dict:
    """당사자 정보를 고칩니다. 돌려주는 것: {"changed": [...], "documents": [고친 서류], "kept": [직접 고쳐 둔 칸]}.

    서류에는 **Shipment 값 그대로였던 칸만** 새 값으로 바꿉니다. 사람이 직접 고쳐 둔 칸은 건드리지 않고 알립니다.
    고친 서류는 다시 검증을 거쳐야 하므로 상태를 '작성됨(generated)'으로 돌립니다. 확정(final) 서류는 건드리지 않습니다.
    """

    from app.repositories import buyer_repository
    from app.services import document_service
    from app.validators.shipment_validator import require_text, validate_parties

    if shipment.status in LOCKED_STATUSES:
        raise ServiceError(f"{shipment.status_label} 상태의 건은 고칠 수 없습니다.", "LOCKED")
    form = form if isinstance(form, dict) else {}
    # 길면 잘라 저장하는 대신 알립니다 — 서류의 주소가 중간에서 끊길 수 있습니다(기업 점검)
    for key, label, limit in (("exporter_address", "수출자 주소", 500), ("buyer_address", "Buyer 주소", 500),
                              ("notify_party", "Notify Party", 300), ("exporter_name", "수출자명", 200),
                              ("buyer_name", "Buyer명", 200)):
        if len(str(form.get(key) or "").strip()) > limit:
            from app.validators import ValidationError
            raise ValidationError(f"{label}은(는) {limit}자 이내로 적어 주세요.", key)
    email = str(form.get("buyer_email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        from app.validators import ValidationError
        raise ValidationError("Buyer 이메일 형식이 맞지 않습니다.", "buyer_email")
    parties = validate_parties({
        "exporter_name": form.get("exporter_name"), "exporter_address": form.get("exporter_address"),
        "notify_party": form.get("notify_party"),
        "buyer": {"name": form.get("buyer_name"), "country": form.get("buyer_country"),
                  "address": form.get("buyer_address"), "contact_email": form.get("buyer_email")}})
    project_name = require_text(form.get("project_name"), "견적명", field="project_name")
    new = {"project_name": project_name, **parties}

    before = _party_snapshot(shipment)
    changed = [key for key, value in new.items() if (before.get(key) or "") != (value or "")]
    if not changed:
        return {"changed": [], "documents": [], "kept": []}
    # 수정에도 같은 제재 검사 — 생성 때 통과한 건의 바이어 국가를 KP·RU·IR 로 바꾸면 그대로 저장됐습니다(무역 실무 점검)
    from app.services.planning_service import check_trade_controls
    from app.collectors import location_client
    destination = location_client.find_location(shipment.destination_code or "") or {}
    destination_country = destination.get("country_code", "")
    check_trade_controls([destination_country, parties["buyer_country"]], form, field="buyer_country",
                         text=" ".join([parties["buyer_name"], parties["buyer_address"], parties["notify_party"]]))
    old_reference = document_service.build_reference(shipment)

    shipment.project_name = project_name
    shipment.exporter_name = parties["exporter_name"]
    shipment.exporter_address = parties["exporter_address"]
    shipment.notify_party = parties["notify_party"]
    if any(key.startswith("buyer_") for key in changed):
        # 같은 바이어 줄을 다른 건이 함께 쓰므로 그 줄을 고치지 않고 새 줄(또는 같은 값의 기존 줄)로 바꿉니다
        shipment.buyer = buyer_repository.get_or_create(
            parties["buyer_name"], parties["buyer_country"], parties["buyer_address"], parties["buyer_email"],
            user_id=shipment.user_id)
    shipment_repository.commit()

    updated, kept, locked = [], [], []
    if propagate:
        new_reference = document_service.build_reference(shipment)
        for document in document_repository.list_for_shipment(shipment):
            if not isinstance(document.data, dict):
                continue
            if document.status == "final":
                # 확정 서류는 건드리지 않지만 **옛 정보로 남는다는 것**을 알립니다(기업 점검: 송장은 옛 수출자, SI 는 새 수출자)
                if any(key in document.data and (document.data.get(key) or "") == (old_reference.get(key) or "")
                       and (new_reference.get(key) or "") != (old_reference.get(key) or "")
                       for source, keys in PARTY_DOCUMENT_FIELDS.items() if source in changed for key in keys):
                    locked.append(DOCUMENT_TYPES.get(document.doc_type, document.doc_type))
                continue
            data = dict(document.data)
            touched = False
            for source, keys in PARTY_DOCUMENT_FIELDS.items():
                if source not in changed:
                    continue
                for key in keys:
                    if key not in data:
                        continue
                    if (data.get(key) or "") == (old_reference.get(key) or ""):
                        data[key] = new_reference.get(key, "")
                        touched = True
                    else:
                        kept.append(f"{DOCUMENT_TYPES.get(document.doc_type, document.doc_type)} · "
                                    f"{document_service.field_label(document.doc_type, key)}")
            if touched:
                document_repository.upsert(shipment, document.doc_type, data, "generated", document.source or "auto")
                updated.append(document.doc_type)
        shipment_repository.commit()
    # "서류 5장의 같은 칸"을 칸 이름 하나로 합칩니다 — 개수만 늘어 사용자가 무엇이 안 바뀌었는지 몰랐습니다
    grouped: dict[str, int] = {}
    for item in kept:
        label = item.split(" · ", 1)[1] if " · " in item else item
        grouped[label] = grouped.get(label, 0) + 1
    kept = [f"{label}({count}장)" if count > 1 else label for label, count in grouped.items()]
    return {"changed": changed, "documents": updated, "kept": kept, "locked": locked}


DELETABLE_STATUSES = ("draft", "quoted", "cancelled")


def delete_blocked_reason(shipment) -> str:
    """지우면 안 되는 건의 이유. 지워도 되면 빈 글자.

    수출신고 관련 서류는 보관 의무가 있고, 부킹·선적 이후의 건을 번호 입력만으로 지울 수 있으면 사고입니다(기업 점검).
    확정한 서류가 있거나 견적 단계를 넘은 건은 '취소(보관)'로만 처리합니다.
    """

    if shipment.status not in DELETABLE_STATUSES:
        return (f"{shipment.status_label} 상태의 건은 지울 수 없습니다. 수출 관련 서류는 보관해야 하므로 "
                "'취소'로 상태를 바꿔 두세요(견적 단계의 건만 지울 수 있습니다).")
    if any(document.status == "final" for document in shipment.documents):
        return "확정(final)한 서류가 있는 건은 지울 수 없습니다. 확정을 풀거나 '취소'로 상태를 바꿔 두세요."
    return ""


def delete_shipment(shipment) -> None:
    """건과 딸린 서류·비용·화물·추적·올린 증빙을 모두 지웁니다(되돌릴 수 없습니다)."""

    from app.services import requirement_service

    for upload in list(shipment.requirement_documents):
        try:
            (requirement_service._upload_root() / upload.stored_name).unlink(missing_ok=True)
        except OSError:                                    # 파일이 이미 없어도 건은 지웁니다
            pass
    shipment_repository.delete(shipment)
    shipment_repository.commit()
