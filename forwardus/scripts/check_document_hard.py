"""어려운 적합성 시험. 은행이 실제로 서류를 반송하는 사유를 그대로 냅니다.

왜 쉬운 시험으로는 모자라나
  한 칸을 크게 틀리게 하면(수량 100 → 1000) 어떤 검사기도 잡습니다. 실무에서
  사고가 나는 것은 그런 것이 아니라 **눈으로는 같아 보이는 차이**입니다.

      HONG KIL DONG CO., LTD   vs   HONG KIL DONG CO.,LTD      (쉼표 뒤 공백)
      Busan                    vs   KRPUS                       (이름 vs 부호)
      USD 614.00               vs   $614                        (기호 vs 부호)
      2026-09-23               vs   23/09/2026                  (날짜 표기)

  은행은 이런 것으로 서류를 돌려보냅니다(UCP 600 불일치). 우리 검사기가
  이것을 어떻게 다루는지가 진짜 문제입니다. 두 방향 모두 위험합니다.

      못 잡으면   →  불일치인 채로 은행에 가서 대금을 못 받습니다.
      다 잡으면   →  같은 뜻인데 경고가 떠서, 사람이 경고를 안 믿게 됩니다.

  그래서 이 시험은 **"잡아야 하는 것"과 "잡으면 안 되는 것"을 나눠서** 셉니다.

쓰는 법
    python scripts/check_document_hard.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app                                  # noqa: E402
from app.processors import document_validator               # noqa: E402
from config import Config                                   # noqa: E402

# (이름, 바꾸는 함수, 잡아야 하는가)
#
# "잡아야 하는가"가 False인 것은 **같은 뜻**입니다. 경고가 뜨면 헛경보입니다.
# True인 것은 뜻이 달라지므로 반드시 잡아야 합니다.
CASES = [
    # --- 같은 뜻입니다. 잡으면 헛경보 ---
    ("앞뒤 공백", lambda v: f"  {v}  ", False),
    ("가운데 공백 두 번", lambda v: str(v).replace(" ", "  ", 1), False),
    ("숫자 천단위 쉼표", lambda v: f"{float(v):,.2f}" if _num(v) else None, False),
    ("소수점 끝 0", lambda v: f"{float(v):.2f}" if _num(v) else None, False),

    # --- 뜻이 다릅니다. 반드시 잡아야 함 ---
    # 대소문자만 다른 것은 **불일치가 아닙니다.** UCP 600에서 은행도 이것으로는
    # 서류를 돌려보내지 않습니다. 잡으면 헛경보입니다.
    ("대소문자 뒤집음", lambda v: str(v).swapcase() if str(v).isascii() and str(v).isalpha() else None, False),

    ("회사명 쉼표 뒤 공백 없앰", lambda v: str(v).replace(", ", ",") if ", " in str(v) else None, True),
    ("이름 끝 한 글자 빠짐", lambda v: str(v)[:-1] if len(str(v)) > 3 else None, True),
    ("품명 줄여 적음", lambda v: str(v).split()[0] if len(str(v).split()) > 1 else None, True),
    ("숫자 자릿수 하나 더", lambda v: float(v) * 10 if _num(v) else None, True),
    ("숫자 조금 다름 (1%)", lambda v: round(float(v) * 1.01, 2) if _num(v) else None, True),
    ("순중량·총중량 뒤바꿈", None, True),        # 아래에서 따로 다룹니다
    ("항구를 이름으로 적음", None, True),         # 〃
    ("통화 기호로 바꿈", None, True),            # 〃
    ("빈칸으로 둠", lambda v: "", True),
]

TEXT_FIELDS = ("exporter", "consignee", "product_description", "notify_party",
               "exporter_address", "consignee_address")
NUM_FIELDS = ("quantity", "gross_weight_kg", "net_weight_kg", "invoice_value", "total_cbm")
PORT_NAMES = {"KRPUS": "Busan", "USLAX": "Los Angeles", "TRIST": "Istanbul",
              "DEHAM": "Hamburg", "NLRTM": "Rotterdam", "USSEA": "Seattle"}


def _num(value) -> bool:
    try:
        float(str(value).replace(",", ""))
        return True
    except (TypeError, ValueError):
        return False


def _build(shipment, document_service):
    reference = document_service.build_reference(shipment)
    forms = {k: list(v) for k, v in document_service.DOCUMENT_FIELDS.items()}
    documents = {k: {f: reference.get(f, "") for f in fields} for k, fields in forms.items()}
    return reference, forms, documents


def _run(documents, reference, forms, field):
    result = document_validator.validate_documents(documents, reference, form_fields=forms)
    return any(f.get("field") == field for f in result["findings"])


def main() -> int:
    # 윈도 기본 콘솔은 cp949라 한글 대시(—)에서 죽습니다. 다 돌려 놓고
    # 마지막 출력에서 멈추면 아무것도 못 봅니다. (2026-09-26)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    app = create_app(Config)
    with app.app_context():
        from app.models import Shipment
        from app.services import document_service

        shipments = [s for s in Shipment.query.all() if s.cargos][:40]

        # 저장된 건은 시험용 값이 많습니다("dwa", "skin"). 그러면 가장 까다로운
        # 경우(회사명 쉼표·여러 낱말 품명·항구 이름)가 한 번도 안 돌아갑니다.
        # 실무 서류에 실제로 적히는 모양을 따로 넣습니다.
        REAL_LIKE = [{
            "exporter": "HONG KIL DONG CO., LTD.",
            "exporter_address": "15, Teheran-ro 7-gil, Gangnam-gu, Seoul, KOREA",
            "consignee": "BESTEKS DIS TICARET LTD. STI.",
            "consignee_address": "Merkez Mah. Ataturk Cad. No:42, Istanbul, TURKIYE",
            "notify_party": "SAME AS CONSIGNEE",
            "product_description": "Ball Chain & Connector - Brass, Raw 100BA",
            "package_type": "CARTON",
            "shipping_marks": "BESTEKS / ISTANBUL / C/NO. 1-100 / MADE IN KOREA",
            "quantity": 100, "gross_weight_kg": 1250.5, "net_weight_kg": 1180.0,
            "total_cbm": 12.5, "invoice_value": 8614.00, "currency": "USD",
            "incoterms": "CIF", "hs_code": "7117190000",
            "pol": "KRPUS", "pod": "TRIST",
            "etd": "2026-09-23", "vessel_or_flight": "HMM ALGECIRAS 0043W",
            "carrier": "HMM", "payment_terms": "T/T 30 DAYS AFTER B/L DATE",
            "freight_term": "FREIGHT PREPAID", "dangerous_goods": "NO",
        }, {
            "exporter": "FORWARDUS TRADING CO., LTD.",
            "exporter_address": "88, Sinsu-ro, Mapo-gu, Seoul, KOREA",
            "consignee": "ACME COSMETICS INC.",
            "consignee_address": "1200 W Olympic Blvd, Los Angeles, CA 90015, USA",
            "notify_party": "ACME COSMETICS INC.",
            "product_description": "Skin Care Lotion 150ml, Assorted",
            "package_type": "CARTON",
            "shipping_marks": "ACME / LOS ANGELES / C/NO. 1-300",
            "quantity": 300, "gross_weight_kg": 2400.0, "net_weight_kg": 2150.75,
            "total_cbm": 18.75, "invoice_value": 24500.50, "currency": "USD",
            "incoterms": "FOB", "hs_code": "3304990000",
            "pol": "KRPUS", "pod": "USLAX",
            "etd": "2026-10-02", "vessel_or_flight": "ONE COMMITMENT 015E",
            "carrier": "ONE", "payment_terms": "L/C AT SIGHT",
            "freight_term": "FREIGHT COLLECT", "dangerous_goods": "NO",
        }]
        should_catch = Counter()
        should_not = Counter()
        missed_detail: list[str] = []
        false_detail: list[str] = []
        runs = 0

        made = [_build(s, document_service) for s in shipments]
        # 실무 모양 서류도 같은 서식 칸으로 채워 함께 시험합니다.
        base_forms = {k: list(v) for k, v in document_service.DOCUMENT_FIELDS.items()}
        for sample in REAL_LIKE:
            made.append((sample, base_forms,
                         {k: {f: sample.get(f, "") for f in fields}
                          for k, fields in base_forms.items()}))

        for reference, forms, documents in made:
            kind = "commercial_invoice"
            fields = [f for f in forms[kind]
                      if f in document_validator.VALIDATION_FIELDS
                      and str(reference.get(f, "")).strip()]

            for name, change, must_catch in CASES:
                for field in fields:
                    value = reference.get(field)
                    # 따로 다루는 세 가지
                    if name == "순중량·총중량 뒤바꿈":
                        if field != "net_weight_kg" or not reference.get("gross_weight_kg"):
                            continue
                        new = reference["gross_weight_kg"]
                        if str(new) == str(value):
                            continue
                    elif name == "항구를 이름으로 적음":
                        if field not in ("pol", "pod") or str(value) not in PORT_NAMES:
                            continue
                        new = PORT_NAMES[str(value)]
                    elif name == "통화 기호로 바꿈":
                        if field != "currency" or str(value).upper() != "USD":
                            continue
                        new = "$"
                    else:
                        if name == "품명 줄여 적음" and field != "product_description":
                            continue
                        if (name in ("회사명 쉼표 뒤 공백 없앰", "대소문자 뒤집음",
                                     "이름 끝 한 글자 빠짐", "가운데 공백 두 번")
                                and field not in TEXT_FIELDS):
                            continue
                        if name in ("숫자 천단위 쉼표", "소수점 끝 0", "숫자 자릿수 하나 더",
                                    "숫자 조금 다름 (1%)") and field not in NUM_FIELDS:
                            continue
                        new = change(value)
                        if new is None or str(new) == str(value):
                            continue

                    broken = {k: dict(v) for k, v in documents.items()}
                    broken[kind][field] = new
                    caught = _run(broken, reference, forms, field)
                    runs += 1

                    if must_catch:
                        should_catch[name] += 1
                        if not caught:
                            should_catch[f"{name}__놓침"] += 1
                            if len(missed_detail) < 12:
                                missed_detail.append(f"{name} · {field}: "
                                                     f"{str(value)[:28]!r} → {str(new)[:28]!r}")
                    else:
                        should_not[name] += 1
                        if caught:
                            should_not[f"{name}__헛경보"] += 1
                            if len(false_detail) < 12:
                                false_detail.append(f"{name} · {field}: "
                                                    f"{str(value)[:28]!r} → {str(new)[:28]!r}")

        print(f"\n{'=' * 70}\n어려운 적합성 시험 — 은행 반송 사유 재현 ({runs}회)\n{'=' * 70}")

        print("\n■ 반드시 잡아야 하는 것 (뜻이 달라집니다)")
        total = miss = 0
        for name, _, must in CASES:
            if not must or name not in should_catch:
                continue
            n, bad = should_catch[name], should_catch.get(f"{name}__놓침", 0)
            total += n
            miss += bad
            mark = "OK" if not bad else f"★ 놓침 {bad}"
            print(f"   {name:<24}{n:>4}회   {mark}")
        print(f"   {'─' * 44}\n   합계 {total}회 · 놓침 {miss}"
              + (f"   → 잡는 비율 {(total - miss) / total * 100:.1f}%" if total else ""))

        print("\n■ 잡으면 안 되는 것 (같은 뜻입니다)")
        total2 = bad2 = 0
        for name, _, must in CASES:
            if must or name not in should_not:
                continue
            n, bad = should_not[name], should_not.get(f"{name}__헛경보", 0)
            total2 += n
            bad2 += bad
            print(f"   {name:<24}{n:>4}회   " + ("OK" if not bad else f"★ 헛경보 {bad}"))
        print(f"   {'─' * 44}\n   합계 {total2}회 · 헛경보 {bad2}")

        if missed_detail:
            print("\n★ 놓친 예 — 이대로 은행에 가면 서류가 돌아옵니다")
            for line in missed_detail:
                print(f"   {line}")
        if false_detail:
            print("\n★ 헛경보 예 — 같은 뜻인데 경고가 떴습니다")
            for line in false_detail:
                print(f"   {line}")
        if not missed_detail and not false_detail:
            print("\n놓침도 헛경보도 없습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
