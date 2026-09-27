"""FAQ 조각(parts/*.jsonl)을 모아 검증하고, 지식베이스와 사람이 읽을 문서를 만듭니다.

    python -m scripts.faq_build            검증 + data/faq/faq.jsonl · faq.md · faq_meta.json 갱신
    python -m scripts.faq_build --check    검증만 (고치지 않음)

하는 일
  1. 규격(SCHEMA.md) 검사: 필드 존재·개수·ID 범위·분류명·중복 질문
  2. 위험한 값 검사: review_status "검증 완료"는 사람이 검토한 뒤에만
  3. faq.jsonl 합치기 (ID 순서) · faq.md 만들기
  4. faq_meta.json 에 kb_version(내용 해시)·건수·갱신일 기록 → 캐시가 저절로 버려집니다

갱신·삭제 방법
  parts/*.jsonl 을 고치고 다시 돌리면 됩니다. FAQ 하나를 지우려면 그 줄을 지우고
  다시 돌리세요. 버전을 올리려면 그 FAQ의 "version" 값을 올립니다.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAQ_DIR = ROOT / "data" / "faq"
PARTS = FAQ_DIR / "parts"

CATEGORY_QUOTA = {
    "수출 준비·거래처 검증": (10, 1, 10),
    "견적·계약·Incoterms": (15, 11, 25),
    "결제·신용장·대금 회수": (15, 26, 40),
    "HS 코드·수출신고·통관": (15, 41, 55),
    "원산지·FTA·인증·수출통제": (15, 56, 70),
    "운송·포워딩·보험·선적 일정": (15, 71, 85),
    "무역서류 작성·불일치·정정": (10, 86, 95),
    "클레임·반품·사후관리": (5, 96, 100),
}
REQUIRED = ["id", "category", "question", "question_variants", "short_answer",
            "detailed_answer", "required_context", "cautions", "keywords", "sources",
            "applicability", "freshness", "review_status", "version", "review", "effective"]
REVIEW_STATES = {"pending", "approved", "rejected"}
FRESHNESS = {"안정적 지식", "정기 확인 필요", "실시간 확인 필요"}
REVIEW = {"검증 완료", "전문가 검토 필요"}
ALLOWED_HOSTS = ("customs.go.kr", "unipass.customs.go.kr", "fta.go.kr", "law.go.kr",
                 "motie.go.kr", "ktc.go.kr", "yestrade.go.kr", "kotra.or.kr", "kita.net",
                 "tradenavi.or.kr", "ksure.or.kr", "korcham.net", "ktnet.co.kr",
                 "mfds.go.kr", "nts.go.kr", "iccwbo.org", "wcoomd.org", "wto.org",
                 "cbp.gov", "fda.gov", "europa.eu", "customs.gov.cn", "customs.go.jp",
                 "kcab.or.kr", "trade.go.kr", "keit.re.kr", "epis.or.kr", "kcs.go.kr")


def load_parts() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(PARTS.glob("*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise SystemExit(f"{path.name}:{number} JSON 오류 — {error}")
    return rows


def check(rows: list[dict]) -> list[str]:
    problems: list[str] = []
    seen_ids: Counter = Counter()
    seen_questions: dict[str, str] = {}
    by_category: Counter = Counter()

    for row in rows:
        rid = row.get("id", "?")
        missing = [field for field in REQUIRED if field not in row]
        if missing:
            problems.append(f"{rid}: 빠진 필드 {missing}")
            continue
        seen_ids[rid] += 1
        by_category[row["category"]] += 1
        if row["category"] not in CATEGORY_QUOTA:
            problems.append(f"{rid}: 모르는 분류 '{row['category']}'")
        else:
            _, low, high = CATEGORY_QUOTA[row["category"]]
            try:
                number = int(str(rid).split("-")[1])
            except (IndexError, ValueError):
                problems.append(f"{rid}: id 모양이 EXP-001이 아닙니다")
                number = -1
            if number >= 0 and not low <= number <= high:
                problems.append(f"{rid}: 분류의 ID 범위(EXP-{low:03d}~{high:03d}) 밖")
        if len(row.get("question_variants") or []) != 3:
            problems.append(f"{rid}: question_variants는 3개여야 합니다")
        if row.get("freshness") not in FRESHNESS:
            problems.append(f"{rid}: freshness 값이 규격 밖 '{row.get('freshness')}'")
        if row.get("review_status") not in REVIEW:
            problems.append(f"{rid}: review_status 값이 규격 밖 '{row.get('review_status')}'")
        if row.get("review_status") == "검증 완료":
            problems.append(f"{rid}: 사람이 검토하기 전에는 '검증 완료'를 쓸 수 없습니다")
        review = row.get("review") or {}
        if review.get("review_status") not in REVIEW_STATES:
            problems.append(f"{rid}: review.review_status 가 규격 밖 '{review.get('review_status')}'")
        if review.get("review_status") == "approved":
            if not str(review.get("reviewer", "")).strip():
                problems.append(f"{rid}: 승인인데 검토자(reviewer)가 비었습니다")
            # 내용이 바뀌면(version이 올라가면) 예전 승인은 무효입니다. 되돌립니다.
            if str(review.get("approved_version", "")) != str(row.get("version", "")):
                review.update(review_status="pending", reviewer="", reviewed_at="",
                              approved_version="",
                              review_notes=f"내용이 version {row.get('version')} 으로 바뀌어 "
                                           "승인을 되돌렸습니다. 다시 검토가 필요합니다.")
                problems.append(f"{rid}: 내용이 바뀌어 승인을 pending으로 되돌렸습니다 (재검토 필요)")
        if not row.get("sources"):
            problems.append(f"{rid}: sources가 비었습니다")
        for source in row.get("sources") or []:
            url = str(source.get("url", ""))
            if not url.startswith("http"):
                problems.append(f"{rid}: 출처 URL이 아닙니다 — {url}")
            elif not any(host in url for host in ALLOWED_HOSTS):
                problems.append(f"{rid}: 허용 목록 밖 출처 — {url}")
        if len(row.get("keywords") or []) < 4:
            problems.append(f"{rid}: keywords가 너무 적습니다")
        key = "".join(str(row.get("question", "")).split())
        if key in seen_questions:
            problems.append(f"{rid}: {seen_questions[key]} 와 질문이 같습니다")
        seen_questions[key] = rid

    for rid, count in seen_ids.items():
        if count > 1:
            problems.append(f"{rid}: id가 {count}번 나옵니다")
    for category, (quota, _, _) in CATEGORY_QUOTA.items():
        if by_category.get(category, 0) != quota:
            problems.append(f"분류 '{category}': {by_category.get(category, 0)}개 (규격 {quota}개)")
    if len(rows) != 100:
        problems.append(f"전체 {len(rows)}개 (규격 100개)")
    return problems


def write(rows: list[dict]) -> dict:
    rows.sort(key=lambda row: row["id"])
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    (FAQ_DIR / "faq.jsonl").write_text(body, encoding="utf-8")

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    meta_path = FAQ_DIR / "faq_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    approved = sum(1 for row in rows if (row.get("review") or {}).get("review_status") == "approved")
    meta.update(kb_version=digest, count=len(rows), approved=approved,
                updated_on=date.today().isoformat(),
                categories={category: sum(1 for row in rows if row["category"] == category)
                            for category in CATEGORY_QUOTA})
    meta.setdefault("thresholds", {})
    meta.setdefault("approval_version", "0")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# 수출 실무 FAQ 100 (검토용)", "",
             f"- 버전 `{digest}` · {len(rows)}건 · 갱신 {meta['updated_on']}",
             "- 작성: ForwardUs / **아직 전문가 검토 전입니다.** 검토한 건만 review_status를 올리세요.",
             "- 규격은 `SCHEMA.md`, 원본은 `faq.jsonl`. 고칠 때는 `parts/*.jsonl`을 고치고",
             "  `python -m scripts.faq_build` 를 다시 돌립니다.", ""]
    for category in CATEGORY_QUOTA:
        lines.append(f"## {category}")
        lines.append("")
        for row in [row for row in rows if row["category"] == category]:
            lines += [f"### {row['id']} {row['question']}", "",
                      f"- **결론** {row['short_answer']}", "",
                      row["detailed_answer"], ""]
            if row.get("cautions"):
                lines += ["**주의**"] + [f"- {line}" for line in row["cautions"]] + [""]
            if row.get("required_context"):
                lines += ["**더 알아야 하는 것**"] + [f"- {line}" for line in row["required_context"]] + [""]
            sources = " · ".join(f"[{row2.get('name','')}]({row2.get('url','')})"
                                 for row2 in row.get("sources") or [])
            lines += [f"**출처** {sources}", "",
                      f"`{row['freshness']}` · `{row['review_status']}` · "
                      f"적용 {json.dumps(row.get('applicability', {}), ensure_ascii=False)} · "
                      f"키워드 {', '.join(row.get('keywords') or [])}", "", "---", ""]
    (FAQ_DIR / "faq.md").write_text("\n".join(lines), encoding="utf-8")
    return meta


def main() -> int:
    rows = load_parts()
    problems = check(rows)
    for problem in problems:
        print("문제:", problem)
    if "--check" in sys.argv:
        print(f"{len(rows)}건 검사 · 문제 {len(problems)}건")
        return 1 if problems else 0
    if problems:
        print(f"\n문제 {len(problems)}건이라 저장하지 않았습니다. 고치고 다시 돌리세요.")
        return 1
    meta = write(rows)
    print(f"저장했습니다. {meta['count']}건 · 승인 {meta['approved']}건 · "
          f"kb_version {meta['kb_version']} · approval_version {meta['approval_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
