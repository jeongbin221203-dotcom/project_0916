# 수출 실무 FAQ 지식베이스 — 작성 규격 (v1)

ForwardUs '무역 상담'이 되풀이되는 질문에 빠르고 일관되게 답하려고 두는 **영구 지식베이스**입니다.
대화 이력 메모리(chat_memory_service)와는 다릅니다. 이 파일은 사람이 읽는 규격이고,
실제 저장은 `data/faq/faq.jsonl` (UTF-8, 한 줄에 FAQ 하나) 입니다.

## 필드

| 필드 | 형 | 설명 |
|---|---|---|
| `id` | str | `EXP-001` ~ `EXP-100` |
| `category` | str | 아래 8개 분류명 중 하나 (정확히 같은 글자) |
| `question` | str | 실무자가 실제로 칠 법한 한 문장 질문 |
| `question_variants` | str[3] | 표현이 다른 유사 질문 3개 (검색용, 평가에는 쓰지 않음) |
| `short_answer` | str | 핵심 결론 2~3문장 |
| `detailed_answer` | str | `결론 → 처리 방법 → 주의사항` 순서. 줄바꿈 허용 |
| `required_context` | str[] | 정확히 답하려면 더 알아야 하는 것 (없으면 `[]`) |
| `cautions` | str[] | 예외·자주 하는 실수 |
| `keywords` | str[] | 검색용 키워드 6~12개 (한국어·영문 약어 섞어서) |
| `sources` | obj[] | `{"name": 기관·문서명, "url": 공식 URL, "checked_on": null}` |
| `applicability` | obj | `{"countries": [...], "items": [...], "terms": [...]}` — 제한 없으면 `["전체"]` |
| `freshness` | str | `안정적 지식` \| `정기 확인 필요` \| `실시간 확인 필요` |
| `review_status` | str | `검증 완료` \| `전문가 검토 필요` |
| `version` | str | `1` 로 고정 (갱신 때 올립니다) |

## 분류와 개수 (합계 100)

| 분류 | 개수 | ID 범위 |
|---|---|---|
| 수출 준비·거래처 검증 | 10 | EXP-001~010 |
| 견적·계약·Incoterms | 15 | EXP-011~025 |
| 결제·신용장·대금 회수 | 15 | EXP-026~040 |
| HS 코드·수출신고·통관 | 15 | EXP-041~055 |
| 원산지·FTA·인증·수출통제 | 15 | EXP-056~070 |
| 운송·포워딩·보험·선적 일정 | 15 | EXP-071~085 |
| 무역서류 작성·불일치·정정 | 10 | EXP-086~095 |
| 클레임·반품·사후관리 | 5 | EXP-096~100 |

## 작성 원칙 (어기면 다시 씁니다)

1. **한국 → 해외 수출 실무**가 기본입니다. 수입 절차는 상대국 제도로만 다룹니다.
2. `detailed_answer`는 반드시 **결론 → 처리 방법 → 주의사항** 순서.
3. **지어내지 않습니다.** 조문 번호·고시 번호·수수료·요율·기한을 확신 없이 쓰지 않습니다.
   확신이 없으면 "기관에 확인해야 합니다"라고 쓰고 `required_context`와 확인처를 남깁니다.
4. **변동 정보(운임·환율·스케줄·관세율 수치)를 고정 숫자로 저장하지 않습니다.**
   그런 질문은 `freshness: 실시간 확인 필요`로 두고, 어디서 조회하는지만 씁니다.
5. **나라·품목·계약 조건에 따라 달라지는 것을 단정하지 않습니다.** `applicability`에 적습니다.
6. `review_status`는 기본 `전문가 검토 필요`입니다. 관세사·변호사 검토를 받지 않았으므로
   `검증 완료`는 **쓰지 않습니다.** (사람이 검토한 뒤 올립니다)
7. `sources`는 아래 **허용 출처**의 실제 공식 도메인만 씁니다. 존재를 확신하지 못하는
   딥링크 대신 기관·서비스의 대표 주소를 씁니다. `checked_on`은 항상 `null`로 두세요.
   (URL 생존 확인은 파이프라인이 따로 합니다)
8. 답변에 개인정보·특정 기업 거래정보를 넣지 않습니다.

## 허용 출처 (이 도메인 밖은 쓰지 않습니다)

- 관세청 https://www.customs.go.kr · UNI-PASS https://unipass.customs.go.kr
- 관세법령정보포털 https://unipass.customs.go.kr/clip/index.do
- FTA 강국, KOREA https://www.fta.go.kr
- 국가법령정보센터 https://www.law.go.kr
- 산업통상자원부 https://www.motie.go.kr · 무역위원회 https://www.ktc.go.kr
- 전략물자관리원(YesTrade) https://www.yestrade.go.kr
- KOTRA https://www.kotra.or.kr · 무역투자24 https://www.kotra.or.kr/subList/20000014703
- 한국무역협회 https://www.kita.net · TradeNAVI https://www.tradenavi.or.kr
- 한국무역보험공사 https://www.ksure.or.kr
- 대한상공회의소 무역인증서비스 https://cert.korcham.net
- 한국무역정보통신 KTNET https://www.ktnet.co.kr
- 식품의약품안전처 https://www.mfds.go.kr · 국세청 https://www.nts.go.kr
- 관세평가분류원 https://www.customs.go.kr/capi/main.do
- ICC https://iccwbo.org (Incoterms® 2020, UCP 600)
- WCO https://www.wcoomd.org · WTO https://www.wto.org
- 수입국 기관: 미국 CBP https://www.cbp.gov, FDA https://www.fda.gov,
  EU TARIC https://taxation-customs.ec.europa.eu, 중국 해관총서 http://www.customs.gov.cn,
  일본 세관 https://www.customs.go.jp

## 저장·갱신

- 원본: `data/faq/faq.jsonl` (이 규격) + 사람이 읽는 `data/faq/faq.md`
- 색인: `app/services/faq_index.py` 가 읽어 메모리 색인을 만듭니다. (BM25 + 문자 n-gram)
- 갱신: jsonl을 고치고 `python -m scripts.faq_build` 로 검증·md 재생성·색인 버전 갱신.
  지식베이스 버전(`data/faq/faq_meta.json`의 `kb_version`)이 올라가면 캐시는 저절로 버려집니다.
