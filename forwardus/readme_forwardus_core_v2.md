# 🚢 FORWARDUS
## 중소기업·1인사업자를 위한 수출 운영 플랫폼

FORWARDUS는 소규모 중소기업과 1인사업자가 별도의 물류 전담 조직 없이도 수출 업무를 진행할 수 있도록 지원하는 **Python / Flask 기반 웹 애플리케이션**입니다.

본 프로젝트는 단순 운임 계산기가 아니라, 실제 수출 업무에서 반복적으로 발생하는 다음 3가지 핵심 문제를 해결하는 것을 목표로 합니다.

> **언제·어떻게 보낼 것인가 → 어떤 서류를 준비할 것인가 → 지금 화물이 어디에 있는가**

이를 기준으로 FORWARDUS의 핵심 기능은 다음 3개 영역에 집중합니다.

1. **운송 계획 (Shipment Planning)**
2. **서류·통관 지원 (Trade Documents & Customs)**
3. **실제 운송 추적 (Shipment Tracking)**

그 외 수출 가능성 판단, 비용 해석, 예외 대응, 자금 관리 등은 **AI Export Assistant**를 통해 보조적으로 지원합니다.

---

# 1. 프로젝트 비전

FORWARDUS의 최종 목표는 다음과 같습니다.

> **소규모 수출기업을 위한 Export Operating System**

사용자가 한 번 입력한 데이터를 견적, 서류, 운송, 추적, 분석 단계에서 반복 입력하지 않고 재사용하도록 설계합니다.

전체 흐름:

```text
Route / Cargo 입력
        ↓
운송 계획
        ↓
Schedule 선택
        ↓
Shipment 생성
        ↓
무역서류 생성
        ↓
Booking / 출항
        ↓
Tracking
        ↓
ETA / Delay Monitoring
        ↓
Shipment History
        ↓
Analytics
```

---

# 2. 핵심 사용자

## 주요 사용자

- 수출 경험이 많지 않은 중소기업
- 물류 전담 인력이 없는 소규모 제조업체
- 해외 판매를 시작하는 1인사업자
- 해외 B2B 거래를 운영하는 스타트업
- 반복적인 소량 수출 업무를 처리하는 실무자

## 사용자 관점의 핵심 고민

사용자는 수출 과정에서 다음과 같은 질문을 가집니다.

### 운송 계획

- 해상과 항공 중 어떤 방식이 적합한가?
- FCL과 LCL 중 무엇을 선택해야 하는가?
- Buyer가 원하는 날짜에 맞추려면 언제 출고해야 하는가?
- 어떤 선박 또는 항공편을 선택해야 하는가?

### 서류·통관

- 어떤 무역서류가 필요한가?
- Commercial Invoice와 Packing List를 어떻게 작성해야 하는가?
- 서류 간 수량, 중량, 가격이 서로 맞는가?
- HS CODE 또는 통관 정보에서 확인할 사항은 무엇인가?

### 실제 운송

- 화물이 현재 어디에 있는가?
- 출항했는가?
- ETA가 변경되었는가?
- 지연이 발생했는가?
- 납기일에 영향이 있는가?

FORWARDUS는 위 세 문제를 핵심 제품 영역으로 정의합니다.

---

# 3. 제품 기능 우선순위

기능을 다음 세 계층으로 구분합니다.

## A. Core Product

실제 프로그램의 중심 기능입니다.

```text
③ 운송 계획
④ 서류·통관
⑤ 실제 운송
```

## B. AI Assistive Layer

핵심 기능을 보조하는 AI 기반 가이드 영역입니다.

```text
① 수출 가능성 판단
② 비용·수익성 해석
⑥ 예외·리스크 대응
⑦ 결제·자금 관리
```

AI는 계산 결과나 규정 정보를 임의로 생성하는 역할이 아니라,
**기존 데이터베이스, 계산 엔진, 외부 API 결과를 해석하고 설명하는 역할**을 담당합니다.

원칙:

> **숫자를 계산하는 것은 코드, 숫자를 설명하는 것은 AI**

> **규정을 판정하는 것은 데이터와 규칙, 확인사항을 안내하는 것은 AI**

## C. Data & Analytics

운영 과정에서 자연스럽게 축적되는 데이터를 활용합니다.

```text
⑧ 운영·분석
```

Shipment 데이터가 누적되면 다음 기능으로 확장합니다.

- Shipment History
- Route KPI
- Average Freight
- Average Transit Time
- Delay Rate
- Buyer별 출하 이력
- 재견적
- 비용 변화 분석

---

# 4. 핵심 기능 1 — Shipment Planning

## 목적

사용자가 화물 정보와 목적지를 입력하면,
가장 적합한 운송 방식과 스케줄을 선택할 수 있도록 지원합니다.

---

## 4.1 Route Setup

### 입력

- 견적명
- 출발 희망일
- 운송 모드
- 출발지
- 도착지

### 운송 모드

```text
SEA
 ├─ FCL
 └─ LCL

AIR
```

### UI 요구사항

화면 왼쪽:

- Calendar
- 출발 희망일 선택

화면 오른쪽:

- SEA / AIR Toggle
- SEA 선택 시 FCL / LCL Toggle
- Origin
- Destination
- Port / Airport Autocomplete

---

## 4.2 Port / Airport Autocomplete

사용자가 도시명, 항구명, 공항명, 코드를 입력하면 후보 목록을 표시합니다.

예:

```text
부산
→ 부산항 (KRPUS)

인천
→ 인천국제공항 (ICN)

Los Angeles
→ Port of Los Angeles (USLAX)
→ Los Angeles International Airport (LAX)
```

Autocomplete 데이터는 UI 코드에 직접 작성하지 않고 별도 데이터 또는 Service 계층에서 관리합니다.

---

## 4.3 Cargo Calculation

### 입력

- Length
- Width
- Height
- Quantity
- Weight
- Invoice Value

### 계산

- Total CBM
- Total Weight
- Revenue Ton
- Chargeable Weight
- Container Quantity

### 해상 Revenue Ton

```text
Revenue Ton = max(Total CBM, Total Weight / 1000)
```

### 항공 Chargeable Weight

```text
Volume Weight = Total CBM × 166.67
Chargeable Weight = max(Actual Weight, Volume Weight)
```

항공사별 Volume Factor 차이를 고려할 수 있도록 상수 또는 설정값으로 분리합니다.

---

## 4.4 Schedule Search

### 표시 정보

- Carrier
- Vessel / Flight
- ETD
- ETA
- Transit Time
- Direct / Transshipment
- Freight
- Data Source

### 정렬

```text
추천순
최저 운임순
최단 운송기간순
```

실제 API가 연결되지 않은 경우 Mock Schedule을 사용할 수 있으나,
반드시 다음과 같이 표시합니다.

```text
source = mock
```

---

## 4.5 Reverse Schedule Planner

Buyer Required Date를 입력하면 출고 준비일을 역산합니다.

```text
Buyer Required Date
        ↓
Final Delivery
        ↓
Import Customs
        ↓
ETA
        ↓
International Transport
        ↓
ETD
        ↓
CY / Cargo Cut-off
        ↓
Export Customs
        ↓
Cargo Ready Date
```

출력 예:

```text
Buyer Required Date : 2026-11-20
Recommended ETA     : 2026-11-16
Recommended ETD     : 2026-11-02
Cargo Ready Date    : 2026-10-29
```

---

# 5. 핵심 기능 2 — Trade Document Center

## 목적

견적 및 Shipment 생성 과정에서 이미 입력된 데이터를 재사용하여
무역서류 작성과 검증을 지원합니다.

사용자가 동일한 정보를 반복 입력하지 않는 것을 핵심 UX 원칙으로 합니다.

---

## 5.1 자동 작성 대상

초기 구현:

- Commercial Invoice
- Packing List
- Proforma Invoice
- Shipping Instruction
- Booking Request

확장 대상:

- Delivery Request
- Certificate of Origin 작성용 데이터
- 수출신고 의뢰 정보

---

## 5.2 자동 입력 데이터

Shipment에서 다음 값을 재사용합니다.

```text
Exporter
Consignee
Notify Party
Incoterms
POL
POD
Product Description
HS CODE
Quantity
Package Type
Gross Weight
Net Weight
Invoice Value
Currency
ETD
ETA
```

---

## 5.3 Document Validation

문서 간 데이터 불일치를 검사합니다.

예:

```text
Commercial Invoice
Quantity = 500 CTN

Packing List
Quantity = 500 CTN

B/L Draft
Quantity = 480 CTN
```

결과:

```text
status = warning
field = quantity
expected = 500
actual = 480
```

검증 대상 예:

- Quantity
- Gross Weight
- Net Weight
- Invoice Value
- Currency
- Incoterms
- HS CODE
- Consignee
- POL
- POD

---

## 5.4 Document Status

```text
draft
generated
validated
final
```

---

# 6. 핵심 기능 3 — Shipment Tracking

## 목적

선적 이후 사용자가 Shipment의 현재 상태와 예상 도착 일정을 이해할 수 있도록 합니다.

단순 선박 위치 지도보다 **이벤트 기반 Shipment Timeline**을 우선합니다.

---

## 6.1 Tracking Event

```text
booking_confirmed
container_pickup
gate_in
customs_cleared
departed
in_transit
arrived
import_customs
out_for_delivery
delivered
```

---

## 6.2 Shipment Timeline

예:

```text
✓ Booking Confirmed
✓ Container Pick Up
✓ Gate In
✓ Customs Cleared
✓ Vessel Departed
● In Transit
○ Arrived
○ Delivered
```

---

## 6.3 ETA Monitoring

기존 ETA와 새로운 ETA를 비교합니다.

예:

```text
Previous ETA
2026-11-12

Current ETA
2026-11-16

Delay
+4 Days
```

ETA가 변경되면 Shipment에 Event를 생성합니다.

---

## 6.4 Tracking Source

Tracking 데이터에는 반드시 출처를 저장합니다.

```text
api
mock
manual
```

Mock Tracking은 실제 실시간 Tracking처럼 표시하지 않습니다.

---

# 7. AI Export Assistant

AI 기능은 별도의 판단 엔진이 아니라
Core Product 데이터를 설명하는 보조 인터페이스입니다.

전체 구조:

```text
Database / External API / Calculation Engine
                    ↓
               실제 데이터
                    ↓
             AI Export Assistant
                    ↓
           설명 / 가이드 / 질의응답
```

---

# 8. AI 보조 기능 1 — 수출 가능성 판단

사용자가 질문:

```text
이 화장품을 미국으로 수출하려면 무엇을 확인해야 해?
```

AI는 다음 데이터를 참고합니다.

- HS CODE
- Destination Country
- Customs API
- Regulation Data
- Certificate Data

응답 예:

```text
현재 HS CODE 기준으로 미국 수출 시 추가 확인이 필요한 규제 항목이 있습니다.
제품 성격에 따라 관련 인증 또는 신고 요건이 적용될 수 있으므로 해당 항목을 확인하세요.
```

AI가 확정적으로 다음과 같이 답하지 않도록 합니다.

```text
수출 가능합니다.
인증이 필요 없습니다.
```

확인이 필요한 항목에는 다음 상태를 사용합니다.

```text
confirmed
check_required
not_applicable
unknown
```

---

# 9. AI 보조 기능 2 — 비용·수익성 해석

물류비 계산 자체는 Python Business Logic에서 수행합니다.

예:

```text
Ocean Freight       820,000 KRW
Origin Charge       340,000 KRW
Customs              55,000 KRW
Insurance            24,000 KRW
Destination Charge  410,000 KRW

Total Logistics Cost
1,649,000 KRW
```

AI는 결과를 설명합니다.

예:

```text
현재 조건에서는 국제운임보다 Origin / Destination Local Charge 비중이 높습니다.
화물량이 증가할 경우 LCL과 FCL 견적을 함께 비교하는 것이 좋습니다.
```

---

# 10. AI 보조 기능 3 — Exception Management

Tracking 시스템이 이상 이벤트를 감지합니다.

예:

```text
Previous ETA
2026-11-12

Current ETA
2026-11-16

Delay
+4 Days
```

AI는 다음과 같은 대응 가이드를 제공합니다.

```text
ETA가 기존 계획보다 4일 지연되었습니다.

확인 권장사항:
1. Buyer 납기일 영향 확인
2. 현지 Delivery 예약 변경 여부 확인
3. Free Time 확인
4. Buyer에게 ETA 변경 안내
```

---

# 11. AI 보조 기능 4 — 결제·자금 관리

Shipment의 비용 및 Payment 데이터를 이용해 Cash Flow를 설명합니다.

예:

```text
Production Payment
-15,000,000 KRW

Freight Payment
-3,000,000 KRW

Buyer Payment
+30,000,000 KRW
```

AI는 다음과 같은 해석을 제공합니다.

```text
현재 Shipment 기준으로 Buyer 대금 수령 전까지 최대 약 18,000,000원의 운전자금이 필요합니다.
```

금액 계산 자체는 AI가 아닌 Python 로직에서 수행합니다.

---

# 12. 운영·분석

Shipment 데이터가 쌓이면 자연스럽게 분석 기능으로 확장합니다.

## Shipment KPI

- Total Shipment
- Total Freight Cost
- Average Cost / CBM
- Average Cost / KG
- Average Transit Time
- Delay Rate
- Customs Hold Rate

## Route KPI

예:

```text
Busan → Los Angeles

Shipment Count
Average Freight
Average Transit Time
Delay Rate
```

## Buyer KPI

- Buyer별 출하 횟수
- Buyer별 평균 물류비
- Buyer별 평균 운송기간
- Buyer별 최근 Shipment

---

# 13. Shipment 중심 데이터 모델

모든 기능은 Shipment ID를 중심으로 연결합니다.

예:

```text
Shipment ID
EXP-2026-00031
```

구조:

```text
Shipment
├─ User
├─ Buyer
├─ Route
├─ Cargo
├─ Incoterms
├─ Quote
├─ Schedule
├─ Documents
├─ Tracking Events
├─ Exceptions
├─ Costs
└─ Payment
```

---

# 14. Shipment 주요 필드

```python
shipment_id
project_name
user_id
buyer_id

trade_type

transport_mode
sea_mode

origin_code
destination_code

cargo_ready_date
etd
eta
buyer_required_date

incoterms
currency
invoice_value

status
created_at
updated_at
```

---

# 15. Shipment Status

```text
draft
quoted
booked
departed
in_transit
arrived
delivered
closed
cancelled
```

---

# 16. 데이터 출처 관리

모든 외부 및 계산 데이터에는 가능한 한 source를 저장합니다.

```text
api
mock
manual
calculated
imputed
```

예:

```python
{
    "freight_usd": 1250,
    "source": "mock"
}
```

Mock 데이터를 실시간 데이터처럼 표시하지 않습니다.

---

# 17. 기술 스택

## Backend

- Python 3.11+
- Flask
- Flask Blueprint
- Jinja2
- SQLAlchemy
- Flask-SQLAlchemy
- Gunicorn
- REST API

## Frontend

- HTML5
- CSS3
- JavaScript
- Jinja2 Template
- 필요 시 Chart.js 또는 Plotly

초기 단계에서는 별도의 React / Vue SPA로 전환하지 않습니다.

## Data

- Pandas
- Requests 또는 httpx
- Python Standard Library

## Database

개발:

```text
SQLite
```

배포:

```text
PostgreSQL
```

## Deployment

- Flask
- Gunicorn
- Render
- PostgreSQL

선택사항:

- Docker

---

# 18. 애플리케이션 구조

외부 API와 UI를 직접 연결하지 않습니다.

```text
External API / Mock Data
        ↓
Collector / Client
        ↓
Normalizer
        ↓
Service
        ↓
Processor / Business Logic
        ↓
Repository
        ↓
Database
        ↓
Route / View
```

---

# 19. 권장 디렉터리 구조

5명이 동시에 개발하므로 기능별로 파일을 분리합니다.

```text
forwardus/
├── run.py
├── config.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
│
├── app/
│   ├── __init__.py
│   ├── extensions.py
│   │
│   ├── routes/
│   │   ├── home.py
│   │   ├── planning.py
│   │   ├── shipment.py
│   │   ├── document.py
│   │   ├── tracking.py
│   │   ├── assistant.py
│   │   └── dashboard.py
│   │
│   ├── services/
│   │   ├── planning_service.py
│   │   ├── shipment_service.py
│   │   ├── document_service.py
│   │   ├── tracking_service.py
│   │   ├── assistant_service.py
│   │   └── analytics_service.py
│   │
│   ├── processors/
│   │   ├── cargo_calculator.py
│   │   ├── cost_calculator.py
│   │   ├── schedule_calculator.py
│   │   ├── document_validator.py
│   │   └── cashflow_calculator.py
│   │
│   ├── collectors/
│   │   ├── schedule_client.py
│   │   ├── tracking_client.py
│   │   ├── customs_client.py
│   │   └── exchange_client.py
│   │
│   ├── repositories/
│   │   ├── shipment_repository.py
│   │   ├── buyer_repository.py
│   │   ├── document_repository.py
│   │   └── tracking_repository.py
│   │
│   ├── models/
│   │   ├── shipment.py
│   │   ├── buyer.py
│   │   ├── cargo.py
│   │   ├── document.py
│   │   ├── tracking_event.py
│   │   └── shipment_cost.py
│   │
│   ├── validators/
│   │   ├── cargo_validator.py
│   │   ├── shipment_validator.py
│   │   └── document_validator.py
│   │
│   ├── templates/
│   │   ├── home/
│   │   ├── planning/
│   │   ├── shipment/
│   │   ├── document/
│   │   ├── tracking/
│   │   ├── assistant/
│   │   └── dashboard/
│   │
│   └── static/
│       ├── css/
│       ├── js/
│       └── images/
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── mock/
│
├── tests/
│   ├── test_cargo_calculator.py
│   ├── test_planning_service.py
│   ├── test_document_validator.py
│   ├── test_tracking_service.py
│   └── test_routes.py
│
└── migrations/
```

---

# 20. Flask Blueprint 원칙

기능별 Blueprint를 사용합니다.

예:

```python
planning_bp = Blueprint(
    "planning",
    __name__,
    url_prefix="/planning"
)
```

권장 URL:

```text
/
/planning
/planning/new

/shipments
/shipments/<shipment_id>

/documents/<shipment_id>

/tracking/<shipment_id>

/assistant/<shipment_id>

/dashboard
```

Route 함수에 대량의 계산 로직을 작성하지 않습니다.

```text
Route
 ↓
Service
 ↓
Processor / Repository
```

---

# 21. 5인 개발 역할 분담

## Developer A — Shipment Planning / Calculation

담당:

- Route Setup
- SEA / AIR
- FCL / LCL
- Cargo Calculation
- Schedule
- Reverse Schedule Planner

주요 영역:

```text
routes/planning.py
services/planning_service.py
processors/
```

---

## Developer B — Frontend / UX

담당:

- Home
- Multi-Step Form
- Calendar
- Toggle
- Autocomplete
- Schedule UI
- Responsive Design
- Shipment Timeline UI

주요 영역:

```text
templates/
static/css/
static/js/
```

---

## Developer C — Trade Documents

담당:

- Commercial Invoice
- Packing List
- Proforma Invoice
- Shipping Instruction
- Document Validation

주요 영역:

```text
routes/document.py
services/document_service.py
document templates
```

---

## Developer D — Tracking / External API

담당:

- Schedule API
- Tracking API
- Customs API
- Exchange API
- Mock Provider
- Normalizer
- ETA Monitoring

주요 영역:

```text
collectors/
services/tracking_service.py
```

---

## Developer E — Database / AI / Analytics / Deployment

담당:

- SQLAlchemy
- Shipment Model
- Buyer
- Shipment History
- AI Assistant 연동
- KPI
- PostgreSQL
- Render
- Gunicorn
- Test / CI

---

# 22. Git Branch 전략

`main`에서 직접 개발하지 않습니다.

```text
main
└─ develop
   ├─ feature/planning
   ├─ feature/documents
   ├─ feature/tracking
   ├─ feature/assistant
   └─ feature/ui
```

작업 예:

```bash
git checkout develop
git pull
git checkout -b feature/document-validator
```

완료 후:

```bash
git add .
git commit -m "feat: add document validation"
git push origin feature/document-validator
```

병합 흐름:

```text
feature/*
   ↓
develop
   ↓
main
```

---

# 23. Commit 규칙

```text
type: description
```

type:

```text
feat
fix
refactor
style
docs
test
chore
```

예:

```text
feat: add shipment eta monitoring
fix: prevent invalid cargo weight
docs: update core product scope
test: add document validator tests
```

---

# 24. Pull Request 규칙

```text
## 변경 목적

## 수정 파일

## 주요 변경사항

## 테스트 결과

## 확인 필요사항
```

Merge 전:

```text
[ ] 프로그램 실행
[ ] Import Error 없음
[ ] JavaScript Error 없음
[ ] 기존 기능 정상
[ ] 테스트 통과
[ ] Secret 포함 여부 확인
[ ] Mock/API 표시 확인
```

최소 1명 리뷰 후 `develop`에 병합합니다.

---

# 25. 동시 개발 충돌 방지

공통 파일은 변경 전 공유합니다.

특히:

```text
app/__init__.py
config.py
requirements.txt
base.html
database models
```

기능별 JavaScript:

```text
planning.js
document.js
tracking.js
assistant.js
dashboard.js
```

기능별 CSS:

```text
base.css
planning.css
document.css
tracking.css
dashboard.css
```

---

# 26. 입력값 검증

모든 숫자 입력은 서버에서 다시 검증합니다.

검증 대상:

- None
- 빈 문자열
- NaN
- Infinity
- 문자열 숫자
- 음수
- 0
- 비정상적으로 큰 값
- 정수 전용 필드

사용자 필수 입력값을 임의 생성하지 않습니다.

---

# 27. 외부 API 오류 처리

필수 처리 항목:

- Timeout
- Authentication Failure
- HTTP Error
- Rate Limit
- Empty Response
- Missing Field
- Invalid Type
- Server Error
- Schema Change

Client Layer에서 오류를 정규화합니다.

```python
{
    "success": False,
    "error_code": "API_TIMEOUT",
    "message": "외부 데이터 조회 시간이 초과되었습니다."
}
```

---

# 28. 환경변수

`.env`

```text
SECRET_KEY=
DATABASE_URL=

SCHEDULE_API_KEY=
TRACKING_API_KEY=
CUSTOMS_API_KEY=
EXCHANGE_API_KEY=

AI_API_KEY=
```

`.env.example`

```text
SECRET_KEY=
DATABASE_URL=
SCHEDULE_API_KEY=
TRACKING_API_KEY=
CUSTOMS_API_KEY=
EXCHANGE_API_KEY=
AI_API_KEY=
```

비밀정보는 Git에 포함하지 않습니다.

---

# 29. Mock Data 정책

실제 API가 준비되지 않은 경우 Mock 데이터를 사용할 수 있습니다.

위치:

```text
data/mock/
```

또는:

```text
collectors/mock_*.py
```

UI 내부에 Mock 데이터를 직접 흩어놓지 않습니다.

화면에는 반드시 다음과 같이 표시합니다.

```text
Data Source: Mock
```

---

# 30. UI / UX 원칙

디자인 방향:

- Toss Style
- Minimal
- Card Based
- 충분한 여백
- 명확한 단계 표시
- Responsive

Primary Color:

```text
#2B66F6
```

주요 컴포넌트:

- Card
- Toggle
- Segmented Button
- Autocomplete
- Calendar
- Badge
- Timeline
- KPI Card
- Modal

---

# 31. 주요 화면

## 화면 1 — Home

- FORWARDUS 소개
- 주요 기능
- 견적 시작 CTA

## 화면 2 — Route Setup

왼쪽:

- Calendar

오른쪽:

- SEA / AIR
- FCL / LCL
- Origin
- Destination
- Autocomplete

## 화면 3 — Incoterms

- Incoterms 선택
- 비용 부담 설명

## 화면 4 — Cargo

- Dimension
- Weight
- Quantity
- Invoice Value
- HS CODE
- CBM
- Revenue Ton
- Chargeable Weight

## 화면 5 — Schedule

- Carrier
- ETD
- ETA
- Transit Time
- Freight
- Schedule 선택

## 화면 6 — Shipment Detail

- Shipment Summary
- Selected Schedule
- Document Status
- Tracking Status
- ETA

## 화면 7 — Document Center

- Commercial Invoice
- Packing List
- Shipping Instruction
- Validation

## 화면 8 — Tracking

- Shipment Timeline
- Current Status
- ETD / ETA
- Delay Alert

## 화면 9 — AI Export Assistant

- 수출 가능성 질문
- 비용 설명
- Delay 대응
- Cash Flow 안내

## 화면 10 — Dashboard

- Shipment History
- KPI
- Route Statistics

---

# 32. 테스트 기준

필수 Unit Test:

- CBM
- Revenue Ton
- Chargeable Weight
- Schedule Date Calculation
- Reverse Schedule
- Document Validation
- Tracking Event
- ETA Change
- Input Validation

필수 Edge Case:

- 빈 값
- 0
- 음수
- 문자열
- None
- NaN
- Infinity
- 비정상적인 대형 값

---

# 33. 개발 우선순위

## Phase 1 — Shipment Planning

```text
Route Setup
↓
Cargo
↓
Incoterms
↓
Schedule
↓
Shipment 생성
```

완료 기준:

- SEA / AIR 선택 가능
- FCL / LCL 선택 가능
- Port / Airport 검색 가능
- Cargo 계산 가능
- Schedule 선택 가능
- Shipment ID 생성 가능

---

## Phase 2 — Trade Document Center

```text
Shipment
↓
Commercial Invoice
↓
Packing List
↓
Shipping Instruction
↓
Document Validation
```

완료 기준:

- Shipment 데이터 재사용
- 문서 자동작성
- 문서 간 필드 비교
- Validation 상태 표시

---

## Phase 3 — Shipment Tracking

```text
Booking
↓
Departed
↓
In Transit
↓
ETA Monitoring
↓
Arrived
↓
Delivered
```

완료 기준:

- Timeline 표시
- ETA 저장
- ETA 변경 감지
- Mock/API Source 표시

---

## Phase 4 — AI Export Assistant

```text
Shipment Data
        ↓
AI Assistant
```

지원 기능:

- Export Readiness
- Cost Explanation
- Exception Guide
- Cash Flow Explanation

---

## Phase 5 — Analytics

- Shipment History
- Buyer History
- Route KPI
- Freight Trend
- Transit Time
- Delay Rate
- 재견적

---

# 34. Definition of Done

기능 완료 조건:

```text
[ ] 요구사항 구현
[ ] 입력값 검증
[ ] 오류 처리
[ ] 기존 기능 회귀 없음
[ ] 모바일 화면 확인
[ ] Unit Test 통과
[ ] Secret 노출 없음
[ ] Mock / API 구분
[ ] PR 리뷰 완료
[ ] develop Merge 완료
```

---

# 35. 로컬 실행

```bash
git clone <repository-url>
cd forwardus
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

설치:

```bash
pip install -r requirements.txt
```

환경변수:

```bash
cp .env.example .env
```

실행:

```bash
flask run
```

또는:

```bash
python run.py
```

정상 실행 예:

```text
Running on http://127.0.0.1:5000
```

---

# 36. 테스트 실행

```bash
pytest
```

신규 기능을 추가하면서 기존 테스트를 삭제하여 통과시키지 않습니다.

---

# 37. Render 배포

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
gunicorn "app:create_app()"
```

환경변수:

```text
SECRET_KEY
DATABASE_URL
SCHEDULE_API_KEY
TRACKING_API_KEY
CUSTOMS_API_KEY
EXCHANGE_API_KEY
AI_API_KEY
```

---

# 38. 핵심 개발 원칙

1. 핵심 제품은 **운송 계획, 서류·통관, Tracking**에 집중합니다.
2. AI는 핵심 기능을 대체하지 않고 설명과 가이드를 담당합니다.
3. 계산은 Python Business Logic에서 수행합니다.
4. 규정 및 외부 데이터는 출처를 기록합니다.
5. Mock 데이터는 실제 데이터와 반드시 구분합니다.
6. 모든 기능은 Shipment ID 중심으로 연결합니다.
7. 이미 입력한 데이터를 다시 입력하게 만들지 않습니다.
8. 정상 동작하는 기존 코드를 불필요하게 재작성하지 않습니다.
9. 기능별 Service / Processor / Repository 계층을 유지합니다.
10. 실제 실행하거나 테스트하지 않은 기능을 검증 완료라고 보고하지 않습니다.

---

# 39. 최종 제품 구조

```text
                FORWARDUS

         ┌────────────────────┐
         │ Shipment Planning  │
         │ 운송 계획           │
         └─────────┬──────────┘
                   ↓
         ┌────────────────────┐
         │ Trade Documents    │
         │ 서류 · 통관         │
         └─────────┬──────────┘
                   ↓
         ┌────────────────────┐
         │ Shipment Tracking  │
         │ 실제 운송           │
         └─────────┬──────────┘
                   ↓
         ┌────────────────────┐
         │ Shipment History   │
         │ Analytics          │
         └────────────────────┘


        AI EXPORT ASSISTANT

   ┌─────────────────────────────┐
   │ Export Readiness            │
   │ Cost / Profit Explanation   │
   │ Exception Guide             │
   │ Cash Flow Guide             │
   └─────────────────────────────┘
```

---

**FORWARDUS**  
Small Business Export Operating Platform  
Python · Flask · SQLAlchemy · PostgreSQL · Pandas
