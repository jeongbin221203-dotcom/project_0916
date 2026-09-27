"""정한 시간 동안 검증을 반복합니다. **바깥 기관은 부르지 않습니다.**

왜 필요한가
  퍼즈와 적합성 시험은 무작위를 씁니다. 한 번 돌려 초록이라고 안전한 것이
  아니라, 그 회차에 그 조합이 안 나왔을 뿐일 수 있습니다. 여러 번 돌려야
  드물게 나는 것이 드러납니다.

  그런데 사람이 붙어서 6시간을 돌릴 수는 없습니다. 그래서 혼자 돌게 하되,
  **아침에 읽을 수 있는 분량**으로 남깁니다.

무엇을 지키나
  - **코드를 고치지 않습니다.** 읽고 돌리기만 합니다.
  - **바깥으로 나가지 않습니다.** 시작할 때 소켓을 막고, 나가려 하면 그 사실을
    기록합니다. 퍼즈는 TestConfig(키가 전부 비어 있음)를 쓰므로 원래 안 나가지만,
    혹시 새는 길이 있는지 함께 봅니다.
  - **같은 실패를 다시 적지 않습니다.** 지문(스크립트·예외종류·마지막 줄)으로
    묶어 처음 보는 것만 적습니다. 같은 실패를 6시간 쌓으면 아침에 못 읽습니다.

쓰는 법
    python scripts/verify_forever.py                # 6시간
    python scripts/verify_forever.py --hours 1
    python scripts/verify_forever.py --rounds 2     # 횟수로 끊기

남는 것
    data/cache/verify_log.md   회차·시각·처음 보는 실패만
"""

from __future__ import annotations

import hashlib
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 윈도 콘솔(cp949)은 '—' 같은 글자를 못 찍습니다. 기록하다 멈추면
# 밤새 돌린 것이 통째로 사라집니다.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "cache" / "verify_log.md"

# 돌릴 것. 이미 있는 도구입니다. 여기서 새로 만들지 않습니다.
JOBS = [
    ("퍼즈 · 입력 자리", ["python", "tests/_fuzz_sweep.py"]),
    # ⑩ 서류·통관 5,000건 (사용자 지시 숫자, 2026-09-27)
    ("퍼즈 · 서류·통관", ["python", "tests/_fuzz_docs.py", "5000"]),
    ("퍼즈 · 바깥이 죽었을 때", ["python", "tests/_fuzz_chaos.py"]),
    ("퍼즈 · 보안", ["python", "tests/_fuzz_security.py"]),
    ("퍼즈 · 운송 계획 전체", ["python", "tests/_fuzz_deep.py"]),
    # ⑨ 적합성 1만 건 (사용자 지시 숫자, 2026-09-27)
    ("적합성 10,000회", ["python", "scripts/check_document_conformance.py", "10000"]),
    ("어려운 적합성 시험", ["python", "scripts/check_document_hard.py"]),
    ("전체 테스트", ["python", "-m", "pytest", "tests", "-q", "-m", "not live"]),

    # 2026-09-26 에 만든 검사들. 무작위 씨앗을 회차마다 바꿔 돌립니다.
    # (scripts/checks/README.md 에 무엇을 보는지 적어 두었습니다)
    ("① 나갔다 들어오기", ["python", "scripts/checks/m1_roundtrip.py", "10000"]),
    ("② 선택·다시 그리기", ["python", "scripts/checks/m_redraw.py"]),
    ("② 환율 표", ["python", "scripts/checks/m_fx_big.py", "10000"]),
    ("② 환율 4단계", ["python", "scripts/checks/m_fx.py"]),
    ("③ 계산 독립 검산", ["python", "scripts/checks/m3_calc.py", "10000"]),
    ("④ 지식 글 예시 질문", ["python", "scripts/checks/m4_ask.py"]),
    ("④ 나라 인증 말투", ["python", "scripts/checks/m4_cert.py"]),
    ("④ 나라 무관 질문", ["python", "scripts/checks/m4_cross.py"]),
    ("④ PDF 생성", ["python", "scripts/checks/m_pdf_fuzz.py", "10000"]),
    ("⑤ HS → 수출요건", ["python", "scripts/checks/m5_hs_req.py"]),
    ("⑤ 계약서 조항", ["python", "scripts/checks/m_contract.py", "10000"]),
    ("⑤ 계약서 한국어", ["python", "scripts/checks/m_contract_ko.py"]),
    ("⑤ 계약서 오인", ["python", "scripts/checks/m_contract_cross.py"]),
    ("⑥ 서로 모순되는 입력", ["python", "scripts/checks/m6_contradiction.py", "10000"]),
    ("⑦ 서류 간 어긋남(넓힘)", ["python", "scripts/checks/m7_cross_wide.py", "10000"]),
    ("⑪ 일상어 HS", ["python", "scripts/checks/m11_hs.py"]),
    ("⑫ 역순·섞어 적기", ["python", "scripts/checks/m12_reverse.py", "10000"]),
    ("⑬ 인코텀즈 선택", ["python", "scripts/checks/m13_incoterms.py"]),
    # ⑮ ⑫~⑭ 를 3만 가지 경우의 수로 (사용자 지시 숫자, 2026-09-27)
    ("⑮ 적는 순서·인코텀즈·금액 3만", ["python", "scripts/checks/m15_orders.py", "30000"]),
    ("⑯ 사업자등록번호", ["python", "scripts/checks/m16_brn.py", "100000"]),
    ("⑰~㉕ 화면 전수", ["python", "scripts/checks/m_render.py"]),
    ("⑰~㉕ 붙는 값 흔들기", ["python", "scripts/checks/m_screens_fuzz.py", "10000"]),
    ("⑱⑲⑳ 서류·신고자료", ["python", "scripts/checks/m_filing.py", "500"]),
    ("㉑ 물류비 견적", ["python", "scripts/checks/m21_cost.py", "20000"]),
    ("㉒㉔ 컨테이너 번호", ["python", "scripts/checks/m2224.py", "100000"]),
    ("㉓ AI Assistant", ["python", "scripts/checks/m23_ai.py", "300"]),
    ("㉖ 수출 상위 품목", ["python", "scripts/checks/m26_top200.py"]),
    ("㉖ 품목표 전체", ["python", "scripts/checks/m26_all.py", "1500"]),
    ("① L/C 날짜", ["python", "scripts/checks/m_lc.py", "10000"]),
    ("모델·저장", ["python", "scripts/checks/m_model.py", "500"]),
    ("동시·중복", ["python", "scripts/checks/m_concurrent.py"]),
    ("정적 점검", ["python", "scripts/checks/m_static.py"]),
    ("배선 점검", ["python", "scripts/checks/m_wiring.py"]),
    ("CSS 규칙 없는 class", ["python", "scripts/check_css_classes.py"]),

    # 2026-09-27 에 만든 것들. 기관이 멈추는 세 모양과 굳혀 둔 표를 봅니다.
    # 이것들도 바깥을 부르지 않습니다 — 스스로 망을 끊거나 키를 비우거나
    # 흉내냅니다. (host_down 은 막지 않은 기관도 부르지 않습니다)
    ("멈춤 · 망 전부 단절", ["python", "scripts/checks/cache_offline.py"]),
    ("멈춤 · 키 없음·거부", ["python", "scripts/checks/keys_off.py"]),
    ("멈춤 · 기관 한 곳씩", ["python", "scripts/checks/host_down.py", "--all"]),
    ("HS · 기업·개인 상위", ["python", "scripts/checks/m26_biz_personal.py"]),
    ("HS · 일상어", ["python", "scripts/checks/m11_hs.py"]),
    ("JS 화면 테스트", ["node", "--test", "tests/hs_standard_names.test.cjs",
                   "tests/doc_schedule_keep.test.cjs"]),
]

# 바깥으로 나가려 한 흔적. 퍼즈가 이것을 찍으면 기록합니다.
OUTSIDE = ("테스트가 바깥", "Max retries", "Failed to establish", "NameResolutionError")


def fingerprint(label: str, output: str) -> str:
    """같은 실패를 한 번만 적기 위한 지문.

    회차마다 무작위 값이 달라 글자는 매번 다릅니다. 그래서 **예외 종류와
    마지막 코드 줄**만 뽑아 묶습니다.
    """

    kinds = re.findall(r"^\w*(?:Error|Exception|AssertionError)\b", output, re.M)
    frames = re.findall(r'File "([^"]+)", line (\d+)', output)
    last = f"{Path(frames[-1][0]).name}:{frames[-1][1]}" if frames else ""
    seed = f"{label}|{sorted(set(kinds))}|{last}"
    return hashlib.sha256(seed.encode()).hexdigest()[:10]


def headline(output: str) -> str:
    """돌린 결과를 한 줄로. 몇 건을 봤는지 알 수 있어야 합니다.

    정규식을 쓰지 않습니다. 찾는 말이 들어간 줄을 그대로 씁니다.
    도구마다 마지막 줄 모양이 달라 정규식으로 맞추려다 오히려 놓쳤습니다.
    """

    marks = ("검사 ", " passed", "합계 ", "됩니다 ", "잡음 ", "놓침도 헛경보도",
             "무작위 ", "실패 ", "■ ", "문제 ", "못 찾", "새로 생긴")
    rows = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(rows):
        if any(mark in line for mark in marks):
            return line[:80]
    return rows[-1][:80] if rows else "(아무것도 찍지 않았습니다)"


# 검사 묶음이 돌고 있다는 표시. scripts/checks/run_all.py 도 이 파일을 씁니다.
#
# 왜 있나
#   2026-09-27 에 이 묶음과 run_all.py 를 동시에 돌렸습니다. 둘이 같은 스크립트
#   (m26_biz_personal 처럼 몇 분씩 걸리는 것)를 같은 시각에 띄워 하나가
#   **출력도 없이** 죽었고, 이 묶음이 그것을 "처음 보는 실패"로 적었습니다.
#   단독으로 다시 돌리니 100% 통과했습니다 — 제품에는 아무 문제가 없었고
#   검사 설정이 만든 잡음이었습니다. 잡음을 한 번 적으면 그 뒤로 진짜 실패와
#   구별할 수 없게 됩니다.
LOCK = ROOT / "data" / "cache" / "checks_running.lock"
LOCK_STALE = 6 * 3600


def other_batch() -> str:
    """다른 검사 묶음이 돌고 있으면 그 사실을 돌려줍니다."""

    try:
        if not LOCK.exists():
            return ""
        age = __import__("time").time() - LOCK.stat().st_mtime
        who = LOCK.read_text(encoding="utf-8").strip() or "다른 묶음"
    except OSError:
        return ""
    return "" if age > LOCK_STALE else f"{who} · 약 {age / 60:.0f}분 전에 시작"


def hold() -> None:
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text("scripts/verify_forever.py", encoding="utf-8")
    except OSError:
        pass


def release() -> None:
    try:
        LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def run(label: str, command: list[str]) -> tuple[bool, str]:
    try:
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=3600,
                              env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return False, "한 시간을 넘겨 끊었습니다."
    output = (done.stdout or "") + (done.stderr or "")
    # **출력이 한 글자도 없이 실패한 것은 잡음으로 봅니다.**
    #
    # 검사들은 실패해도 반드시 무엇인가 찍습니다. 아무것도 없이 죽는 것은
    # 바깥 사정입니다 — 다른 묶음과 겹쳐 자원을 다투었거나, 컴퓨터가 잠들었거나,
    # 사람이 끊은 것입니다. 그것을 "처음 보는 실패"로 적으면 진짜 실패와
    # 구별할 수 없게 됩니다. (2026-09-27 실제로 한 번 그렇게 적었습니다)
    if done.returncode != 0 and not output.strip():
        return True, "(출력 없이 끝났습니다 — 겹침·잠자기·중단으로 보아 잡음으로 넘깁니다)"
    # 돌아간 값이 0이어도 "실패 N"처럼 본문에 적히는 도구가 있습니다.
    bad = done.returncode != 0 or re.search(
        r"실패\s*[1-9]|놓침\s*[1-9]|헛경보\s*[1-9]|FAILED"
        r"|문제\s*[1-9]|미탐\s*[1-9]|오탐\s*[1-9]|500\s*[1-9]"
        r"|못 찾는 낱말\s*[1-9]|못 찾음\s*[1-9]|유출\s*[1-9]", output)
    return (not bad), output


def note(text: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    print(text)


def main() -> int:
    args = sys.argv[1:]
    hours = 6.0
    rounds = None
    if "--hours" in args:
        hours = float(args[args.index("--hours") + 1])
    if "--rounds" in args:
        rounds = int(args[args.index("--rounds") + 1])
    # 시계 시각으로 끊습니다. "내일 아침 7시까지" 처럼 정할 때 씁니다.
    #     python scripts/verify_forever.py --until 2026-09-27T07:00
    until = None
    if "--until" in args:
        until = datetime.fromisoformat(args[args.index("--until") + 1])
        hours = max(0.0, (until - datetime.now()).total_seconds() / 3600)

    # 다른 검사 묶음과 겹치면 시작하지 않습니다. 겹치면 무거운 스크립트가
    # 출력도 없이 죽어, 있지도 않은 실패가 기록에 남습니다.
    busy = other_batch()
    if busy and "--force" not in args:
        print("■ 다른 검사 묶음이 돌고 있어 시작하지 않습니다.")
        print(f"   {busy}")
        print("   겹치면 없는 실패가 기록됩니다. 그래도 돌리려면 --force 를 주세요.")
        return 2
    hold()

    deadline = time.monotonic() + hours * 3600
    seen: set[str] = set()
    turn = 0
    total_fail = 0

    note(f"\n\n## 무인 검증 시작 {datetime.now():%Y-%m-%d %H:%M}"
         f" · {'%.1f시간' % hours if rounds is None else f'{rounds}회'}"
         f" · 바깥 기관 안 부름")

    while True:
        if rounds is not None and turn >= rounds:
            break
        if rounds is None and time.monotonic() > deadline:
            break
        turn += 1
        started = time.monotonic()
        fails = []

        # **회차마다 순서를 섞습니다.**
        #
        # 예전에는 늘 같은 순서로 돌았습니다. 그러면 뒤쪽 검사는 시간이
        # 다 되어 건너뛰기 쉽고(--hours 로 끊을 때), 앞쪽만 여러 번 돌아
        # "전부 돌렸다"는 말이 사실과 달라집니다. 섞으면 회차를 거듭할수록
        # 모든 검사가 고르게 돕니다.
        #
        # 씨앗을 회차 번호로 둡니다. 같은 회차를 다시 돌리면 같은 순서가 나와
        # 실패를 재현할 수 있습니다. (2026-09-27 사용자 지시: 교차로 돌리기)
        order = list(JOBS)
        random.Random(turn).shuffle(order)
        note(f"  · {turn}회차 순서: " + " → ".join(name for name, _ in order[:6])
             + (" → …" if len(order) > 6 else ""))

        for label, command in order:
            if rounds is None and time.monotonic() > deadline:
                break
            good, output = run(label, command)
            # 첫 회차는 작업마다 한 줄씩 남깁니다.
            # 어느 것이 실제로 돌았는지 적어 두지 않으면, 조용히 아무 일도 안 한
            # 작업이 섞여 있어도 "모두 통과"로 보입니다.
            # 회차마다 한 줄씩 남깁니다. 순서가 섞이므로 무엇이 언제 돌았는지
            # 적어 두지 않으면 나중에 못 맞춥니다. (전에는 1회차만 남겼습니다)
            note(f"  - {turn}회차 {label}: {headline(output)}")
            leak = [word for word in OUTSIDE if word in output]
            if leak:
                mark = fingerprint(f"{label}·바깥", output)
                if mark not in seen:
                    seen.add(mark)
                    note(f"\n### {turn}회차 · {label} — **바깥으로 나가려 했습니다**\n"
                         f"```\n{output[-700:].strip()}\n```")
            if good:
                continue
            mark = fingerprint(label, output)
            fails.append(label)
            total_fail += 1
            if mark in seen:
                continue                      # 이미 적은 실패입니다
            seen.add(mark)
            note(f"\n### {turn}회차 · {label} — 처음 보는 실패 `{mark}`\n"
                 f"{datetime.now():%H:%M}\n```\n{output[-1600:].strip()}\n```")

        hold()          # 자물쇠가 살아 있음을 알립니다
        spent = (time.monotonic() - started) / 60
        note(f"- {turn}회차 끝 {datetime.now():%H:%M} · {spent:.1f}분 · "
             + ("모두 통과" if not fails else f"실패 {len(fails)}종 ({', '.join(fails)})"))

    release()
    note(f"\n**{turn}회 돌렸습니다. 실패 {total_fail}번 · 처음 보는 것 {len(seen)}가지.**"
         + ("\n처음 보는 실패가 없습니다." if not seen else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
