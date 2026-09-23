"""Application configuration."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{BASE_DIR / 'instance' / 'forwardus.db'}"
    # Render provides postgres:// URLs; SQLAlchemy 2.x needs an explicit driver (psycopg 3).
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


# UNI-PASS (관세청) OpenAPI: each service has its own key, read from UNIPASS_KEY_<NAME>.
UNIPASS_SERVICES = {
    "HS_NAVIGATION": "HS CODE 내비게이션",
    "HS_CODE_SEARCH": "HS부호검색",
    "SIMPLE_REFUND_COMPANY": "간이정액적용비적용업체조회",
    "SIMPLE_REFUND_RATE": "간이정액환급율표조회",
    "INSPECTION_QUARANTINE": "검사검역내역조회",
    "TARIFF_RATE": "관세율기본조회",
    "CUSTOMS_EXCHANGE_RATE": "관세환율정보조회",
    "SHIPPING_COMPANY_DETAIL": "선박회사내역조회",
    "SHIPPING_COMPANY_LIST": "선박회사목록조회",
    "EXPORT_PERFORMANCE_BY_DECLARATION": "수출신고번호별수출이행내역조회",
    "EXPORT_DECLARATION_VERIFY": "수출신고필증검증",
    "EXPORT_PERIOD_SHORTENING_ITEM": "수출이행기간단축대상품목조회",
    "EXPORT_PERFORMANCE_BY_VIN": "수출이행내역차대번호조회",
    "DECLARATION_ATTACHMENT_SUBMISSION": "수출입신고 첨부서류사후제출 유무",
    "DECLARATION_CORRECTION_STATUS": "수출입신고서 정정신청 처리상태 제공",
    "REQUIREMENT_APPROVAL": "수출입요건승인내역조회",
    "ENTRY_DEPARTURE_REPORT": "입출항보고내역조회",
    "ARRIVAL_REPORT_AIR": "입항보고내역조회(항공)",
    "ARRIVAL_REPORT_SEA": "입항보고내역조회(해상)",
    "REEXPORT_COMPLETION_REPORT": "재수출 이행 완료보고 처리정보 제공",
    "REEXPORT_CONDITIONAL_IMPORT_DEADLINE": "재수출 조건부 수입의 수출이행 기한 정보제공",
    "REEXPORT_EXEMPTION_BALANCE": "재수출면세이행잔량조회",
    "DEPARTURE_PERMIT_AIR": "출항허가항공 조회",
    "DEPARTURE_PERMIT_SEA": "출항허가해상 조회",
    "CONTAINER_DETAIL": "컨테이너내역조회",
    "STATISTICS_CODE": "통계부호내역조회",
    "CUSTOMS_CLEARANCE_CODE": "통관고유부호조회",
    "AIRLINE_DETAIL": "항공사내역조회",
    "AIRLINE_LIST": "항공사목록조회",
    "FORWARDER_DETAIL": "화물운송주선업자내역조회",
    "FORWARDER_LIST": "화물운송주선업자목록조회",
    "CARGO_CLEARANCE_PROGRESS": "화물통관진행정보조회",
}


class Config:
    """Base configuration loaded from environment variables."""

    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    PORT = int(os.getenv("PORT", "5000"))
    SECRET_KEY = os.getenv("SECRET_KEY") or "forwardus-local-dev-key"

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DATA_DIR = BASE_DIR / "data"
    MOCK_DATA_DIR = DATA_DIR / "mock"
    # 바깥에서 받은 참고자료(HS 품목분류표·도착국 세율)를 두는 곳. git에 올리지 않습니다.
    CACHE_DIR = DATA_DIR / "cache"

    EXCHANGE_RATE_USD_KRW = float(os.getenv("EXCHANGE_RATE_USD_KRW", "1380"))
    API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "8"))

    # 닿지 않은 기관을 이만큼 건너뜁니다. 0을 넣으면 매번 다시 부릅니다.
    #
    # 관세청이 막혀 있을 때 HS 검색 한 번이 여덟 번을 부르며 30초를 썼습니다.
    # 화면은 20초에 끊으므로 아무것도 못 봤습니다. 한 번 닿지 않으면
    # 그다음부터는 기다리지 않고 가지고 있는 자료로 답합니다.
    API_OUTAGE_SECONDS = float(os.getenv("API_OUTAGE_SECONDS", "60"))

    # 선사·항공사 실스케줄. 둘 다 무료이고 따로 신청해야 합니다.
    # HMM_API_KEY: apiportal.hmm21.com (해상 항구간 스케줄, 시간당 300회)
    # DATA_GO_KR_SERVICE_KEY: data.go.kr 인천국제공항공사 화물기 운항 일정
    HMM_API_KEY = os.getenv("HMM_API_KEY", "")
    DATA_GO_KR_SERVICE_KEY = os.getenv("DATA_GO_KR_SERVICE_KEY", "")

    SCHEDULE_API_KEY = os.getenv("SCHEDULE_API_KEY", "")
    TRACKING_API_KEY = os.getenv("TRACKING_API_KEY", "")
    CUSTOMS_API_KEY = os.getenv("CUSTOMS_API_KEY", "")
    # 환율 시세표(사이드바 💱). 앞의 것이 있으면 앞의 것을 씁니다. (fx_board_client)
    # EXCHANGE_API_KEY: 한국수출입은행 현재환율 API authkey (은행 고시 TTB·TTS·매매기준율)
    # OPEN_EXCHANGE_RATES_APP_ID: openexchangerates.org (시장 환율, 무료 월 1,000회)
    EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
    OPEN_EXCHANGE_RATES_APP_ID = os.getenv("OPEN_EXCHANGE_RATES_APP_ID", "")
    # 사진·스캔 서류를 읽는 Tesseract OCR (app/processors/ocr.py). 비워 두면 흔한 설치 경로를 찾습니다.
    # TESSERACT_CMD: tesseract.exe 경로 · TESSDATA_DIR: kor/eng.traineddata가 있는 폴더
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")
    TESSDATA_DIR = os.getenv("TESSDATA_DIR", "")
    # OPENAI_API_KEY로 적어 두신 경우에도 받습니다. 둘 중 하나만 있으면 됩니다.
    AI_API_KEY = os.getenv("AI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    # HS 품목분류는 틀리면 관세포탈이 되는 자리라 더 나은 모형을 씁니다.
    # 상담·서류 읽기는 gpt-4o-mini로 충분하지만 여기만 따로 둡니다.
    AI_HS_MODEL = os.getenv("AI_HS_MODEL", "gpt-4o")
    # 올린 서류(오퍼시트)를 읽는 모형. 스캔 사진도 읽어야 해서 그림을 보는 모형이어야 합니다.
    # 단가·금액이 서류에 그대로 찍히는 자리라 상담용(mini)보다 나은 모형을 씁니다.
    AI_DOC_MODEL = os.getenv("AI_DOC_MODEL", "gpt-4o")

    UNIPASS_API_KEYS = {name: os.getenv(f"UNIPASS_KEY_{name}", "") for name in UNIPASS_SERVICES}


    # 시작 화면을 잠급니다.
    #
    # 왼쪽 줄, 탭, 적는 칸, 고객 상담 단추가 모두 눌리지 않습니다.
    # 위쪽 메뉴(운송 계획 · Shipments · 컨테이너 조회 · 관세청 조회 · 로그인)만
    # 그대로 씁니다.
    #
    # 보여 주기용으로 시작 화면만 막아 둘 때 씁니다.
    #
    # 기본은 열어 둡니다. 시작 화면이 이제 대화하는 주 화면이라, 잠근 채로
    # 두면 이 서비스의 본체가 통째로 안 보입니다.
    # 발표나 시연 때만 .env에 HOME_LOCKED=1 을 넣어 잠그세요.
    HOME_LOCKED = os.getenv("HOME_LOCKED", "0") == "1"

    # 모든 사용자의 Shipment를 보는 마스터 계정. 앱이 뜰 때 없으면 만듭니다.
    # 비밀번호는 처음 만들 때만 씁니다. 운영에서는 .env에서 꼭 바꾸세요.
    # TODO(보안): 브랜치를 모두 합친 뒤 기본 비밀번호 "1234"를 없앱니다.
    MASTER_EMAIL = os.getenv("MASTER_EMAIL", "forwardus@gmail.com").strip().lower()
    MASTER_PASSWORD = os.getenv("MASTER_PASSWORD", "1234")


class TestConfig(Config):
    """Configuration for automated tests (in-memory database)."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    # 시험할 때는 열어 둡니다. 잠근 채로 돌리면 평소 경로를 아무도 보지
    # 않게 되어, 잠금을 푸는 날 무엇이 깨졌는지 알 수 없습니다.
    # 잠금 자체를 보는 테스트는 그때만 켜서 봅니다.
    HOME_LOCKED = False

    # 테스트는 OpenAI를 부르지 않습니다.
    #
    # 키가 있으면 대화 창구가 실제로 바깥을 부릅니다. 느려지고, 돈이 나가고,
    # 무엇보다 남의 서버 사정에 따라 테스트가 됐다 안 됐다 합니다.
    # (실제로 이것 때문에 한 번 실패했습니다)
    # AI를 보는 테스트는 ai_client.chat을 흉내 내서 씁니다.
    AI_API_KEY = ""

    # 기관이 막혀 있으면 연결이 끊길 때까지 기다립니다. 기본 8초인데,
    # Shipment를 만드는 테스트마다 한 번씩 물어보니 전체가 한 시간을 넘겼습니다.
    # 테스트는 우리 코드가 맞는지 보는 것이지 기관이 살아 있는지 보는 것이
    # 아닙니다. 못 받으면 예시 값으로 넘어가는 길이 이미 있습니다.
    # (실데이터를 확인하는 테스트는 needs_customs_api로 건너뜁니다)
    API_TIMEOUT_SECONDS = 2.0

    # 건너뛰기는 꺼 둡니다.
    #
    # 테스트는 일부러 끊긴 응답을 여러 번 흉내 냅니다. 켜 두면 첫 번째만
    # 진짜로 불리고 나머지는 건너뛰어, 무엇을 보려던 테스트인지 알 수 없게
    # 됩니다. 건너뛰기 자체를 보는 테스트는 그때만 켜서 봅니다.
    API_OUTAGE_SECONDS = 0.0
