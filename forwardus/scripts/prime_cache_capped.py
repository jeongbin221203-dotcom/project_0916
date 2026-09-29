"""기관이 살아 있을 때 받아서 파일로 남깁니다. **키당 상한은 없습니다.** (9-27 5회 -> 9-29 10회 -> 9-29 해지)

왜 상한이 있나
  기관 서버가 불안정합니다. 한 번에 몰아치면 잠시 막히고, 그러면 다음 사람이
  쓰려 할 때 안 됩니다. 기존 prime_cache.py 는 한 번에 수십 번 부릅니다.
  이 스크립트는 **코드로 세어서** 상한을 넘기면 아예 안 보냅니다.
  (2026-09-27 사용자 지시)

무엇을 받나 — 값어치 순으로 열 개씩
  같은 키로 다섯 번만 부를 수 있으니, **자주 쓰이고 잘 안 바뀌는 것**부터
  받습니다. 화물 추적처럼 움직이는 값은 일부러 받지 않습니다. 어제 "부산
  출항"이었다고 오늘도 그렇게 답하면 거짓말이 됩니다.

무엇을 지키나
  - **받은 것만 남깁니다.** 실패하면 아무것도 덮어쓰지 않습니다. 어제 받은
    값이 오늘 못 받았다고 지워지면 안 됩니다. (snapshot.remember 가 그렇게 합니다)
  - source 가 "api" 인 답만 저장합니다. 예시(mock)나 내부 표(internal)를
    저장하면 그것이 다시 "저장된 실제 값"인 척하게 됩니다.
  - 호출 사이를 띄웁니다.
  - 키 값을 화면에 찍지 않습니다.

    python scripts/prime_cache_capped.py
    python scripts/prime_cache_capped.py --check     # 무엇이 저장돼 있는지만
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 상한 없음. 2026-09-29 사용자 지시로 해지했습니다 (9-27 5회 -> 9-29 10회 -> 해지).
#
# 해지해도 지금 호출 수는 그대로입니다 — 받을 대상이 키마다 열 개 안쪽이라
# 상한이 막고 있던 자리가 없었습니다 (9/29 실행 116회, 막힌 것 0건).
# 앞으로 대상을 열 개 넘게 늘리면 그때부터 실제로 늘어납니다.
#
# **PAUSE 는 남겨 둡니다.** 상한과 다른 장치입니다. 한꺼번에 몰아치면 기관이
# 잠시 막고, 그러면 다음 사람이 쓰려 할 때 안 됩니다.
MAX_PER_KEY = None     # None = 상한 없음
PAUSE = 1.2

used: dict[str, int] = defaultdict(int)
saved: list[str] = []
missed: list[str] = []


def budget(key: str) -> bool:
    """보낼지 정하고 횟수를 셉니다. 상한이 없어도 **세는 것은 계속합니다** —
    끝에 키별 호출 수를 적어야 얼마나 두드렸는지 눈으로 볼 수 있습니다.
    """

    if MAX_PER_KEY is not None and used[key] >= MAX_PER_KEY:
        return False
    used[key] += 1
    time.sleep(PAUSE)
    return True


def grab(key: str, label: str, call) -> None:
    """한 번 받아 옵니다. 저장은 각 collector 안의 snapshot.remember 가 합니다."""

    if not budget(key):
        print(f"   - {label:<38} 상한({MAX_PER_KEY}회) 도달 — 보내지 않음")
        return
    try:
        found = call()
    except Exception as error:                        # noqa: BLE001
        missed.append(f"{label}: {type(error).__name__}")
        print(f"   △ {label:<38} 죽음 {type(error).__name__}")
        return

    source = (found or {}).get("source", "")
    data = (found or {}).get("data")
    size = len(data) if hasattr(data, "__len__") else "-"
    if found and found.get("success") and source == "api":
        saved.append(f"{label} ({size})")
        print(f"   ✓ {label:<38} 받아서 저장 · 항목 {size}")
    elif found and found.get("success"):
        # 예시나 내부 표입니다. 저장하면 "실제로 받은 값"인 척하게 됩니다.
        print(f"   ○ {label:<38} 실데이터 아님(source={source}) — 저장 안 함")
    else:
        message = str((found or {}).get("message", ""))[:44]
        missed.append(f"{label}: {message}")
        print(f"   △ {label:<38} 못 받음 — {message}")


def show_cache() -> None:
    from app.collectors import file_cache

    folder = file_cache.cache_dir()
    files = sorted(p for p in folder.glob("*.json"))
    print(f"■ 저장된 것 {len(files)}개 · {folder}")
    for path in files:
        age = (time.time() - path.stat().st_mtime) / 86400
        print(f"   {path.stem:<44} {path.stat().st_size:>7,}바이트 · {age:.1f}일 전")


def main() -> int:
    from app import create_app
    from config import Config

    app = create_app(Config)
    with app.app_context():
        if "--check" in sys.argv:
            show_cache()
            return 0

        from app.collectors import (carrier_client, customs_client, customs_extra_client,
                                    exchange_client, port_stats_client, trade_stats_client)

        cap = "상한 없음" if MAX_PER_KEY is None else f"키당 최대 {MAX_PER_KEY}회"
        print(f"■ 기관이 살아 있을 때 받아 둡니다 · {cap}\n")

        # ── 환율 — 가장 값어치 있습니다. 견적 금액에 그대로 곱해집니다 ──────
        print("── 환율 (하루 한 번 고시라 같은 것을 열 번 불러도 같은 답입니다.\n   그래서 횟수를 늘리지 않고 서로 다른 세 곳을 받습니다)")
        grab("CUSTOMS_EXCHANGE_RATE", "관세청 고시환율",
             exchange_client.fetch_krw_rates)
        grab("CUSTOMS_EXCHANGE_RATE", "통화 이름표",
             exchange_client.fetch_currency_names)
        from app.collectors import fx_board_client
        grab("CUSTOMS_EXCHANGE_RATE", "환율 시세표 (수출입은행 → OXR → 관세청)",
             fx_board_client.board)

        # ── 업체 등록부 — 거의 안 바뀝니다. 화면 자동완성이 씁니다 ─────────
        print("\n── 선박회사 등록부 (registry · 180일)")
        for name in ("에이치엠엠", "고려해운", "장금상선", "팬오션", "흥아라인",
                     "남성해운", "천경해운", "범주해운", "태영상선", "동영해운"):
            grab("SHIPPING_COMPANY_LIST", f"선사 · {name}",
                 lambda n=name: carrier_client.search_shipping_companies(n))

        print("\n── 항공사 등록부 (registry · 180일)")
        for name in ("대한항공", "아시아나항공", "제주항공", "에어인천", "페덱스",
                     "진에어", "티웨이항공", "에어부산", "유피에스", "디에이치엘"):
            grab("AIRLINE_LIST", f"항공사 · {name}",
                 lambda n=name: customs_extra_client.search_airlines(n))

        print("\n── 포워더 등록부 (registry · 180일)")
        for name in ("판토스", "현대글로비스", "씨제이대한통운", "롯데글로벌로지스", "한진",
                     "동방", "세방", "인터지스", "케이씨티시", "유수로지스틱스"):
            grab("FORWARDER_LIST", f"포워더 · {name}",
                 lambda n=name: customs_extra_client.search_forwarders(n))

        # ── 법령·요건 — 법이 바뀔 때만 바뀝니다 (law · 90일) ──────────────
        # 우리나라 수출 상위 품목 위주로 다섯 개만 고릅니다.
        # **실제로 있는 HSK 10자리여야 합니다.** 2026-09-27 에 세 개가 틀린 것을
        # 찾았습니다 — 3304990000 · 8507600000 · 8708299000 은 존재하지 않는
        # 부호였고, 기관이 "조회된 관세율 정보가 없습니다"로 답한 것은 맞는
        # 동작이었습니다. 우리는 그것을 "기관 미등재"로 적어 두고 있었습니다.
        # 관세청 품목표(data/mock/hsk_codes.json)에 대어 고쳤습니다.
        TOP_HS = ("3304991000",    # 기초화장용 제품류 — 대미 수출 1위 소비재
                  "8507602000",    # 리튬이온 축전지 (전기차용)
                  "3306100000",    # 치약
                  "1902301010",    # 라면
                  "8708290000",    # 자동차 차체부품 (기타)
                  # 2026-09-29 추가. 다섯 개 모두 품목표(2026-01-01 기준)에서
                  # 실재를 확인했습니다. 지어낸 부호를 넣으면 기관이 "조회된
                  # 정보가 없습니다"로 답하고, 우리는 그것을 "미등재"로 잘못
                  # 적어 두게 됩니다. (2026-09-27 에 실제로 그랬습니다)
                  "8542311000",    # 모노리식 집적회로 — 수출 1위 품목
                  "8517130000",    # 스마트폰
                  "4011101000",    # 래디알 타이어
                  "2710121000",    # 자동차 휘발유
                  "3902100000")    # 폴리프로필렌
        print("\n── 세관장확인대상 법령 (law · 90일)")
        for hs in TOP_HS:
            grab("REQUIREMENT_APPROVAL", f"수출요건 · {hs}",
                 lambda h=hs: customs_extra_client.export_requirement_laws(h))

        print("\n── HS 내비게이션 (law · 90일)")
        for hs in TOP_HS:
            grab("HS_NAVIGATION", f"HS 내비 · {hs}",
                 lambda h=hs: customs_extra_client.hs_navigation(h))

        print("\n── 간이정액 환급율 (law · 90일)")
        for hs in TOP_HS:
            grab("SIMPLE_REFUND_RATE", f"환급율 · {hs}",
                 lambda h=hs: customs_extra_client.refund_rate(h))

        print("\n── 수출이행기간 단축품목 (law · 90일)")
        for hs in TOP_HS:
            grab("EXPORT_PERIOD_SHORTENING_ITEM", f"단축품목 · {hs}",
                 lambda h=hs: customs_extra_client.shortened_loading_period(h))

        # ── 관세율 — 돈이 걸린 값이라 오래 두지 않습니다 ────────────────
        print("\n── 관세율")
        for hs in TOP_HS:
            grab("TARIFF_RATE", f"관세율 · {hs}",
                 lambda h=hs: customs_client.fetch_tariff_rates(h))

        # ── 공공데이터포털 — 월 단위 통계 (stats · 45일) ─────────────────
        print("\n── 공공데이터포털 (stats · 45일)")
        grab("DATA_GO_KR_SERVICE_KEY", "인천공항 화물기 시간표",
             carrier_client.fetch_icn_cargo_flights)
        grab("DATA_GO_KR_SERVICE_KEY", "항만 물동량",
             port_stats_client.port_traffic)
        grab("DATA_GO_KR_SERVICE_KEY", "컨테이너 처리실적",
             port_stats_client.container_throughput)
        for hs4 in ("3304", "8507", "8542", "8517", "8703", "7208", "2710"):
            grab("DATA_GO_KR_SERVICE_KEY", f"품목 수출입실적 · {hs4}",
                 lambda h=hs4: trade_stats_client.item_trade(h))

        # ── 그 밖의 필수 자료 ────────────────────────────────────────
        #
        # 위에서 안 받은 것 가운데 **없으면 화면이 비는** 것들입니다.
        # 부르는 창구가 달라 상한을 따로 씁니다. (2026-09-27)
        from app.collectors import ksure_client

        print("\n── 국가코드 (거의 안 바뀝니다)")
        grab("STATISTICS_CODE", "관세청 국가코드표",
             customs_client.fetch_country_codes)

        print("\n── 주요 항구 (stats · 45일)")
        grab("PORT_BUSIEST", "물동량 많은 항구", port_stats_client.busiest_ports)
        grab("PORT_BUSIEST", "권역별 물동량", port_stats_client.region_traffic)

        print("\n── 수출 상대국 (stats · 45일)")
        for hs4 in ("3304", "8507", "1902", "8542", "8517",
                    "8703", "7208", "4011", "2710", "3902"):
            grab("TRADE_TOP_DEST", f"어디로 나가나 · {hs4}",
                 lambda h=hs4: trade_stats_client.top_destinations(h))

        print("\n── 무역보험공사 결제정보 (나라별 대금 회수 위험)")
        for country in ("US", "CN", "JP", "VN", "DE",
                        "IN", "ID", "TR", "MX", "PL"):
            grab("KSURE", f"결제정보 · {country}",
                 lambda c=country: ksure_client.payment_info(c))

    cap = "없음" if MAX_PER_KEY is None else f"{MAX_PER_KEY}회"
    print(f"\n■ 키별 호출 횟수 (상한 {cap})")
    for key in sorted(used):
        over = "!" if MAX_PER_KEY is not None and used[key] > MAX_PER_KEY else " "
        print(f"   {over} {key:<36} {used[key]}회")

    print(f"\n■ 마무리 · 총 {sum(used.values())}회")
    print(f"   받아서 저장한 것 {len(saved)}건")
    print(f"   못 받은 것      {len(missed)}건   (예전에 받아 둔 값은 그대로 둡니다)")
    for row in missed[:10]:
        print(f"   △ {row}")
    # 상한이 없으면 넘길 수도 없습니다. None 과 크기를 견주면 TypeError 입니다.
    if MAX_PER_KEY is not None and any(n > MAX_PER_KEY for n in used.values()):
        print("\n★ 상한을 넘긴 키가 있습니다.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
