"""받아 둔 API 키가 **실제로 응답하는지** 한 번씩 두드려 봅니다.

왜 필요한가
  키를 .env에 넣어 두어도 쓸 수 있는지는 다른 문제입니다. 신청은 했는데 승인이 안
  났거나, 서비스마다 키가 달라 엉뚱한 키를 넣어 두었거나, 기관이 주소를 바꾼 경우가
  있습니다. 그런 것은 화면에서 조회가 안 될 때에야 드러납니다.

무엇을 지키나
  - **키 값을 찍지 않습니다.** 서비스 이름과 결과(OK·인증 실패·응답 없음)만 봅니다.
  - 바깥 기관을 부르므로 한 번에 다 부르지 않고 차례로, 짧은 제한시간으로 봅니다.
  - 기관이 잠깐 느린 것과 키가 잘못된 것을 가려 적습니다.

쓰는 법
    python scripts/check_api_keys.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app                      # noqa: E402
from config import Config                       # noqa: E402

OK = "됩니다"
FALLBACK = "대체 데이터"
AUTH = "키 문제"
DOWN = "기관 응답 없음"
NONE = "키 없음"

# 수집기는 기관이 막히면 내부 표나 예시 데이터로 내려갑니다. 그래야 화면이 멈추지
# 않기 때문입니다. 그런데 그때도 success는 True입니다. 그것을 "키가 됩니다"로
# 세면 **가짜 데이터를 보면서 잘 되고 있다고 믿게 됩니다.** 출처를 함께 봅니다.
REAL_SOURCES = {"api"}


def _mark(result: dict) -> str:
    if result.get("success"):
        source = str(result.get("source") or "")
        return OK if source in REAL_SOURCES else f"{FALLBACK}({source or '출처 없음'})"
    code = str(result.get("error_code") or "")
    message = str(result.get("message") or "")
    if "AUTH" in code or "인증" in message or "키" in message:
        return AUTH if "없습니다" not in message else NONE
    if "TIMEOUT" in code or "닿지" in message or "연결" in message:
        return DOWN
    return f"{code or '확인 필요'}"


def main() -> int:
    # 윈도 기본 콘솔은 cp949라 한글 대시(—)에서 죽습니다. 다 돌려 놓고
    # 마지막 출력에서 멈추면 아무것도 못 봅니다. (2026-09-26)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    app = create_app(Config)
    with app.app_context():
        from app.collectors import (carrier_client, customs_client, customs_extra_client,
                                    exchange_client, ksure_client, port_stats_client,
                                    trade_stats_client)

        checks = [
            # (묶음, 보여 줄 이름, 부르는 함수, 인자)
            ("UNI-PASS", "선사 목록", carrier_client.search_shipping_companies, ("에이치엠엠",)),
            ("UNI-PASS", "항공사 목록", customs_extra_client.search_airlines, ("대한항공",)),
            ("UNI-PASS", "포워더 목록", customs_extra_client.search_forwarders, ("판토스",)),
            ("UNI-PASS", "HS부호 검색", customs_client.search_hs_codes, ("치약",)),
            ("UNI-PASS", "통관고유부호", customs_extra_client.clearance_code, ()),
            ("UNI-PASS", "간이정액환급률", customs_extra_client.refund_rate, ("3306100000",)),
            ("UNI-PASS", "수출이행기간 단축품목", customs_extra_client.shortened_loading_period,
             ("3306100000",)),
            ("UNI-PASS", "HS 내비게이션", customs_extra_client.hs_navigation, ("3306100000",)),
            ("공공데이터포털", "세관장확인대상", customs_extra_client.export_requirement_laws,
             ("3306100000",)),
            ("공공데이터포털", "품목별 수출입실적", trade_stats_client.item_trade, ("3306",)),
            ("공공데이터포털", "국가별 수출 상위", trade_stats_client.top_destinations, ("3306",)),
            ("공공데이터포털", "항만 물동량", port_stats_client.port_traffic, ()),
            ("공공데이터포털", "컨테이너 처리실적", port_stats_client.container_throughput, ()),
            ("공공데이터포털", "인천공항 화물기", carrier_client.fetch_icn_cargo_flights, ()),
            ("공공데이터포털", "무역보험공사 결제정보", ksure_client.payment_info, ("US",)),
            ("한국수출입은행", "환율", exchange_client.fetch_krw_rates, ()),
            ("UNI-PASS", "관세환율", exchange_client.fetch_unipass_rates, ()),
        ]

        # 받아 두었지만 config.py가 이름조차 읽지 않는 키. 키가 살아 있어도
        # 코드에 닿지 않으므로 화면에서는 쓰이지 않습니다. 여기서 함께 알려 줍니다.
        unused = ("AVIATIONSTACK_API_KEY", "CUSTOMS_TRADE_STATS_SERVICE_KEY",
                  "MOF_VESSEL_SCHEDULE_SERVICE_KEY", "OPENWEATHER_API_KEY",
                  "KAKAO_REST_API_KEY")

        print(f"{'묶음':<12}{'서비스':<24} 결과")
        print("-" * 62)
        counts = {OK: 0, AUTH: 0, DOWN: 0, NONE: 0}
        fallbacks = []
        for group, label, call, args in checks:
            try:
                result = call(*args)
            except Exception as error:                      # noqa: BLE001
                print(f"{group:<12}{label:<24} 부르다 멈춤: {type(error).__name__}")
                continue
            mark = _mark(result if isinstance(result, dict) else {"success": True})
            counts[mark] = counts.get(mark, 0) + 1
            if mark.startswith(FALLBACK):
                fallbacks.append(label)
            note = ""
            if mark != OK and isinstance(result, dict) and result.get("message"):
                note = f"  ({str(result['message'])[:46]})"
            print(f"{group:<12}{label:<24} {mark}{note}")

        print("-" * 62)
        print(f"됩니다 {counts.get(OK, 0)} · 대체 데이터 {len(fallbacks)} · "
              f"키 문제 {counts.get(AUTH, 0)} · 기관 응답 없음 {counts.get(DOWN, 0)} · "
              f"키 없음 {counts.get(NONE, 0)}")
        print("\n※ '기관 응답 없음'은 키가 아니라 그쪽 서버 문제입니다. 잠시 뒤 다시 해 보세요.")
        if fallbacks:
            print(f"※ '대체 데이터'는 화면은 돌아가지만 **그 기관의 실제 값이 아닙니다.**\n"
                  f"   {', '.join(fallbacks)} — 이 값으로 고객에게 답하면 안 됩니다.")

        import os

        idle = [name for name in unused if os.getenv(name, "").strip()]
        if idle:
            print(f"\n※ 받아 두었지만 코드가 읽지 않는 키 {len(idle)}개 — 쓰려면 config.py에 "
                  f"같은 이름으로 선언해야 합니다.\n   {', '.join(idle)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
