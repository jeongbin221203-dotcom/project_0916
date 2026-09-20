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

    EXCHANGE_RATE_USD_KRW = float(os.getenv("EXCHANGE_RATE_USD_KRW", "1380"))
    API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "8"))

    # 선사·항공사 실스케줄. 둘 다 무료이고 따로 신청해야 합니다.
    # HMM_API_KEY: apiportal.hmm21.com (해상 항구간 스케줄, 시간당 300회)
    # DATA_GO_KR_SERVICE_KEY: data.go.kr 인천국제공항공사 화물기 운항 일정
    HMM_API_KEY = os.getenv("HMM_API_KEY", "")
    DATA_GO_KR_SERVICE_KEY = os.getenv("DATA_GO_KR_SERVICE_KEY", "")

    SCHEDULE_API_KEY = os.getenv("SCHEDULE_API_KEY", "")
    TRACKING_API_KEY = os.getenv("TRACKING_API_KEY", "")
    CUSTOMS_API_KEY = os.getenv("CUSTOMS_API_KEY", "")
    EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
    AI_API_KEY = os.getenv("AI_API_KEY", "")

    UNIPASS_API_KEYS = {name: os.getenv(f"UNIPASS_KEY_{name}", "") for name in UNIPASS_SERVICES}


class TestConfig(Config):
    """Configuration for automated tests (in-memory database)."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
