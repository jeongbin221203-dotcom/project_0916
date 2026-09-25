"""수정 전/후 속도·토큰을 같은 질문으로 번갈아 재고, 단계별로 나눠 기록합니다.

    python -m scripts.faq_speed --n 12 --repeat 2            실제 OpenAI를 부릅니다(돈이 듭니다)
    python -m scripts.faq_speed --n 12 --repeat 2 --stub     API 없이 흐름만

왜 번갈아 재나
  before를 몰아서 재고 after를 몰아서 재면, 그 사이 OpenAI가 느려진 것을 '개선'으로
  읽게 됩니다. 질문마다 before→after, after→before 순서를 번갈아 섞습니다.

무엇을 나눠 재나
  route(의도·조건·FAQ검색, 임베딩 포함) · search(근거 재조회) · lookup(공식 조회) · llm(생성) · total
  오류·시간 초과도 버리지 않고 셉니다. 성공만 골라 재면 좋아 보일 뿐입니다.
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

from app.collectors import ai_client  # noqa: E402
from app.services import faq_cache, faq_index, support_chat_service  # noqa: E402

EVAL = ROOT / "data" / "faq" / "eval"
OUT = EVAL / "results"


def questions(n: int) -> list[dict]:
    """최종 평가 세트에서 고르게 뽑습니다. (유형이 쏠리지 않게)"""

    rows = [json.loads(line) for line in (EVAL / "final_v3.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if n >= len(rows):
        return rows
    stride = len(rows) / n
    return [rows[int(i * stride)] for i in range(n)]


class Counter:
    """호출 수와 토큰을 셉니다. (임베딩은 따로)"""

    def __init__(self, stub: bool):
        self.stub = stub
        self.reset()
        self._real = ai_client.request_text

    def reset(self):
        self.llm = self.embed = self.prompt_tokens = self.completion_tokens = 0
        self.errors = 0

    def __enter__(self):
        ai_client.request_text = self._wrapped
        return self

    def __exit__(self, *_):
        ai_client.request_text = self._real

    def _wrapped(self, method, url, **kwargs):
        if url.endswith("/embeddings"):
            self.embed += 1
            return self._real(method, url, **kwargs)
        self.llm += 1
        if self.stub:
            body = {"choices": [{"message": {"content": "(stub) 답"}}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
            return {"success": True, "source": "api", "data": json.dumps(body)}
        result = self._real(method, url, **kwargs)
        if not result.get("success"):
            self.errors += 1
            return result
        try:
            usage = json.loads(result["data"]).get("usage") or {}
            self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(usage.get("completion_tokens") or 0)
        except (ValueError, TypeError):
            pass
        return result


def ask_before(question: str) -> dict:
    """수정 전 경로: FAQ·캐시·경로판단 없이 곧장 AI에게."""

    from app.services import trade_insight_service

    started = time.perf_counter()
    messages = [{"role": "system", "content": support_chat_service.SYSTEM_PROMPT},
                {"role": "system", "content": support_chat_service._incoterms_reference()},
                {"role": "system", "content": support_chat_service._today_note()},
                {"role": "user", "content": question}]
    result = ai_client.chat(messages, max_tokens=support_chat_service.MAX_ANSWER_TOKENS,
                            tools=trade_insight_service.TOOLS,
                            run_tool=trade_insight_service.run_tool,
                            force_tool=support_chat_service.wants_data(question))
    total = (time.perf_counter() - started) * 1000
    return {"ok": bool(result["success"]), "total_ms": round(total, 1),
            "stages": {"llm_ms": round(total, 1)}, "route": "llm"}


def ask_after(question: str) -> dict:
    started = time.perf_counter()
    try:
        answer = support_chat_service.ask(question)
    except Exception as error:                        # noqa: BLE001
        return {"ok": False, "total_ms": round((time.perf_counter() - started) * 1000, 1),
                "stages": {}, "route": f"error:{type(error).__name__}"}
    total = (time.perf_counter() - started) * 1000
    data = answer.get("data") or {}
    trace = data.get("trace") or {}
    return {"ok": bool(answer.get("success")), "total_ms": round(total, 1),
            "stages": trace.get("stages", {}),
            "route": data.get("route") or answer.get("source", "")}


def summarize(rows: list[dict], counter: Counter, label: str, n_questions: int) -> dict:
    times = sorted(row["total_ms"] for row in rows)
    def stage(name):
        values = [row["stages"].get(name, 0) for row in rows if row["stages"].get(name)]
        return round(statistics.median(values), 1) if values else 0.0
    return {"label": label, "samples": len(rows), "questions": n_questions,
            "p50_ms": round(statistics.median(times), 1) if times else 0,
            "p95_ms": round(times[int(len(times) * 0.95) - 1], 1) if times else 0,
            # 체인 단계별 중앙값. analyze/route는 우리 규칙이라 아주 짧고, search에
            # 임베딩 호출이, lookup에 바깥 API가, llm에 답 쓰기가 들어갑니다.
            "analyze_ms_p50": stage("analyze_ms"), "search_ms_p50": stage("search_ms"),
            "route_ms_p50": stage("route_ms"), "lookup_ms_p50": stage("lookup_ms"),
            "llm_ms_p50": stage("llm_ms"), "chain_ms_p50": stage("chain_ms"),
            "llm_calls": counter.llm, "embed_calls": counter.embed,
            "llm_calls_per_question": round(counter.llm / max(1, len(rows)), 3),
            "prompt_tokens": counter.prompt_tokens,
            "completion_tokens": counter.completion_tokens,
            "tokens_per_question": round((counter.prompt_tokens + counter.completion_tokens)
                                         / max(1, len(rows))),
            "errors": counter.errors,
            "routes": {name: sum(1 for row in rows if row["route"] == name)
                       for name in sorted({row["route"] for row in rows})}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=12, help="질문 수")
    parser.add_argument("--repeat", type=int, default=2, help="질문당 반복 횟수")
    parser.add_argument("--stub", action="store_true")
    parser.add_argument("--warm", action="store_true", help="after를 캐시가 찬 상태로도 재기")
    args = parser.parse_args()

    items = questions(args.n)
    faq_index.load(force=True)
    before_rows, after_rows = [], []
    before_counter, after_counter = Counter(args.stub), Counter(args.stub)

    faq_cache.clear()
    for repeat in range(args.repeat):
        for index, item in enumerate(items):
            # 순서를 번갈아 섞습니다. (바깥 API가 느려진 시각이 한쪽에만 몰리지 않게)
            first_after = (index + repeat) % 2 == 0
            order = ("after", "before") if first_after else ("before", "after")
            for which in order:
                if which == "before":
                    with before_counter:
                        before_rows.append(ask_before(item["question"]))
                else:
                    with after_counter:
                        after_rows.append(ask_after(item["question"]))

    summaries = [summarize(before_rows, before_counter, "before", len(items)),
                 summarize(after_rows, after_counter, "after(캐시 빔→참 섞임)", len(items))]

    if args.warm:
        warm_counter = Counter(args.stub)
        warm_rows = []
        with warm_counter:
            for item in items:                     # 캐시가 이미 찬 상태
                warm_rows.append(ask_after(item["question"]))
        summaries.append(summarize(warm_rows, warm_counter, "after(캐시 참)", len(items)))

    OUT.mkdir(parents=True, exist_ok=True)
    name = f"speed_{'stub' if args.stub else 'real'}_n{args.n}x{args.repeat}.json"
    (OUT / name).write_text(json.dumps(
        {"summaries": summaries, "before": before_rows, "after": after_rows},
        ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"질문 {len(items)}개 × 반복 {args.repeat}회 "
          f"({'모의' if args.stub else '실제 OpenAI'})")
    for row in summaries:
        print(json.dumps(row, ensure_ascii=False))
    print(f"\n{(OUT / name).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
