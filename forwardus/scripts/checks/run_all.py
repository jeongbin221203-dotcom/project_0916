"""scripts/checks 의 검사를 **전부** 돌리고 한 장으로 정리합니다.

왜 있나
  검사가 39개까지 늘었습니다. 하나씩 돌리면 무엇을 돌렸고 무엇을 안 돌렸는지
  알 수 없습니다. 그리고 한동안 안 돌린 검사가 조용히 깨져 있어도 모릅니다.

바깥을 부르지 않습니다
  대부분은 tests/_fuzz_app.build_app() (키가 전부 비어 있는 설정)을 씁니다.
  키를 쓰는 셋(cache_offline · keys_off · host_down)은 스스로 망을 끊거나 키를
  비우거나 흉내냅니다. 그래서 이 묶음은 기관을 부르지 않습니다.
  (실키 검사는 scripts/check_api_keys_live.py 로 따로, 키당 5회 상한으로 합니다)

**다른 검사 묶음과 겹치면 시작하지 않습니다.** 아래 already_running() 을 보세요.

    python scripts/checks/run_all.py
    python scripts/checks/run_all.py --quick     # 오래 걸리는 것은 건너뜁니다
    python scripts/checks/run_all.py --only m26  # 이름에 m26 이 든 것만
    python scripts/checks/run_all.py --force     # 겹쳐도 돌립니다
"""

from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 한 검사에 이만큼까지 기다립니다. 넘으면 끊고 '시간 초과'로 적습니다.
TIMEOUT = 900
# --quick 에서 건너뛸 것들. 수만 번 돌려 몇 분씩 걸립니다.
SLOW = {"m9_conformance", "m10_docs", "m15_combos", "m16_business_no",
        "m22_container", "m24_bl", "m26_all", "m26_biz_personal", "m7_cross"}

# 검사 묶음이 돌고 있다는 표시. verify_forever.py 도 이 파일을 씁니다.
LOCK = ROOT / "data" / "cache" / "checks_running.lock"
# 이만큼 지난 자물쇠는 죽은 것으로 봅니다. (컴퓨터가 꺼졌거나 강제로 끊긴 경우)
LOCK_STALE = 6 * 3600


def already_running() -> str:
    """다른 검사 묶음이 돌고 있으면 그 사실을 한 줄로 돌려줍니다.

    왜 막나
      2026-09-27 에 이 묶음과 verify_forever.py 를 동시에 돌렸습니다. 둘이 같은
      스크립트(m26_biz_personal 처럼 몇 분씩 걸리는 것)를 같은 시각에 띄워,
      하나가 **출력도 없이** 죽었습니다. 교차 검증은 그것을 "처음 보는 실패"로
      적었습니다. 단독으로 다시 돌리니 100% 통과했습니다 — 제품에는 아무
      문제가 없었고, 검사 설정이 만든 잡음이었습니다.

      잡음을 한 번 기록하면 그 뒤로 진짜 실패와 구별할 수 없게 됩니다.
      그래서 겹치면 아예 시작하지 않습니다.
    """

    try:
        if not LOCK.exists():
            return ""
        age = time.time() - LOCK.stat().st_mtime
        who = LOCK.read_text(encoding="utf-8").strip() or "다른 묶음"
    except OSError:
        return ""
    if age > LOCK_STALE:
        return ""
    return f"{who} · 약 {age / 60:.0f}분 전에 시작"


def hold(who: str) -> None:
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(who, encoding="utf-8")
    except OSError:
        pass                    # 자물쇠를 못 걸어도 검사는 돌려야 합니다.


def release() -> None:
    try:
        LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def scripts(only: str) -> list[Path]:
    found = sorted(p for p in HERE.glob("*.py") if p.name != Path(__file__).name)
    return [p for p in found if not only or only in p.stem]


def main() -> int:
    busy = already_running()
    if busy and "--force" not in sys.argv:
        print("■ 다른 검사 묶음이 돌고 있어 시작하지 않습니다.")
        print(f"   {busy}")
        print("   같은 스크립트를 동시에 돌리면 출력 없이 죽어 **없는 실패**가 기록됩니다.")
        print("   그래도 돌리려면 --force 를 주세요.")
        return 2

    quick = "--quick" in sys.argv
    only = ""
    for index, arg in enumerate(sys.argv):
        if arg == "--only" and index + 1 < len(sys.argv):
            only = sys.argv[index + 1]

    jobs = scripts(only)
    if quick:
        jobs = [p for p in jobs if p.stem not in SLOW]
    print(f"■ 검사 {len(jobs)}개를 돌립니다"
          + (" (오래 걸리는 것 제외)" if quick else "")
          + (f" · 이름에 '{only}' 가 든 것만" if only else "") + "\n")

    hold("scripts/checks/run_all.py")
    rows: list[tuple[str, int, float, str]] = []
    try:
        for path in jobs:
            started = time.monotonic()
            try:
                done = subprocess.run([sys.executable, str(path.relative_to(ROOT))],
                                      cwd=ROOT, capture_output=True, timeout=TIMEOUT)
                code = done.returncode
                text = (done.stdout or b"").decode("utf-8", "replace").strip()
                if not text:
                    text = (done.stderr or b"").decode("utf-8", "replace").strip()
            except subprocess.TimeoutExpired:
                code, text = -1, f"{TIMEOUT}초를 넘겨 끊었습니다"
            spent = time.monotonic() - started

            # 마지막 줄 가운데 뜻이 있는 것을 한 줄 골라 적습니다.
            tail = ""
            for line in reversed(text.splitlines()):
                line = line.strip()
                if line and not line.startswith(("·", "-", "=")):
                    tail = line[:88]
                    break
            mark = "O" if code == 0 else ("T" if code == -1 else "X")
            rows.append((path.stem, code, spent, tail))
            print(f"   {mark} {path.stem:<24} {spent:6.1f}초  {tail}")
            hold("scripts/checks/run_all.py")      # 자물쇠 시각을 갱신합니다
    finally:
        release()

    good = [row for row in rows if row[1] == 0]
    bad = [row for row in rows if row[1] != 0]
    total = sum(row[2] for row in rows)
    print(f"\n■ 마무리 · {len(rows)}개 · {total / 60:.1f}분")
    print(f"   O 통과   {len(good)}")
    print(f"   X 실패   {len(bad)}")
    if bad:
        print("\n■ 통과하지 못한 것")
        for name, code, spent, tail in bad:
            why = "시간 초과" if code == -1 else f"종료코드 {code}"
            print(f"   X {name:<24} {why}  {tail}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
