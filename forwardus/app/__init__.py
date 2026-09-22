"""FORWARDUS application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request, url_for

from config import Config
from app.extensions import db


def migrate_cargo_lines(database) -> None:
    """화물 여러 건을 담을 수 있게 cargos 표를 고칩니다.

    예전 표는 Shipment 하나에 화물 하나만 달 수 있었고(shipment_pk UNIQUE)
    line_no 칸이 없었습니다. SQLite는 제약을 지우지 못하므로 새 표를 만들어
    기존 행을 옮긴 뒤 이름을 바꿉니다. 이미 고쳐진 DB에서는 아무 것도 하지 않습니다.
    """

    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "cargos" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("cargos")}

    if "line_no" not in columns:
        old_columns = ", ".join(sorted(columns - {"id"}))
        with database.engine.begin() as connection:
            connection.execute(text("ALTER TABLE cargos RENAME TO cargos_old"))
            database.metadata.tables["cargos"].create(connection)
            connection.execute(text(
                f"INSERT INTO cargos (id, line_no, {old_columns}) "
                f"SELECT id, 1, {old_columns} FROM cargos_old"))
            connection.execute(text("DROP TABLE cargos_old"))
        columns |= {"line_no"}

    # 위험물 칸은 뒤에 더해진 것이라 기존 행에는 없습니다. 칸만 덧붙이면 됩니다.
    added = {"is_dangerous": "BOOLEAN NOT NULL DEFAULT 0",
             "un_number": "VARCHAR(10) NOT NULL DEFAULT ''",
             "dg_class": "VARCHAR(5) NOT NULL DEFAULT ''",
             "packing_group": "VARCHAR(5) NOT NULL DEFAULT ''",
             "proper_shipping_name": "VARCHAR(200) NOT NULL DEFAULT ''",
             # 품목별 금액도 나중에 더해졌습니다.
             "unit_price": "FLOAT",
             "amount": "FLOAT",
             # 단가의 기준(낱개 수량 · 가격 단위 · 포장당 낱개 수)도 나중에 더해졌습니다.
             "unit_quantity": "FLOAT",
             "price_unit": "VARCHAR(10) NOT NULL DEFAULT ''",
             "units_per_package": "FLOAT"}
    missing = {name: spec for name, spec in added.items() if name not in columns}
    if missing:
        with database.engine.begin() as connection:
            for name, spec in missing.items():
                connection.execute(text(f"ALTER TABLE cargos ADD COLUMN {name} {spec}"))


def migrate_shipment_columns(database) -> None:
    """수출신고 자료용 칸을 기존 DB에 덧붙입니다."""

    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "shipments" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("shipments")}
    added = {
        "exporter_business_no": "VARCHAR(20) NOT NULL DEFAULT ''",
        "customs_trade_kind": "VARCHAR(4) NOT NULL DEFAULT '11'",
        "customs_payment_method": "VARCHAR(4) NOT NULL DEFAULT 'TT'",
        "country_of_origin": "VARCHAR(60) NOT NULL DEFAULT 'KR'",
        # 컨테이너·통관 조회에 쓰는 번호
        "bl_no": "VARCHAR(30) NOT NULL DEFAULT ''",
        "export_declaration_no": "VARCHAR(20) NOT NULL DEFAULT ''",
        "cargo_no": "VARCHAR(20) NOT NULL DEFAULT ''",
    }
    missing = {name: spec for name, spec in added.items() if name not in columns}
    if missing:
        with database.engine.begin() as connection:
            for name, spec in missing.items():
                connection.execute(text(f"ALTER TABLE shipments ADD COLUMN {name} {spec}"))


# 표준단가 표에서 나오는 비용 항목. 예전에는 이것도 "mock"으로 저장했는데,
# 가짜가 아니라 추정값이라 "tariff"로 고쳐 부릅니다.
TARIFF_COST_CODES = ("origin_trucking", "terminal_handling", "documentation",
                     "export_customs", "destination_charge")


def migrate_requirement_documents(database) -> None:
    """원산지증명서의 협정 칸을 기존 DB에 덧붙입니다."""

    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "requirement_documents" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("requirement_documents")}
    if "agreement" not in columns:
        with database.engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE requirement_documents ADD COLUMN agreement VARCHAR(120) "
                "NOT NULL DEFAULT ''"))


def migrate_cost_sources(database) -> None:
    """이미 저장된 비용 줄의 출처 표기를 고칩니다. 운임은 그대로 둡니다."""

    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "shipment_costs" not in inspector.get_table_names():
        return
    codes = ", ".join(f"'{code}'" for code in TARIFF_COST_CODES)
    with database.engine.begin() as connection:
        connection.execute(text(
            f"UPDATE shipment_costs SET source = 'tariff' "
            f"WHERE source = 'mock' AND code IN ({codes})"))


def create_app(config_class: type[Config] = Config) -> Flask:
    """Create and configure the Flask application."""

    flask_app = Flask(__name__)
    flask_app.config.from_object(config_class)

    db_uri = flask_app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///") and ":memory:" not in db_uri:
        Path(db_uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

    db.init_app(flask_app)

    from app import models  # noqa: F401  Registers model metadata.
    from app.routes import register_blueprints

    register_blueprints(flask_app)

    with flask_app.app_context():
        db.create_all()
        migrate_cargo_lines(db)
        migrate_shipment_columns(db)
        migrate_cost_sources(db)
        migrate_requirement_documents(db)

    @flask_app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @flask_app.context_processor
    def inject_globals():
        # 고객상담 창은 모든 화면에 붙으므로 여기서 한 번만 준비합니다.
        from app.services import support_chat_service

        from app.routes.auth import current_user

        return {"nav_active": request.blueprint or "", "static_url": static_url,
                "current_user": current_user(),
                "support_chat_intro": support_chat_service.intro(),
                "support_icon": support_icon(),
                "brand_logo": _pick_image("logo"),
                "brand_mark": _pick_image("logo_mark"),
                "home_locked": flask_app.config.get("HOME_LOCKED", False)}

    # 화면에 쓰는 그림은 파일만 올려 두면 바뀌도록 합니다.
    # app/static/images/ 에 아래 이름으로 넣으면 코드를 고치지 않아도 됩니다.
    #   logo.png        회사 로고 전체 (글자까지 들어간 가로형)
    #   logo_mark.svg   로고 마크만 (정사각형 · 좁은 자리에서 씁니다)
    #   support_whale.png  고객 상담 단추 그림
    IMAGE_TYPES = (".png", ".webp", ".jpg", ".jpeg", ".svg")

    def _pick_image(stem: str) -> str:
        folder = Path(flask_app.static_folder or "") / "images"
        for suffix in IMAGE_TYPES:
            if (folder / f"{stem}{suffix}").exists():
                return static_url(f"images/{stem}{suffix}")
        return ""

    def support_icon() -> str:
        return _pick_image("support_whale")

    def static_url(filename: str) -> str:
        """정적 파일 URL에 수정 시각을 붙입니다.

        파일을 고치면 주소가 바뀌므로 브라우저가 예전 파일을 계속 쓰지 않습니다.
        """

        path = Path(flask_app.static_folder or "") / filename
        version = int(path.stat().st_mtime) if path.exists() else 0
        return url_for("static", filename=filename, v=version)

    @flask_app.template_filter("won")
    def format_won(value):
        return "-" if value is None else f"{round(value):,}원"

    @flask_app.template_filter("num")
    def format_number(value, digits: int = 0):
        if value is None or value == "":
            return "-"
        return f"{value:,.{digits}f}"

    @flask_app.template_filter("d")
    def format_date(value):
        return value.isoformat() if hasattr(value, "isoformat") and value else (value or "-")

    def _wants_json() -> bool:
        return request.path.startswith("/api") or "/api/" in request.path

    @flask_app.errorhandler(404)
    def not_found(_error):
        if _wants_json():
            return jsonify({"success": False, "error_code": "NOT_FOUND", "message": "요청한 리소스를 찾을 수 없습니다."}), 404
        return render_template("error.html", code=404, message="요청한 페이지를 찾을 수 없습니다."), 404

    @flask_app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        if _wants_json():
            return jsonify({"success": False, "error_code": "SERVER_ERROR", "message": "일시적인 오류가 발생했습니다."}), 500
        return render_template("error.html", code=500, message="일시적인 오류가 발생했습니다."), 500

    return flask_app
