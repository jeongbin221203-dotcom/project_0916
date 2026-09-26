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
    ("퍼즈 · 서류·통관", ["python", "tests/_fuzz_docs.py"]),
    ("퍼즈 · 바깥이 죽었을 때", ["python", "tests/_fuzz_chaos.py"]),
    ("퍼즈 · 보안", ["python", "tests/_fuzz_security.py"]),
    ("퍼즈 · 운송 계획 전체", ["python", "tests/_fuzz_deep.py"]),
    ("적합성 100회", ["python", "scripts/check_document_conformance.py", "100"]),
    ("어려운 적합성 시험", ["python", "scripts/check_document_hard.py"]),
    ("전체 테스트", ["python", "-m", "pytest", "tests", "-q", "-m", "not live"]),

    # 2026-09-26 에 만든 검사들. 무작위 씨앗을 회차마다 바꿔 돌립니다.
    # (scripts/checks/README.md 에 무엇을 보는지 적어 두었습니다)
    ("① 나갔다 들어오기", ["python", "scripts/checks/m1_roundtrip.py", "3000"]),
    ("② 선택·다시 그리기", ["python", "scripts/checks/m_redraw.py"]),
    ("② 환율 표", ["python", "scripts/checks/m_fx_big.py", "5000"]),
    ("② 환율 4단계", ["python", "scripts/checks/m_fx.py"]),
    ("③ 계산 독립 검산", ["python", "scripts/checks/m3_calc.py", "5000"]),
    ("④ 지식 글 예시 질문", ["python", "scripts/checks/m4_ask.py"]),
    ("④ 나라 인증 말투", ["python", "scripts/checks/m4_cert.py"]),
    ("④ 나라 무관 질문", ["python", "scripts/checks/m4_cross.py"]),
    ("④ PDF 생성", ["python", "scripts/checks/m_pdf_fuzz.py", "3000"]),
    ("⑤ HS → 수출요건", ["python", "scripts/checks/m5_hs_req.py"]),
    ("⑤ 계약서 조항", ["python", "scripts/checks/m_contract.py", "5000"]),
    ("⑤ 계약서 한국어", ["python", "scripts/checks/m_contract_ko.py"]),
    ("⑤ 계약서 오인", ["python", "scripts/checks/m_contract_cross.py"]),
    ("⑥ 서로 모순되는 입력", ["python", "scripts/checks/m6_contradiction.py", "3000"]),
    ("⑪ 일상어 HS", ["python", "scripts/checks/m11_hs.py"]),
    ("⑫ 역순·섞어 적기", ["python", "scripts/checks/m12_reverse.py", "3000"]),
    ("⑯ 사업자등록번호", ["python", "scripts/checks/m16_brn.py", "30000"]),
    ("⑰~㉕ 화면 전수", ["python", "scripts/checks/m_render.py"]),
    ("⑰~㉕ 붙는 값 흔들기", ["python", "scripts/checks/m_screens_fuzz.py", "3000"]),
    ("⑱⑲⑳ 서류·신고자료", ["python", "scripts/checks/m_filing.py", "500"]),
    ("㉑ 물류비 견적", ["python", "scripts/checks/m21_cost.py", "5000"]),
    ("㉒㉔ 컨테이너 번호", ["python", "scripts/checks/m2224.py", "30000"]),
    ("㉓ AI Assistant", ["python", "scripts/checks/m23_ai.py", "300"]),
    ("㉖ 수출 상위 품목", ["python", "scripts/checks/m26_top200.py"]),
    ("㉖ 품목표 전체", ["python", "scripts/checks/m26_all.py", "1500"]),
    ("① L/C 날짜", ["python", "scripts/checks/m_lc.py", "5000"]),
    ("모델·저장", ["python", "scripts/checks/m_model.py", "500"]),
    ("동시·중복", ["python", "scripts/checks/m_concurrent.py"]),
    ("정적 점검", ["python", "scripts/checks/m_static.py"]),
    ("배선 점검", ["python", "scripts/checks/m_wiring.py"]),
    ("CSS 규칙 없는 class", ["python", "scripts/check_css_classes.py"]),
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


def run(label: str, command: list[str]) -> tuple[bool, str]:
    try:
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=3600,
                              env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return False, "한 시간을 넘겨 끊었습니다."
    output = (done.stdout or "") + (done.stderr or "")
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

        for label, command in JOBS:
            if rounds is None and time.monotonic() > deadline:
                break
            good, output = run(label, command)
            # 첫 회차는 작업마다 한 줄씩 남깁니다.
            # 어느 것이 실제로 돌았는지 적어 두지 않으면, 조용히 아무 일도 안 한
            # 작업이 섞여 있어도 "모두 통과"로 보입니다.
            if turn == 1:
                note(f"  - {label}: {headline(output)}")
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

        spent = (time.monotonic() - started) / 60
        note(f"- {turn}회차 끝 {datetime.now():%H:%M} · {spent:.1f}분 · "
             + ("모두 통과" if not fails else f"실패 {len(fails)}종 ({', '.join(fails)})"))

    note(f"\n**{turn}회 돌렸습니다. 실패 {total_fail}번 · 처음 보는 것 {len(seen)}가지.**"
         + ("\n처음 보는 실패가 없습니다." if not seen else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
