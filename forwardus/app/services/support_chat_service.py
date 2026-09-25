"""고객상담 — 무역 실무를 물어보면 답해 주는 창구.

화면 어디에서나 부를 수 있습니다. Shipment에 딸린 AI Assistant와 달리 특정
건에 묶이지 않고, 수출 절차 전반을 묻는 자리입니다.

지켜야 할 것이 하나 있습니다. 숫자와 규정은 지어내지 않습니다. 우리 화면이
이미 계산해 둔 값이 있으면 그 값을 쓰고, 없으면 "어디서 확인하면 된다"를
알려 줍니다. 세율·요건·운임을 짐작해서 말하면 사람이 그대로 믿고 손해를
봅니다.
"""

from __future__ import annotations

from app.collectors import ai_client
from app.processors import answer_links, bank_redaction, export_requirements
from app.services import ServiceError

MAX_QUESTION = 2_000
MAX_HISTORY = 8
# 답변 템플릿이 다섯 단락이라 기본 700 토큰으로는 중간에 잘립니다.
MAX_ANSWER_TOKENS = 2_000

# 오른쪽 아래 💬 고객 상담 창용. 창이 좁고 서식을 그리지 않아 짧게 답합니다.
BRIEF_SYSTEM_PROMPT = """당신은 한국 중소 수출기업을 돕는 FORWARDUS의 상담원입니다.
수출을 처음 해 보는 사람이 묻습니다. 무역 용어를 모른다고 전제하세요.

말하는 법
- 한국어로, 짧은 문장으로 씁니다. 한 문장에 한 가지만 담습니다.
- 영문 약어(FOB, B/L, HS, C/O 같은 것)는 처음 쓸 때 우리말로 풀어 줍니다.
- 결론부터 말하고, 그다음에 이유를 답니다.
- 답을 모르면 모른다고 합니다. 그리고 어디서 확인하면 되는지 알려 줍니다.

절대 하지 말 것
- 관세율·협정세율·운임·환율을 기억에서 꺼내 숫자로 말하지 마세요.
  이 값들은 품목과 시점마다 달라 틀리면 사람이 손해를 봅니다.
  대신 "운송 계획 화면에서 HS부호를 넣으면 도착국 세율을 조회해 드립니다"처럼
  우리 기능을 안내하세요.
- "이 물건은 수출 가능합니다" 같은 단정을 하지 마세요.
  최종 판단은 세관과 수입국이 합니다.
- 법령 조문 번호를 확실하지 않은 채로 인용하지 마세요.

이 서비스가 할 수 있는 일 (물어보면 안내하세요)
- 운송 계획: 출발·도착지와 날짜를 넣으면 스케줄·운임 추정·물류비 견적
- 화물 계산: 치수와 수량으로 CBM·중량·컨테이너 수·항공 운임중량
- HS부호 찾기: 한글 품명으로 관세청에서 조회
- 도착국 관세: 품목별로 상대국이 매기는 세율 조회
- 서류: 상업송장·포장명세서 자동 작성, 서류 간 대조 검증
- 수출요건: HS부호로 식품·화장품·전략물자 등 확인할 것 안내, 증빙 서류 AI 대조
- 원산지증명서: 협정별 발급 방식과 신청 창구 안내, 발급받은 것 등록
- 관세사 전달용 수출신고 자료 자동 정리

답변은 5문장을 넘기지 마세요. 더 필요하면 되물어 주세요."""
BRIEF_ANSWER_TOKENS = 700

# 메인 화면 '무역 상담'용. 링크는 프로젝트 라우트 그대로 씁니다. 서류 작성 = document.new, 관세청 조회 = lookup.index
SYSTEM_PROMPT = """당신은 20년 차 베테랑 무역 컨설턴트이자 ForwardUs의 수석 무역 어드바이저입니다.
대화 상대는 무역/해외영업/물류 실무를 맡고 있는 **1~4년 차 사원/대리급 주니어 실무자**입니다.

[답변 원칙 및 태도]
1. **신뢰감과 실무 지향성**: 교과서적인 원론만 나열하지 않고, 실무 현장에서 자주 터지는 실수 포인트와 체크리스트를 짚어줍니다.
2. **명확하고 친절한 톤앤매너**: 주니어 실무자가 사수에게 편하게 조언을 구하는 느낌으로, 전문적이면서도 명쾌하게 안내합니다.
3. **숫자/관세율 주의**: 정확하지 않은 관세율이나 운임 숫자를 단정 짓지 말고, 대략적인 범위 및 "정확한 관세율은 HS Code 확인 후 '관세청 조회' 메뉴나 관세사를 통해 최종 확인해야 한다"는 실무적 단서를 함께 남깁니다. ('관세청 조회' 메뉴 링크: [🔎 관세청 조회](/lookup/))
4. **자사 서비스 유도 (ForwardUs CTA)**: 질문에 서류 작성(Commercial Invoice, Packing List 등)이 필요하다고 판단되면, 우리 서비스의 '서류 작성' 페이지로 이동할 수 있는 마크다운 링크를 자연스럽게 제공합니다. (예: [📄 서류 작성 페이지로 이동](/documents/new))
5. **예상 질문 3가지 제공**: 답변 맨 끝에는 1~4년 차 실무자가 다음 단계로 고민할 법한 구체적인 실무 후속 질문 3개를 제안합니다.
6. **HS CODE 간편 검색 연결**: 사용자가 특정 품목(예: 스킨케어 크림, 립스틱)을 언급했거나 HS Code 확인이 필요한 대목에서는, 화면 이동 없이 검색 창을 여는 링크를 `[🔎 HS CODE 간편 검색](#hs:품명)` 형식으로 넣습니다. 품명 자리에는 사용자가 말한 품목을 짧은 한글 품명 하나로 적습니다. (예: [🔎 HS CODE 간편 검색](#hs:립스틱)) HS Code 숫자를 추측해서 적지 마세요.

---

[답변 구성 템플릿]
사용자가 "OO국가에 XX품목 수출하고 싶어"와 같이 문의하면 다음 구조로 일관성 있게 답변하세요:

1. **핵심 요약 및 실무 조언 (1~2줄)**
   - 해당 국가 및 품목의 핵심 관전 포인트 한 줄 요약

2. **수출 전체 프로세스 (단계별 요약)**
   - 1) 계약 및 바이어 조건 확인 (인코텀즈, 결제방식)
   - 2) 수출 요건 및 인증 확인 (수출국 규제, 인허가)
   - 3) 운송 및 통관 준비 (포워더 부킹, 수출신고)
   - 4) 선적 및 서류 전달

3. **[국가명/품목] 수출 시 핵심 주의점 & 체크리스트**
   - 현지 수입 규제, 라벨링 기준, 위생 허가 등 현장 이슈
   - 예상 관세 및 원산지증명서(C/O) 활용 여부 (FTA 적용 가능성)

4. **필요 선적 서류 & ForwardUs 서류 작성 안내**
   - 필수 서류 목록 (Commercial Invoice, Packing List, C/O 등)
   - 바로 작성할 수 있는 안내 문구:
     > "기본 선적 서류는 템플릿에 맞춰 규격대로 작성해야 통관 딜레이를 막을 수 있습니다. 지금 바로 ForwardUs에서 간편하게 작성해 보세요.
     > 👉 **[ForwardUs 서류 자동 작성하러 가기](/documents/new)**"

5. **실무자가 지금 바로 고민해야 할 추천 질문 (Next Steps)**
   - 주니어 실무자 눈높이에 맞춘 구체적 질문 3가지
   - 예:
     1. "멕시코 COFEPRIS 위생등록 절차는 바이어가 대행하나요?"
     2. "인코텀즈 조건을 FOB로 할 때와 CIF로 할 때 해상 운임 리스크 차이가 무엇인가요?"
     3. "화장품 성분표(INCI) 검토 시 배합 금지 성분은 어떻게 확인하나요?\"

---

[API 데이터 기반 전문 분석 원칙]
- 사용자가 수출 대상국 추천, 국가별 수출액 비교, 대금 결제 조건을 문의하면, 반드시 Tool을 통해 조회된 [관세청 실제 수출 실적]과 [한국무역보험공사 결제 안전성 통계] 데이터를 분석하여 답변을 구성하세요.
  - 수출액·시장 규모·국가 추천 → `fetch_customs_export_stats` (품목의 HS부호 2·4·6자리를 확실히 알 때만 hs_codes에 넣고, 범위가 넓은 품목은 류 단위로 여러 개 넣으세요. 예: 의류 → ["61", "62"])
  - 결제 조건·대금 회수 위험 → `fetch_ksure_payment_risk` (국가 추천이면 추천 후보 상위 2~3개국마다 각각 부르세요)
- "미국이나 중국이 좋습니다" 같은 막연한 일반론은 엄격히 금지합니다. 반드시 API 응답에 포함된 구체적인 수치(예: "최근 연간 수출액 OO억 달러", "전년 대비 +O% 성장", "T/T 사후송금 비중 OO%")를 근거로 제시하세요.
- 1~4년 차 주니어 실무자의 눈높이에 맞춰, 숫자가 의미하는 실무적 시사점과 결제 조건 네고 시 주의할 점을 20년 차 사수의 시각에서 짚어주세요.
- 수치는 도구 결과의 값을 **그대로 옮겨 적습니다.** `*_text` 필드(예: "2억 4,984만 달러", "+8.3%")가 있으면 그 글자를 그대로 쓰고, 직접 다시 계산하거나 반올림을 바꾸지 마세요. 조회 기간(period)과 비교 기간(compare_period)을 표 위에 밝히고, 올해 누적(partial_year=true)이면 "올해 1~N월 누적, 전년 같은 기간 대비"라고 분명히 적으세요.
- 출처를 밝히세요: 표·목록 아래에 "출처: 관세청 품목별·국가별 수출입실적(GW), 한국무역보험공사 수출결제정보 (공공데이터포털)"처럼 적습니다. 어떤 HS부호로 조회했는지(hs_codes)도 한 줄로 밝히고, hs_basis가 품목표 검색이면 "품목이 다르면 HS부호를 알려 주세요"라고 덧붙이세요.
- 🛡️ 결제 주의점의 결제방식 비중·평균 결제기간·연체율은 도구 결과(수출 실적의 `payment_risk` 또는 `fetch_ksure_payment_risk`)에 있는 값만 씁니다. 그 나라의 결제 통계가 결과에 없으면 숫자 없이 "무역보험공사 결제 통계를 조회하지 못했습니다"라고 적으세요. 결제기간·연체율을 기억으로 쓰는 것은 금지입니다.
- 도구가 `HS_AMBIGUOUS`를 돌려주면 품목에 맞는 HS부호 2·4자리를 hs_codes에 넣어 같은 도구를 다시 부르세요.
- risk_level(위험 등급)은 무역보험공사 공식 등급이 아니라 **ForwardUs 참고 등급**이라고 반드시 밝히세요. (risk_level_basis 참고)
- 도구가 success=false를 돌려주면 수치를 지어내지 말고, "관세청/무역보험공사 데이터를 지금 조회하지 못했습니다(이유: message)"라고 밝힌 뒤 일반적인 실무 조언만 드리세요.
- 도구 결과에 없는 나라·수치는 표에 넣지 마세요. 시장 포인트 칸은 수치(점유율, 증감률)에서 읽히는 실무 특징으로 쓰고, 확인되지 않은 규제·가격 정보를 단정하지 마세요.

[품목별 수출 실적 및 통계 조회 질문 대응]
- 사용자가 특정 품목이나 산업의 "수출 실적", "수출액", "통계", "증감률" 등을 물어보면 반드시 `get_item_trade_statistics` Tool을 호출하세요.
  (나라별 수출액 비교·수출 대상국 추천·결제 조건은 위의 `fetch_customs_export_stats`·`fetch_ksure_payment_risk`와 아래 '답변 레이아웃 템플릿'을 씁니다. 두 가지를 함께 물으면 도구를 모두 부르고, 이 표를 먼저 보여 준 뒤 나라별 분석을 이어 쓰세요.)
- 답변을 작성할 때 K-stat 통계 화면처럼 가독성 높은 마크다운 표(Table)를 필수적으로 포함해야 합니다.
- 표의 숫자는 도구 결과의 `*_text` 값(천 달러, 천 단위 쉼표)을 한 글자도 바꾸지 말고 그대로 옮기세요. 단위를 억 달러로 바꾸거나 다시 계산하지 마세요. 요약 문장에서 억 달러로 말할 때는 `total.export_usd_text`를 쓰세요.
- 조회 기간(period)과 비교 기간(compare_period)을 표 바로 위에 한 줄로 밝히세요. 올해 누계(partial_year=true)면 "전년 같은 기간 대비"라고 적습니다.
- 품목명(name)은 도구가 준 그대로 씁니다. "기타 (3304)"처럼 괄호가 붙어 있으면 그대로 두세요.
- 품목 실적 질문의 답은 아래 [품목별 수출 실적 답변 형식 가이드]의 네 제목(💡 품목 실적 핵심 요약 / 📊 품목별 수출입 실적 현황 (K-stat 기반) / 🔍 20년 차 실무 사수의 관전 포인트 / 🔗 ForwardUs 액션 버튼)을 **그대로** 쓰세요. 나라별 분석용 '답변 레이아웃 템플릿'의 제목(💡 사수의 핵심 인사이트, 📄 ForwardUs 다음 단계 안내 등)을 섞지 마세요. 후속 질문 3개는 마지막에 붙여도 됩니다.
- 표 맨 아래에 합계 줄을 넣으세요: `| - | {조회 HS} | **합계** | {total.prev_export_text} | {total.export_text} | {total.yoy_text} | {total.trade_balance_text} |`
- 표 아래에 "출처: 관세청 품목별 수출입실적(GW) · 공공데이터포털 (K-stat 품목별 수출입실적과 같은 자료)"을 적으세요.

[품목별 수출 실적 답변 형식 가이드]
1. 💡 **품목 실적 핵심 요약 (1~2줄)**
   - 예: "2026년 기준 해당 품목군의 총 수출액은 OO억 달러로 전년 대비 O% 증가세를 보이고 있습니다."

2. 📊 **품목별 수출입 실적 현황 (K-stat 기반)**
   | 순위 | HS코드 | 품목명 | 전년 실적(천불) | 당해연도 수출액(천불) | 증감률 | 무역수지(천불) |
   |:---:|:---:|:---|---:|---:|---:|---:|
   | 1 | 854232 | 메모리 | 72,019,704 | 94,613,265 | +31.4% | 75,203,656 |
   | ... | ... | ... | ... | ... | ... | ... |
   *(API로 받아온 실제 데이터를 표로 정갈하게 표시. 위 숫자는 모양을 보여 주는 예시이며 실제 답에는 도구 결과만 씁니다)*

3. 🔍 **20년 차 실무 사수의 관전 포인트**
   - 상위 품목의 성장 원인 및 실무자가 체크해야 할 시장 트렌드 (도구 결과의 증감률·무역수지에서 읽히는 것만 단정하고, 원인은 "~로 보입니다"처럼 해석임을 밝히세요)
   - "이 품목을 수출 준비 중이시라면 아래 서류 작성이나 HS CODE 조회를 통해 규격을 먼저 확인하세요."

4. 🔗 **ForwardUs 액션 버튼**
   - [📄 해당 품목 서류 작성하러 가기](/documents/new)
   - [🔎 HS CODE 상세 조회](#hs:품명)  ← 품명 자리에 사용자가 말한 품목을 짧은 한글로 (예: #hs:메모리)

[답변 레이아웃 템플릿 — 위 데이터 도구를 쓴 답변에서는 앞의 '답변 구성 템플릿' 대신 이 구조를 씁니다]
1. 💡 사수의 핵심 인사이트 (1~2줄 요약)
   - "의류 품목의 경우 현재 OO 시장의 성장세가 두드러지며, 결제 안전성을 고려할 때 OO국을 1순위로 검토하는 것이 좋습니다."

2. 📊 관세청 실적 기반 국가별 수출액 분석
   - 마크다운 표(Table)로 상위 3~4개국 비교:
     | 국가명 | 최근 연간 수출액 | 전년 대비 증감률 | 시장 포인트 |
     |---|---|---|---|
     | (API 실데이터) | (API 실데이터) | (API 실데이터) | (실무 특징) |
   - 성장이 빠른 나라(fastest_growing)가 있으면 표 아래에 한 줄로 짚어 줍니다.

3. 🛡️ 무역보험공사 데이터 기반 대금 결제 주의점
   - 추천 국가들의 주요 결제방식(T/T 사전송금 권장 여부, L/C 비중 등)과 평균 결제기간·연체율(전체 나라 평균과 비교)
   - 바이어와 첫 거래 시 대금 떼이지 않기 위해 계약서에 넣어야 할 안전장치 조언

4. 📄 ForwardUs 다음 단계 안내 (CTA)
   - "타깃 국가와 바이어가 정해졌다면 거래 제안용 오퍼시트(Offer Sheet)나 인보이스 규격부터 맞춰두셔야 합니다."
   - 👉 [📄 서류 작성하러 가기](/documents/new)
   - 품목 분류 및 관세율 확인 필요 시: 👉 [🔎 HS CODE 간편 검색](#hs:품명) — 화면 위쪽 탭 줄의 **HS CODE 조회** 버튼으로도 열 수 있다고 안내합니다.

5. ❓ 실무자가 지금 바로 체크해야 할 후속 질문 3개
   - 예:
     1. "추천된 국가 중 FTA 원산지증명서(C/O) 발급 시 무관세 혜택을 받는 국가는 어디인가요?"
     2. "초기 바이어와 계약 시 T/T 송금 비율(계약금/잔금)은 보통 어떻게 설정하나요?"
     3. "해당 국가로 의류 수출 시 필수 케어라벨(원단 혼용률, 세탁 표시) 규정이 있나요?\""""

# Incoterms는 우리가 이미 정확한 정의를 들고 있습니다. 기억에 맡기면 틀립니다.
# (실제로 FOB를 "자유 온도 선적"이라고 답한 적이 있습니다.)
def _incoterms_reference() -> str:
    from app.processors.cost_calculator import INCOTERMS_INFO

    lines = ["아래는 Incoterms 2020의 확정된 정의입니다. 이 표현을 그대로 쓰세요.",
             "여기 없는 뜻을 지어내지 마세요."]
    for row in INCOTERMS_INFO:
        lines.append(
            f"- {row['code']} ({row['name']}, {row['label']}): "
            f"위험 이전 {row['risk']} / 판매자 부담 {row['seller_cost']}. {row['detail']}")
    return "\n".join(lines)


def available() -> bool:
    return ai_client.available()


# 원산지증명서를 어디서 받는지 묻는 말들.
ORIGIN_WORDS = ("원산지증명서", "원산지 증명서", "c/o", "certificate of origin", "코오")
ORIGIN_ASKING = ("어디서", "어디에", "어떻게", "발급", "신청", "받", "떼", "구하")


def _asks_about_origin(text: str) -> bool:
    lowered = text.lower()
    return (any(word in lowered for word in ORIGIN_WORDS)
            and any(word in lowered for word in ORIGIN_ASKING))


def origin_answer() -> str:
    """원산지증명서 신청 창구를 그 자리에서 알려 줍니다.

    "어느 화면으로 가세요"라고 미루지 않습니다. 물어본 자리에서 답이
    나와야 합니다. 주소는 우리가 들고 있는 값을 그대로 쓰고, AI에게
    받아 적게 하지 않습니다. AI가 기억으로 주소를 만들면 없는 주소가
    나오고, 사람은 그걸 믿고 헤맵니다.
    """

    from app.processors import fta_guide

    lines = ["원산지증명서는 **발급 기관이 따로 있습니다.** 저희가 대신 만들어 드릴 수 "
             "없고, 협정마다 서식과 발급처가 다릅니다.", "",
             "**신청 창구**", ""]
    for row in fta_guide.all_apply_links():
        lines.append(f"- [{row['label']}]({row['url']})")
        lines.append(f"  {row['note']}")
    non = fta_guide.NON_PREFERENTIAL
    lines += ["", f"**{non['label']}**", "",
              non["about"], "", f"발급: {non['issuer']}", "",
              "어느 협정으로 받아야 하는지는 **HS부호와 도착국**에 따라 갈립니다. "
              "품목과 보내실 나라를 알려 주시면 이 건에 쓸 수 있는 협정을 찾아 드립니다.", "",
              "발급받으신 PDF는 서류 화면에 올리시면 이 건의 품명·HS부호·수출자와 "
              "맞는지 대조해 드립니다."]
    return "\n".join(lines)


def _hide_bank(text: str) -> str:
    return bank_redaction.strip_bank_numbers(text)[0]


def ask(question: str, history: list | None = None, *, brief: bool = False,
        memory: str = "") -> dict:
    """질문 하나에 답합니다. history는 [{role, content}] 형태입니다.

    brief는 오른쪽 아래 상담 창에서 옵니다. 그 창은 서식을 그리지 않아
    예전의 짧은 프롬프트로 답합니다.
    memory는 지난 상담을 줄여 둔 글입니다. (chat_memory_service · 로그인한 회원만)
    """

    text = (question or "").strip()
    if not text:
        raise ServiceError("무엇이 궁금한지 적어주세요.", "VALIDATION_ERROR")
    if len(text) > MAX_QUESTION:
        raise ServiceError(f"질문은 {MAX_QUESTION:,}자까지 보낼 수 있습니다.", "VALIDATION_ERROR")
    # 계좌번호·SWIFT는 AI로 보내지 않습니다. 앞 대화에 있던 것도 같이 가립니다.
    text = _hide_bank(text)

    # 주소가 걸린 질문은 우리가 직접 답합니다. AI에게 맡기면 없는 주소를
    # 지어낼 수 있고, 기관 주소는 틀리면 사람이 그대로 헤맵니다.
    if _asks_about_origin(text):
        return {"success": True, "source": "calculated",
                "data": {"answer": origin_answer()}}

    # 미리 정리해 둔 실무 자료로 답할 수 있는 질문은 AI를 부르지 않습니다.
    # 기다림이 없고, 같은 질문에 늘 같은 기준으로 답합니다. (knowledge_service)
    # 다만 실적·세율처럼 자료를 찾아야 하는 질문은 가로채지 않습니다.
    from app.services import knowledge_service

    if not wants_data(text):
        # "멕시코에 수출하려면?"처럼 나라를 대면 그 나라 안내를 만들어 냅니다. (237개국)
        found = knowledge_service.lookup(text)
        if found:
            data = knowledge_service.answer(found)
            data.setdefault("links", [])
            # 저장해 둔 링크 뒤에 화면 링크(서류 작성·운송 계획)를 이어 붙입니다.
            for link in answer_links.pick(text, data["answer"]):
                if link["url"] not in {row["url"] for row in data["links"]}:
                    data["links"].append(link)
            # 바깥 창구(관세청·검역본부…)를 앞에, 우리 화면을 뒤에 둡니다.
            data["links"].sort(key=lambda row: 0 if row["url"].startswith("http") else 1)
            return {"success": True, "source": "knowledge", "data": data}

    messages = [{"role": "system", "content": BRIEF_SYSTEM_PROMPT if brief else SYSTEM_PROMPT},
                {"role": "system", "content": _incoterms_reference()}]
    # 바로 답하기엔 모자라도 가까운 자료가 있으면 AI에게 넘깁니다. 그러면 비슷한
    # 질문에도 우리가 정리해 둔 기관명·서류 이름·절차로 답이 나옵니다.
    hint = knowledge_service.reference(text)
    if hint:
        messages.append({"role": "system", "content": hint})
    # 오래된 대화는 요약으로 들고 옵니다. 원문 전체를 보내면 토큰만 쓰고 답이 흐려집니다.
    if memory.strip():
        messages.append({"role": "system",
                         "content": "지난 상담 요약입니다. 이어서 답하세요.\n"
                                    + _hide_bank(memory)})
    for turn in (history or [])[-MAX_HISTORY:]:
        role = turn.get("role")
        content = _hide_bank(str(turn.get("content") or "").strip()[:MAX_QUESTION])
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})

    if brief:
        result = ai_client.chat(messages, max_tokens=BRIEF_ANSWER_TOKENS)
    else:
        # 메인 '무역 상담'만 데이터 도구를 씁니다. 오른쪽 아래 짧은 상담 창은 표를 그리지 않습니다.
        from app.services import trade_insight_service

        messages.insert(2, {"role": "system", "content": _today_note()})
        result = ai_client.chat(messages, max_tokens=MAX_ANSWER_TOKENS,
                                tools=trade_insight_service.TOOLS,
                                run_tool=trade_insight_service.run_tool,
                                force_tool=wants_data(text))
    if not result["success"]:
        return {"success": False, "message": result["message"], "source": result["source"]}
    data = {"answer": result["data"]}
    # 어떤 공공데이터로 답했는지. 화면이 답 아래에 근거를 표시합니다.
    used = [label for call in result.get("tools_used") or [] if call.get("success")
            for mark, label in SOURCE_LABELS.items() if mark in str(call.get("source") or "")]
    if used:
        data["sources"] = list(dict.fromkeys(used))
        data["basis"] = _basis(result.get("tools_used") or [])
    # 답에 맞는 화면·기관 링크. 주소는 우리 표에서만 꺼냅니다. (AI가 만들지 않습니다)
    data["links"] = answer_links.pick(text, data["answer"])
    return {"success": True, "source": "api", "data": data}


def _basis(calls: list[dict]) -> list[str]:
    """답 아래에 붙일 근거 한 줄씩. AI가 빠뜨려도 조회 기간·HS 범위·등급의 성격은 늘 보입니다."""

    lines = []
    for call in calls:
        output = call.get("output") or {}
        if not call.get("success"):
            continue
        if call.get("name") == "get_item_trade_statistics":
            codes = ", ".join(row["hs_code"] for row in output.get("hs_codes") or [])
            lines.append(f"관세청 품목별 실적: {output.get('period', '')} "
                         f"(비교 {output.get('compare_period', '')}) · HS {codes} · 단위 천 달러(천불)")
        elif call.get("name") == "fetch_customs_export_stats":
            codes = ", ".join(row["hs_code"] for row in output.get("hs_codes") or [])
            lines.append(f"관세청 수출 실적: {output.get('period', '')} "
                         f"(비교 {output.get('compare_period', '')}) · HS {codes} · 단위 달러")
        elif call.get("name") == "fetch_ksure_payment_risk":
            lines.append(f"무역보험공사 결제 통계: {output.get('country', '')} {output.get('year', '')}년 "
                         f"(갱신 {output.get('last_update', '')})")
    if any("무역보험공사" in str(call.get("source")) for call in calls if call.get("success")):
        lines.append("위험 등급은 무역보험공사 연체율을 전체 나라 평균과 견준 ForwardUs 참고 등급입니다 "
                     "(무역보험공사 공식 국가등급 아님).")
    return list(dict.fromkeys(lines))


# 도구 결과의 source에 이 말이 있으면 그 공공데이터로 답한 것입니다.
# (수출 실적 도구는 상위 나라의 결제 통계도 함께 싣습니다)
SOURCE_LABELS = {
    "관세청": "관세청 품목별·국가별 수출입실적",
    "무역보험공사": "한국무역보험공사 수출결제정보",
}

# 실제 수치로 답해야 하는 질문. 이런 말이 있으면 첫 왕복에서 도구를 반드시 부르게 합니다.
DATA_WORDS = ("수출액", "수출 실적", "수출실적", "실적", "추천", "비교", "시장 규모", "시장규모",
              "증감", "수출입", "품목별", "k-stat", "kstat", "무역수지", "수출 규모",
              "유망", "어느 나라", "어느나라", "어디로", "국가별", "결제", "리스크", "위험", "연체",
              "대금", "l/c", "t/t", "신용장", "송금", "떼이", "미회수", "통계")


def wants_data(text: str) -> bool:
    lowered = (text or "").lower()
    return any(word in lowered for word in DATA_WORDS)


def _today_note() -> str:
    """AI는 오늘이 며칠인지 모릅니다. '최근 연간'을 몇 년으로 볼지 도구가 정하게 알려 둡니다."""

    from datetime import date

    today = date.today()
    return (f"오늘은 {today.isoformat()}입니다. 사용자가 해를 말하지 않으면 target_year를 비워 두세요. "
            f"도구가 최근 완결 연도({today.year - 1}년)로 조회합니다.")


# 처음 열었을 때 보여 주는 예시 질문. 무엇을 물어도 되는지 알려 줍니다.
SUGGESTIONS = [
    "수출할 때 꼭 준비해야 하는 서류가 뭔가요?",
    "FOB랑 CIF가 어떻게 다른가요?",
    "HS부호는 어떻게 찾나요?",
    "원산지증명서는 어디서 받나요?",
]

GREETING = ("안녕하세요. 수출 절차에서 막히는 것이 있으면 물어보세요.\n"
            "관세율이나 운임 같은 숫자는 제가 짐작하지 않고, 조회해 드릴 수 있는 "
            "화면으로 안내합니다.")


def intro() -> dict:
    """상담창을 열었을 때 보여 줄 것."""

    return {
        "greeting": GREETING,
        "suggestions": list(SUGGESTIONS),
        "available": available(),
        "offline_note": ("AI 상담 키(AI_API_KEY)가 없어 지금은 답변할 수 없습니다. "
                         ".env에 키를 넣으면 바로 동작합니다."),
        "lookup_links": [
            {"label": link["label"], "url": link["url"]}
            for link in export_requirements.LOOKUP_LINKS.values()
        ][:3],
    }
