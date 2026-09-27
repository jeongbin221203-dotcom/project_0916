"""이름 붙여 저장해 둔 서류 초안. Shipment가 없어도 남습니다.

검토 창(서류 미리보기 & 검토)에서 사람이 견적명을 적으면 여기로 옵니다.
스케줄을 아직 안 골랐어도, 서류부터 먼저 썼어도 저장됩니다. 대시보드는
이 줄을 "작성 중"으로 보여 주고, 나중에 Shipment를 만들면 승격됩니다.

여기서 지키는 것
  1. 남의 초안은 열 수 없습니다. 모든 조회가 user_id로 걸립니다.
  2. 계좌번호·SWIFT는 저장하지 않습니다. (bank_redaction)
  3. 이름을 안 적어도 저장은 됩니다. 도착국가_대표품목_날짜로 지어 넣습니다.
     이름 없는 줄이 목록에 쌓이면 무엇이 무엇인지 알 수 없습니다.
"""

from __future__ import annotations

from datetime import timezone

from app.extensions import db
from app.models.document_draft import MAX_TITLE
from app.processors import bank_redaction
from app.services import ServiceError
from app.validators import ValidationError

MAX_DOCUMENTS = 6
MAX_FIELD_CHARS = 500
MAX_ITEM_ROWS = 20
# 회원 한 사람이 쌓아 둘 수 있는 초안. 넘으면 가장 오래된 것부터 지웁니다.
MAX_DRAFTS_PER_USER = 50
SOURCES = ("chat", "upload", "document")


def _text(value, limit: int = MAX_FIELD_CHARS) -> str:
    text = str(value if value is not None else "").strip()[:limit]
    return bank_redaction.strip_bank_numbers(text)[0] if text else ""


# --- 받아 적기 ---------------------------------------------------------------------

def _clean_documents(raw) -> list[dict]:
    """검토 창이 보낸 서류 묶음. 아는 모양만 받고 길이를 자릅니다."""

    rows = raw if isinstance(raw, list) else []
    cleaned = []
    for row in rows[:MAX_DOCUMENTS]:
        if not isinstance(row, dict) or not _text(row.get("kind"), 40):
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        values = {key: _text(value) for key, value in data.items()
                  if isinstance(key, str) and not isinstance(value, (dict, list))}
        items = [
            {key: _text(cell, 300) for key, cell in item.items()
             if isinstance(key, str) and not isinstance(cell, (dict, list))}
            for item in (data.get("items") or [])[:MAX_ITEM_ROWS] if isinstance(item, dict)]
        if items:
            values["items"] = items
        cleaned.append({"kind": _text(row.get("kind"), 40),
                        "title": _text(row.get("title"), 120),
                        "data": values})
    return cleaned


def _clean_draft(raw) -> dict:
    """승격에 쓸 초안(칸 값 + 품목). 서류 작성 화면의 칸 이름 그대로입니다."""

    raw = raw if isinstance(raw, dict) else {}
    draft = {key: _text(value) for key, value in raw.items()
             if isinstance(key, str) and key != "items" and not isinstance(value, (dict, list))}
    draft["items"] = [
        {key: _text(cell, 300) for key, cell in item.items()
         if isinstance(key, str) and not isinstance(cell, (dict, list))}
        for item in (raw.get("items") or [])[:MAX_ITEM_ROWS] if isinstance(item, dict)]
    return {key: value for key, value in draft.items() if value}


def suggest_title(draft: dict) -> str:
    """이름을 안 적었을 때 붙일 이름. 서류 작성 화면과 같은 규칙입니다."""

    from app.services import document_start_service

    draft = draft if isinstance(draft, dict) else {}
    items = draft.get("items") if isinstance(draft.get("items"), list) else []
    return document_start_service.suggest_project_name(draft, items)


# --- 저장·조회 ---------------------------------------------------------------------

def _require_viewer(viewer):
    if viewer is None:
        raise ServiceError("로그인이 필요합니다.", "UNAUTHORIZED", 401)
    return viewer


def get(viewer, draft_id) -> "DocumentDraft":                     # noqa: F821
    """내 초안 한 건. 남의 것이면 없는 것으로 답합니다."""

    from app.models import DocumentDraft

    _require_viewer(viewer)
    try:
        draft_id = int(draft_id)
    except (TypeError, ValueError):
        raise ServiceError("초안을 찾지 못했습니다.", "DRAFT_NOT_FOUND", 404) from None
    record = DocumentDraft.query.filter_by(id=draft_id, user_id=viewer.id).first()
    if record is None:
        # 남의 것인지 없는 것인지 구별해 주지 않습니다.
        raise ServiceError("초안을 찾지 못했습니다.", "DRAFT_NOT_FOUND", 404)
    return record


def save(viewer, payload: dict) -> dict:
    """검토 창에서 적은 견적명과 서류 값을 저장합니다. id가 있으면 그 줄을 고칩니다.

    Shipment를 만들지 않습니다. 스케줄을 고르기 전에도 남아야 하니까요.
    """

    from app.models import DocumentDraft

    _require_viewer(viewer)
    if not isinstance(payload, dict):
        raise ValidationError("저장할 내용을 읽지 못했습니다.", "payload")

    draft = _clean_draft(payload.get("draft"))
    documents = _clean_documents(payload.get("documents"))
    title = _text(payload.get("quote_title"), MAX_TITLE) or suggest_title(draft)

    record = get(viewer, payload["id"]) if payload.get("id") else None
    if record is None:
        record = DocumentDraft(user_id=viewer.id)
        db.session.add(record)
    elif record.is_promoted:
        # 이미 Shipment가 된 건입니다. 이름은 Shipment 쪽이 기준이 됩니다.
        raise ServiceError("이미 확정된 건입니다. 서류 센터에서 고쳐 주세요.", "DRAFT_PROMOTED")

    record.quote_title = title
    # 빈 값으로 덮지 않습니다. 이름만 고치려고 부를 수도 있습니다.
    if documents:
        record.documents = documents
    if draft:
        record.draft = draft
    source = _text(payload.get("source"), 20)
    record.source = source if source in SOURCES else (record.source or "chat")
    db.session.commit()
    _trim(viewer)
    return as_dict(record)


def rename(viewer, draft_id, title: str) -> dict:
    """견적명만 고칩니다. 검토 창에서 이름 칸을 벗어날 때 부릅니다."""

    record = get(viewer, draft_id)
    if record.is_promoted:
        raise ServiceError("이미 확정된 건입니다. 서류 센터에서 고쳐 주세요.", "DRAFT_PROMOTED")
    cleaned = _text(title, MAX_TITLE)
    if not cleaned:
        raise ValidationError("견적명을 적어 주세요.", "quote_title")
    record.quote_title = cleaned
    db.session.commit()
    return as_dict(record)


def delete(viewer, draft_id) -> None:
    record = get(viewer, draft_id)
    db.session.delete(record)
    db.session.commit()


def _trim(viewer) -> None:
    """한 사람이 쌓아 둘 수 있는 수를 넘으면 오래된 것부터 지웁니다.

    승격된 줄은 Shipment와 이어져 있어 지우지 않습니다.
    """

    from app.models import DocumentDraft

    extra = (DocumentDraft.query
             .filter_by(user_id=viewer.id, shipment_pk=None)
             .order_by(DocumentDraft.updated_at.desc())
             .offset(MAX_DRAFTS_PER_USER).all())
    if not extra:
        return
    for record in extra:
        db.session.delete(record)
    db.session.commit()


def list_open(viewer) -> list:
    """아직 확정 전(Shipment 없음)인 내 초안. 최근에 고친 것부터."""

    from app.models import DocumentDraft

    if viewer is None:
        return []
    return (DocumentDraft.query
            .filter_by(user_id=viewer.id, shipment_pk=None)
            .order_by(DocumentDraft.updated_at.desc()).all())


# --- 승격 -------------------------------------------------------------------------

def promote(viewer, draft_id, shipment) -> None:
    """스케줄을 골라 Shipment를 만들었습니다. 이 초안을 그 건에 잇습니다.

    이 뒤로 대시보드는 이 줄을 "작성 중"에서 빼고 Shipment로 보여 줍니다.
    견적명은 Shipment.project_name으로 이미 옮겨 간 뒤입니다.
    (document_start_service.create가 draft_id를 받아 이름부터 가져갑니다)
    """

    try:
        record = get(viewer, draft_id)
    except ServiceError:
        return                       # 없는 초안을 가리켜도 서류 만들기는 막지 않습니다.
    record.shipment_pk = shipment.id
    db.session.commit()


def title_of(viewer, draft_id) -> str:
    """승격할 때 가져갈 견적명. 없으면 빈 문자열."""

    try:
        return get(viewer, draft_id).quote_title
    except ServiceError:
        return ""


# --- 화면·API 모양 -----------------------------------------------------------------

def as_dict(record) -> dict:
    if record is None:
        return {}
    updated = record.updated_at.replace(tzinfo=timezone.utc)
    return {"id": record.id, "quote_title": record.quote_title,
            "kinds": record.kinds, "source": record.source,
            "shipment_id": record.shipment.shipment_id if record.shipment else "",
            "updated_at": updated.isoformat(),
            "updated_ms": int(updated.timestamp() * 1000)}
