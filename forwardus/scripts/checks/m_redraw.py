"""다시 그리면서 **고른 것이 사라지는** 자리를 모두 찾습니다.

스케줄 문제의 일반형입니다. innerHTML 로 목록을 새로 그리면 그 안의
radio·checkbox·select 는 체크가 지워집니다. 같은 값이 목록에 그대로 있어도
화면에는 아무것도 안 고른 것처럼 보이고, "고르세요"가 다시 뜹니다.
"""
import sys, io, re
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# innerHTML 로 무엇을 써 넣는 줄
WRITE = re.compile(r"(\w+)\.innerHTML\s*=")
# 그 부근에 폼 조작 요소가 들어가는가
CONTROL = re.compile(r"<(input|select|option|textarea)\b", re.I)
RESTORE = re.compile(r"\.(checked|selected|value)\s*=")

rows = []
for path in sorted(Path("app/static/js").glob("*.js")):
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    for index, line in enumerate(lines):
        m = WRITE.search(line)
        if not m:
            continue
        # 쓰는 내용이 한 줄로 안 끝날 수 있어 뒤 25줄까지 봅니다
        chunk = "\n".join(lines[index:index + 25])
        if not CONTROL.search(chunk):
            continue
        # 같은 덩어리 안이나 바로 뒤 30줄 안에서 고른 것을 되살리는가
        after = "\n".join(lines[index:index + 45])
        restored = bool(RESTORE.search(after))
        kinds = sorted({k.lower() for k in CONTROL.findall(chunk)})
        rows.append((path.name, index + 1, m.group(1), ",".join(kinds), restored))

# 하나씩 열어 확인한 것. 되살릴 것이 없거나 일부러 비우는 자리입니다. (2026-09-26)
#   contract_clauses.js  처음 한 번 짜 넣는 판 (다시 그리지 않습니다)
#   home.js:card         고른 것을 읽어 두고 checked 로 다시 넣습니다
#   home.js:logEl        대화를 일부러 비웁니다
#   home.js:listEl       기본이 '모두 고름' 입니다
#   planning.js          state.schedule_id 로 checked 를 다시 넣습니다
KNOWN = {("contract_clauses.js", "host"), ("home.js", "card"),
         ("home.js", "logEl"), ("home.js", "listEl"),
         ("planning.js", "scheduleList")}

print(f"■ 목록을 다시 그리면서 폼 요소를 넣는 자리 {len(rows)}곳")
print()
risky = [r for r in rows if not r[4] and (r[0], r[2]) not in KNOWN]
for name, line, target, kinds, restored in rows:
    mark = "✓ 되살림" if restored else "★ 안 되살림"
    print(f"   {mark:<12} {name}:{line:<5} {target:<16} <{kinds}>")
print()
print(f"   고른 것을 되살리지 않는 **새** 자리 {len(risky)}곳"
      f" (알고 있는 것 {sum(1 for r in rows if not r[4]) - len(risky)}곳)")
for name, line, target, kinds, _ in risky:
    print(f"   ★ {name}:{line} {target} <{kinds}>")
