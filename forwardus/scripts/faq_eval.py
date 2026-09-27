"""개선 전/후를 같은 질문·같은 모델로 견줍니다.

    python -m scripts.faq_eval --mode before --llm stub
    python -m scripts.faq_eval --mode after  --llm stub
    python -m scripts.faq_eval --mode after  --llm real --sample 15      실제 API (돈이 듭니다)

모드
  before  FAQ 검색·캐시를 끄고 지금까지처럼 매번 AI에게 묻습니다.
  after   FAQ 검색·캐시를 켭니다.

llm
  stub  AI를 부르지 않고 고정 지연(--llm-latency 밀리초)만 흉내 냅니다.
        검색 품질·경로 선택·캐시 적중은 그대로 재고, 지연은 "AI를 부른 횟수 × 지연"으로 봅니다.
  real  실제 OpenAI를 부릅니다. 토큰·지연이 진짜 값입니다. --sample 로 개수를 줄이세요.

재는 것
  경로 분포 · Recall@1/3/5 · 정답 FAQ 선택률 · 틀린 FAQ 직접 반환율 ·
  허용 경로 준수율 · 응답 시간 p50/p95 · AI 호출 수 · 토큰 · 캐시 적중률
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

EVAL_DIR = ROOT / "data" / "faq" / "eval"
# 어떤 평가 파일을 쓸지. 기본은 150문항(회귀), --set final 이면 최종 독립 60문항.
EVAL_SETS = {"regression": "eval_*.jsonl", "final": "final_v2.jsonl",
             "final3": "final_v3.jsonl"}
RESULT_DIR = EVAL_DIR / "results"
STUB_ANSWER = ("(stub) 질문을 받았습니다. 조건에 따라 달라질 수 있으니 관세사·세관에 확인하세요.")


def load_questions(which: str = "regression") -> list[dict]:
    rows = []
    for path in sorted(EVAL_DIR.glob(EVAL_SETS[which])):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class Recorder:
    """AI 호출 횟수·토큰·지연을 셉니다. (stub이면 부르지 않고 흉내만)"""

    def __init__(self, mode: str, latency_ms: int):
        self.mode = mode
        self.latency = latency_ms / 1000
        self.calls = 0
        self.embed_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._real = ai_client.request_text

    def __enter__(self):
        if self.mode == "stub":
            ai_client.request_text = self._stub
        else:
            ai_client.request_text = self._measured
        return self

    def __exit__(self, *_):
        ai_client.request_text = self._real

    def _stub(self, method, url, **kwargs):
        # 임베딩은 흉내 내지 않고 실제로 부릅니다. 흉내 내면 검색이 낱말만 쓰게 되어
        # 무엇을 재는지 알 수 없게 됩니다. (임베딩은 싸고 빠릅니다)
        if url.endswith("/embeddings"):
            self.embed_calls += 1
            return self._real(method, url, **kwargs)
        self.calls += 1
        payload = kwargs.get("json") or {}
        # 토큰은 글자 수로 어림합니다. (한국어 대략 2.2자 = 1토큰)
        chars = sum(len(str(message.get("content") or ""))
                    for message in payload.get("messages") or [])
        self.prompt_tokens += round(chars / 2.2)
        self.completion_tokens += 120
        time.sleep(self.latency)
        body = {"choices": [{"message": {"content": STUB_ANSWER}}]}
        return {"success": True, "source": "api", "data": json.dumps(body)}

    def _measured(self, method, url, **kwargs):
        if url.endswith("/embeddings"):
            self.embed_calls += 1
            return self._real(method, url, **kwargs)
        self.calls += 1
        result = self._real(method, url, **kwargs)
        if result.get("success"):
            try:
                usage = json.loads(result["data"]).get("usage") or {}
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
            except (ValueError, TypeError):
                pass
        return result


def run(mode: str, llm: str, latency_ms: int, sample: int | None, warm: bool,
        which: str = "regression") -> dict:
    questions = load_questions(which)
    if sample and sample < len(questions):
        # 앞에서 N개를 자르면 유형이 쏠립니다(앞쪽이 전부 faq_typical). 고르게 띄어서 뽑습니다.
        stride = len(questions) / sample
        questions = [questions[int(i * stride)] for i in range(sample)]
    faq_cache.clear()
    faq_index.load(force=True)

    rows = []
    with Recorder(llm, latency_ms) as recorder:
        if warm:                                   # 캐시가 채워진 상태를 보려면 한 바퀴 먼저
            for item in questions:
                _ask(item, mode)
            faq_cache_stats_before = faq_cache.stats()
        else:
            faq_cache_stats_before = faq_cache.stats()
        for item in questions:
            before_calls = recorder.calls
            started = time.perf_counter()
            answer = _ask(item, mode)
            elapsed = (time.perf_counter() - started) * 1000
            hits = faq_index.search(item["question"], 5) if mode == "after" else ()
            rows.append({
                "id": item["id"], "type": item["type"], "question": item["question"],
                "gold": item.get("gold_faq_id"), "allowed_paths": item.get("allowed_paths") or [],
                "source": answer.get("source"),
                "route": (answer.get("data") or {}).get("route", ""),
                "evidence": [item["status"] for item in
                             ((answer.get("data") or {}).get("evidence") or [])],
                "faq_id": (answer.get("data") or {}).get("faq_id"),
                "faq_context": (answer.get("data") or {}).get("faq_context") or [],
                "top_ids": [faq["id"] for faq, *_ in hits],
                "top_scores": [score for _, score, *_ in hits],
                "top_similarity": [row[3] if len(row) > 3 else 0.0 for row in hits],
                "llm_calls": recorder.calls - before_calls, "ms": round(elapsed, 1),
                "answer_chars": len((answer.get("data") or {}).get("answer") or ""),
            })
    return {"mode": mode, "llm": llm, "warm_cache": warm, "rows": rows,
            "llm_calls": recorder.calls, "embed_calls": recorder.embed_calls,
            "prompt_tokens": recorder.prompt_tokens,
            "completion_tokens": recorder.completion_tokens,
            "cache": faq_cache.stats(), "cache_before": faq_cache_stats_before,
            "kb_version": faq_index.kb_version(),
            "thresholds": faq_index.thresholds()}


def _ask(item: dict, mode: str) -> dict:
    if mode == "before":
        return _ask_without_faq(item["question"])
    try:
        return support_chat_service.ask(item["question"])
    except Exception as error:                       # noqa: BLE001 - 평가는 멈추지 않습니다
        return {"success": False, "source": "error", "data": {"answer": str(error)}}


def _ask_without_faq(question: str) -> dict:
    """개선 전 경로. FAQ·캐시를 건너뛰고 예전처럼 곧장 AI에게 묻습니다."""

    from app.services import trade_insight_service

    messages = [{"role": "system", "content": support_chat_service.SYSTEM_PROMPT},
                {"role": "system", "content": support_chat_service._incoterms_reference()},
                {"role": "system", "content": support_chat_service._today_note()},
                {"role": "user", "content": question}]
    result = ai_client.chat(messages, max_tokens=support_chat_service.MAX_ANSWER_TOKENS,
                            tools=trade_insight_service.TOOLS,
                            run_tool=trade_insight_service.run_tool,
                            force_tool=support_chat_service.wants_data(question))
    if not result["success"]:
        return {"success": False, "source": result["source"], "data": {"answer": ""}}
    return {"success": True, "source": "api", "data": {"answer": result["data"]}}


def summarize(result: dict) -> dict:
    rows = result["rows"]
    times = sorted(row["ms"] for row in rows)
    labelled = [row for row in rows if row["gold"]]
    # 캐시에서 나온 답은 "무엇을 캐시했는지"로 갈립니다. FAQ를 담아 둔 것이면 FAQ 직접 반환이고,
    # AI 답을 담아 둔 것이면 AI 경로입니다. 뭉뚱그리면 경로 준수율이 엉뚱하게 나옵니다.
    directs = [row for row in rows
               if row["source"] == "faq" or (row["source"] == "cache" and row["faq_id"])]
    wrong_direct = [row for row in directs if row["gold"] and row["faq_id"] != row["gold"]]
    no_gold_direct = [row for row in directs if not row["gold"]]

    def recall(k: int) -> float:
        if not labelled:
            return 0.0
        return sum(1 for row in labelled if row["gold"] in row["top_ids"][:k]) / len(labelled)

    def path_of(row: dict) -> str:
        if row["source"] == "cache":
            return "faq_direct" if row["faq_id"] else (row.get("route") or "llm")
        if row["source"] == "api":
            # api로 나갔어도 근거를 조회했는지에 따라 경로가 다릅니다.
            return row.get("route") or "llm"
        return {"faq": "faq_direct", "clarification": "clarification",
                "calculated": "general_guidance", "error": "error"}.get(
                    row["source"], row["source"])

    # 평가 파일마다 경로 이름이 조금 다릅니다(옛 세트: ask_more/live_lookup/out_of_scope).
    ALIAS = {"llm": {"llm", "faq_context", "general_guidance", "out_of_scope"},
             "faq_direct": {"faq_direct"},
             "faq_context": {"llm", "faq_context", "general_guidance"},
             "general_guidance": {"llm", "general_guidance", "out_of_scope"},
             "clarification": {"clarification", "ask_more"},
             "external_lookup": {"external_lookup", "live_lookup", "llm"},
             "faq_direct": {"faq_direct"}}
    allowed_ok = [row for row in rows if not row["allowed_paths"]
                  or ALIAS.get(path_of(row), {path_of(row)}) & set(row["allowed_paths"])]
    return {
        "mode": result["mode"], "llm": result["llm"], "warm_cache": result["warm_cache"],
        "questions": len(rows),
        "route": {name: sum(1 for row in rows if row["source"] == name)
                  for name in sorted({row["source"] for row in rows})},
        "path": {name: sum(1 for row in rows if path_of(row) == name)
                 for name in sorted({path_of(row) for row in rows})},
        "p50_ms": round(statistics.median(times), 1) if times else 0,
        "p95_ms": round(times[int(len(times) * 0.95) - 1], 1) if times else 0,
        "mean_ms": round(statistics.fmean(times), 1) if times else 0,
        # 측정 구간에서 실제로 부른 횟수만 셉니다. 캐시를 채우는 워밍업 바퀴의 호출을
        # 질문 수로 나누면 "질문당 호출"이 부풀려집니다. (옛 보고서의 1.087이 그 경우)
        "llm_calls": sum(row["llm_calls"] for row in rows),
        "llm_calls_total_including_warmup": result["llm_calls"],
        "llm_calls_per_question": round(
            sum(row["llm_calls"] for row in rows) / max(1, len(rows)), 3),
        "embed_calls": result.get("embed_calls", 0),
        "prompt_tokens": result["prompt_tokens"], "completion_tokens": result["completion_tokens"],
        "tokens_per_question": round((result["prompt_tokens"] + result["completion_tokens"])
                                     / max(1, len(rows))),
        "recall@1": round(recall(1), 4), "recall@3": round(recall(3), 4),
        "recall@5": round(recall(5), 4),
        "labelled_questions": len(labelled),
        "direct_returns": len(directs),
        "direct_correct": len(directs) - len(wrong_direct) - len(no_gold_direct),
        "direct_wrong_faq": len(wrong_direct),
        "direct_without_gold": len(no_gold_direct),
        "allowed_path_rate": round(len(allowed_ok) / max(1, len(rows)), 4),
        # 캐시는 두 가지로 봅니다: 질문 몇 건이 캐시로 답했나(분모=질문 수),
        # 그리고 get()이 몇 번 맞았나(분모=조회 횟수). 옛 보고서는 이 둘을 섞었습니다.
        "cache_answered_questions": sum(1 for row in rows if row["source"] == "cache"),
        "cache_answered_rate": round(
            sum(1 for row in rows if row["source"] == "cache") / max(1, len(rows)), 4),
        "cache": result["cache"], "kb_version": result["kb_version"],
        "thresholds": result["thresholds"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("before", "after"), required=True)
    parser.add_argument("--llm", choices=("stub", "real"), default="stub")
    parser.add_argument("--llm-latency", type=int, default=0,
                        help="stub일 때 AI 호출 한 번에 넣을 지연(ms)")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--warm", action="store_true", help="캐시가 채워진 상태로 측정")
    parser.add_argument("--tag", default="")
    parser.add_argument("--set", dest="which", choices=tuple(EVAL_SETS), default="regression")
    args = parser.parse_args()

    result = run(args.mode, args.llm, args.llm_latency, args.sample, args.warm, args.which)
    summary = summarize(result)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    name = (f"{args.which}_{args.mode}_{args.llm}{'_warm' if args.warm else ''}"
            f"{('_' + args.tag) if args.tag else ''}")
    (RESULT_DIR / f"{name}.json").write_text(
        json.dumps({"summary": summary, "rows": result["rows"]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
