"""기관에서 받을 수 있는 것을 **미리 다 받아 파일로 저장**합니다.

왜 필요한가
  기관은 자주 멈춥니다. 2026-09-25에는 관세청 UNI-PASS가 하루 종일 닿지
  않았습니다. 그날 화면에서는 선사 목록도, 항공사 목록도, 관세환율도 빈칸이
  되었습니다. 어제까지 잘 받아 둔 값이 있었는데도, 서버를 다시 켜면 그마저
  사라졌습니다.

  기관이 살아 있을 때 받아 파일로 남겨 두면, 막힌 동안에도 **실제로 받았던
  값**으로 답할 수 있습니다. 인터넷이 아예 없는 곳에서도 마찬가지입니다.
  예시 데이터를 지어내는 것과는 다릅니다.

무엇을 지키나
  - **받은 것만 남깁니다.** 실패하면 아무것도 덮어쓰지 않습니다. 어제 받은
    값이 오늘 못 받았다고 지워지면 안 됩니다.
  - 기관을 천천히 부릅니다. 한 번에 몰아치면 차단당합니다.
  - 키 값을 화면에 찍지 않습니다.
  - 화물 추적은 **일부러 저장하지 않습니다.** 어제 "부산 출항"이었다고 오늘도
    그렇게 답하면 거짓말이 됩니다. 움직이는 값은 못 받으면 못 받았다고 합니다.

쓰는 법
    python scripts/prime_cache.py              # 오래된 것만 다시 받습니다
    python scripts/prime_cache.py --all        # 전부 다시 받습니다
    python scripts/prime_cache.py --check      # 무엇이 저장돼 있는지만 봅니다

일주일마다 저절로 돌리려면
    Windows   작업 스케줄러에 등록합니다.
              schtasks /create /tn ForwardUsCache /sc weekly /d SUN /st 04:00 ^
                /tr "python C:\\...\\forwardus\\scripts\\prime_cache.py"
    macOS·리눅스
              crontab -e 에 아래 한 줄
              0 4 * * 0 cd /path/to/forwardus && python scripts/prime_cache.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app                                  # noqa: E402
from config import Config                                   # noqa: E402

# 기관을 잇따라 부르지 않고 쉬는 시간. 몰아치면 차단당합니다.
PAUSE_SECONDS = 1.0

# 일주일이 지나면 다시 받습니다. (사용자 요청: 1주일 간격 자동 최신화)
REFRESH_DAYS = 7

# 미리 받아 둘 것. (이름, 무엇을 부르나, 자료 종류)
#
# 자료 종류는 snapshot.MAX_DAYS의 열쇠입니다. 얼마나 오래된 것까지 쓸지를 정합니다.
#
# 선사·항공사·포워더는 **자주 찾는 이름**만 미리 받습니다. 등록부 전체를 받을
# 수 있는 창구가 없어서, 화면에서 실제로 검색하는 이름을 미리 채워 둡니다.
SHIPPING_LINES = ("에이치엠엠", "고려해운", "장금상선", "흥아라인", "팬오션", "대한해운")
AIRLINES = ("대한항공", "아시아나항공", "제주항공", "에어인천")
FORWARDERS = ("판토스", "현대글로비스", "씨제이대한통운", "롯데글로벌로지스")


def plan():
    """(이름, 부르는 함수, 종류). 함수는 그때그때 import합니다."""

    from app.collectors import (carrier_client, customs_extra_client, exchange_client,
                                ksure_client, port_stats_client, trade_stats_client)

    jobs = [("환율", exchange_client.fetch_krw_rates, "rates")]
    for name in SHIPPING_LINES:
        jobs.append((f"선사 · {name}",
                     lambda n=name: carrier_client.search_shipping_companies(n), "registry"))
    for name in AIRLINES:
        jobs.append((f"항공사 · {name}",
                     lambda n=name: customs_extra_client.search_airlines(n), "registry"))
    for name in FORWARDERS:
        jobs.append((f"포워더 · {name}",
                     lambda n=name: customs_extra_client.search_forwarders(n), "registry"))
    jobs += [
        ("항만 물동량", port_stats_client.port_traffic, "stats"),
        ("컨테이너 처리실적", port_stats_client.container_throughput, "stats"),
        ("인천공항 화물기", carrier_client.fetch_icn_cargo_flights, "stats"),
        ("무역보험공사 결제정보 (미국)", lambda: ksure_client.payment_info("US"), "stats"),
        ("품목별 수출입실적 (3304)", lambda: trade_stats_client.item_trade("3304"), "stats"),
    ]
    return jobs


# HS부호 하나로 답이 정해지는 조회들. 자주 다루는 품목만 미리 받습니다.
# (등록부 전체를 내려받는 창구가 없어, 실제로 조회하는 부호를 채워 둡니다)
COMMON_HS = ("3304990000", "3306100000", "2106909099", "8517120000",
             "3004909900", "2710192200", "7117190000", "6109100000")


def unipass_plan():
    """UNI-PASS에서 HS부호로 받는 것들. 기관이 살아 있어야 받습니다.

    2026-09-26 현재 unipass.customs.go.kr 이 통째로 닿지 않습니다. 그래서
    이 목록은 지금 전부 실패합니다. 기관이 살아난 뒤 다시 돌리면 채워집니다.
    """

    from app.collectors import customs_extra_client as C

    jobs = []
    for code in COMMON_HS:
        jobs += [
            (f"간이정액환급률 · {code}", lambda c=code: C.refund_rate(c), "law"),
            (f"수출이행기간 단축 · {code}", lambda c=code: C.shortened_loading_period(c), "law"),
            (f"HS 내비게이션 · {code}", lambda c=code: C.hs_navigation(c), "law"),
        ]
    return jobs


def laws_plan():
    """자주 나오는 HS부호의 세관장확인 법령. 법이 바뀔 때만 바뀌므로 오래 씁니다."""

    from app.collectors import customs_extra_client

    return [(f"세관장확인 · {code}",
             lambda c=code: customs_extra_client.export_requirement_laws(c), "law")
            for code in COMMON_HS]


def main() -> int:
    everything = "--all" in sys.argv
    only_check = "--check" in sys.argv

    app = create_app(Config)
    with app.app_context():
        from app.collectors import snapshot

        jobs = plan() + laws_plan() + unipass_plan()

        if only_check:
            print(f"{'자료':<34}{'저장됨':<10}나이")
            print("-" * 58)
            kept = 0
            for label, _call, kind in jobs:
                age = _stored(label, kind)
                if age is not None:
                    kept += 1
                    print(f"{label:<34}{'있음':<10}{age}일 전")
                else:
                    print(f"{label:<34}{'없음':<10}-")
            print("-" * 58)
            print(f"{kept}/{len(jobs)}개가 저장돼 있습니다. "
                  f"없는 것을 채우려면 --all 없이 그냥 돌리세요.")
            return 0

        fresh = saved = skipped = failed = 0
        print(f"미리 받기 시작 — {len(jobs)}개 "
              f"({'전부 다시' if everything else f'{REFRESH_DAYS}일 지난 것만'})\n")
        for label, call, kind in jobs:
            key = _key_of(label)
            if not everything:
                age = _stored(label, kind)
                if age is not None and age < REFRESH_DAYS:
                    skipped += 1
                    continue
            try:
                result = call()
            except Exception as error:                        # noqa: BLE001
                print(f"  {label:<34}부르다 멈춤: {type(error).__name__}")
                failed += 1
                continue

            source = (result or {}).get("source", "")
            if result and result.get("success") and source in ("api", "market"):
                fresh += 1
                print(f"  {label:<34}받았습니다 ({source})")
                saved += 1
            elif result and result.get("success"):
                # 대체 데이터입니다. 저장하지 않습니다 — 그것이 다시 "실제로
                # 받았던 값"인 척하게 됩니다.
                print(f"  {label:<34}대체 데이터({source}) — 저장하지 않습니다")
                failed += 1
            else:
                message = str((result or {}).get("message", ""))[:40]
                print(f"  {label:<34}못 받았습니다 ({message})")
                failed += 1
            time.sleep(PAUSE_SECONDS)

        print(f"\n받음 {fresh} · 아직 싱싱해서 건너뜀 {skipped} · 못 받음 {failed}")
        if failed:
            print("※ 못 받은 것은 **덮어쓰지 않았습니다.** 예전에 받아 둔 값이 있으면 "
                  "그대로 남아 있습니다. 기관이 살아난 뒤 다시 돌리세요.")
    return 0


def _stored(label: str, kind: str):
    """저장된 것이 있으면 (나이, 설명). 환율만 저장 방식이 다릅니다."""

    from app.collectors import exchange_client, snapshot

    if label == "환율":
        # 환율은 snapshot이 아니라 exchange_client가 따로 남깁니다.
        # (통화 162개를 담고 적용일까지 함께 적어야 해서 모양이 다릅니다)
        got = exchange_client._last_good()
        return got["stored_days"] if got else None
    got = snapshot.recall(_key_of(label), kind)
    return got["stored_days"] if got else None


def _key_of(label: str) -> str:
    """화면에 보여 준 이름을 저장 열쇠로. 수집기가 쓰는 이름과 맞춥니다."""

    if label.startswith("선사 · "):
        return f"ships_{label.split(' · ', 1)[1]}"
    if label.startswith("항공사 · "):
        return f"airlines_{label.split(' · ', 1)[1]}"
    if label.startswith("포워더 · "):
        return f"forwarders_{label.split(' · ', 1)[1]}"
    if label.startswith("세관장확인 · "):
        return f"laws_{label.split(' · ', 1)[1]}_1"
    if label.startswith("간이정액환급률 · "):
        return f"refund_rate_{label.split(' · ', 1)[1]}"
    if label.startswith("수출이행기간 단축 · "):
        return f"short_period_{label.split(' · ', 1)[1]}"
    if label.startswith("HS 내비게이션 · "):
        return f"hs_nav_{label.split(' · ', 1)[1]}"
    return label


if __name__ == "__main__":
    raise SystemExit(main())
