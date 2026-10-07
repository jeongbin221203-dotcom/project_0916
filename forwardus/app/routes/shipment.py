"""Shipment list and detail screens."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.models.shipment import SHIPMENT_STATUSES
from app.routes import load_shipment
from app.routes.auth import login_required
from app.services import ServiceError, shipment_service

shipment_bp = Blueprint("shipment", __name__, url_prefix="/shipments")


@shipment_bp.get("")
@login_required
def index():
    """예전 Shipments 목록. 목록은 Dashboard로 합쳤습니다. 옛 주소·즐겨찾기는 그리로 보냅니다."""

    status = request.args.get("status") or None
    if status not in SHIPMENT_STATUSES:
        status = None
    return redirect(url_for("dashboard.index", status=status))


@shipment_bp.get("/<shipment_id>")
def detail(shipment_id: str):
    shipment = load_shipment(shipment_id)
    return render_template("shipment/detail.html", **shipment_service.build_summary(shipment))


@shipment_bp.route("/<shipment_id>/edit", methods=["GET", "POST"])
def edit(shipment_id: str):
    """당사자 정보(견적명·수출자·Notify·바이어) 수정 — 서류에도 함께 반영합니다."""

    from sqlalchemy.orm.exc import StaleDataError

    from app.extensions import db
    from app.validators import ValidationError

    shipment = load_shipment(shipment_id)
    if request.method == "POST":
        try:
            result = shipment_service.update_shipment(shipment, request.form,
                                                      propagate=request.form.get("propagate") == "1")
        except StaleDataError:
            # 다른 곳에서 먼저 지웠거나 바꿨습니다 — 500 대신 안내(동시 수정·삭제 시험에서 500)
            db.session.rollback()
            flash("다른 화면에서 이 건이 먼저 바뀌었거나 지워졌습니다. 목록에서 다시 열어 주세요.", "error")
            return redirect(url_for("dashboard.index"))
        except (ValidationError, ServiceError) as exc:
            flash(str(exc), "error")
            return render_template("shipment/edit.html", shipment=shipment, form=request.form,
                                   need_confirm=getattr(exc, "code", "") == "RESTRICTED_CONFIRM",
                                   snapshot=shipment_service._party_snapshot(shipment)), 400
        if not result["changed"]:
            flash("바뀐 내용이 없습니다.", "info")
        else:
            message = "수정했습니다."
            if result["documents"]:
                message += f" 서류 {len(result['documents'])}개에 반영했고, 다시 검증해야 확정할 수 있습니다."
            if result["kept"]:
                message += f" 직접 고쳐 둔 칸 {len(result['kept'])}개는 그대로 두었습니다({', '.join(result['kept'][:4])}{' …' if len(result['kept']) > 4 else ''})."
            if result.get("locked"):
                message += (f" 확정(final)한 서류 {len(result['locked'])}개({', '.join(result['locked'])})는 옛 정보 그대로입니다 — "
                            "확정을 풀고 다시 반영하세요.")
            flash(message, "success")
        return redirect(url_for("shipment.detail", shipment_id=shipment_id))
    return render_template("shipment/edit.html", shipment=shipment, form=None,
                           snapshot=shipment_service._party_snapshot(shipment))


@shipment_bp.post("/<shipment_id>/delete")
def delete(shipment_id: str):
    from sqlalchemy.orm.exc import StaleDataError

    from app.extensions import db

    shipment = load_shipment(shipment_id)
    blocked = shipment_service.delete_blocked_reason(shipment)
    if blocked:
        flash(blocked, "error")
        return redirect(url_for("shipment.detail", shipment_id=shipment_id))
    if (request.form.get("confirm") or "").strip().upper() != shipment.shipment_id.upper():
        flash("확인을 위해 건 번호를 정확히 입력해야 지울 수 있습니다.", "error")
        return redirect(url_for("shipment.detail", shipment_id=shipment_id))
    try:
        shipment_service.delete_shipment(shipment)
    except StaleDataError:
        db.session.rollback()
        flash("이미 지워졌거나 다른 곳에서 바뀐 건입니다.", "error")
        return redirect(url_for("dashboard.index"))
    flash(f"{shipment_id} 건을 지웠습니다.", "success")
    return redirect(url_for("dashboard.index"))


@shipment_bp.post("/<shipment_id>/status")
def change_status(shipment_id: str):
    shipment = load_shipment(shipment_id)
    try:
        shipment_service.transition(shipment, request.form.get("action", ""))
        flash(f"상태가 '{shipment.status_label}'(으)로 변경되었습니다.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return redirect(url_for("shipment.detail", shipment_id=shipment_id))
