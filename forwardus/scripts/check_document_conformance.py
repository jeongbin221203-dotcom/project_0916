"""실제 서류로 적합성 검사를 여러 번 돌려 봅니다. (기본 100회)

왜 필요한가
  서류 간 검증은 "값이 서로 다르면 잡는다"가 전부입니다. 그런데 정말 잡는지는
  **틀린 서류를 넣어 봐야** 압니다. 테스트에 있는 몇 가지 경우만으로는
  "이 종류의 틀림은 못 잡는다"를 알 수 없습니다.

  그래서 저장된 실제 Shipment에서 진짜 서류를 만들고, 한 곳씩 일부러 틀리게
  고친 뒤 검증기가 잡아내는지 봅니다.

무엇을 봅니다
  1. 멀쩡한 서류를 통과시키는가   — 헛경보(false alarm)
  2. 틀린 서류를 잡아내는가       — 놓침(miss)
  3. 무엇을 못 잡는가             — 칸별로 모아서 보여 줍니다

  **놓침이 헛경보보다 위험합니다.** 헛경보는 사람이 보고 넘기지만, 놓친 것은
  그대로 세관에 갑니다.

쓰는 법
    python scripts/check_document_conformance.py           # 100회
    python scripts/check_document_conformance.py 300       # 횟수 지정
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app                                  # noqa: E402
from app.processors import document_validator               # noqa: E402
from config import Config                                   # noqa: E402

# 일부러 틀리게 만드는 방법. 실무에서 실제로 나오는 실수만 넣습니다.
#
#   숫자를 바꿔 적음      패킹리스트 중량을 송장에서 옮기며 자릿수를 틀림
#   단위를 헷갈림         kg과 t, 낱개와 박스
#   통화를 틀림           USD 계약인데 송장에 EUR
#   항구를 바꿔 적음      POL/POD를 거꾸로
#   빈칸으로 둠           옮기다 빠뜨림
def _swap_last(value):
    text = str(value or "")
    if not text:
        return "X"
    return text[:-1] + ("Y" if text[-1].upper() == "X" else "X")



BREAKERS = {
    "숫자_자릿수": lambda v: _digits(v, 10),
    "숫자_조금": lambda v: _digits(v, 1.15),
    "빈칸": lambda v: "",
    # 마지막 글자를 바꿉니다. **정말 달라지게** 바꿔야 합니다.
    # 예전에는 늘 "X"로 바꿔서, 품명이 "x" 한 글자인 건은 "X"가 되어
    # 대소문자만 달라진 채로 "안 잡혔다"고 세었습니다. 검증기는 대소문자를
    # 같게 보므로 잡을 것이 없었던 것입니다. (2026-09-26)
    "글자_바꿈": _swap_last,
    "통화_바꿈": lambda v: "EUR" if str(v).upper() != "EUR" else "USD",
}


def _digits(value, factor):
    try:
        return round(float(str(value).replace(",", "")) * factor, 2)
    except (TypeError, ValueError):
        return f"{value}0"


def pick_breaker(field: str) -> str:
    if field in ("quantity", "gross_weight_kg", "net_weight_kg", "invoice_value"):
        return random.choice(["숫자_자릿수", "숫자_조금", "빈칸"])
    if field == "currency":
        return "통화_바꿈"
    return random.choice(["글자_바꿈", "빈칸"])


def main() -> int:
    # 윈도 기본 콘솔은 cp949라 한글 대시(—)에서 죽습니다. 다 돌려 놓고
    # 마지막 출력에서 멈추면 아무것도 못 봅니다. (2026-09-26)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    random.seed(20260926)                       # 같은 결과가 다시 나오게

    app = create_app(Config)
    with app.app_context():
        from app.models import Shipment
        from app.services import document_service

        shipments = [s for s in Shipment.query.all() if s.cargos]
        if not shipments:
            print("서류를 만들 Shipment가 없습니다.")
            return 1

        clean_pass = clean_fail = 0
        caught = missed = 0
        miss_by_field: Counter = Counter()
        catch_by_field: Counter = Counter()
        no_target = 0

        for turn in range(rounds):
            shipment = shipments[turn % len(shipments)]
            reference = document_service.build_reference(shipment)
            forms = {kind: list(fields)
                     for kind, fields in document_service.DOCUMENT_FIELDS.items()}
            # 이 건의 진짜 값으로 서류를 만듭니다. (지어낸 값이 아닙니다)
            documents = {kind: {f: reference.get(f, "") for f in fields}
                         for kind, fields in forms.items()}

            # 1) 멀쩡한 서류는 통과해야 합니다.
            clean = document_validator.validate_documents(documents, reference,
                                                          form_fields=forms)
            real = [f for f in clean["findings"] if f.get("kind") in ("reference", "cross")]
            if real:
                clean_fail += 1
                if clean_fail <= 3:
                    print(f"  헛경보 예: {real[0].get('message', '')[:96]}")
            else:
                clean_pass += 1

            # 2) 한 곳을 일부러 틀리게 하고, 잡는지 봅니다.
            targets = [(kind, field)
                       for kind, fields in forms.items()
                       for field in fields
                       if field in document_validator.VALIDATION_FIELDS
                       and reference.get(field) not in (None, "")]
            if not targets:
                no_target += 1
                continue
            kind, field = random.choice(targets)
            broken = {k: dict(v) for k, v in documents.items()}
            broken[kind][field] = BREAKERS[pick_breaker(field)](reference.get(field))

            result = document_validator.validate_documents(broken, reference,
                                                           form_fields=forms)
            hit = any(f.get("field") == field for f in result["findings"])
            if hit:
                caught += 1
                catch_by_field[field] += 1
            else:
                missed += 1
                miss_by_field[field] += 1

        tried = caught + missed
        print(f"\n{'=' * 64}\n적합성 검사 {rounds}회 (Shipment {len(shipments)}건 돌려가며)\n{'=' * 64}")
        print(f"\n■ 멀쩡한 서류를 통과시키는가")
        print(f"   통과 {clean_pass} · 헛경보 {clean_fail}"
              + ("   ← 헛경보가 있으면 사람이 경고를 안 믿게 됩니다" if clean_fail else "   (헛경보 없음)"))
        print(f"\n■ 틀린 서류를 잡아내는가  (한 번에 한 칸씩 망가뜨림)")
        if tried:
            print(f"   잡음 {caught} · 놓침 {missed}  → 잡는 비율 {caught / tried * 100:.1f}%")
        if no_target:
            print(f"   (검사 대상 칸이 없어 건너뛴 회차 {no_target})")
        if catch_by_field:
            print(f"\n   잡은 칸: " + ", ".join(f"{f}×{n}" for f, n in catch_by_field.most_common()))
        if miss_by_field:
            print(f"\n   ★ 못 잡은 칸 — 여기가 구멍입니다")
            for field, count in miss_by_field.most_common():
                label = document_validator.VALIDATION_FIELDS.get(field, field)
                print(f"      {field} ({label}) ×{count}")
        else:
            print(f"\n   못 잡은 칸 없음.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
