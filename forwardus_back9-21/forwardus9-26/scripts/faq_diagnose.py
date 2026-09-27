"""평가에서 기대와 어긋난 문항의 원인을 나눕니다. (임계값 탓으로 뭉뚱그리지 않기)

    python -m scripts.faq_diagnose --set final --tag v2

무엇을 보나
  저장된 평가 결과(results/*.json)의 문항마다 검색 점수·후보·선택 경로를 다시 확인하고,
  아래 원인 중 하나로 나눕니다. 사람이 읽고 고칠 수 있게 표로 남깁니다.

원인 분류
  no_candidate       후보 5개 안에 정답 FAQ가 없음 (검색이 못 찾음)
  wrong_pick         후보에는 있는데 다른 FAQ를 1위로 고름
  threshold_block    1위가 정답인데 문턱(점수·겹침·유사도)에 걸려 경로가 내려감
  condition_mismatch 조건(나라·Incoterms 등)이 FAQ와 달라 막음
  not_in_kb          지식베이스에 답이 될 FAQ가 애초에 없음 (gold 없음)
  approval_blocked   승인 전 자료라 faq_direct가 막힘
  lookup_unsupported 공식 조회 창구가 없어 external_lookup으로 못 감
  clarify_missed     되물어야 하는데 되묻지 않음
  clarify_extra      되물을 필요가 없는데 되물음
  label_doubt        기대 경로 쪽이 의심스러움 (사람 확인 필요)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import consult_chain, faq_index  # noqa: E402

RESULTS = ROOT / "data" / "faq" / "eval" / "results"
EVAL = ROOT / "data" / "faq" / "eval"


def load_expectations(which: str) -> dict:
    name = {"final": "final_v2.jsonl", "final3": "final_v3.jsonl"}.get(which, "eval_*.jsonl")
    rows = {}
    for path in sorted(EVAL.glob(name)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                rows[item["id"]] = item
    return rows


def classify(row: dict, item: dict) -> tuple[str, str]:
    """(원인, 설명). row는 측정 결과, item은 기대값."""

    question = row["question"]
    plan = consult_chain.decide(question)
    verdict = faq_index.decide(question)
    limits = faq_index.thresholds()
    took = row.get("route") or row.get("source")
    allowed = set(item.get("allowed_paths") or [])
    gold = row.get("gold")
    top = [faq["id"] for faq, *_ in verdict["candidates"]]

    detail = (f"경로 {took} / 기대 {sorted(allowed)} · 1위 {top[0] if top else '-'} "
              f"점수 {verdict['score']:.2f} 겹침 {verdict['coverage']:.2f} "
              f"뜻 {verdict['similarity']:.2f}")

    if took in allowed:
        return "ok", detail
    if "faq_direct" in allowed and took == "faq_context" and not plan["approved"]:
        return "approval_blocked", detail
    if item.get("must_ask") and took != "clarification":
        return "clarify_missed", detail
    if took == "clarification" and not item.get("must_ask"):
        return "clarify_extra", detail
    if "external_lookup" in allowed and took != "external_lookup":
        return "lookup_unsupported", detail
    if gold:
        if gold not in top:
            return "no_candidate", detail
        if top and top[0] != gold:
            return "wrong_pick", detail
        if verdict["coverage"] < limits["context_coverage"] and \
                verdict["similarity"] < limits["context_similarity"]:
            return "threshold_block", detail
        if any("나라" in reason or "Incoterms" in reason for reason in verdict["reasons"]):
            return "condition_mismatch", detail
        return "label_doubt", detail
    if took in ("general_guidance", "faq_context"):
        return "not_in_kb", detail
    return "label_doubt", detail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", dest="which", default="final")
    parser.add_argument("--tag", default="v2")
    parser.add_argument("--mode", default="after")
    args = parser.parse_args()

    path = RESULTS / f"{args.which}_{args.mode}_stub_{args.tag}.json"
    if not path.exists():
        print(f"{path.name} 이 없습니다. 먼저 faq_eval 을 돌리세요.")
        return 1
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    expectations = load_expectations(args.which)

    tally: Counter = Counter()
    lines = ["| 문항 | 유형 | 원인 | 상세 |", "|---|---|---|---|"]
    for row in rows:
        item = expectations.get(row["id"], {})
        cause, detail = classify(row, item)
        tally[cause] += 1
        if cause != "ok":
            lines.append(f"| {row['id']} | {row['type']} | **{cause}** | {detail} |")

    total = len(rows)
    print(f"문항 {total}개 · 기대와 맞음 {tally['ok']}개")
    for cause, count in tally.most_common():
        if cause != "ok":
            print(f"  {cause:20} {count:3}건 ({count}/{total})")

    out = RESULTS / f"diagnose_{args.which}_{args.tag}.md"
    header = [f"# 불일치 원인 분류 — {args.which} ({args.tag})", "",
              f"- 문항 {total}개 중 기대와 맞음 {tally['ok']}개, 어긋남 {total - tally['ok']}개",
              "- 원인별: " + ", ".join(f"{cause} {count}" for cause, count in tally.most_common()
                                      if cause != "ok"), ""]
    out.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    print(f"\n{out.relative_to(ROOT)} 에 적었습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
