# 외부 자료·라이브러리 출처와 라이선스

FORWARDUS 가 쓰는 데이터와 도구의 출처입니다. 라이선스 이름은 각 배포처 안내를 기준으로 적었고, **제출·배포 전에 법무 확인이
필요한 항목은 "확인 필요"** 로 표시했습니다. 데이터를 다시 만드는 순서는 `forwardus/docs/data_refresh.md` 를 보세요.

## 데이터

| 자료 | 쓰는 곳 | 출처 | 라이선스·조건 |
|---|---|---|---|
| UN/LOCODE (항구 코드·이름) | 항구 목록, 직접 입력 | UNECE | 출처 표기 조건이 있을 수 있음 — 확인 필요 |
| World Port Index (항구 규모) | 항구 분류 | 미국 NGA | 미국 정부 공개 자료 |
| OurAirports (공항) | 공항 목록 | ourairports.com | 퍼블릭 도메인 |
| airline-route-data (직항 노선) | 항공 직항 여부 | 공개 저장소 | 확인 필요 |
| searoute / marnet 해상 항로망 | 해상 거리·소요일 | searoute-py, EMODnet 기반 | 확인 필요 |
| ISO 3166 국가 목록 | 국가 이름·코드 | 공개 목록 | 확인 필요 |
| 관세청 UNI-PASS·공공데이터포털 API | 관세·세관장확인·환율 조회 | 관세청·data.go.kr | 이용약관 준수, 키는 이용자가 발급 |
| 한-FTA 협정 정보·세율 | FTA 안내 | 관세청 FTA 포털 | 공공누리 등 확인 필요 |
| CUAD / LEDGAR (계약서 시험 자료) | 계약서 점검 규칙 검증 | The Atticus Project 등 | CC BY 4.0 |
| 도착국 규제·인증 안내(`country_notes_extra.py` 등) | 나라별 안내 | 인증기관·법률사무소·정부 공지 요약 | 요약·재서술, **공식 원문과 대조 전 — 줄마다 "확인 필요"** |

## 폰트·라이브러리

| 항목 | 쓰는 곳 | 라이선스 |
|---|---|---|
| Nanum 계열 글꼴 (Docker 이미지의 `fonts-nanum`) | 서류 PDF 한글 | SIL Open Font License 1.1 |
| Flask, SQLAlchemy, Jinja2, Werkzeug, gunicorn | 웹 앱 | BSD 계열 / MIT |
| Pillow, pdfplumber, pypdfium2, python-docx, pytesseract | 서류 읽기·그리기 | HPND(Pillow) / MIT / Apache-2.0 등 |
| Tesseract OCR | 사진·스캔 서류 읽기 | Apache-2.0 |
| httpx, python-dotenv | 외부 호출·설정 | BSD |

## 확인이 필요한 파일

- 저장소 루트의 `NanumSquareNeoOTF-*.otf` 5개는 현재 코드에서 참조하지 않습니다. 라이선스 전문 없이 보관 중이므로
  (1) 제거하거나 (2) 라이선스 파일과 함께 두는 것을 결정해 주세요.
- 외부 AI(OpenAI) 로 전송되는 내용과 범위는 `README.md` 의 "데이터 흐름" 절에 적었습니다.
