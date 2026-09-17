# 🚢 Forwardus: 데이터 기반 디지털 포워딩 견적 & 무역 시뮬레이션 플랫폼

> **프로젝트 목적**
> 복잡한 무역 물류 절차를 처음 접하는 수출 화주 및 1인 기업을 위해, 직관적인 단계별 견적 입력 흐름과 **토스증권(Toss Invest)**의 미니멀·모던한 UI를 결합한 **원스톱 포워딩 스케줄 예약 및 무역 지표 분석 대시보드**를 구축합니다.

---

## 📌 1. 프로젝트 핵심 개발 요구사항 요약

1. **디자인 톤앤매너 (Design System)**:
   - **레퍼런스**: [토스증권](https://corp.tossinvest.com/ko) 기반의 여백 중심 모던 미니멀리즘.
   - 둥근 모서리(`border-radius: 12px~16px`), 명확한 타이포그래피 계층(`Pretendard` 또는 `Nanum Gothic`), 부드러운 인터랙션, 과도한 색상 배제(포인트 컬러: 토스 블루 `#2B66F6` 또는 `#1C5CAB`).
   - 스케줄 조회 화면은 **"스카이스캐너 / 마이리얼트립 등 항공권·여행사 예약 플랫폼"**처럼 직관적인 타임라인 및 카드 뷰로 구성.
2. **평가 기준 엄격 준수 (Grading Standard Checklist)**:
   - [x] **데이터 수집 (15점)**: 관세청/포워더/해수부 API 및 크롤링 연동, HS CODE 및 국가 필수 포함, `.env` 보안 준수, 반복문 다량 데이터 적재[cite: 2].
   - [x] **전처리 품질 (15점)**: 한국수출입은행/공공 환율 API를 통한 실시간 원화(KRW) 환산 및 단위 통일, Pandas 결측치 보정(중앙값 대체 배지 표기)[cite: 2].
   - [x] **지표 및 분석 (25점)**: 도메인 특화 KPI 산출 (수출자 총부담액, R/T·kg당 운임, 전년/전분기 대비 변동률), 비즈니스 시사점 2문장 이상 도출[cite: 2].
   - [x] **화면 완성도 (25점)**: 다단계 인터랙티브 웹 폼, 반응형 차트(Plotly), 스케줄 티켓 리스트, 요약 KPI 카드[cite: 2].

---

## 🗺️ 2. 페이지 네비게이션 및 다단계(Multi-Step) 구조

전체 프로세스는 `Start (Home)` ➡️ `Multi-step Form (Step 1~4)` ➡️ `Schedule Select (Ticket View)` ➡️ `Final Dashboard & Leaderboard` 단계로 이어집니다.

### [화면 1] 견적서 작성 시작하기 (Landing Home)
- **헤더**: 미니멀 브랜드 로고(FORWARDUS) 및 주요 통계 지표 브리핑.
- **히어로 섹션**: "수출 화물 견적부터 선박 스케줄 예약까지 한 번에" 원클릭 시작 CTA 버튼.
- **특징 안내**: 실시간 환율 반영, HS CODE 자동 추천, 숨은 로컬 부대비용 사전 계산[cite: 2].

### [화면 2] 기본 운송 경로 설정 (Route Setup)
- **수출 고정**: 무역 구분은 '수출(Export)'로 고정.
- **견적명 입력**: 사용자 프로젝트 식별용 태그 (예: "2026-1차 북미 화장품 수출").
- **운송 모드 토글**: `해상 FCL` / `해상 LCL` / `항공 AIR` 세그먼트 버튼.
- **항구/공항 검색 및 자동완성 (Autocomplete)**:
  - 입력창 포커스 및 타이핑 시 하단 DB 드롭다운 자동 필터링 (예: '부산' 입력 시 `부산항 (KRPUS)` 매핑).
  - 항공 선택 시 출발지는 `인천국제공항(ICN)`으로 자동 전환 및 도착 공항(LAX, SGN, FRA 등) 자동완성.

### [화면 3] 인코텀즈(Incoterms® 2020) 선택 (Terms Selection)
- **규칙 카드 뷰**: `EXW`, `FCA`, `FOB`, `CFR`, `CIF`, `CPT`, `CIP`, `DAP`, `DDP`.
- **운송 모드 유효성 가드 (Validation Guard)**:
  - 항공 선택 시 해상 전용 조건(`FOB`, `CFR`, `CIF`)은 비활성화(Disabled)되며 `FCA`, `CPT`, `CIP`로 자동 안내 및 대체.
- **비용·위험 분기 인터랙션**:
  - 조건 클릭 시 "수출자 vs 수입자 비용 부담 범위"와 "화물 위험 이전 시점(본선 적재 vs 도착지 인도)"을 토스 스타일의 타임라인 바(Bar)로 직관적 안내.

### [화면 4] 화물 제원 및 지능형 HS CODE 추천 (Cargo & Tariff)
- **화물 치수/중량 입력**: 가로·세로·높이(cm), 박스 수량, 박스당 중량(kg), 신고가격(USD).
  - *실시간 파생 계산*: 총 CBM, 해상 R/T(Revenue Ton, 최소 1 R/T 보정), 항공 청구중량(Chargeable Weight, 1 CBM = 166.67kg).
  - FCL 선택 시 20GP / 40GP / 40HC 컨테이너 필요 대수 및 적재율(%) 자동 산출.
- **지능형 HS CODE 추천 엔진 (★핵심 차별점)**:
  - 사용자가 제품 키워드(예: "화장품", "수지", "스웨터") 입력 시 후보 HS CODE 리스트 다중 노출.
  - 선택한 도착 국가의 **기본세율(MFN)**과 **FTA 특혜세율**, 수출입 통관 규제(인증 필요 여부)를 비교 분석하여 **가장 유리한 "추천 HS CODE" 배지 부여**.
- **부가 옵션 설정**:
  - 적하보험(Marine Insurance) 가입 토글 (CIF/CIP 선택 시 110% 부보 의무 자동 체크 및 잠금).
  - 수출신고 방식(관세사 대행 vs UNI-PASS 자가 신고).
  - 화주 예산(KRW) 입력 (KPI 맞춤 분석용).

### [화면 5] 선박·항공 스케줄 조회 (Travel-Agency Style Schedule View)
- **컨셉**: **스카이스캐너/트립닷컴 항공권 예매 UI 차용**.
- **정렬 필터**: `추천순(최적 밸런스)`, `최저 운임순`, `최단 운송기간순`.
- **스케줄 티켓 카드 구성**:
  - 선사/항공사 로고 (HMM, Maersk, ONE, 대한항공 등).
  - 출항일(ETD) ➡️ 도착일(ETA) 타임라인 그래픽 및 소요 일수 (예: "13일 소요 · 직항").
  - 운임 표시: 실시간 환율 적용 원화(KRW) 굵은 글씨 표기 및 USD 보조 표기[cite: 2].
  - 태그 배지: `[정시도착 98%]`, `[특가운임]`, `[친환경선박 ETS 최저]`.
  - [선택하고 상세 견적서 보기] 액션 버튼.

### [화면 6] 최종 견적 명세서 & 분석 대시보드 (Final Dashboard)
- **요약 KPI 카드 3종**:
  1. Door-to-Door 총 예상비용 (KRW)[cite: 2].
  2. 인코텀즈 조건 기준 **수출자 실부담액 (KRW)**[cite: 2].
  3. 화주 예산 대비 잔여/초과액 및 달성률(%)[cite: 2].
- **비용 상세 명세서 (8구간 MECE 체계)**:
  - 수출지 내륙운송 / 수출통관 / 선적지 터미널 / 국제운임 / 적하보험 / 도착지 터미널 / 수입통관·관세 / 수입지 내륙배송.
  - 원통화 금액과 원화(KRW) 환산 금액 병기 및 결측 보정 배지(`대체값`) 표시[cite: 2].
- **데이터 분석 시각화**:
  - **비용 구성비 도넛 차트**: 순수 물류비 vs 수입 제세(관세/부가세) 토글 지원.
  - **운임 시계열 추이 차트**: 최근 12개월~24개월간 항로 운임 지수 꺾은선그래프 및 전년 동기(YoY), 전분기(QoQ) 변동률 비교[cite: 2].
- **AI / 규칙 기반 운송 시사점 브리핑 (Insight Callout)**:
  - 2문장 이상의 시장 분석 코멘트 자동 생성 (예: 운임 등락률, FCL vs LCL 전환 시 물류비 절감액, 인코텀즈 협상 권고)[cite: 2].
- **시뮬레이션 리더보드 (Leaderboard / Scenario Comparison)**:
  - 현재 조건 vs 운영 대안(컨테이너 규격 변경, LCL 전환) vs 협상 대안(FOB 변경) 간의 비용 절감 랭킹 테이블.

---

## 🧮 3. 핵심 도메인 계산 공식 (Business Logic Specification)

1. **체적 및 운임톤(R/T)**:
   - 해상: $\text{R/T} = \max(\text{Total CBM}, \frac{\text{Total Weight (kg)}}{1000})$ (최소 1 R/T)
   - 항공 청구중량: $\text{Chargeable Kg} = \max(\text{Total Weight (kg)}, \text{Total CBM} \times 166.67)$
2. **적하보험료 (CIF 110% 부보 원칙)**:
   - $\text{보험가액} = \frac{\text{FOB} + \text{Freight}}{1 - (1.1 \times \text{Rate})}$
   - $\text{보험료(USD)} = \text{보험가액} \times 1.1 \times \text{Rate}$ (원화 환산 시 최소 10,000원 보정)[cite: 2]
3. **수입 과세가격 및 관세**:
   - 미국: FOB 기준 거래가격
   - EU / 베트남: CIF 기준 가격
   - $\text{관세(KRW)} = \text{과세가격} \times (\text{FTA or MFN 세율} + \text{추가관세율})$[cite: 2]
4. **외화 원화 환산**:
   - $\text{KRW 금액} = \text{외화 금액(USD/EUR)} \times \text{당일 환율(매매기준율)}$[cite: 2]

---

## 📂 4. 권장 프로젝트 디렉터리 구조

```text
project_forwardus/
├── .env.example                 # API Key 및 환경변수 템플릿 (.env는 Git 제외)
├── .gitignore                   # venv, .env, __pycache__, raw_data 제외
├── requirements.txt             # 의존성 패키지 명세
├── README.md                    # 프로젝트 문서
├── config.py                    # 환율, 항만 코드, 인코텀즈 마스터 설정
├── main.py                      # 애플리케이션 진입점 (Streamlit or Flask)
├── src/
│   ├── collectors/              # [평가 1] 수집 레이어
│   │   ├── api_customs.py       # 관세청 품목별/국가별 API 수집 (반복문)
│   │   ├── api_exchange.py      # 환율 API 수집 (수출입은행/공공데이터)
│   │   └── mock_schedules.py    # 선박/항공 스케줄 및 운임 DB
│   ├── processors/              # [평가 2] 전처리 레이어
│   │   ├── cleaner.py           # 결측치 보정 (중앙값 대체) 및 타입 정제
│   │   ├── cargo_calc.py        # CBM, R/T, 컨테이너 대수 연산 엔진
│   │   └── quote_engine.py      # 8구간 원가 산출 및 인코텀즈 분기 로직
│   ├── analytics/               # [평가 3] 분석 레이어
│   │   ├── kpi_metrics.py       # YoY, 절감률, 예산 적합도 계산
│   │   └── insight_generator.py # 룰 기반 비즈니스 시사점(2문장 이상) 생성
│   └── views/                   # [평가 4] 화면 렌더링 레이어 (Toss Style)
│       ├── step1_route.py       # 경로 및 자동완성
│       ├── step2_incoterms.py   # 인코텀즈 타임라인
│       ├── step3_cargo.py       # 화물 제원 & HS 코드 추천
│       ├── step4_schedule.py    # 여행사 티켓 뷰 (스케줄 선택)
│       └── step5_dashboard.py   # 최종 명세서, 차트, 시뮬레이션 리더보드
└── data/
    ├── raw/                     # 원천 API 응답 캐시
    └── processed/               # 정제된 항로/운임 기준 테이블