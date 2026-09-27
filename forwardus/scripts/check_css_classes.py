"""화면이 쓰는 class 에 CSS 규칙이 있는가.

    python scripts/check_css_classes.py

왜 있나
  채움 수(18/18) 칸이 화면 너비만큼 늘어나 보인 적이 있습니다. 원인은
  .doc_head_right 에 CSS 규칙이 **아예 없었던 것**이었습니다. 감싼 칸이
  블록이 되어 안의 .doc_score 가 칸 너비만큼 늘어났습니다.
  (flex: 0 0 auto 는 부모가 flex 일 때만 듣습니다)

  이런 것은 테스트로 안 잡힙니다. 화면은 200으로 뜨고 글자도 다 나옵니다.
  눈으로 봐야만 보입니다. 그래서 **규칙 없는 class** 를 세어 둡니다.
  (2026-09-26)

읽는 법
  여기 뜨는 이름이 전부 문제인 것은 아닙니다. 감싸기만 하는 껍데기는
  규칙이 없어도 됩니다. 아래 KNOWN 에 그런 것을 적어 두었습니다.
  **새 이름이 뜨면** 그 자리가 정말 규칙 없이 괜찮은지 한 번 보세요.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]

# 규칙이 없어도 되는 것. 감싸기만 하거나 JS 가 붙잡는 고리입니다.
# (2026-09-26 하나씩 열어 확인했습니다 — 화면에 영향 없음)
KNOWN = {
    "calendar_panel", "cc_body", "cc_intro", "ctr_year", "has_flyout",
    "incoterm_step", "pick_card_row", "route_fields", "schedule_main",
    "step", "track_event", "upload_result",
}

CLASS_IN_HTML = re.compile(r"""class\s*=\s*["']([^"'{}]*)["']""")
CLASSLIST = re.compile(r"""classList\.(?:add|remove|toggle)\(\s*["'`]([\w\- ]+)["'`]""")


def _defined() -> set[str]:
    css = "\n".join(p.read_text(encoding="utf-8")
                    for p in sorted((ROOT / "app/static/css").glob("*.css")))
    return set(re.findall(r"\.([a-zA-Z_][\w\-]*)", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))


def _used() -> dict[str, str]:
    found: dict[str, str] = {}

    def take(text: str, where: str, pattern: re.Pattern) -> None:
        for match in pattern.finditer(text):
            for name in match.group(1).split():
                if not name or "{" in name or "}" in name:
                    continue
                found.setdefault(name, f"{where}:{text[:match.start()].count(chr(10)) + 1}")

    for path in sorted((ROOT / "app/templates").rglob("*.html")):
        take(path.read_text(encoding="utf-8"), path.name, CLASS_IN_HTML)
    for path in sorted((ROOT / "app/static/js").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        take(text, path.name, CLASS_IN_HTML)
        take(text, path.name, CLASSLIST)
    return found


def main() -> bool:
    defined, used = _defined(), _used()
    missing = {name: where for name, where in used.items() if name not in defined}
    fresh = {name: where for name, where in missing.items() if name not in KNOWN}

    print(f"CSS 에 적힌 이름 {len(defined):,}개 · 화면이 쓰는 이름 {len(used):,}개")
    print(f"규칙 없는 class {len(missing)}개 (알고 있는 것 {len(missing) - len(fresh)}개)")
    for name, where in sorted(fresh.items()):
        print(f"  ★ {name:<28} {where}")
    if not fresh:
        print("새로 생긴 것 없음.")
    return bool(fresh)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
