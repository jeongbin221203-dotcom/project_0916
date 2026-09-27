"""서류·통관·조회 쪽 스윕.

정상적으로 만들어진 Shipment를 하나 두고, 거기에 이상한 값을 계속 밀어 넣어
서류 생성·수정·검증·업로드·조회가 버티는지 봅니다.

    python tests/_fuzz_docs.py [반복횟수]
"""

from __future__ import annotations

import io as _io
import random
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._fuzz_app import build_app
from app.extensions import db
from app.services import ServiceError
from app.validators import ValidationError

NASTY = [None, "", " ", "0", "-1", "abc", "1,000", "1e309", "nan", "inf",
         "가" * 600, "x" * 5000, "<script>", "'; DROP TABLE x;--", "\x00",
         "😀", True, False, 0, -1, 1.5, 10 ** 30, [], {}, [1], {"a": 1}]

NUMBERS = ["1", "1000", "1,000.50", "", None, "abc", -5, 0, 10 ** 15, "  7  "]


def a_shipment():
    from app.services import planning_service as ps

    payload = {
        "project_name": "스윕 테스트",
        "transport_mode": "SEA", "sea_mode": "LCL",
        "origin_code": "KRPUS", "destination_code": "USLAX",
        "requested_departure_date": "2026-11-02",
        "incoterms": "FOB", "currency": "USD", "invoice_value": "5000",
        "cargo": {"items": [
            {"product_description": "샴푸", "hs_code": "3305100000",
             "package_type": "carton", "quantity": 100, "length_cm": 40,
             "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 12,
             "net_weight_kg": 900, "amount": "3000"},
            {"product_description": "치약", "hs_code": "3306100000",
             "package_type": "carton", "quantity": 50, "length_cm": 30,
             "width_cm": 20, "height_cm": 20, "weight_per_package_kg": 8,
             "amount": "2000"},
        ]},
        "exporter_name": "포워더스", "exporter_address": "서울",
        "buyer": {"name": "ACME", "country": "US", "address": "LA",
                  "contact_email": "a@b.c"},
    }
    schedules = ps.search_schedules(payload)
    payload["schedule_id"] = schedules["items"][0]["schedule_id"]
    return ps.create_shipment(payload)


class Sweep:
    def __init__(self):
        self.crashes: dict[tuple, list] = {}
        self.checked = 0

    def run(self, label, fn, *args, **kwargs):
        self.checked += 1
        try:
            fn(*args, **kwargs)
        except (ValidationError, ServiceError):
            pass
        except Exception as error:          # noqa: BLE001 - 조사 도구
            where = traceback.extract_tb(error.__traceback__)[-1]
            key = (type(error).__name__, f"{Path(where.filename).name}:{where.lineno}")
            self.crashes.setdefault(key, []).append((label, str(error)[:150]))

    def report(self) -> int:
        total = sum(len(v) for v in self.crashes.values())
        print(f"\n{'=' * 70}\n검사 {self.checked:,}건 · 예상 못 한 예외 {total}건 "
              f"({len(self.crashes)}곳)\n{'=' * 70}")
        for (kind, where), rows in sorted(self.crashes.items(), key=lambda x: -len(x[1])):
            print(f"\n[{len(rows):>5}건] {kind} @ {where}")
            for label, message in rows[:3]:
                print(f"        {label} -> {message}")
        return len(self.crashes)


class FakeFile:
    def __init__(self, data, filename, mimetype="application/octet-stream"):
        self._data = data
        self.filename = filename
        self.mimetype = mimetype

    def read(self):
        return self._data


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


def main(rounds: int) -> int:
    # 윈도 기본 콘솔은 cp949라 한글 대시(—)에서 죽습니다. 다 돌려 놓고
    # 마지막 출력에서 멈추면 아무것도 못 봅니다. (2026-09-26)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    block_outbound()
    app = build_app()          # 버리는 메모리 DB 위에서만 돕니다
    s = Sweep()
    rng = random.Random(20260921)

    with app.app_context():
        db.create_all()
        from app.services import (container_tracking_service as cts,
                                  customs_filing_service as cfs,
                                  document_service as ds,
                                  requirement_service as rs,
                                  shipment_service, tracking_service)

        shipment = a_shipment()

        # 1) 서류 생성·검증은 몇 번을 해도 같아야 합니다.
        for _ in range(3):
            s.run("generate_documents", ds.generate_documents, shipment)
            s.run("generate_documents(overwrite)", ds.generate_documents, shipment, overwrite=True)
            s.run("check_documents", ds.check_documents, shipment)
            s.run("validate_shipment_documents", ds.validate_shipment_documents, shipment)

        # 2) 서류 수정 폼에 이상한 값을 넣습니다.
        doc_types = list(ds.DOCUMENT_TYPES)
        for _ in range(rounds):
            doc_type = rng.choice(doc_types)
            fields = ds.DOCUMENT_FIELDS[doc_type]
            form = {rng.choice(fields): rng.choice(NASTY) for _ in range(rng.randint(1, 5))}
            if rng.random() < 0.4:
                form[f"item-{rng.randint(0, 5)}-{rng.choice(['quantity', 'description', 'amount'])}"] \
                    = rng.choice(NASTY)
            if rng.random() < 0.2:
                form["없는칸"] = rng.choice(NASTY)
            s.run(f"update_document[{doc_type}]", _update, ds, shipment, doc_type, form)
            s.run(f"document_sections[{doc_type}]", _sections, ds, shipment, doc_type)

        # 3) 그 밖의 서비스도 같은 Shipment로 훑습니다.
        for label, fn in [
            ("filing_sheet", lambda: cfs.filing_sheet(shipment)),
            ("filing_text", lambda: cfs.as_text(cfs.filing_sheet(shipment))),
            ("requirements_for", lambda: rs.requirements_for(shipment)),
            ("origin_guide", lambda: ds.origin_certificate_guide(shipment)),
            ("timeline", lambda: tracking_service.build_timeline(shipment)),
            ("cost_groups", lambda: shipment_service.cost_groups(shipment)),
            ("track_shipment", lambda: cts.track_shipment(shipment)),
        ]:
            for _ in range(3):
                s.run(label, fn)

        # 4) 신고 자료 칸과 조회 번호에 이상한 값
        for value in NASTY:
            s.run(f"update_filing[{value!r}]", cfs.update_filing_fields, shipment, {
                "exporter_business_no": value, "customs_trade_kind": value,
                "customs_payment_method": value, "country_of_origin": value})
            s.run(f"save_numbers[{value!r}]", cts.save_numbers, shipment, {
                "bl_no": value, "export_declaration_no": value, "cargo_no": value})
            text = value if isinstance(value, str) else str(value)
            s.run(f"detect_kind[{text[:20]!r}]", cts.detect_kind, text)

        # 5) 업로드: 확장자·내용·크기를 섞습니다.
        names = ["a.pdf", "a.PDF", "a.txt", "a.docx", "a.png", "a.exe", "a", "a.tar.gz",
                 "..\\..\\evil.pdf", "가" * 300 + ".pdf", "a.pdf\x00.exe"]
        blobs = [b"", b"x", b"%PDF-1.4 broken", b"\x89PNG\r\n", "글자".encode(),
                 b"A" * 1000, b"\x00" * 100]
        for name in names:
            for blob in blobs:
                s.run(f"upload[{name}]", _upload, rs, shipment, blob, name, rng)

        # 6) 없는 것을 지우거나 분석해 봅니다.
        for bogus in (-1, 0, 999999):
            s.run(f"analyze[{bogus}]", rs.analyze, shipment, bogus)
            s.run(f"delete_upload[{bogus}]", rs.delete_upload, shipment, bogus)

    return s.report()


def _update(ds, shipment, doc_type, form):
    ds.update_document(shipment, doc_type, form)


def _sections(ds, shipment, doc_type):
    document = ds.get_document(shipment, doc_type)
    ds.document_sections(document)
    ds.document_items(document)
    ds.document_view(document)


def _upload(rs, shipment, blob, name, rng):
    document = rs.upload(shipment, FakeFile(blob, name), rng.choice(
        ["cosmetic", "origin", "", "없는키", None]))
    rs.analyze(shipment, document.id)
    rs.delete_upload(shipment, document.id)


if __name__ == "__main__":
    sys.exit(1 if main(int(sys.argv[1]) if len(sys.argv) > 1 else 300) else 0)
