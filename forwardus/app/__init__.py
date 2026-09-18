"""FORWARDUS application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from config import Config
from app.extensions import db


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

    @flask_app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @flask_app.context_processor
    def inject_globals():
        return {"nav_active": request.blueprint or ""}

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
