"""답변을 채점해 정확성을 %로 냅니다. (자동 채점 — 사람 검토의 대체가 아닙니다)

    python -m scripts.faq_grade --n 70              현재 코드(after)를 채점
    python -m scripts.faq_grade --n 70 --both       수정 전(before)과 함께 채점해 비교

어떻게 채점하나
  평가 세트(final_v3)의 문항마다 작성자가 적어 둔 채점 기준(expected_points)과
  경로별 필수 조건(path_requirements)이 있습니다. 답변이 그 기준을 지켰는지
  **다른 모델 호출(gpt-4o-mini)** 에게 물어 0/1로 셉니다.

무엇을 믿을 수 있고 무엇은 못 믿나
  - 셀 수 있는 것: 기준 항목을 답변이 담았는가 / 금지된 단정을 했는가 / 되물었는가
  - 못 믿는 것: 무역 실무상 그 답이 진짜 맞는지. 그건 관세사가 봐야 합니다.
  그래서 이 점수는 **'기준 충족률'** 이지 '정답률'이 아닙니다. 보고서에도 그렇게 씁니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.collectors import ai_client  # noqa: E402
from app.services import faq_cache, support_chat_service  # noqa: E402

EVAL = ROOT / "data" / "faq" / "eval"
OUT = EVAL / "results"

JUDGE_PROMPT = """당신은 무역 상담 답변을 채점합니다. 관대하게 주지 마세요.

아래 질문과 채점 기준, 그리고 상담 답변을 봅니다. 기준마다 답변이 그 내용을 담았는지
0(아니다) 또는 1(그렇다)로만 답합니다. 비슷한 말이면 1, 언급이 없거나 반대로 말하면 0입니다.

추가로 세 가지를 봅니다.
- unsupported_claim: 공식 근거 없이 규정·세율·허용 여부를 단정했으면 1, 아니면 0
- admits_unknown: 확인하지 못한 것을 확인하지 못했다고 밝혔으면 1, 그럴 필요가 없었으면 1, 숨겼으면 0
- useful: 질문에 실제로 쓸모 있는 내용을 주었으면 1, 되묻기만 하거나 빈 답이면 0
  (단, 되물어야 마땅한 질문이면 되물은 것도 useful 1로 봅니다)

JSON만 출력합니다. 설명하지 마세요.
{"points": [0 또는 1, ...], "unsupported_claim": 0, "admits_unknown": 1, "useful": 1}"""


def load(n: int) -> list[dict]:
    rows = [json.loads(line) for line in (EVAL / "final_v3.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if n >= len(rows):
        return rows
    stride = len(rows) / n
    return [rows[int(i * stride)] for i in range(n)]


def answer_after(question: str) -> dict:
    result = support_chat_service.ask(question)
    data = result.get("data") or {}
    return {"answer": data.get("answer", ""), "route": data.get("route") or result.get("source")}


def answer_before(question: str) -> dict:
    from app.services import trade_insight_service

    messages = [{"role": "system", "content": support_chat_service.SYSTEM_PROMPT},
                {"role": "system", "content": support_chat_service._incoterms_reference()},
                {"role": "system", "content": support_chat_service._today_note()},
                {"role": "user", "content": question}]
    result = ai_client.chat(messages, max_tokens=support_chat_service.MAX_ANSWER_TOKENS,
                            tools=trade_insight_service.TOOLS,
                            run_tool=trade_insight_service.run_tool,
                            force_tool=support_chat_service.wants_data(question))
    return {"answer": result["data"] if result["success"] else "", "route": "llm"}


def judge(item: dict, answer: str) -> dict:
    points = item.get("expected_points") or []
    rules = item.get("path_requirements") or {}
    body = (f"[질문]\n{item['question']}\n\n"
            f"[채점 기준]\n" + "\n".join(f"{i+1}. {point}" for i, point in enumerate(points))
            + ("\n\n[경로별 지켜야 할 것]\n" + "\n".join(f"- {k}: {v}" for k, v in rules.items())
               if rules else "")
            + (f"\n\n[되물어야 할 것]\n" + "\n".join(f"- {ask}" for ask in item["must_ask"])
               if item.get("must_ask") else "")
            + f"\n\n[상담 답변]\n{answer[:4000]}")
    result = ai_client.chat([{"role": "system", "content": JUDGE_PROMPT},
                             {"role": "user", "content": body}], max_tokens=300)
    if not result["success"]:
        return {"points": [0] * len(points), "unsupported_claim": 0, "admits_unknown": 0,
                "useful": 0, "judge_failed": True}
    text = result["data"]
    match = re.search(r"\{.*\}", text, re.S)
    try:
        parsed = json.loads(match.group(0)) if match else {}
    except ValueError:
        parsed = {}
    scored = list(parsed.get("points") or [])[:len(points)]
    scored += [0] * (len(points) - len(scored))
    return {"points": scored, "unsupported_claim": int(parsed.get("unsupported_claim") or 0),
            "admits_unknown": int(parsed.get("admits_unknown") or 0),
            "useful": int(parsed.get("useful") or 0), "judge_failed": False}


def run(items: list[dict], mode: str) -> dict:
    rows = []
    for item in items:
        faq_cache.clear()
        produced = answer_after(item["question"]) if mode == "after" else answer_before(
            item["question"])
        verdict = judge(item, produced["answer"])
        rows.append({"id": item["id"], "type": item["type"], "route": produced["route"],
                     "points_total": len(item.get("expected_points") or []),
                     "points_met": sum(verdict["points"]),
                     "unsupported_claim": verdict["unsupported_claim"],
                     "admits_unknown": verdict["admits_unknown"], "useful": verdict["useful"],
                     "judge_failed": verdict["judge_failed"],
                     "answer_chars": len(produced["answer"])})
        time.sleep(0.2)
    total_points = sum(row["points_total"] for row in rows) or 1
    met = sum(row["points_met"] for row in rows)
    n = len(rows) or 1
    return {"mode": mode, "questions": len(rows),
            "criteria_met_rate": round(met / total_points, 4), "criteria_met": met,
            "criteria_total": total_points,
            "full_marks_rate": round(sum(1 for row in rows
                                         if row["points_met"] == row["points_total"]) / n, 4),
            "unsupported_claim_rate": round(sum(row["unsupported_claim"] for row in rows) / n, 4),
            "admits_unknown_rate": round(sum(row["admits_unknown"] for row in rows) / n, 4),
            "useful_rate": round(sum(row["useful"] for row in rows) / n, 4),
            "judge_failures": sum(1 for row in rows if row["judge_failed"]),
            "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=70)
    parser.add_argument("--both", action="store_true")
    args = parser.parse_args()

    items = load(args.n)
    results = [run(items, "after")]
    if args.both:
        results.append(run(items, "before"))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"grade_n{len(items)}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"자동 채점 (문항 {len(items)}개) — 사람 검토 아님")
    for row in results:
        print(f"\n[{row['mode']}]")
        print(f"  기준 충족률   {row['criteria_met_rate']:.1%} "
              f"({row['criteria_met']}/{row['criteria_total']})")
        print(f"  전항목 충족   {row['full_marks_rate']:.1%}")
        print(f"  근거 없는 단정 {row['unsupported_claim_rate']:.1%}")
        print(f"  모름 인정     {row['admits_unknown_rate']:.1%}")
        print(f"  유용성        {row['useful_rate']:.1%}")
        print(f"  채점 실패     {row['judge_failures']}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
