"""기관 **한 곳만** 막혔을 때 화면이 사는지 봅니다.

앞선 두 검사와 다릅니다
  cache_offline.py  바깥을 **전부** 막습니다. 인터넷이 없는 상황입니다.
  keys_off.py       키가 없거나 거부됩니다. 기관은 살아 있습니다.
  이 검사           **그 기관만** 닿지 않습니다. 나머지는 멀쩡합니다.

왜 따로 봐야 하나
  실제로 자주 일어나는 일은 이쪽입니다 — 관세청 정기점검, 방화벽, DNS,
  유니패스만 느려짐. 그때 관세청에 매인 것은 저장분으로 넘어가야 하고,
  **관세청과 무관한 것은 그대로 잘 돼야 합니다.** 한 곳이 막혔다고 화면이
  통째로 멈추면 안 됩니다.

  그리고 base_client 의 회로차단기가 그 기관만 골라 건너뛰는지도 여기서 봅니다.
  (닿지 않은 기관은 60초 동안 부르지 않습니다)

    python scripts/checks/host_down.py                       # 유니패스
    python scripts/checks/host_down.py --host apis.data.go.kr
    python scripts/checks/host_down.py --all                 # 주요 기관을 하나씩
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SAVED_OK = {"stored", "cache", "internal"}
# 한 번에 하나씩 막아 보는 기관들.
HOSTS = ("unipass.customs.go.kr", "apis.data.go.kr", "openapi.data.go.kr")

TOP_HS = ("3304991000", "8507602000", "3306100000", "1902301010", "8708290000")


def jobs():
    """(무엇, 이름표, 부르는 함수, 그 기관에 매여 있는가) 목록.

    '매여 있는가' 가 False 인 것은 막은 기관과 상관없는 조회입니다. 그것까지
    같이 죽으면 **한 곳이 막혔는데 화면이 통째로 멈추는** 것이라 문제입니다.
    """

    from app.collectors import (carrier_client, customs_client, customs_extra_client,
                                exchange_client, ksure_client, port_stats_client,
                                trade_stats_client)

    rows = [
        ("관세청", "고시환율", exchange_client.fetch_krw_rates, "unipass"),
        ("관세청", "HS 찾기 · 립스틱", lambda: customs_client.search_hs_codes("립스틱"), "unipass"),
        ("관세청", "국가코드표", customs_client.fetch_country_codes, "unipass"),
        ("관세청", "선사 · 에이치엠엠",
         lambda: carrier_client.search_shipping_companies("에이치엠엠"), "unipass"),
        ("관세청", "항공사 · 대한항공",
         lambda: customs_extra_client.search_airlines("대한항공"), "unipass"),
        ("관세청", "포워더 · 판토스",
         lambda: customs_extra_client.search_forwarders("판토스"), "unipass"),
    ]
    for hs in TOP_HS:
        rows.append(("관세청", f"관세율 · {hs}",
                     lambda h=hs: customs_client.fetch_tariff_rates(h), "unipass"))
    rows += [
        ("포털", "수출요건 · 3306100000",
         lambda: customs_extra_client.export_requirement_laws("3306100000"), "data.go.kr"),
        ("포털", "항만 물동량", port_stats_client.port_traffic, "data.go.kr"),
        ("포털", "컨테이너 처리실적", port_stats_client.container_throughput, "data.go.kr"),
        ("포털", "품목 수출입실적 · 3304",
         lambda: trade_stats_client.item_trade("3304"), "data.go.kr"),
        ("포털", "수출 상대국 · 3304",
         lambda: trade_stats_client.top_destinations("3304"), "data.go.kr"),
        ("포털", "결제정보 · US", lambda: ksure_client.payment_info("US"), "data.go.kr"),
        # ── 바깥을 아예 부르지 않는 것들. 어느 기관이 막혀도 멀쩡해야 합니다.
        ("로컬", "품목표 찾기 (표준품명)", _standard_lookup, "none"),
        ("로컬", "통화 목록", _currency_options, "none"),
    ]
    return rows


def _standard_lookup():
    from app.collectors import hsk_catalog

    rows = hsk_catalog.search("신선마늘(육쪽)") or []
    return {"success": bool(rows), "source": "internal", "data": rows,
            "message": "" if rows else "품목표에서 못 찾았습니다."}


def _currency_options():
    from app.collectors import exchange_client

    rows = exchange_client.currency_options()
    return {"success": bool(rows), "source": "internal", "data": rows, "message": ""}


def measure(host: str) -> list[tuple]:
    import httpx

    from app import create_app
    from app.collectors import base_client
    from config import Config

    app = create_app(Config)
    real = httpx.request
    blocked = {"n": 0}
    stubbed = {"n": 0}
    live_others = "--live-others" in sys.argv

    class Blank:
        """닿기는 했지만 줄 것이 없는 응답. (기관을 실제로 부르지 않습니다)"""

        status_code = 200
        text = "<result/>"
        content = b"<result/>"
        headers = {"content-type": "text/xml"}

        def json(self):
            return {}

        def raise_for_status(self):
            return None

    def maybe(method, url, **kwargs):
        # 막은 기관만 끊습니다.
        if host in str(url):
            blocked["n"] += 1
            raise httpx.ConnectError(f"{host} 에 닿지 않습니다 (검사)")
        # **나머지 기관은 기본으로 부르지 않습니다.**
        #
        # 이 검사가 보려는 것은 "막은 기관과 무관한 조회가 같이 죽지 않는가"
        # 입니다. 그걸 보는 데 실제 호출이 필요하지 않습니다. 그런데 처음에는
        # 그대로 내보내서, --all 로 한 번 돌릴 때마다 기관 호출을 수십 회
        # 썼습니다. 기관 서버가 불안정하고 키마다 한도가 있습니다.
        #
        # 그래서 기본은 "닿았지만 줄 것이 없다"로 흉내냅니다. 실패가 아니라
        # 응답이므로 회로차단기도 켜지지 않고, 각 조회는 저장분·내부 표로
        # 넘어가거나 빈손으로 답합니다. 둘 다 "같이 죽었다"와 구별됩니다.
        # 진짜로 불러 보려면 --live-others 를 주세요. (2026-09-27)
        if not live_others:
            stubbed["n"] += 1
            return Blank()
        return real(method, url, **kwargs)

    rows: list[tuple] = []
    with app.app_context():
        work = jobs()
        base_client.clear_outages()
        print(f"■ {host} 만 막았습니다. 나머지 기관은 그대로 씁니다.\n")
        with patch("httpx.request", maybe):
            for group, name, call, tied in work:
                try:
                    found = call() or {}
                except Exception as error:                  # noqa: BLE001
                    rows.append((group, name, "죽음 " + type(error).__name__, "X", tied))
                    continue
                source = str(found.get("source", ""))
                if not found.get("success"):
                    mark = "X"
                elif source in SAVED_OK:
                    mark = "O"
                else:
                    mark = "A"          # 기관에서 지금 받았습니다 (막은 곳이 아님)
                rows.append((group, name, source or "(없음)", mark, tied))
        base_client.clear_outages()
    how = "실제로 불렀습니다" if live_others else "부르지 않고 흉내냈습니다"
    print(f"   (막아서 끊은 호출 {blocked['n']}회 · 나머지 기관 {stubbed['n']}회는 {how})\n")
    return rows


def report(host: str, rows: list[tuple]) -> int:
    last = ""
    for group, name, source, mark, _tied in rows:
        if group != last:
            print("-- " + group)
            last = group
        print(f"   {mark} {name:<26} {source}")

    key = "unipass" if "unipass" in host else ("data.go.kr" if "data.go.kr" in host else host)
    tied = [r for r in rows if r[4] == key]
    free = [r for r in rows if r[4] != key]
    tied_ok = sum(1 for r in tied if r[3] == "O")
    tied_bad = [r for r in tied if r[3] == "X"]
    free_bad = [r for r in free if r[3] == "X"]

    print(f"\n■ {host} 에 매인 것 {len(tied)}가지")
    print(f"   O 저장분·내부 표로 답함   {tied_ok}")
    print(f"   X 못 답한다             {len(tied_bad)}")
    for _g, name, source, _m, _t in tied_bad:
        print(f"      X {name} — {source}")
    print(f"■ 그 기관과 무관한 것 {len(free)}가지")
    print(f"   X 같이 죽은 것          {len(free_bad)}   <- 있으면 안 됩니다")
    for _g, name, source, _m, _t in free_bad:
        print(f"      X {name} — {source}")
    # 무관한 것이 죽으면 확실한 버그입니다. 매인 것은 굳힐 자료가 없을 수 있습니다.
    return 1 if free_bad else 0


def main() -> int:
    hosts = HOSTS if "--all" in sys.argv else None
    if not hosts:
        picked = "unipass.customs.go.kr"
        for index, arg in enumerate(sys.argv):
            if arg == "--host" and index + 1 < len(sys.argv):
                picked = sys.argv[index + 1]
        hosts = (picked,)
    bad = 0
    for host in hosts:
        bad += report(host, measure(host))
        print()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
