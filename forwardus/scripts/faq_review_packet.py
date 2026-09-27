"""관세사에게 넘길 검토 패킷을 만듭니다. (문서 100개가 아니라 '주장' 단위로)

    python -m scripts.faq_review_packet                고위험 3개 분류(45건)
    python -m scripts.faq_review_packet --top 9        직접 반환에 실제로 걸리는 9건만
    python -m scripts.faq_review_packet --all          100건 전부

왜 주장 단위인가
  FAQ 한 건은 평균 875자입니다. 100건을 통째로 읽어 달라고 하면 아무도 검토해 주지
  않습니다. 규정을 단정하는 문장(기한·의무·법령·기관)만 뽑으면 한 건당 2~5개로 줄고,
  검토자는 ○/×/수정만 적으면 됩니다.

무엇이 안 들어가나
  이 스크립트는 **승인하지 않습니다.** 검토자가 종이에 적어 온 결과를 사람이
  `scripts/faq_review.py --approve` 로 넣어야 승인됩니다. AI는 승인자가 될 수 없습니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAQ_DIR = ROOT / "data" / "faq"
OUT = FAQ_DIR / "review"

# 틀리면 비용·지연·처벌로 가는 분류. 여기부터 검토받습니다.
HIGH_RISK = ("HS 코드·수출신고·통관", "원산지·FTA·인증·수출통제", "결제·신용장·대금 회수")
# 직접 반환에 실제로 걸리는 FAQ. (faq_diagnose 측정 결과, 2026-09-25)
TOP_BLOCKING = ["EXP-031", "EXP-041", "EXP-016", "EXP-086", "EXP-076",
                "EXP-046", "EXP-088", "EXP-015", "EXP-060"]

# 규정을 단정하는 문장. 이런 문장만 뽑아 검토받습니다.
CLAIM = re.compile(r"(해야 합니다|하여야|해야 하고|받아야|내야|제출해야|신고해야|금지|필수|"
                   r"의무|기한|이내|까지|대상입니다|해당합니다|적용됩니다|됩니다\.|"
                   r"법|고시|규정|협정|조항|제\d+조)")
# 이미 조건부로 쓴 문장은 검토 부담이 낮습니다. (단정이 아니므로)
HEDGED = re.compile(r"(다를 수 있|확인하세요|확인해야|달라집니다|경우에 따라|관세사|세관에|"
                    r"문의|권장|일반적으로)")


def claims_of(faq: dict) -> list[dict]:
    text = faq.get("detailed_answer", "") + "\n" + faq.get("short_answer", "")
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n", text) if part.strip()]
    rows = []
    for sentence in sentences:
        if len(sentence) < 12 or not CLAIM.search(sentence):
            continue
        rows.append({"text": sentence[:300], "hedged": bool(HEDGED.search(sentence))})
    # 단정 문장을 앞에 둡니다. 검토자가 위험한 것부터 봅니다.
    rows.sort(key=lambda row: row["hedged"])
    return rows[:6]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=0, help="직접 반환에 걸리는 상위 N건만")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    rows = [json.loads(line) for line in (FAQ_DIR / "faq.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if args.top:
        picked = [row for row in rows if row["id"] in TOP_BLOCKING[:args.top]]
        title = f"직접 반환에 걸리는 {len(picked)}건"
    elif args.all:
        picked = rows
        title = "전체 100건"
    else:
        picked = [row for row in rows if row["category"] in HIGH_RISK]
        title = f"고위험 3개 분류 {len(picked)}건"

    total_claims = sum(len(claims_of(row)) for row in picked)
    lines = [
        f"# 무역 FAQ 검토 패킷 — {title}", "",
        "## 검토자께",
        "",
        "ForwardUs 수출 상담 서비스가 쓰는 FAQ입니다. **아직 아무도 검토하지 않았습니다.**",
        "문서를 통째로 읽으실 필요는 없습니다. 아래 **규정을 단정한 문장**만 봐 주시면 됩니다.",
        "",
        f"- 검토 대상 {len(picked)}건 · 확인할 문장 {total_claims}개",
        "- 각 문장에 **○(맞음) · ×(틀림) · △(조건부·수정 필요)** 중 하나를 적어 주세요.",
        "- ×나 △이면 '어떻게 고쳐야 하는지'를 한 줄 적어 주세요. 그 문장만 고치겠습니다.",
        "- 실무 관행이라 딱 잘라 말하기 어려우면 △로 두고 그 이유를 적어 주세요.",
        "",
        "### 검토자 정보 (승인 기록에 남습니다)",
        "",
        "| 항목 | 적어 주세요 |",
        "|---|---|",
        "| 성명 | |",
        "| 자격·등록번호 (관세사 등) | |",
        "| 소속 | |",
        "| 검토일 | |",
        "",
        "> 이 표가 비어 있으면 승인으로 기록하지 않습니다. "
        "AI 점검이나 '전문가 페르소나'는 검토자가 될 수 없습니다.",
        "", "---", "",
    ]

    for faq in picked:
        claims = claims_of(faq)
        sources = " · ".join(f"[{row.get('name','')}]({row.get('url','')})"
                             for row in (faq.get("sources") or [])[:3])
        lines += [f"## {faq['id']} · {faq['category']}", "",
                  f"**질문** {faq['question']}", "",
                  f"**요약 답변** {faq['short_answer']}", "",
                  f"**출처** {sources}",
                  f"**적용 범위** {json.dumps(faq.get('applicability', {}), ensure_ascii=False)}",
                  f"**갱신 성격** {faq.get('freshness','')} · **현재 상태** "
                  f"{(faq.get('review') or {}).get('review_status','pending')}", "",
                  "| # | 확인할 문장 | ○/×/△ | 고칠 내용 |", "|---|---|---|---|"]
        for number, claim in enumerate(claims, 1):
            mark = "" if claim["hedged"] else " **(단정)**"
            lines.append(f"| {number} | {claim['text']}{mark} |  |  |")
        if not claims:
            lines.append("| – | (규정을 단정한 문장이 없습니다. 절차 설명만 있습니다) |  |  |")
        lines += ["", "**이 FAQ 전체 판정** ☐ 승인  ☐ 수정 후 승인  ☐ 보류",
                  "", "검토 의견: ", "", "---", ""]

    OUT.mkdir(parents=True, exist_ok=True)
    name = ("packet_top.md" if args.top else
            "packet_all.md" if args.all else "packet_high_risk.md")
    (OUT / name).write_text("\n".join(lines), encoding="utf-8")
    print(f"{(OUT / name).relative_to(ROOT)} · FAQ {len(picked)}건 · 확인 문장 {total_claims}개")
    print("검토 결과를 받으면 이렇게 넣습니다:")
    print('  python -m scripts.faq_review --approve EXP-031 --reviewer "홍길동 관세사(등록 12345)" '
          '--note "3번 문장 수정 후 승인"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
