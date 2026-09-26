"""검색 방식을 견줍니다. (원문 / 핵심질문 / 둘 합치기)

    python -m scripts.faq_search_ab --data tuning_v2     튜닝 데이터로
    python -m scripts.faq_search_ab --data paraphrases   예전 튜닝 데이터로

왜 재나
  긴 질문을 짧게 줄이면 검색이 좋아질 것 같지만, 조건이 빠져 엉뚱한 FAQ가 올라오기도 합니다.
  바꾸기 전에 세 방식을 같은 질문으로 돌려 Recall@1/@3과 임베딩 호출 수를 견줍니다.
  (임베딩은 질문마다 한 번이라, '둘 합치기'는 호출이 최대 2배입니다)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import consult_chain, consult_intent, faq_index  # noqa: E402

TUNING = ROOT / "data" / "faq" / "tuning"


def load(name: str) -> list[dict]:
    path = TUNING / f"{name}.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("gold_faq_id"):
            rows.append({"question": item["question"], "gold": item["gold_faq_id"],
                         "kind": item.get("kind", item.get("style", ""))})
    return rows


def run(rows: list[dict], mode: str) -> dict:
    hit1 = hit3 = 0
    times = []
    for row in rows:
        started = time.perf_counter()
        if mode == "original":
            hits = faq_index.search(row["question"], 5)
        elif mode == "core":
            core = consult_intent.split_question(row["question"])["core"]
            hits = faq_index.search(core, 5)
        else:
            core = consult_intent.split_question(row["question"])["core"]
            hits = consult_chain.search_for(row["question"], None, 5)
        times.append((time.perf_counter() - started) * 1000)
        ids = [faq["id"] for faq, *_ in hits]
        hit1 += 1 if ids[:1] == [row["gold"]] else 0
        hit3 += 1 if row["gold"] in ids[:3] else 0
    total = max(1, len(rows))
    return {"mode": mode, "questions": len(rows),
            "recall@1": round(hit1 / total, 4), "recall@3": round(hit3 / total, 4),
            "hit1": hit1, "hit3": hit3,
            "p50_ms": round(statistics.median(times), 1) if times else 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tuning_v2")
    args = parser.parse_args()

    rows = load(args.data)
    print(f"정답이 있는 질문 {len(rows)}개 ({args.data})")
    print(f"{'방식':10}{'Recall@1':>12}{'Recall@3':>12}{'p50(ms)':>10}")
    for mode in ("original", "core", "merged"):
        outcome = run(rows, mode)
        print(f"{mode:10}{outcome['recall@1']:>12.3f}{outcome['recall@3']:>12.3f}"
              f"{outcome['p50_ms']:>10.1f}   ({outcome['hit1']}/{outcome['questions']}, "
              f"{outcome['hit3']}/{outcome['questions']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
