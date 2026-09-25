"""FAQ 검색·캐시 자체의 속도를 잽니다. (AI를 부르지 않는 구간)

    python -m scripts.faq_bench                한 번에 하나씩 (단일 요청)
    python -m scripts.faq_bench --threads 8    여러 요청이 동시에 올 때

왜 따로 재나
  전체 응답 시간은 AI가 대부분을 차지해 우리 코드의 몫이 묻힙니다. FAQ로 바로 답하는
  길과 캐시에서 꺼내는 길은 AI를 부르지 않으므로, 그 구간만 따로 재야 의미가 있습니다.
  (gunicorn은 요청을 여러 워커가 나눠 받지만, 색인은 워커마다 한 벌씩 메모리에 뜹니다)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import faq_cache, faq_index  # noqa: E402

TUNING = ROOT / "data" / "faq" / "tuning" / "paraphrases.jsonl"


def questions() -> list[str]:
    if TUNING.exists():
        return [json.loads(line)["question"]
                for line in TUNING.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row["question"] for row in faq_index.load()["rows"]]


def once(question: str) -> tuple[float, str]:
    started = time.perf_counter()
    verdict = faq_index.decide(question)
    if verdict["route"] == "faq_direct":
        faq_index.answer_text(verdict["faq"])
    return (time.perf_counter() - started) * 1000, verdict["route"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()

    faq_index.load(force=True)
    faq_cache.clear()
    items = questions() * args.repeat
    started = time.perf_counter()
    if args.threads > 1:
        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            results = list(pool.map(once, items))
    else:
        results = [once(question) for question in items]
    wall = time.perf_counter() - started

    times = sorted(row[0] for row in results)
    routes: dict[str, int] = {}
    for _, route in results:
        routes[route] = routes.get(route, 0) + 1
    print(json.dumps({
        "questions": len(items), "threads": args.threads,
        "p50_ms": round(statistics.median(times), 3),
        "p95_ms": round(times[int(len(times) * 0.95) - 1], 3),
        "max_ms": round(times[-1], 3),
        "throughput_per_sec": round(len(items) / wall, 1),
        "routes": routes,
        "index_load_ms": None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
