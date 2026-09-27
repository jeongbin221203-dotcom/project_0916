"""**API 키가 정지되었을 때** 화면이 사는지 전수로 확인합니다.

망이 끊긴 것과 다릅니다
  scripts/checks/cache_offline.py 는 소켓을 막습니다. 그러면 연결 오류가 나고
  base_client 의 회로차단기가 켜집니다.
  키 정지는 다릅니다 — 기관은 살아 있고 **인증을 거부**합니다. 그리고 키를
  아예 빼면 조회 함수가 기관을 부르기도 전에 "키 없음"으로 돌아섭니다.
  이 두 갈래에서 각각 저장분·내부 표로 넘어가는지 따로 봐야 합니다.

무엇을 재나 — 두 가지 상황
  ① 키를 비웠을 때   (해지·미발급·.env 를 잃음)
  ② 키가 거부될 때   (정지·만료·한도 초과 → 기관이 오류문을 줌)

무엇이 통과인가
  O  답했고 출처도 맞다        success=True · source 가 stored·cache·internal
  !  답은 하는데 출처가 틀리다  success=True 인데 source=api — 받은 척합니다
  X  못 답한다                success=False

  **X 가 곧 버그는 아닙니다.** 화물 추적처럼 지금 값을 물어야 하는 것은 키가
  없으면 답할 수 없는 것이 맞습니다. 다만 **세율·법령·등록부처럼 잘 안 바뀌는
  것**은 굳혀 두었어야 합니다. 그것이 X 로 남으면 고칠 곳입니다.

    python scripts/checks/keys_off.py
    python scripts/checks/keys_off.py --rejected   # ② 거부되는 상황만
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SAVED_OK = {"stored", "cache", "internal"}

# 키를 비우는 자리. config 의 이름 그대로입니다.
KEY_NAMES = ("UNIPASS_API_KEYS", "CUSTOMS_CONFIRM_API_KEY", "DATA_GO_KR_SERVICE_KEY",
             "OPEN_EXCHANGE_RATES_APP_ID", "AI_API_KEY", "EXCHANGE_API_KEY", "HMM_API_KEY")

# 기관이 키를 거부할 때 주는 모양. UNI-PASS 는 200 에 오류문을 실어 보냅니다.
REJECTED_XML = ("<trrtQryRtnVo><ntceInfo>등록되지 않은 인증키입니다. "
                "인증키를 확인하세요.</ntceInfo></trrtQryRtnVo>")

TOP_HS = ("3304991000", "8507602000", "3306100000", "1902301010", "8708290000")


def jobs_and_kinds():
    """(무엇, 이름표, 부르는 함수, 굳혀야 하는가) 목록.

    '굳혀야 하는가' 가 True 인 것은 잘 안 바뀌는 자료입니다. 키가 없어도
    답해야 합니다. False 는 지금 값을 물어야 하는 것이라 답하지 못해도 맞습니다.
    """

    from app.collectors import (carrier_client, container_client, customs_client,
                                customs_extra_client, exchange_client, ksure_client,
                                port_stats_client, trade_stats_client)

    rows = [
        ("환율", "고시환율", exchange_client.fetch_krw_rates, True),
        ("품목표", "HS 찾기 · 립스틱", lambda: customs_client.search_hs_codes("립스틱"), True),
        ("품목표", "국가코드표", customs_client.fetch_country_codes, True),
        ("등록부", "선사 · 에이치엠엠",
         lambda: carrier_client.search_shipping_companies("에이치엠엠"), True),
        ("등록부", "항공사 · 대한항공",
         lambda: customs_extra_client.search_airlines("대한항공"), True),
        ("등록부", "포워더 · 판토스",
         lambda: customs_extra_client.search_forwarders("판토스"), True),
    ]
    for hs in TOP_HS:
        rows.append(("세율", f"관세율 · {hs}",
                     lambda h=hs: customs_client.fetch_tariff_rates(h), True))
    for hs in TOP_HS:
        rows.append(("법령", f"수출요건 · {hs}",
                     lambda h=hs: customs_extra_client.export_requirement_laws(h), True))
    rows += [
        ("통계", "항만 물동량", port_stats_client.port_traffic, True),
        ("통계", "컨테이너 처리실적", port_stats_client.container_throughput, True),
        ("통계", "품목 수출입실적 · 3304", lambda: trade_stats_client.item_trade("3304"), True),
        ("통계", "수출 상대국 · 3304", lambda: trade_stats_client.top_destinations("3304"), True),
        ("보험", "결제정보 · US", lambda: ksure_client.payment_info("US"), True),
        # ── 아래는 **지금 값**을 물어야 하는 것들입니다. 못 답해도 맞습니다.
        ("지금 값", "화물 진행 조회",
         lambda: container_client.cargo_progress(cargo_no="12345678901"), False),
        ("지금 값", "인천공항 화물기", carrier_client.fetch_icn_cargo_flights, False),
    ]
    return rows


def measure(label: str, rejected: bool) -> list[tuple]:
    from app import create_app
    from app.collectors import base_client
    from config import Config

    app = create_app(Config)
    rows: list[tuple] = []
    with app.app_context():
        jobs = jobs_and_kinds()

        # **앱 설정을 직접 비웁니다.**
        #
        # base_client.get_config 를 갈아 끼우면 안 됩니다. 각 collector 가
        #   from app.collectors.base_client import get_config
        # 로 자기 이름을 따로 들고 있어, base_client 쪽만 바꿔도 닿지 않습니다.
        # 처음에 그렇게 했다가 **키가 살아 있는 채로 "전부 통과"가 찍혔습니다.**
        # get_config 는 current_app.config 를 읽으므로 여기를 비우면 전부 닿습니다.
        if not rejected:
            for name in KEY_NAMES:
                app.config[name] = {} if name == "UNIPASS_API_KEYS" else ""

        class Refused:
            """기관이 **200으로 답하면서 인증을 거부**하는 응답을 흉내냅니다."""

            status_code = 200
            text = REJECTED_XML
            content = REJECTED_XML.encode("utf-8")
            headers = {"content-type": "text/xml"}

            def json(self):
                # 공공데이터포털은 JSON 으로도 같은 말을 실어 보냅니다.
                return {"response": {"header": {
                    "resultCode": "30",
                    "resultMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}}}

            def raise_for_status(self):
                return None

        def refusing(method, url, **kwargs):
            return Refused()

        print("■ " + label + "\n")
        patches = []
        if rejected:
            # **httpx 층에서 흉내내야 합니다.**
            #
            # 처음에는 각 모듈의 request_text 를 갈아 끼웠습니다. 그러면
            # base_client 의 인증 거부 감지(auth_refused)를 통째로 건너뛰어,
            # 고쳐 놓은 것이 안 돌고도 "여전히 10건이 받은 척한다"고 찍혔습니다.
            # httpx.request 를 갈면 진짜 흐름이 그대로 지나갑니다. (2026-09-27)
            patches.append(patch("httpx.request", refusing))
            for one in patches:
                one.start()
        try:
            for group, name, call, must in jobs:
                try:
                    found = call() or {}
                except Exception as error:                  # noqa: BLE001
                    rows.append((group, name, "죽음 " + type(error).__name__, "X", must))
                    continue
                source = str(found.get("source", ""))
                if not found.get("success"):
                    mark = "X"
                elif source in SAVED_OK:
                    mark = "O"
                else:
                    mark = "!"
                rows.append((group, name, source or "(없음)", mark, must))
        finally:
            for one in patches:
                one.stop()
            base_client.clear_outages()
    return rows


def report(rows: list[tuple]) -> int:
    last = ""
    for group, name, source, mark, must in rows:
        if group != last:
            print("-- " + group)
            last = group
        tail = "" if must else "   (지금 값이라 못 답해도 맞습니다)"
        print(f"   {mark} {name:<26} {source}{tail}")

    should = [row for row in rows if row[4]]
    good = sum(1 for row in should if row[3] == "O")
    lied = [row for row in should if row[3] == "!"]
    gone = [row for row in should if row[3] == "X"]
    print(f"\n■ 굳혀야 하는 것 {len(should)}가지")
    print(f"   O 답했고 출처도 맞다        {good}")
    print(f"   ! 답은 하는데 출처가 틀리다  {len(lied)}")
    print(f"   X 못 답한다                {len(gone)}   <- 고칠 곳입니다")
    for _group, name, source, _mark, _must in lied:
        print(f"   ! {name} — {source}")
    for _group, name, source, _mark, _must in gone:
        print(f"   X {name} — {source}")
    return 1 if (lied or gone) else 0


def main() -> int:
    if "--rejected" in sys.argv:
        return report(measure("② 키가 거부될 때 (정지·만료·한도 초과)", True))
    bad = report(measure("① 키를 비웠을 때 (해지·미발급·.env 를 잃음)", False))
    print()
    bad += report(measure("② 키가 거부될 때 (정지·만료·한도 초과)", True))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
