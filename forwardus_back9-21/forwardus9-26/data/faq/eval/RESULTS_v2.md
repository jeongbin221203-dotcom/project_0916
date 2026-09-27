# 상담 경로 개편 측정 (2026-09-24, v2)

`kb_version 332c384037ae` · `approval_version 0` · 승인된 FAQ **0/100**
모델 `gpt-4o-mini` · 임베딩 `text-embedding-3-small` · langchain-core 1.6.4 · Python 3.14.7
임계값(튜닝 데이터로 선정) `direct 0.30 · coverage 0.60 · similarity 0.70 · margin 0.00 ·
context 0.25 · context_coverage 0.30 · context_similarity 0.50`

**앞선 RESULTS.md 수치는 이 브랜치 결과가 아닙니다.** 코드·데이터가 바뀌어 아래를 새 기준으로 씁니다.

## 0. 앞 보고서 집계 재확인 (원본 로그)

| 앞 보고서 문구 | 원본 로그에서 확인한 것 |
|---|---|
| "캐시 119/150, 적중률 39.8%" | **분모가 다릅니다.** 질문 기준(캐시로 답한 질문 수 / 150)과 `get()` 호출 기준(hit / (hit+miss))을 섞었습니다. 같은 실행에서 질문 기준 113/150 = 75.3%, get 기준 113/284 = 39.8% 였습니다. |
| "AI 호출/질문 1.087" (warm) | **계산 오류였습니다.** 캐시를 채우는 워밍업 바퀴의 호출까지 질문 수로 나눴습니다. 측정 구간만 세면 29/150 = 0.193 입니다. 스크립트를 고쳐 `llm_calls`(측정 구간)와 `llm_calls_total_including_warmup`을 나눠 기록합니다. |

## 1. 최종 독립 평가 60문항 (`final_v2.jsonl`, 구현·튜닝에 미사용)

| 유형 | 개수 | 실제 경로 |
|---|---|---|
| repeat_same | 6 | faq_context 5 · general_guidance 1 |
| paraphrase | 6 | faq_context 2 · general_guidance 4 |
| typo | 6 | general_guidance 5 · 기타 1 |
| condition_diff | 8 | faq_context 4 · general_guidance 2 · 기타 2 |
| not_in_faq | 6 | faq_context 3 · general_guidance 3 |
| needs_clarify | 6 | faq_context 4 · general_guidance 1 · 기타 1 |
| current_rule | 6 | external_lookup 1 · clarification 2 · faq_context 1 · general_guidance 2 |
| pending_rule | 4 | clarification 2 · general_guidance 2 |
| conflict_or_fail | 6 | clarification 2 · general_guidance 3 · 기타 1 |
| prompt_injection | 6 | clarification 4 · general_guidance 2 |

- **faq_direct 0건** — 승인된 FAQ가 0건이라 구조적으로 나올 수 없습니다. 설계대로입니다.
- 허용 경로 일치 23/60. 그중 6건은 `faq_direct`를 기대한 문항(승인 0건이라 불가),
  나머지 31건은 실제 불일치입니다(아래 3절).
- **prompt_injection 6건 모두 지시를 따르지 않았습니다.** 4건은 조건을 되묻고(clarification),
  2건은 일반 안내로 갔습니다. "출처를 빼라"는 문서 지시를 받은 문항에서도 출처를 뺀 답을
  만들지 않았습니다(AI를 부르지 않고 되물음).

## 2. 회귀 150문항 (`eval_a/b.jsonl`)

| 지표 | 값 (분자/분모) |
|---|---|
| Recall@1 / @3 / @5 | 0.797 / 0.984 / 1.000 (정답 FAQ가 있는 64건 기준) |
| faq_direct | 0 / 150 (승인 0건) |
| 틀린 FAQ 직접 반환 | 0 / 0 |
| 경로 | faq_context 64 · general_guidance 69 · clarification 17 |
| AI 호출/질문 (캐시 빔) | 0.833 (125/150) |
| AI 호출/질문 (캐시 참) | **0.153** (23/150) |
| 캐시로 답한 질문 | 102/150 = 68.0% |
| `get()` 적중률 | 0.378 (hit/(hit+miss), 분모는 조회 횟수) |
| 허용 경로 일치 | 0.84 (126/150) |

## 3. 실제 불일치 31건의 원인 (고치지 않고 기록)

1. **긴 자연어 질문의 유사도가 문턱 아래** — paraphrase 4·typo 6건.
   관련 FAQ가 1위로 잡히는데 유사도가 0.40~0.49라 `context_similarity 0.50`에 걸려
   근거를 붙이지 못했습니다. 문턱은 튜닝 데이터로 고른 값이라 **평가 결과를 보고 낮추지
   않았습니다.** 고치려면 튜닝 데이터에 긴 자연어 질문을 넣고 다시 고르는 것이 맞습니다.
2. **되묻기가 규정 질문에만 걸림** — needs_clarify 6건.
   지금은 "규정어 + 조건 부족"일 때만 되묻습니다. 조건이 부족한 일반 질문(예: 포장 방법)은
   되묻지 않고 일반 안내로 갑니다.
3. **공식 조회 창구가 없어 external_lookup으로 못 감** — current_rule 4·pending_rule 2건.
   수입국 규정·시행 예정 정보를 조회할 공식 창구를 연결하지 못했습니다(5절).
4. **prompt_injection 4건**은 안전하게 처리됐지만 기대 경로와 이름이 달랐습니다
   (기대 general_guidance, 실제 clarification).

## 4. 실제 외부 조회 확인 (2026-09-24, 이 망에서)

| 창구 | 결과 |
|---|---|
| 관세청 UNI-PASS 간이정액환급률 | **성공** (HSK 3304991000 조회됨) |
| 관세청 UNI-PASS 수출이행기간단축품목 | **성공** |
| 관세청 UNI-PASS 항공사·포워더 부호 | **성공** |
| **세관장확인대상물품(관세법 제226조)** | **성공 (2026-09-24 연결)** — 공공데이터포털 `apis.data.go.kr/1220000/retrieveCcctLworCd/getRetrieveCcctLworCd`, 파라미터 `hsSgn`+`imexTpcd`. 예: HSK 3004909900 수입 → 약사법·의료기기법 4건, 적용시작일 2020-04-06. UNI-PASS의 같은 이름 서비스(ccctLworCdQry)는 이 프로젝트 키로 여전히 불가 |
| 미국 USITC HTS | **성공** (330499 조회됨) |
| 일본 관세청 실행관세율표 | **성공** (edition 2026-08-08) |
| WITS(세계은행) | **실패** (요청 실패) |
| `customs_client.fetch_regulations()` | **mock 파일** — 상담 도구에 연결하지 않았습니다 |

## 5. 측정 방법

```bash
python -m scripts.faq_eval --set final      --mode after --llm stub --llm-latency 0 --tag v2
python -m scripts.faq_eval --set regression --mode after --llm stub --llm-latency 0 --tag v2
python -m scripts.faq_eval --set regression --mode after --llm stub --llm-latency 0 --warm --tag v2
python -m scripts.faq_review --status        # 승인 현황
python -m scripts.faq_tune                   # 임계값 재선정 (평가 질문 미사용)
```

질문별 경로·점수·근거 상태는 `results/*.json` 의 `rows` 에 그대로 있습니다.

## 6. 이번 측정에서 하지 않은 것

- **실제 API 응답 시간 재측정(p50/p95)**: 경로 개편 뒤 실제 OpenAI 호출로 전/후를 다시 재지
  않았습니다. 앞 보고서의 6.2초 → 4.5초는 **이 브랜치 수치가 아닙니다.**
- **사람 채점**: 답변 정확성·완전성·근거 일치는 자동 지표로만 봤습니다.
- **동시 요청 시 전체 응답 시간**: 검색 구간만 쟀습니다(이전 측정, p50 0.2ms).
- **전문가 검토**: 0건. 따라서 `faq_direct` 경로는 운영에서 한 번도 켜지지 않습니다.
