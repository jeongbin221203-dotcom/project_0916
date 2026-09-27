"""받아 둔 자료로 **기관 없이도** 답하는지 전수로 확인합니다.

왜 이 확인이 필요한가
  prime_cache_capped.py 는 "저장했다"고 찍고 끝납니다. 그런데 저장만 하고
  꺼내 보지 않는 조회가 실제로 둘 있었습니다(간이정액 환급율·수출이행기간
  단축품목). 파일에 남겨 두고도 기관이 죽으면 빈손으로 답했습니다.
  그래서 **파일이 있느냐**가 아니라 **기관을 막아도 답이 나오느냐**를 봅니다.

어떻게 막나
  socket.socket 을 갈아 끼워 바깥으로 나가는 길을 끊습니다. 이러면 진짜
  기관이 멈춘 것과 같은 상황이 됩니다. API 키는 건드리지 않습니다 —
  키가 있는데도 저장분으로 답하는지 보아야 하기 때문입니다.

무엇을 가리나 — 세 갈래입니다
  O  답했고 출처도 맞다        success=True · source=stored(또는 internal)
  !  답은 하는데 출처가 틀리다  success=True · source=api — **망을 끊었는데
     "기관에서 받았다"고 적습니다.** 사용자에게 방금 받은 값인 척하게 됩니다.
     이 프로젝트의 원칙("받지 못하면 예시 값이라 적는다")을 어깁니다.
  X  못 답한다                success=False — 받아 둔 것이 없습니다.

  **source 만 보면 안 됩니다.** 실패도 fail(code, "api", ...) 로 source 를
  "api" 라고 적기 때문에, 답한 것과 실패한 것이 같은 글자로 보입니다.
  success 를 먼저 보고 그다음 source 를 봅니다.

    python scripts/checks/cache_offline.py
"""

from __future__ import annotations

import io
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 받아 둔 값을 뜻하는 출처. 관례가 둘입니다 — snapshot 은 "stored",
# file_cache 를 직접 쓰는 곳은 "cache" 라고 적습니다. 둘 다 통과입니다.
# "internal" 은 품목표처럼 원래 로컬인 것입니다.
SAVED_OK = {"stored", "cache", "internal"}


def cut_the_wire() -> None:
    """바깥으로 나가는 길을 끊습니다."""

    class Blocked(socket.socket):
        def connect(self, *args, **kwargs):              # noqa: ANN002, ANN003
            raise OSError("이 검사에서는 바깥으로 나갈 수 없습니다")

        def connect_ex(self, *args, **kwargs):           # noqa: ANN002, ANN003
            raise OSError("이 검사에서는 바깥으로 나갈 수 없습니다")

    socket.socket = Blocked                              # type: ignore[misc]


def build_jobs(app):
    """prime_cache_capped.py 가 받아 두겠다고 적은 것과 같은 목록입니다."""

    from app.collectors import (carrier_client, customs_client, customs_extra_client,
                                exchange_client, ksure_client, port_stats_client,
                                trade_stats_client)

    TOP_HS = ("3304990000", "8507600000", "3306100000", "1902301010", "8708299000")

    jobs: list[tuple[str, str, object]] = [
        ("환율", "오늘 고시환율", exchange_client.fetch_krw_rates),
        ("등록부", "선사 · 에이치엠엠",
         lambda: carrier_client.search_shipping_companies("에이치엠엠")),
        ("등록부", "선사 · 고려해운",
         lambda: carrier_client.search_shipping_companies("고려해운")),
        ("등록부", "항공사 · 대한항공",
         lambda: customs_extra_client.search_airlines("대한항공")),
        ("등록부", "포워더 · 판토스",
         lambda: customs_extra_client.search_forwarders("판토스")),
    ]
    for hs in TOP_HS:
        jobs += [
            ("법령·요건", f"수출요건 · {hs}",
             lambda h=hs: customs_extra_client.export_requirement_laws(h)),
            ("법령·요건", f"HS 내비 · {hs}",
             lambda h=hs: customs_extra_client.hs_navigation(h)),
            ("법령·요건", f"환급율 · {hs}",
             lambda h=hs: customs_extra_client.refund_rate(h)),
            ("법령·요건", f"단축품목 · {hs}",
             lambda h=hs: customs_extra_client.shortened_loading_period(h)),
            ("관세율", f"관세율 · {hs}",
             lambda h=hs: customs_client.fetch_tariff_rates(h)),
        ]
    jobs += [
        ("통계", "항만 물동량", port_stats_client.port_traffic),
        ("통계", "컨테이너 처리실적", port_stats_client.container_throughput),
        ("통계", "물동량 많은 항구", port_stats_client.busiest_ports),
        ("통계", "권역별 물동량", port_stats_client.region_traffic),
        ("통계", "인천공항 화물기", carrier_client.fetch_icn_cargo_flights),
        ("통계", "국가코드표", customs_client.fetch_country_codes),
    ]
    for hs4 in ("3304", "8507", "1902"):
        jobs += [("통계", f"품목 수출입실적 · {hs4}",
                  lambda h=hs4: trade_stats_client.item_trade(h)),
                 ("통계", f"수출 상대국 · {hs4}",
                  lambda h=hs4: trade_stats_client.top_destinations(h))]
    for country in ("US", "CN", "JP", "VN", "DE"):
        jobs += [("보험", f"결제정보 · {country}",
                  lambda c=country: ksure_client.payment_info(c))]
    return jobs


def main() -> int:
    from app import create_app
    from config import Config

    app = create_app(Config)
    rows: list[tuple[str, str, str, str]] = []

    with app.app_context():
        jobs = build_jobs(app)
        cut_the_wire()
        print("■ 바깥으로 나가는 길을 끊고 물어봅니다.\n")

        for group, label, call in jobs:
            try:
                found = call() or {}
            except Exception as error:                   # noqa: BLE001
                rows.append((group, label, f"죽음 {type(error).__name__}", "X"))
                continue
            source = str(found.get("source", ""))
            if not found.get("success"):
                mark = "X"
            elif source in SAVED_OK:
                mark = "O"
            else:
                mark = "!"           # 답은 했는데 출처를 틀리게 적었습니다
            rows.append((group, label, source or "(없음)", mark))

    last = ""
    for group, label, source, mark in rows:
        if group != last:
            print(f"-- {group}")
            last = group
        print(f"   {mark} {label:<28} {source}")

    tally = {mark: [label for _, label, _, m in rows if m == mark] for mark in "O!X"}
    print(f"\n■ 모두 {len(rows)}가지")
    print(f"   O 답했고 출처도 맞다        {len(tally['O'])}")
    print(f"   ! 답은 하는데 출처가 틀리다  {len(tally['!'])}   <- 'api'라고 적습니다")
    print(f"   X 못 답한다                {len(tally['X'])}")

    if tally["!"]:
        print("\n■ 망을 끊었는데 'api'라고 적는 것 — 받은 척합니다")
        for label in tally["!"]:
            print(f"   ! {label}")
    if tally["X"]:
        print("\n■ 기관 없이는 답하지 못하는 것 — 받아 둔 것이 없습니다")
        for label in tally["X"]:
            print(f"   X {label}")
    return 1 if (tally["!"] or tally["X"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
