"""`.env`를 `.env.example` 차례대로 다시 씁니다. **값은 그대로 옮깁니다.**

왜 필요한가
  키를 받을 때마다 파일 끝에 붙이다 보니 같은 서비스 키가 여기저기 흩어집니다.
  그러면 "이 키가 이미 있나" 확인하려고 파일 전체를 훑게 되고, 같은 키를 두 번
  적어 뒤엣것이 앞엣것을 덮는 사고가 납니다.

무엇을 지키나
  - **값을 화면에 찍지 않습니다.** 정리 결과는 키 이름과 개수만 알려 줍니다.
  - 값을 고치지 않습니다. 따옴표·공백까지 적힌 그대로 옮깁니다.
  - `.env.example`에 없는 키도 버리지 않습니다. 맨 아래 "그 밖의 키"로 모읍니다.
  - 같은 키가 두 번 있으면 **뒤엣것(실제로 쓰이는 값)**만 남기고 알려 줍니다.
  - 고치기 전 파일을 `.env.bak`으로 남깁니다.

쓰는 법
    python scripts/tidy_env.py            # 무엇이 바뀔지 보여 주기만 합니다
    python scripts/tidy_env.py --write    # 실제로 고칩니다
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
BACKUP = ROOT / ".env.bak"


def read_pairs(path: Path) -> tuple[dict[str, str], list[str]]:
    """{키: 줄 전체}와 중복된 키 목록. 값은 읽되 밖으로 내보내지 않습니다."""

    found: dict[str, str] = {}
    duplicated: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in found:
            duplicated.append(key)
        found[key] = stripped          # 뒤엣것이 남습니다 (dotenv와 같은 규칙)
    return found, duplicated


def example_layout(path: Path) -> list[tuple[str, str]]:
    """(종류, 내용). 종류는 "comment" 또는 "key"입니다. 주석도 그대로 옮깁니다."""

    layout: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            layout.append(("blank", ""))
        elif stripped.startswith("#"):
            layout.append(("comment", line.rstrip()))
        elif "=" in stripped:
            layout.append(("key", stripped.split("=", 1)[0].strip()))
    return layout


def build(values: dict[str, str], layout: list[tuple[str, str]]) -> tuple[str, list[str]]:
    lines: list[str] = []
    used: set[str] = set()
    for kind, content in layout:
        if kind == "blank":
            # 빈 줄이 잇따르지 않게 합니다.
            if lines and lines[-1] != "":
                lines.append("")
        elif kind == "comment":
            lines.append(content)
        else:
            key = content
            used.add(key)
            lines.append(values.get(key, f"{key}="))

    extra = [key for key in values if key not in used]
    if extra:
        lines += ["", "# ----- 그 밖의 키 -----",
                  "# .env.example에 없는 키입니다. 쓰는 것이면 .env.example에도 이름을 적어 주세요.",
                  "# (이름만 적고 값은 비워 둡니다. 그래야 다음 사람이 무엇을 받아야 하는지 압니다)"]
        lines += [values[key] for key in extra]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n", extra


def main() -> int:
    if not ENV.exists():
        print(".env 파일이 없습니다.")
        return 1

    values, duplicated = read_pairs(ENV)
    layout = example_layout(EXAMPLE)
    text, extra = build(values, layout)

    filled = [key for key, line in values.items() if line.split("=", 1)[1].strip()]
    print(f"키 {len(values)}개 (값이 있는 것 {len(filled)}개)")
    if duplicated:
        print(f"두 번 적힌 키 {len(duplicated)}개 — 뒤엣것만 남깁니다: {', '.join(sorted(set(duplicated)))}")
    if extra:
        print(f".env.example에 없는 키 {len(extra)}개: {', '.join(extra)}")
    missing = [key for kind, key in layout if kind == "key" and key not in values]
    if missing:
        print(f"아직 안 받은 키 {len(missing)}개 (빈 줄로 넣어 둡니다): {', '.join(missing)}")

    if "--write" not in sys.argv:
        print("\n미리보기입니다. 실제로 고치려면 --write 를 붙이세요.")
        return 0

    shutil.copyfile(ENV, BACKUP)
    ENV.write_text(text, encoding="utf-8")
    print(f"\n정리했습니다. 원래 파일은 {BACKUP.name} 으로 남겼습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
