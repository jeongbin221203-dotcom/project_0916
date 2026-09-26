---
title: 캐나다 수출 인증 (cUL/CSA · ISED · SFCR)
keywords: 캐나다, CSA, cUL, cETL, SCC, ISED, ICES-003, SFCR, CFIA, 불어 라벨, Bill 96, 이중언어, 한·캐나다 FTA, 캐나다 통관, 필드평가, 인증, 수출 인증, 인증 필요
must: 캐나다, csa인증, cul, ised, sfcr, 캐나다 인증, 퀘벡
ask: 캐나다 수출할 때 UL 인증만 있으면 되나요?
links: Electrical Safety Authority (인정 인증마크)|https://esasafe.com/electrical-products/recognized-certification-marks/ ;; ISED Canada 무선기기 인증절차(RSP-100)|https://ised-isde.canada.ca/site/spectrum-management-telecommunications/en/devices-and-equipment/radio-standards-procedures-rsp/rsp-100-certification-radio-apparatus-and-broadcasting-equipment ;; CFIA 식품 수입 라이선스|https://inspection.canada.ca/en/food-licences ;; 포장·라벨 규칙 (C.R.C. c.417)|https://laws-lois.justice.gc.ca/eng/regulations/C.R.C.,_c._417/page-1.html ;; 퀘벡 OQLF Bill 96 제품 상표 규정|https://www.oqlf.gouv.qc.ca/francisation/entreprises/marque-commerce-produits.html ;; CBSA 한·캐나다 FTA 원산지증명서 BSF760|https://www.cbsa-asfc.gc.ca/publications/forms-formulaires/bsf760-eng.html
see: cert-usa, cert-australia, fta-origin
---
캐나다에는 단일 국가 인증마크가 없고, **주(州) 전기안전법이 "SCC 인정 인증기관의 마크가 붙은 제품"만 판매·전시·광고·설치를 허용**하는 구조입니다. 즉 **자기선언(SDoC)이 불가능**하고, 미인증 제품은 세관을 통과해도 주 당국이 판매를 막고 **건별 현장평가**를 요구합니다.

### ★ "UL 마크가 있으니 캐나다도 된다" — 가장 흔한 오류

미국 단독 UL 마크는 캐나다에서 무효입니다. **cUL / cULus**처럼 **"c"가 있거나** CSA·cETL 등 캐나다 인증이어야 합니다. 마크 왼쪽 소문자 **c = Canada**, 오른쪽 **us = USA**입니다.
미인증이면 BC는 **SPE-1000**, 온타리오는 **ESAFE** 건별 현장평가로 비용과 일정이 급증합니다.

### 어떤 품목에 걸리나

- **전기제품 — 제3자 인증 강제**
  - 온타리오: Ontario Electrical Safety Code Rule 2-022, O.Reg 438/07. ESA 공식 문구 — *"before an electrical product... is used, sold, displayed or advertised for sale in Ontario, it must be approved by an accredited certification or evaluation agency"*
  - BC: Electrical Safety Regulation s.21(1), 대안은 SPE-1000 현장평가
  - 설치는 **CSA C22.1**, 제품 규격은 **CSA C22.2 시리즈**
- **무선/통신 — ISED Canada**
  - **RSS-Gen** — 라벨에 **`IC:` 접두 + 인증번호**를 영구·판독가능하게, 또는 e-labelling
  - **RSP-100** 인증 절차 / 인증 시 **Technical Acceptance Certificate(TAC)** 발급, **REL** 등재
  - **ICES-003** — IT기기 EMC, **인증서 없는 자기선언**이며 표기는 **`CAN ICES-003(A/B) / NMB-003(A/B)`**
- **식품 — SFCR(SOR/2018-108)** — 일부 예외를 빼면 **라이선스 없이 수입 금지**
- 그 밖에 CCPSA(완구·가정용품), 섬유(**CA Identification Number**), 화장품(Cosmetic Notification Form), 천연건강제품(NPN + Site Licence)

### 필요한 서류

**전기** — SCC 인정 인증기관의 **Certificate of Compliance**, CSA C22.2 규격별 **Test Report**, CB 경유 시 **CB Test Certificate + Report**, 미인증 시 **현장평가 보고서·승인 라벨**

**무선/EMC** — **TAC**, **ISED 인증번호**(`IC: xxxx-yyyy`), **Form A**(캐나다 대리인 명기), **Applicant–Canadian Representative Agreement**, ICES-003은 **SDoC + 시험성적서**

**식품** — **SFC Licence 번호**, 서면 **Preventive Control Plan(PCP)**, **추적기록 2년**, **Integrated Import Declaration(IID)**

**통관·라벨** — **CBSA 양식 BSF 760**(한·캐나다 FTA 원산지증명서), Commercial Invoice, Canada Customs Invoice(CI1), **이중언어 아트워크**와 퀘벡 프랑스어 확인본, 품목별 CA 번호·CNF·NPN

### 어디서 받나

인정기구는 **SCC**, 온타리오 ESA 인정 인증마크 기관은 40곳 이상(CSA, UL/ULC, Intertek ETL, TÜV Rheinland·SÜD, NSF, DEKRA, QPS, QAI, Nemko, MET, IAPMO 등)입니다. 무선은 **ISED Certification and Engineering Bureau** 또는 캐나다가 인정한 해외 인증기관(FCB), 식품은 **CFIA**(My CFIA·AIRS), 섬유 CA 번호는 **Competition Bureau Canada**(**CAD $100 1회**, 온라인 5영업일)입니다.

**한국 창구** — **UL Solutions Korea**(수원·의왕·평택 시험소), **CSA Group**(서울 사무소, 2026년 4월 용인 자동차 EMC 시험소), **KTC**(CSA Group과 제휴, IECEE CB 연계), Intertek·TÜV SÜD·TÜV Rheinland 한국 법인. 일반적으로 **한국에서 시험 → 해외 CB가 인증서 발급** 구조입니다.

### 절차

**전기** — 규격 확정 → 샘플·기술문서 → 시험 → **공장심사** → 인증서 → 정기 사후관리
**무선** — 시험 → CB 또는 ISED 신청 + **Form A** → TAC → REL 등재 → `IC:` 라벨
**식품** — 위해 식별 → 요건 파악 → 공급자 검증 → **PCP 작성** → 리콜 절차 문서화 → **My CFIA로 SFC licence** → **IID 제출**(도착 90일 전부터) → 추적기록 2년 → 연 1회 모의 리콜
- 라이선스 **유효기간 2년**, 갱신은 만료 **120일 전**

기간·수수료는 인증기관 견적제라 공표값이 없습니다(확인 필요). 공표가 확인된 것은 **CA Identification Number CAD $100**뿐입니다.

### FTA

**한·캐나다 FTA(CKFTA)는 2015년 1월 1일 발효**했습니다. 관세대우 코드는 **KRT – Code 30**입니다.
**원산지증명은 자율증명이 아니라 지정양식**입니다 — **CBSA 양식 BSF 760**, **수출자가 빠짐없이 판독 가능하게 작성**, **Blanket period 최대 12개월**, **영어·프랑스어·한국어** 제공. 수입자가 특혜 신청 시 이 증명서를 **소지**하고 있어야 합니다.

### 실무에서 자주 틀리는 것

1. **미국 UL만 믿는 것** (위 참조)
2. **프랑스어 누락** — 연방 규칙상 제품명·**순수량** 등 법정 표시는 영·불 병기이고 식품 **Nutrition Facts는 이중언어 포맷 의무**입니다. 여기에 **퀘벡 Bill 96**이 상표 안의 일반·설명 문구(성분·색상·향·특성)까지 프랑스어를 요구합니다 — **2025년 6월 1일 발효**, 재고 소진 유예는 **2027년 6월 1일 종료**입니다. 영문 전용 아트워크는 퀘벡 유통 불가입니다.
3. **SFC licence 주체 혼동** — 라이선스는 원칙적으로 **캐나다 수입자**가 보유하며 캐나다 내 고정사업장을 요구합니다.
4. **무선기기에 캐나다 대리인 미지정** — 해외 신청인은 **Canadian Representative 지정과 Form A 서명이 필수**이고, 제품이 시장에 있는 **전 기간** 계약이 유효해야 합니다. 대리인은 **감사용 샘플 무상 제공** 의무를 집니다.
5. **ICES-003을 "인증"으로 오해** — 그건 자기선언이고, 반대로 무선(RSS)은 자기선언이 불가하며 TAC가 필수입니다. 이 둘을 뒤바꾸는 사례가 많습니다.
