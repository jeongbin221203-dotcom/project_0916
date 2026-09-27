# 수출 실무 FAQ 지식베이스

ForwardUs '무역 상담'이 되풀이되는 질문에 빠르게 답하려고 두는 **영구 지식베이스**입니다.
로그인한 회원의 지난 상담을 줄여 두는 `chat_memory_service`(대화 이력 메모리)와는 다른 것입니다.
여기 있는 글은 사용자별이 아니라 **모두에게 같은 답**이고, 서버 파일로 남습니다.

## 파일

| 파일 | 무엇 |
|---|---|
| `SCHEMA.md` | 작성 규격 · 허용 출처 도메인 · 분류별 개수 |
| `parts/part_*.jsonl` | 사람이 고치는 원본 조각 (분류별) |
| `faq.jsonl` | 합쳐서 검증한 지식베이스 (앱이 읽는 파일) |
| `faq.md` | 사람이 검토하려고 보는 문서 (자동 생성, 직접 고치지 마세요) |
| `faq_meta.json` | `kb_version`, 건수, 갱신일, 검색 임계값, 튜닝 결과 |
| `source_check.json` | 출처 URL 생존 확인 결과 (확인일·닿지 못한 주소) |
| `eval/eval_a.jsonl`, `eval/eval_b.jsonl` | 독립 평가 질문 150개 (+ 라벨 `gold_faq_id`) |
| `eval/results/*.json` | 개선 전/후 측정 결과 |

## 왜 파일인가 (벡터 DB를 두지 않은 이유)

이 프로젝트에는 벡터 저장소도 임베딩 모델도 없고, requirements에 LangChain도 없습니다.
FAQ 100건은 BM25 + 문자 2-gram으로 메모리에서 충분히 찾히고(색인 만드는 데 수십 ms),
질문이 짧아 한국어 표기 흔들림("인코텀즈가 모야")이 의미 차이보다 큽니다.
건수가 수천 건으로 늘거나 문단 단위 검색이 필요해지면 그때 임베딩·벡터 저장소를 붙이세요.
붙일 자리는 `app/services/faq_index.py` 의 `search()` 하나입니다.

## 고치는 방법

```bash
# 1. 원본을 고칩니다 (분류별 파일)
#    - 고치기: 해당 줄의 내용을 고치고 "version" 을 올립니다 ("1" → "2")
#    - 지우기: 그 줄을 지웁니다
#    - 넣기:   같은 분류의 ID 범위 안에서 빈 번호를 씁니다 (SCHEMA.md 표 참고)
code data/faq/parts/part_03.jsonl

# 2. 검증 + 지식베이스·문서 다시 만들기 (kb_version 이 바뀌고 캐시가 저절로 버려집니다)
python -m scripts.faq_build

# 3. 출처 URL이 살아 있는지 확인하고 확인일 적기
python -m scripts.faq_sources_check --write && python -m scripts.faq_build

# 4. 검색 임계값 다시 고르기 (평가 질문은 쓰지 않습니다)
python -m scripts.faq_tune

# 5. 개선 효과 다시 재기
python -m scripts.faq_eval --mode after --llm stub --tag v2
```

앱은 뜰 때 `faq.jsonl` 을 한 번 읽습니다. 파일을 고쳤으면 서버를 다시 띄우거나
`faq_index.load(force=True)` 를 부르세요.

## 검증 상태 (중요)

**100건 전부 `전문가 검토 필요` 입니다.** 관세사·변호사·포워더의 검토를 받지 않았습니다.
답변 끝에는 언제나 "나라·품목·계약 조건에 따라 달라질 수 있어 최종 확인은 관세사·세관·은행에"가
붙습니다. 사람이 검토한 건만 `review_status` 를 `검증 완료` 로 올리세요
(`scripts/faq_build.py` 는 검토 없이 올리는 것을 막습니다 — 검토자가 직접 고쳐야 합니다).

출처 URL은 `scripts/faq_sources_check.py` 가 실제로 받아 보고 `checked_on` 을 적습니다.
받아 보지 못한 주소는 `checked_on` 이 비어 있고 `source_check.json` 에 이유가 남습니다.
(미국 FDA·중국 해관총서·KTNET은 이 망에서 봇 차단·응답 없음으로 확인하지 못했습니다)
