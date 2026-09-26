"""컨테이너·B/L 조회.

번호 하나를 받아 어떤 번호인지 알아보고 맞는 곳에 물어봅니다.

- 수출신고번호(숫자 15자리) → 실제로 실렸는지, 적재의무기한이 언제까지인지
- B/L번호 → 수출 쪽(선적 여부)과 수입 쪽(통관 진행) 둘 다
- 화물관리번호(15~19자리) → 통관 진행과 그 화물의 컨테이너 번호·봉인번호
- 컨테이너번호 → 관세청은 이 번호로 찾아주지 않습니다. 그렇다고 알려 줍니다.

적재의무기한은 중요합니다. 수출신고가 수리된 날부터 30일 안에 배에 싣지 않으면
신고수리가 취소되고 과태료가 붙습니다. 부가세 영세율 근거도 함께 사라집니다.
그래서 남은 날짜를 눈에 띄게 알려 줍니다.
"""

from __future__ import annotations

from datetime import date

from app.collectors import container_client
from app.processors.korean import particle

# 적재의무기한이 이만큼 남으면 경고합니다.
DEADLINE_WARNING_DAYS = 7

QUERY_KINDS = {
    "export_declaration": "수출신고번호",
    "bl": "B/L번호",
    "cargo": "화물관리번호",
    "container": "컨테이너번호",
}


def detect_kind(query: str) -> str:
    """번호 모양만 보고 어떤 번호인지 짐작합니다."""

    text = "".join(ch for ch in (query or "").upper() if ch.isalnum())
    if not text:
        return ""
    if container_client.is_container_no(text):
        return "container"
    if text.isdigit() and len(text) == 15:
        return "export_declaration"
    # 화물관리번호는 15~19자리이고 앞이 숫자 두 자리(연도)로 시작합니다.
    if 15 <= len(text) <= 19 and text[:2].isdigit() and not text.isdigit():
        return "cargo"
    return "bl"


def deadline_status(load_deadline: str, shipped: bool, today: date | None = None) -> dict:
    """적재의무기한까지 며칠 남았는지. 이미 실었으면 따지지 않습니다."""

    if not load_deadline:
        return {}
    try:
        due = date.fromisoformat(load_deadline)
    except ValueError:
        return {}
    days = (due - (today or date.today())).days

    if shipped:
        return {"kind": "done", "days": days, "due": load_deadline,
                "text": f"적재의무기한은 {load_deadline}이었고 이미 선적을 마쳤습니다."}
    if days < 0:
        return {"kind": "over", "days": days, "due": load_deadline,
                "text": f"적재의무기한({load_deadline})이 {abs(days)}일 지났습니다. "
                        "수출신고 수리가 취소될 수 있습니다. 세관에 바로 확인하세요."}
    if days <= DEADLINE_WARNING_DAYS:
        return {"kind": "soon", "days": days, "due": load_deadline,
                "text": f"적재의무기한({load_deadline})까지 {days}일 남았습니다. "
                        "기한 안에 싣지 못하면 신고수리가 취소되고 과태료가 붙습니다."}
    return {"kind": "ok", "days": days, "due": load_deadline,
            "text": f"적재의무기한은 {load_deadline}입니다. {days}일 남았습니다."}


def track(query: str, *, bl_year: str = "", today: date | None = None) -> dict:
    """번호 하나로 찾을 수 있는 것을 모두 찾아옵니다."""

    text = (query or "").strip()
    if not text:
        return {"available": False, "query": "", "kind": "",
                "message": "컨테이너번호·B/L번호·수출신고번호 가운데 하나를 입력해주세요."}

    kind = detect_kind(text)
    result = {"query": text, "kind": kind, "kind_label": QUERY_KINDS.get(kind, ""),
              "available": False, "export": None, "cargo": None, "containers": [],
              "notes": [], "message": ""}

    if kind == "container":
        # 관세청은 컨테이너 번호를 입력으로 받지 않습니다. 지어내지 않고 알려 줍니다.
        result["message"] = (
            f"관세청은 컨테이너 번호로는 조회해 주지 않습니다. "
            f"{text}{particle(text, '이')} 실린 B/L번호나 화물관리번호로 찾아주세요. "
            "B/L번호로 찾으면 그 건에 실린 컨테이너 번호와 봉인번호가 함께 나옵니다.")
        return result

    if kind in ("export_declaration", "bl"):
        params = ({"declaration_no": text} if kind == "export_declaration" else {"bl_no": text})
        found = container_client.export_performance(**params)
        if found["success"] and found["data"]:
            rows = found["data"]
            for row in rows:
                row["deadline"] = deadline_status(row["load_deadline"], row["shipped"], today)
            result["export"] = rows
            result["available"] = True
        elif not found["success"] and found["error_code"] != "API_NO_DATA":
            result["notes"].append(f"수출이행내역: {found['message']}")

    if kind in ("bl", "cargo"):
        params = {"cargo_no": text} if kind == "cargo" else {"mbl_no": text, "bl_year": bl_year}
        if kind == "bl" and not bl_year:
            result["notes"].append(
                "수입 통관 진행정보는 B/L번호와 함께 입항년도(4자리)가 있어야 조회됩니다.")
        else:
            found = container_client.cargo_progress(**params)
            if found["success"] and found["data"]:
                result["cargo"] = found["data"]
                result["available"] = True
                cargo_no = (found["data"].get("cargo_no")
                            if found["data"]["kind"] == "detail" else "")
                if cargo_no:
                    boxes = container_client.container_detail(cargo_no)
                    if boxes["success"]:
                        result["containers"] = boxes["data"] or []
                    elif boxes["error_code"] != "API_NO_DATA":
                        result["notes"].append(f"컨테이너내역: {boxes['message']}")
            elif not found["success"] and found["error_code"] != "API_NO_DATA":
                result["notes"].append(f"화물통관 진행정보: {found['message']}")

    if kind == "cargo" and not result["containers"]:
        boxes = container_client.container_detail(text)
        if boxes["success"] and boxes["data"]:
            result["containers"] = boxes["data"]
            result["available"] = True
        elif not boxes["success"] and boxes["error_code"] != "API_NO_DATA":
            note = f"컨테이너내역: {boxes['message']}"
            if note not in result["notes"]:
                result["notes"].append(note)

    if not result["available"] and not result["message"]:
        result["message"] = (
            "조회가 완료되지 않아 관세청 기록 유무를 확인할 수 없습니다. "
            "아래 안내를 확인해 주세요."
        ) if result["notes"] else (
            f"{QUERY_KINDS.get(kind, '이 번호')}로 조회했지만 관세청에 기록이 없습니다. "
            "번호를 다시 확인해 주세요. 수출은 신고가 수리된 뒤에, "
            "수입은 적하목록이 제출된 뒤에 조회됩니다.")
    return result


def track_shipment(shipment, *, bl_year: str = "", today: date | None = None) -> dict:
    """이 Shipment에 적어 둔 번호로 바로 조회합니다."""

    number = (shipment.bl_no or "").strip() or (shipment.export_declaration_no or "").strip()
    if not number:
        return {"available": False, "query": "", "kind": "", "notes": [], "containers": [],
                "export": None, "cargo": None,
                "message": "B/L번호나 수출신고번호를 먼저 등록하면 바로 조회해 드립니다."}
    return track(number, bl_year=bl_year, today=today)


def save_numbers(shipment, form: dict) -> None:
    """부킹 뒤에 받는 번호를 저장합니다. 모양이 이상하면 막습니다."""

    from app.repositories import shipment_repository
    from app.validators import ValidationError

    bl_no = "".join(ch for ch in str(form.get("bl_no") or "").upper() if ch.isalnum())[:30]

    declaration = "".join(ch for ch in str(form.get("export_declaration_no") or "")
                          if ch.isdigit())[:20]
    if declaration and len(declaration) != 15:
        raise ValidationError("수출신고번호는 숫자 15자리입니다.", "export_declaration_no")

    cargo_no = "".join(ch for ch in str(form.get("cargo_no") or "").upper() if ch.isalnum())[:20]
    if cargo_no and not 15 <= len(cargo_no) <= 19:
        raise ValidationError("화물관리번호는 15~19자리입니다.", "cargo_no")

    shipment.bl_no = bl_no
    shipment.export_declaration_no = declaration
    shipment.cargo_no = cargo_no
    shipment_repository.commit()
