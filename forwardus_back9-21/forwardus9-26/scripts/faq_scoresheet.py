"""사람이 채점할 자료를 만듭니다. (자동 지표로는 못 보는 것들)

    python -m scripts.faq_scoresheet --n 20          실제 답변을 받아 채점표를 만듭니다
    python -m scripts.faq_scoresheet --n 20 --blind  어느 쪽이 수정 전/후인지 가립니다

왜 만드나
  검색이 맞았는지는 기계가 셉니다. 그러나 "답이 실제로 쓸모 있는지", "미검토 자료를
  검증된 사실처럼 말하지 않았는지"는 사람이 읽어야 압니다. 자동 점수로 대신하지 않습니다.

채점 항목 (각 0~2점: 0 아니다 · 1 부분 · 2 그렇다)
  1 정확성      질문에 맞는 답인가
  2 완전성      필요한 내용을 빠뜨리지 않았나
  3 조건 일치   나라·품목·시점 조건을 지켰나
  4 근거 일치   규정 주장에 공식 근거가 붙었나 (근거 없는 단정은 0점)
  5 출처 표시   출처·시행일·조회 시각이 적절히 보이나
  6 모름 인정   확인 못 한 것을 확인 못 했다고 했나
  7 과장 금지   미승인 FAQ를 전문가가 검증한 사실처럼 말하지 않았나
  8 유용성      (악성 지시가 섞인 문항) 정상 질문에는 제대로 답했나
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import support_chat_service  # noqa: E402

EVAL = ROOT / "data" / "faq" / "eval"
OUT = EVAL / "review"


def load(n: int) -> list[dict]:
    rows = [json.loads(line) for line in (EVAL / "final_v3.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if n >= len(rows):
        return rows
    stride = len(rows) / n
    return [rows[int(i * stride)] for i in range(n)]


def answer_before(question: str) -> dict:
    from app.collectors import ai_client
    from app.services import trade_insight_service

    messages = [{"role": "system", "content": support_chat_service.SYSTEM_PROMPT},
                {"role": "system", "content": support_chat_service._incoterms_reference()},
                {"role": "system", "content": support_chat_service._today_note()},
                {"role": "user", "content": question}]
    result = ai_client.chat(messages, max_tokens=support_chat_service.MAX_ANSWER_TOKENS,
                            tools=trade_insight_service.TOOLS,
                            run_tool=trade_insight_service.run_tool,
                            force_tool=support_chat_service.wants_data(question))
    return {"answer": result["data"] if result["success"] else f"(실패) {result['message']}",
            "route": "llm", "evidence": []}


def answer_after(question: str) -> dict:
    result = support_chat_service.ask(question)
    data = result.get("data") or {}
    return {"answer": data.get("answer", ""), "route": data.get("route") or result.get("source"),
            "evidence": [f"{item['status']} · {item['agency']} {item['document']}"
                         for item in (data.get("evidence") or [])]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--blind", action="store_true")
    parser.add_argument("--seed", type=int, default=20260924)
    args = parser.parse_args()

    random.seed(args.seed)
    items = load(args.n)
    OUT.mkdir(parents=True, exist_ok=True)

    lines = ["# 사람 채점표 — 무역 상담 답변", "",
             "각 항목 0(아니다) · 1(부분) · 2(그렇다). 빈칸으로 두지 말고 이유를 한 줄 적어 주세요.",
             "", "> **아직 아무도 채점하지 않았습니다.** 이 파일은 채점을 받기 위한 자료입니다.",
             "> 채점자: __________  날짜: __________  소속·자격: __________", ""]
    key = []
    for index, item in enumerate(items, 1):
        pair = [("A", answer_before(item["question"])), ("B", answer_after(item["question"]))]
        if args.blind:
            random.shuffle(pair)
        key.append({"no": index, "id": item["id"],
                    "A": "before" if pair[0][1]["route"] == "llm" and not args.blind else
                         ("before" if pair[0][1] is pair[0][1] and pair[0][0] == "A" and
                          pair[0][1].get("route") == "llm" else "after"),
                    "mapping": {label: ("before" if body["route"] == "llm" and
                                        not body["evidence"] else "after")
                                for label, body in pair}})
        lines += [f"## {index}. [{item['id']}] {item['type']}", "",
                  f"**질문** {item['question']}", "",
                  "**채점 기준(작성자가 적어 둔 것)**"]
        lines += [f"- {point}" for point in item.get("expected_points", [])]
        if item.get("must_ask"):
            lines += ["", "**되물어야 할 것**"] + [f"- {ask}" for ask in item["must_ask"]]
        lines += ["", f"**허용 경로** {', '.join(item.get('allowed_paths', []))}", ""]
        for label, body in pair:
            lines += [f"### 답변 {label}", "",
                      "```", body["answer"][:2500].strip() or "(빈 답)", "```", ""]
            if body["evidence"]:
                lines += ["근거: " + " / ".join(body["evidence"]), ""]
        lines += ["| 항목 | 답변 A | 답변 B | 메모 |", "|---|---|---|---|",
                  "| 1 정확성 |  |  |  |", "| 2 완전성 |  |  |  |",
                  "| 3 조건 일치 |  |  |  |", "| 4 근거 일치 |  |  |  |",
                  "| 5 출처 표시 |  |  |  |", "| 6 모름 인정 |  |  |  |",
                  "| 7 과장 금지 |  |  |  |", "| 8 유용성 |  |  |  |", "", "---", ""]

    sheet = OUT / ("scoresheet_blind.md" if args.blind else "scoresheet.md")
    sheet.write_text("\n".join(lines), encoding="utf-8")
    (OUT / "scoresheet_key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{sheet.relative_to(ROOT)} · 문항 {len(items)}개")
    print("정답표(어느 쪽이 수정 전/후인지)는 scoresheet_key.json 에 따로 두었습니다.")
    print("채점 전에는 열지 마세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
