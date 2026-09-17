# 프로젝트 개발 및 협업 규칙 (Rules)

팀 프로젝트의 코드 품질 유지와 버전 관리 혼란을 방지하기 위한 표준 규칙입니다.
(AI 툴 이용시 해당 파일 참조시켜주세요.)

---

## 1. Git 커밋 규칙 (Commit Rules)

### Commit Summary 형식
* **형식**: `변경파일명_작성자이니셜_v(횟수)`
* **예시**: 
  * `requirements.txt_MS_v1`
  * `data_loader.js_JH_v2`
  * `app.py_MS_v1`
* **세부내용**: 변경 파일 명과 변경내용(추가/수정/삭제)를 명시합니다.

---

## 2. 파일 명명 규칙 (File Naming Conventions)

* 모든 파일명은 **영문 소문자**와 **snake_case(밑줄 `_`)** 조합으로 작성합니다.
* 특수문자, 공백, 한글 사용은 금지합니다.
* 파일의 목적이 드러나도록 명확하게 작성합니다.
  * **스크립트/모듈**: `데이터처리_세부기능.py` 형식 (예: `preprocess_data.py`, `model_train.py`)
  * **설정 및 환경 파일**: `config.py`, `requirements.txt`
  * **데이터 파일**: `원본/가공_데이터명.확장자` (예: `raw_user_logs.csv`, `cleaned_sales_2026.csv`)
  * **노트북(Jupyter)**: `순번_목적.ipynb` 형식 (예: `01_eda_distribution.ipynb`)

---

## 3. 코드 작성 표준 (Coding Standards)

### 변수 및 함수 명명 (Variables & Functions)
* **변수명**: 영문 소문자와 밑줄(`_`)을 사용하는 **snake_case**로 작성합니다.
  * 올바른 예: `app_data = pd.read_csv("data.csv")`, `user_count = 10`
  * 잘못된 예: `appData`, `UserCount`, `a1`
* **함수명**: 동작을 나타내는 동사로 시작하며 **snake_case**로 작성합니다.
  * 예: `calculate_mean()`, `load_raw_data()`
* **상수명**: 전체 대문자와 **snake_case**로 작성합니다.
  * 예: `MAX_ITERATION = 100`, `DEFAULT_TIMEOUT = 5`
* **클래스명**: 단어의 첫 글자를 대문자로 하는 **PascalCase**로 작성합니다.
  * 예: `DataPipeline`, `StockAnalyzer`

### 코드 주석 및 문서화
* 주석과 독스트링(Docstring)은 명확하고 간결한 기술 문서 어조(경어체/명사형 종결)로 작성합니다.
* 구어체, 친근한 어투, 비표준 약어는 코드 내에 작성하지 않습니다.

---

## 4. 디렉터리 구조 표준 (Directory Structure)



－－－－－
