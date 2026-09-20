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
             "dg_class": "VARCHAR(5) NOT NULL DEFAULT ''"}
    missing = {name: spec for name, spec in added.items() if name not in columns}
    if missing:
        with database.engine.begin() as connection:
            for name, spec in missing.items():
                connection.execute(text(f"ALTER TABLE cargos ADD COLUMN {name} {spec}"))


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

    @flask_app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @flask_app.context_processor
    def inject_globals():
        return {"nav_active": request.blueprint or "", "static_url": static_url}

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
