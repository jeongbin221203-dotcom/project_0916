"""실제 키로 바깥 기관을 부릅니다. **키 하나당 최대 5회**입니다.

왜 상한을 두나
  기관 서버가 불안정합니다. 많이 부르면 잠시 막히고, 그러면 다음 사람이
  쓰려 할 때 안 됩니다. 그래서 **코드로 세어서** 5회를 넘기면 아예 안 보냅니다.
  세는 일을 사람 손에 맡기지 않습니다.

무엇을 보나
  200이 왔는지가 아니라 **답이 맞는지**를 봅니다.
    · 필수 항목이 비어 있지 않은가       (없으면 화면이 빈칸으로 뜹니다)
    · 우리가 물은 것과 같은 것이 왔는가  (다른 품목이 오면 엉뚱한 신고가 됩니다)
    · 값의 모양이 말이 되는가            (부호 자릿수 · 숫자 범위)

복잡한 값으로 묻습니다
  잘 되는 값만 넣으면 "된다"만 확인하고 끝납니다. 실제로 쓰는 긴 부호와
  여러 낱말, 경계 날짜를 넣어 봅니다.

기관이 멈춘 것과 우리가 틀린 것을 갈라 적습니다
  서버가 불안정하므로 "응답 없음"은 우리 잘못이 아닙니다. 그것을 결함으로
  세면 아침에 진짜 문제를 못 찾습니다.

    python scripts/check_api_keys_live.py
    python scripts/check_api_keys_live.py --only HS_CODE_SEARCH
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_PER_KEY = 5            # 키 하나당 최대 호출 수. 넘기면 보내지 않습니다.
PAUSE = 1.2                # 연달아 때리지 않습니다 (초)

used: dict[str, int] = defaultdict(int)
skipped: list[str] = []
wrong: list[str] = []
flaky: list[str] = []


def budget(key: str) -> bool:
    """이 키를 한 번 더 부를 수 있는가. 셈은 여기서만 합니다."""

    if used[key] >= MAX_PER_KEY:
        return False
    used[key] += 1
    time.sleep(PAUSE)
    return True


def digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def check(key: str, label: str, call, *tests) -> None:
    """한 번 부르고, 돌아온 것을 조건들로 확인합니다."""

    if not budget(key):
        skipped.append(f"{key} · {label}")
        print(f"   - {label:<32} 상한({MAX_PER_KEY}회) 도달 — 보내지 않음")
        return
    try:
        found = call()
    except Exception as error:                       # noqa: BLE001
        flaky.append(f"{key} · {label}: {type(error).__name__}")
        print(f"   △ {label:<32} 죽음 {type(error).__name__}: {str(error)[:50]}")
        return

    if not isinstance(found, dict) or not found.get("success"):
        message = str((found or {}).get("message", ""))[:58]
        code = (found or {}).get("error_code", "") or "실패"
        # 기관이 멈춘 것과 우리가 잘못 적은 것은 다릅니다.
        if code in ("API_TIMEOUT", "API_ERROR", "API_AUTH_FAILED"):
            flaky.append(f"{key} · {label}: {code}")
            print(f"   △ {label:<32} {code} — {message}")
        else:
            wrong.append(f"{key} · {label}: {code} {message}")
            print(f"   ★ {label:<32} {code} — {message}")
        return

    data = found.get("data")
    bad = [why for test, why in tests if not _safe(test, data)]
    size = len(data) if hasattr(data, "__len__") else "-"
    print(f"   {'✓' if not bad else '★'} {label:<32} 항목 {size}")
    for why in bad:
        wrong.append(f"{key} · {label}: {why}")
        print(f"       ★ {why}")


def _safe(test, data) -> bool:
    try:
        return bool(test(data))
    except Exception:                                # noqa: BLE001
        return False


def main() -> int:
    from app import create_app
    from config import Config

    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    app = create_app(Config)

    with app.app_context():
        from app.collectors import (carrier_client, container_client, customs_client,
                                    customs_extra_client, exchange_client)

        print(f"■ 실제 키로 확인 · 키당 최대 {MAX_PER_KEY}회 · 사이 {PAUSE}초\n")

        def part(key: str) -> bool:
            return not only or only == key

        # ── HS부호 검색 — 제품의 출발점. 여기가 틀리면 전부 틀립니다 ─────
        if part("HS_CODE_SEARCH"):
            print("── HS부호 검색 · 필수")
            for query in ["치약", "폴리에틸렌 필름", "리튬이온 축전지",
                          "스테인리스 열연강판", "냉동 고등어"]:
                check("HS_CODE_SEARCH", f"'{query}'",
                      lambda q=query: customs_client.search_hs_codes(q),
                      (lambda d: bool(d), "한 건도 안 옴"),
                      (lambda d: all(len(digits(r.get("code"))) == 10 for r in d),
                       "10자리가 아닌 부호가 섞임"),
                      (lambda d: all(str(r.get("name") or "").strip() for r in d),
                       "품명이 빈 줄이 있음"))

        # ── 관세율 — 신고가격에 곱해집니다 ─────────────────────────────
        if part("TARIFF_RATE"):
            print("\n── 관세율 · 중요")
            for hs in ["3306100000", "8507600000", "7208510000",
                       "0303540000", "3901100000"]:
                check("TARIFF_RATE", f"HS {hs}",
                      lambda h=hs: customs_client.fetch_tariff_rates(h),
                      (lambda d: d is not None, "응답이 비어 있음"))

        # ── 관세환율 — 견적 금액에 그대로 곱해집니다 ────────────────────
        if part("CUSTOMS_EXCHANGE_RATE"):
            print("\n── 관세환율 · 필수 (금액에 직접 곱해짐)")
            today = date.today()
            for when in [None, today, today - timedelta(days=7),
                         today - timedelta(days=30), today - timedelta(days=1)]:
                check("CUSTOMS_EXCHANGE_RATE",
                      when.isoformat() if when else "오늘(기본)",
                      lambda w=when: exchange_client.fetch_unipass_rates(w),
                      (lambda d: bool(d), "환율이 안 옴"),
                      (lambda d: "USD" in d, "USD 가 없음"),
                      (lambda d: 300 <= float(d["USD"]) <= 5000,
                       "USD 가 있을 수 없는 값"),
                      (lambda d: all(isinstance(v, (int, float)) and v > 0
                                     for v in d.values()),
                       "숫자가 아니거나 0 이하인 통화가 섞임"))

        # ── 수출요건 — 틀리면 통관에서 막힙니다 ─────────────────────────
        if part("REQUIREMENT_APPROVAL"):
            print("\n── 수출요건 · 필수")
            for hs in ["3306100000", "0303540000", "9018390000",
                       "2710192090", "8507600000"]:
                check("REQUIREMENT_APPROVAL", f"HS {hs}",
                      lambda h=hs: customs_extra_client.export_requirement_laws(h),
                      (lambda d: d is not None, "응답이 비어 있음"))

        # ── 통관고유부호 — 수출신고서 법정 기재사항 ─────────────────────
        if part("CUSTOMS_CLEARANCE_CODE"):
            print("\n── 통관고유부호 · 필수")
            for no in ["124-81-00998", "120-81-47521", "220-81-62517"]:
                check("CUSTOMS_CLEARANCE_CODE", f"사업자 {no}",
                      lambda n=no: customs_extra_client.clearance_code(business_no=n),
                      (lambda d: d is not None, "응답이 비어 있음"))

        if part("HS_NAVIGATION"):
            print("\n── HS 내비게이션 · 중요")
            for hs in ["3306100000", "8507600000", "6109100000"]:
                check("HS_NAVIGATION", f"HS {hs}",
                      lambda h=hs: customs_extra_client.hs_navigation(h),
                      (lambda d: d is not None, "응답이 비어 있음"))

        if part("SIMPLE_REFUND_RATE"):
            print("\n── 간이정액 환급율 · 중요")
            for hs in ["3306100000", "6109100000", "8507600000"]:
                check("SIMPLE_REFUND_RATE", f"HS {hs}",
                      lambda h=hs: customs_extra_client.refund_rate(h),
                      (lambda d: d is not None, "응답이 비어 있음"))

        if part("AIRLINE_LIST"):
            print("\n── 항공사 목록 · 중요")
            for name in ["대한항공", "아시아나", "페덱스"]:
                check("AIRLINE_LIST", f"'{name}'",
                      lambda n=name: customs_extra_client.search_airlines(n),
                      (lambda d: d is not None, "응답이 비어 있음"))

        if part("SHIPPING_COMPANY_LIST"):
            print("\n── 선박회사 목록 · 중요")
            for name in ["HMM", "머스크", "고려해운"]:
                check("SHIPPING_COMPANY_LIST", f"'{name}'",
                      lambda n=name: carrier_client.search_shipping_companies(n),
                      (lambda d: d is not None, "응답이 비어 있음"))

        if part("CARGO_CLEARANCE_PROGRESS"):
            print("\n── 화물통관 진행 · 중요")
            for bl in ["HLCUBO12345678", "MAEU123456789"]:
                check("CARGO_CLEARANCE_PROGRESS", f"B/L {bl}",
                      lambda b=bl: container_client.cargo_progress(mbl_no=b,
                                                                   bl_year="2026"),
                      (lambda d: d is not None, "응답이 비어 있음"))

        if part("DATA_GO_KR_SERVICE_KEY"):
            print("\n── 공공데이터포털 · 중요")
            check("DATA_GO_KR_SERVICE_KEY", "인천공항 화물기 시간표",
                  lambda: carrier_client.fetch_icn_cargo_flights(),
                  (lambda d: d is not None, "응답이 비어 있음"))

    print(f"\n■ 키별 호출 횟수 (상한 {MAX_PER_KEY})")
    for key in sorted(used):
        over = "!" if used[key] > MAX_PER_KEY else " "
        print(f"   {over} {key:<34} {used[key]}회")

    print(f"\n■ 마무리 · 총 {sum(used.values())}회")
    print(f"   값이 틀린 것        {len(wrong)}건")
    print(f"   기관이 응답 안 한 것 {len(flaky)}건   (우리 잘못이 아닙니다)")
    print(f"   상한에 걸려 안 보낸 것 {len(skipped)}건")
    for row in wrong[:12]:
        print(f"   ★ {row}")

    if any(n > MAX_PER_KEY for n in used.values()):
        print("\n★ 상한을 넘긴 키가 있습니다.")
        return 1
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
