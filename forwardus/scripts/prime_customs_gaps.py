"""관세청 자료 가운데 **아직 못 받은 것만** 받아 둡니다. 키당 최대 5회.

왜 따로 만드나
  prime_cache_capped.py 는 목록을 처음부터 끝까지 다시 돕니다. 이미 저장된
  것도 또 부르므로, 5회 상한이 이미 있는 것에 다 쓰여 정작 빈 칸은 못 채웁니다.
  실제로 그렇게 됐습니다 — 지시한 25건 가운데 법령·세율 계열 20건이 비어
  있었습니다. (scripts/checks/cache_offline.py 가 찾았습니다)

  그래서 이 스크립트는 **먼저 기관을 막고 물어봐서** 저장분으로 답하는 것을
  가려내고, 답하지 못하는 것만 실제로 부릅니다.

무엇을 지키나
  - 키 하나당 5회. 코드로 세어서 넘기면 아예 안 보냅니다. (사용자 지시)
  - 받은 것만 남깁니다. 실패하면 예전 값을 건드리지 않습니다.
  - source 가 "api" 인 답만 저장됩니다 (snapshot.remember 가 그렇게 합니다).
  - 키 값을 화면에 찍지 않습니다.
  - 호출 사이를 띄웁니다. 기관 서버가 불안정합니다.

    python scripts/prime_customs_gaps.py --dry     # 무엇을 부를지만 보기
    python scripts/prime_customs_gaps.py
"""

from __future__ import annotations

import io
import socket
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MAX_PER_KEY = 5
PAUSE = 1.5
SAVED_OK = {"stored", "cache", "internal"}

# 우리나라 수출 상위 품목. prime_cache_capped.py 와 같은 목록입니다.
# **실제로 있는 HSK 10자리여야 합니다.** 2026-09-27 에 세 개가 틀린 것을 찾았습니다
# — 3304990000 · 8507600000 · 8708299000 은 존재하지 않는 부호였습니다. 기관이
# "조회된 관세율 정보가 없습니다"로 답한 것이 맞았고, 우리가 그것을 "기관 미등재"로
# 적어 두고 있었습니다. 관세청 품목표에 대어 고쳤습니다.
TOP_HS = ("3304991000",    # 기초화장용 제품류 — 대미 수출 1위 소비재
          "8507602000",    # 리튬이온 축전지 (전기차용)
          "3306100000",    # 치약
          "1902301010",    # 라면
          "8708290000")    # 자동차 차체부품 (기타)

used: dict[str, int] = defaultdict(int)


def build_jobs():
    """(키 이름, 이름표, 부르는 함수) 목록. 관세청 것만 담습니다."""

    from app.collectors import customs_client, customs_extra_client

    jobs = [("STATISTICS_CODE", "국가코드표", customs_client.fetch_country_codes)]
    for hs in TOP_HS:
        jobs += [
            ("REQUIREMENT_APPROVAL", f"수출요건 · {hs}",
             lambda h=hs: customs_extra_client.export_requirement_laws(h)),
            ("HS_NAVIGATION", f"HS 내비 · {hs}",
             lambda h=hs: customs_extra_client.hs_navigation(h)),
            ("SIMPLE_REFUND_RATE", f"환급율 · {hs}",
             lambda h=hs: customs_extra_client.refund_rate(h)),
            ("EXPORT_PERIOD_SHORTENING_ITEM", f"단축품목 · {hs}",
             lambda h=hs: customs_extra_client.shortened_loading_period(h)),
            ("TARIFF_RATE", f"관세율 · {hs}",
             lambda h=hs: customs_client.fetch_tariff_rates(h)),
        ]
    return jobs


def find_gaps(jobs) -> list:
    """기관을 막고 물어봐서, 저장분으로 답하지 못하는 것만 고릅니다."""

    real = socket.socket

    class Blocked(socket.socket):
        def connect(self, *args, **kwargs):              # noqa: ANN002, ANN003
            raise OSError("빈 칸을 가리는 중입니다")

        def connect_ex(self, *args, **kwargs):           # noqa: ANN002, ANN003
            raise OSError("빈 칸을 가리는 중입니다")

    socket.socket = Blocked                              # type: ignore[misc]
    gaps, have = [], []
    try:
        for key, label, call in jobs:
            try:
                found = call() or {}
            except Exception:                            # noqa: BLE001
                gaps.append((key, label, call))
                continue
            if found.get("success") and str(found.get("source", "")) in SAVED_OK:
                have.append(label)
            else:
                gaps.append((key, label, call))
    finally:
        socket.socket = real                             # type: ignore[misc]
        # **차단기를 반드시 끕니다.**
        #
        # 위에서 소켓을 막았으므로 조회마다 API_CONNECTION_ERROR 가 났고,
        # base_client 가 "이 기관은 닿지 않는다"고 60초간 기억했습니다.
        # 그 기억을 지우지 않으면 뒤이은 **진짜 호출이 로컬에서 거부**됩니다.
        # 처음 돌렸을 때 23건이 전부 그렇게 죽었습니다. 요청은 한 건도
        # 나가지 않았으니 기관 쪽 상한은 줄지 않았지만, 아무것도 못 받았습니다.
        # (2026-09-27)
        from app.collectors.base_client import clear_outages
        clear_outages()
    return gaps, have


def main() -> int:
    from app import create_app
    from config import Config

    app = create_app(Config)
    with app.app_context():
        jobs = build_jobs()
        gaps, have = find_gaps(jobs)

        print(f"■ 관세청 {len(jobs)}가지 · 이미 저장됨 {len(have)} · 채울 것 {len(gaps)}\n")
        for label in have:
            print(f"   - {label:<26} 이미 저장분으로 답합니다 — 부르지 않습니다")

        # 키별로 몇 번 부를지 먼저 보여 줍니다. 상한을 넘는 것은 다음 회차로 미룹니다.
        plan: dict[str, list] = defaultdict(list)
        for key, label, call in gaps:
            plan[key].append((label, call))
        print(f"\n■ 부를 계획 (키당 최대 {MAX_PER_KEY}회)")
        for key in sorted(plan):
            rows = plan[key]
            over = max(0, len(rows) - MAX_PER_KEY)
            print(f"   {key:<32} {min(len(rows), MAX_PER_KEY)}회"
                  + (f"  (+{over}건은 다음 회차로 미룸)" if over else ""))
        if "--dry" in sys.argv:
            return 0

        print()
        saved, missed, skipped, empty = [], [], [], []
        for key in sorted(plan):
            for label, call in plan[key]:
                if used[key] >= MAX_PER_KEY:
                    skipped.append(label)
                    print(f"   . {label:<26} 상한({MAX_PER_KEY}회) 도달 — 보내지 않음")
                    continue
                used[key] += 1
                time.sleep(PAUSE)
                try:
                    found = call() or {}
                except Exception as error:               # noqa: BLE001
                    missed.append(f"{label}: {type(error).__name__}")
                    print(f"   ^ {label:<26} 죽음 {type(error).__name__}")
                    continue
                source = str(found.get("source", ""))
                data = found.get("data")
                size = len(data) if hasattr(data, "__len__") else "-"
                if found.get("success") and source == "api" and data not in (None, [], {}, ""):
                    saved.append(label)
                    print(f"   O {label:<26} 받아서 저장 · 항목 {size}")
                elif found.get("success") and source == "api":
                    # 기관이 답했는데 내용이 비었습니다. snapshot.remember 는
                    # 빈 것을 저장하지 않습니다 — 옳은 동작입니다. 빈 껍데기를
                    # 저장해 두면 다음에 "받아 둔 값이 있다"며 빈 답을 내놓습니다.
                    #
                    # **이것은 "규제가 없다"가 아닙니다.** 이 조회에 걸리는 항목이
                    # 없다는 뜻이고, 품목분류가 틀렸을 수도 있습니다.
                    empty.append(label)
                    print(f"   . {label:<26} 기관이 답했으나 내용 없음 — 저장할 것이 없습니다")
                elif found.get("success"):
                    print(f"   . {label:<26} 실데이터 아님(source={source}) — 저장 안 함")
                else:
                    message = str(found.get("message", ""))[:46]
                    missed.append(f"{label}: {message}")
                    print(f"   ^ {label:<26} 못 받음 — {message}")

    print(f"\n■ 키별 호출 횟수 (상한 {MAX_PER_KEY})")
    for key in sorted(used):
        mark = "!" if used[key] > MAX_PER_KEY else " "
        print(f"   {mark} {key:<32} {used[key]}회")

    print(f"\n■ 마무리 · 총 {sum(used.values())}회")
    print(f"   받아서 저장 {len(saved)}건 · 기관에 자료 없음 {len(empty)}건 · "
          f"못 받음 {len(missed)}건 · 상한으로 미룸 {len(skipped)}건")
    if empty:
        print("
■ 기관이 답했으나 내용이 빈 것 — 저장할 것이 없습니다")
        print("   ('규제 없음'이 아닙니다. 이 조회에 걸리는 항목이 없다는 뜻입니다)")
        for label in empty:
            print(f"   . {label}")
    for row in missed:
        print(f"   ^ {row}")
    if any(count > MAX_PER_KEY for count in used.values()):
        print("\n★ 상한을 넘긴 키가 있습니다.")
        return 1
    print("\n다음: python scripts/checks/cache_offline.py 로 꺼내 쓸 수 있는지 확인하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
