"""Forwardus Flask application entry point."""

from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from config import Config
from src.collectors.mock_data import (
    get_bootstrap_data,
    get_hs_codes,
    get_locations,
    get_schedules,
)
from src.processors.cargo_calc import CargoValidationError, calculate_cargo_metrics
from src.processors.quote_engine import QuoteValidationError, build_quote


def create_app(config_class: type[Config] = Config) -> Flask:
    """Create and configure the Flask application."""

    flask_app = Flask(__name__)
    flask_app.config.from_object(config_class)

    @flask_app.get("/")
    def index():
        return render_template("index.html", bootstrap_data=get_bootstrap_data())

    @flask_app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @flask_app.get("/api/locations")
    def locations():
        mode = request.args.get("mode", "fcl")
        return jsonify({"items": get_locations(mode)})

    @flask_app.get("/api/schedules")
    def schedules():
        mode = request.args.get("mode", "fcl")
        sort_by = request.args.get("sort", "recommended")
        return jsonify({"items": get_schedules(mode, sort_by)})

    @flask_app.get("/api/hs-codes")
    def hs_codes():
        keyword = request.args.get("q", "")
        return jsonify({"items": get_hs_codes(keyword)})

    @flask_app.post("/api/calculate")
    def calculate():
        try:
            return jsonify(calculate_cargo_metrics(request.get_json(silent=True) or {}))
        except CargoValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @flask_app.post("/api/quote")
    def quote():
        try:
            return jsonify(build_quote(request.get_json(silent=True) or {}))
        except (CargoValidationError, QuoteValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @flask_app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "요청한 페이지를 찾을 수 없습니다."}), 404

    @flask_app.errorhandler(500)
    def server_error(_error):
        return jsonify({"error": "일시적인 오류가 발생했습니다."}), 500

    return flask_app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config["PORT"], debug=app.config["DEBUG"])

