"""FAQ 전문가 검토 상태를 다룹니다.

    python -m scripts.faq_review --init                 검토 칸이 없는 FAQ에 pending으로 넣기
    python -m scripts.faq_review --status               분류별 검토 현황 보기
    python -m scripts.faq_review --approve EXP-011 --reviewer "홍길동 관세사" --note "확인함"
    python -m scripts.faq_review --reject  EXP-011 --reviewer "홍길동 관세사" --note "근거 부족"

지키는 것
  - 승인은 **사람 이름**이 있어야 합니다. AI나 자동 점검은 승인자가 될 수 없습니다.
    (--reviewer 에 ai·assistant·claude·gpt 같은 이름을 넣으면 거부합니다)
  - 승인은 그때의 content_version에 붙습니다. 내용을 고쳐 version이 올라가면
    faq_build가 그 승인을 pending으로 되돌립니다. 예전 승인이 새 글을 덮지 못합니다.
  - 상태가 바뀌면 approval_version(= faq_meta.json)이 올라가고, 그 값이 캐시 열쇠에
    들어가므로 예전 답은 저절로 버려집니다.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAQ_DIR = ROOT / "data" / "faq"
PARTS = FAQ_DIR / "parts"
META = FAQ_DIR / "faq_meta.json"

EMPTY_REVIEW = {"review_status": "pending", "reviewer": "", "reviewed_at": "",
                "approved_version": "", "review_notes": ""}
# 사람이 아닌 이름. 승인자로 받지 않습니다.
NOT_A_PERSON = re.compile(r"(?i)\b(ai|assistant|claude|gpt|chatgpt|bot|자동|시스템|model)\b")


def load_parts() -> list[tuple[Path, list[dict]]]:
    return [(path, [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()])
            for path in sorted(PARTS.glob("*.jsonl"))]


def save(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                    encoding="utf-8")


def bump_approval_version() -> str:
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    meta["approval_version"] = str(int(meta.get("approval_version", 0)) + 1)
    meta["approval_changed_at"] = datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta["approval_version"]


def init() -> int:
    changed = 0
    for path, rows in load_parts():
        for row in rows:
            if "review" not in row:
                row["review"] = dict(EMPTY_REVIEW)
                changed += 1
            # 시행일·종료일은 아는 것만 채웁니다. 모르면 빈 칸으로 둡니다.
            row.setdefault("effective", {"effective_from": "", "effective_to": "",
                                         "confirmed": False})
        save(path, rows)
    print(f"검토 칸을 넣은 FAQ {changed}건 (모두 pending)")
    return 0


def status() -> int:
    tally: Counter = Counter()
    by_category: dict[str, Counter] = {}
    for _, rows in load_parts():
        for row in rows:
            state = (row.get("review") or {}).get("review_status", "없음")
            tally[state] += 1
            by_category.setdefault(row["category"], Counter())[state] += 1
    print("전체:", dict(tally))
    for category, counts in by_category.items():
        print(f"  {category}: {dict(counts)}")
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    print("approval_version:", meta.get("approval_version", "0"))
    return 0


def set_state(faq_id: str, state: str, reviewer: str, note: str) -> int:
    if state == "approved":
        if not reviewer.strip():
            print("승인하려면 --reviewer 에 검토한 사람 이름을 적어야 합니다.")
            return 1
        if NOT_A_PERSON.search(reviewer):
            print(f"'{reviewer}'는 사람 검토자로 받지 않습니다. "
                  "AI 점검은 전문가 승인이 아닙니다.")
            return 1
    found = False
    for path, rows in load_parts():
        for row in rows:
            if row["id"] != faq_id:
                continue
            found = True
            row.setdefault("review", dict(EMPTY_REVIEW))
            row["review"].update(
                review_status=state, reviewer=reviewer,
                reviewed_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                approved_version=row.get("version", "1") if state == "approved" else "",
                review_notes=note)
            save(path, rows)
            break
        if found:
            break
    if not found:
        print(f"{faq_id} 를 찾지 못했습니다.")
        return 1
    version = bump_approval_version()
    print(f"{faq_id} → {state} (검토자 {reviewer or '-'}) · approval_version {version}")
    print("이어서 python -m scripts.faq_build 를 돌리세요. (캐시가 버려집니다)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--approve", default="")
    parser.add_argument("--reject", default="")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if args.init:
        return init()
    if args.approve:
        return set_state(args.approve, "approved", args.reviewer, args.note)
    if args.reject:
        return set_state(args.reject, "rejected", args.reviewer, args.note)
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
