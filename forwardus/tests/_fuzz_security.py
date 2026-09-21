"""보안 관점 스윕.

터지는지가 아니라 "빠져나가는지"를 봅니다.
- 올린 파일이 지정한 폴더 밖에 쓰이지 않는지
- 사람이 넣은 글이 화면에 그대로 실행되지 않는지 (XSS)
- 남의 Shipment를 건드릴 수 있는지

    python tests/_fuzz_security.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.validators import ValidationError

# 화면에 그대로 나오면 안 되는 글.
PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "\"><script>alert(1)</script>",
    "'><svg/onload=alert(1)>",
    "javascript:alert(1)",
    "{{7*7}}",
    "${7*7}",
    "<iframe src=javascript:alert(1)>",
]

TRAVERSAL = [
    "../../../etc/passwd.pdf",
    "..\\..\\..\\windows\\system32\\evil.pdf",
    "/etc/passwd.pdf",
    "C:\\Windows\\evil.pdf",
    "....//....//evil.pdf",
    "%2e%2e%2f%2e%2e%2fevil.pdf",
    "a\x00.exe.pdf",
]


class FakeFile:
    def __init__(self, data, filename):
        self._data, self.filename, self.mimetype = data, filename, "text/plain"

    def read(self):
        return self._data


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'OK ' if ok else '실패'} {label}{(' · ' + detail) if detail and not ok else ''}")
    return ok


def block_outbound() -> None:
    """스윕이 실제 기관을 부르지 못하게 막습니다.

    예전에 이 스윕을 돌리다 관세청이 우리 IP를 방화벽에서 차단했습니다.
    호출 제한이 아니라 TCP 연결 자체가 막혀 브라우저로도 못 들어갔습니다.
    스윕은 우리 코드가 버티는지 보는 것이지 남의 서버를 시험하는 것이 아닙니다.

    실제 호출로 확인하려면 FORWARDUS_FUZZ_LIVE=1 을 주고 돌리세요.
    """

    import os

    if os.environ.get("FORWARDUS_FUZZ_LIVE") == "1":
        return

    import httpx

    def offline(*args, **kwargs):
        raise httpx.ConnectError("스윕에서는 바깥으로 나가지 않습니다.")

    httpx.request = offline


def main() -> int:
    block_outbound()
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    failures = 0

    with app.app_context():
        db.create_all()
        from app.services import (container_tracking_service as cts,
                                  document_service as ds,
                                  planning_service as ps,
                                  requirement_service as rs)

        payload = {
            "project_name": "보안 점검", "transport_mode": "SEA", "sea_mode": "LCL",
            "origin_code": "KRPUS", "destination_code": "USLAX",
            "requested_departure_date": "2026-11-02",
            "incoterms": "FOB", "currency": "USD", "invoice_value": "5000",
            "cargo": {"items": [{"product_description": PAYLOADS[0], "hs_code": "3305100000",
                                 "package_type": "carton", "quantity": 10, "length_cm": 40,
                                 "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 12}]},
            "exporter_name": PAYLOADS[1], "exporter_address": PAYLOADS[2],
            "buyer": {"name": PAYLOADS[3], "country": "US", "address": PAYLOADS[4],
                      "contact_email": "a@b.c"},
        }
        payload["schedule_id"] = ps.search_schedules(payload)["items"][0]["schedule_id"]
        shipment = ps.create_shipment(payload)
        ds.generate_documents(shipment)

        print("\n[1] 올린 파일이 지정한 폴더 밖으로 나가지 않는가")
        root = rs._upload_root().resolve()
        for name in TRAVERSAL:
            try:
                document = rs.upload(shipment, FakeFile(b"CERTIFICATE", name), "origin")
            except ValidationError:
                check(f"{name!r} 거절", True)
                continue
            where = (root / document.stored_name).resolve()
            inside = root in where.parents or where.parent == root
            failures += not check(f"{name!r} -> {document.stored_name}", inside, str(where))
            rs.delete_upload(shipment, document.id)

        print("\n[2] 사람이 넣은 글이 화면에서 그대로 실행되지 않는가")
        client = app.test_client()
        pages = [
            "/", "/shipments", f"/shipments/{shipment.shipment_id}",
            f"/documents/{shipment.shipment_id}",
            f"/documents/{shipment.shipment_id}/commercial_invoice",
            f"/documents/{shipment.shipment_id}/packing_list",
            f"/documents/{shipment.shipment_id}/requirements",
            f"/documents/{shipment.shipment_id}/customs-filing",
            f"/tracking/{shipment.shipment_id}",
            f"/assistant/{shipment.shipment_id}",
            "/tracking/container?q=" + PAYLOADS[0],
        ]
        # 위험한 것은 <, >, " 가 살아서 태그가 되는 경우입니다.
        # javascript: 같은 글자는 URL 자리에 들어갈 때만 문제이고,
        # 본문 글로 나오는 것은 그냥 글자입니다. (아래에서 따로 봅니다)
        dangerous = [p for p in PAYLOADS if any(ch in p for ch in "<>\"'")]
        for path in pages:
            html = client.get(path).get_data(as_text=True)
            raw = [p for p in dangerous if p in html]
            failures += not check(f"GET {path}", not raw, f"태그가 살아 있음: {raw[:1]}")

        print("\n[2-2] 사람이 넣은 값이 링크 주소로 쓰이지 않는가")
        for path in pages:
            html = client.get(path).get_data(as_text=True)
            urls = re.findall(r'(?:href|src|action)="([^"]*)"', html)
            bad = [u for u in urls if u.lower().startswith(("javascript:", "data:text/html"))]
            failures += not check(f"링크 {path}", not bad, f"위험한 주소: {bad[:1]}")

        print("\n[3] 남의 건을 건드릴 수 있는가")
        other = client.get("/documents/EXP-9999-99999")
        failures += not check("없는 Shipment는 404", other.status_code in (302, 404),
                              f"HTTP {other.status_code}")
        for bogus in ("../../etc", "%2e%2e", "' OR 1=1--", "EXP-2026-00001'"):
            response = client.get(f"/documents/{bogus}")
            failures += not check(f"이상한 id {bogus!r}", response.status_code < 500,
                                  f"HTTP {response.status_code}")

        print("\n[4] 저장하는 번호가 걸러지는가")
        cts.save_numbers(shipment, {"bl_no": "<script>x</script>HDMU1",
                                    "export_declaration_no": "abc122100900340033def",
                                    "cargo_no": ""})
        failures += not check("B/L에서 기호 제거", shipment.bl_no == "SCRIPTXSCRIPTHDMU1",
                              shipment.bl_no)
        failures += not check("신고번호는 숫자만",
                              shipment.export_declaration_no == "122100900340033",
                              shipment.export_declaration_no)

    print(f"\n{'=' * 60}\n실패 {failures}건\n{'=' * 60}")
    return failures


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
