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
             # 보관 온도(냉장·냉동)와 특수 컨테이너(오픈탑·플랫랙·탱크) 요청
             "temperature_requirement": "VARCHAR(20) NOT NULL DEFAULT ''",
             "special_container_type": "VARCHAR(20) NOT NULL DEFAULT ''",
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


def migrate_buyer_columns(database) -> None:
    """바이어를 등록한 회원 칸을 기존 buyers 표에 덧붙입니다. 옛 줄은 주인 없음(NULL)으로 둡니다."""

    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "buyers" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("buyers")}
    if "user_id" not in columns:
        with database.engine.begin() as connection:
            connection.execute(text("ALTER TABLE buyers ADD COLUMN user_id INTEGER"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_buyers_user_id ON buyers (user_id)"))


def migrate_user_columns(database) -> None:
    """마스터 표시 칸을 기존 users 표에 덧붙입니다."""

    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "is_master" not in columns:
        with database.engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE users ADD COLUMN is_master BOOLEAN NOT NULL DEFAULT FALSE"))


def ensure_master_account(database, email: str, password: str) -> None:
    """마스터 계정이 없으면 만듭니다.

    같은 이메일로 먼저 가입한 일반 계정이 있으면 마스터로 올리고 비밀번호도
    정해 둔 값으로 바꿉니다. 그대로 두면 먼저 가입한 사람이 마스터가 됩니다.
    이미 마스터이면 비밀번호를 건드리지 않습니다.
    """

    from sqlalchemy.exc import IntegrityError

    from app.models import User

    if not email or not password:
        return
    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(email=email, name="ForwardUs 마스터", is_master=True)
        user.set_password(password)
        database.session.add(user)
    elif not user.is_master:
        user.is_master = True
        user.set_password(password)
    else:
        return
    try:
        database.session.commit()
    except IntegrityError:
        # **다른 일꾼이 같은 순간에 먼저 만들었습니다.**
        #
        # 위는 "찾아보고 → 없으면 넣는" 모양이라 그 사이가 비어 있습니다.
        # gunicorn 일꾼 둘이 같이 뜨면 둘 다 "없다"를 보고 둘 다 넣습니다.
        # 뒤늦은 쪽이 UNIQUE 에 걸리는데, 그때 이 일꾼이 죽으면 gunicorn 이
        # "Worker failed to boot" 로 **앱 전체를 내립니다.** (2026-09-27 Render 502)
        #
        # 겹친 것 자체는 잘못이 아닙니다 — 만들려던 것이 이미 있으니 된 것입니다.
        # 되돌리고 다시 찾아봅니다. 정말 있으면 조용히 넘어갑니다.
        database.session.rollback()
        if User.query.filter_by(email=email).first() is None:
            raise                       # 없는데도 실패했다면 그건 진짜 문제입니다


# 코드가 반드시 있다고 믿는 열. 준비 작업이 실패한 뒤 이것이 없으면 뜨지 않습니다.
REQUIRED_COLUMNS = {"users": ("is_master",), "buyers": ("user_id",), "shipments": ("user_id", "status")}


def _missing_schema() -> list[str]:
    from sqlalchemy import inspect

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    missing = []
    for table, columns in REQUIRED_COLUMNS.items():
        if table not in tables:
            missing.append(table)
            continue
        have = {column["name"] for column in inspector.get_columns(table)}
        missing += [f"{table}.{name}" for name in columns if name not in have]
    return missing


# 뜰 때 하는 데이터베이스 준비에 거는 자물쇠 번호. 아무 숫자나 되지만,
# 이 앱의 준비 작업임을 가리키는 표지라 바꾸지 않습니다.
SETUP_LOCK_KEY = 8711_0916


def setup_database(flask_app) -> None:
    """테이블을 만들고 옛 자료를 손본 뒤 마스터 계정을 둡니다.

    **한 번에 하나씩만 합니다.**

    왜 자물쇠가 필요한가
      gunicorn 일꾼이 둘 이상이면 같은 순간에 다 같이 이 일을 합니다.
      db.create_all() 은 "있나 보고 → 없으면 만드는" 모양이라 그 사이가
      비어 있습니다. 둘 다 "없다"를 보고 둘 다 CREATE TABLE 을 던지면
      뒤늦은 쪽이 터집니다.

        psycopg.errors.UniqueViolation: pg_type_typname_nsp_index
        DETAIL:  Key (typname, typnamespace)=(buyers, 2200) already exists.

      일꾼 하나가 죽으면 gunicorn 이 "Worker failed to boot" 로 **앱 전체를
      내립니다.** 첫 화면조차 안 뜹니다. (2026-09-27 Render 502)

      뜰 때 하는 일이 여섯 가지인데 전부 같은 경합을 안고 있어, 하나씩
      막으면 끝이 없습니다. 통째로 자물쇠 안에 넣습니다.

    pg_advisory_xact_lock 은 거래가 끝나면 **스스로 풀립니다.** 풀어 주는 것을
    잊거나, 중간에 터져서 자물쇠가 걸린 채 남는 일이 없습니다.

    SQLite(로컬·시험)에는 이런 자물쇠가 없습니다. 거기서는 프로세스가 하나라
    애초에 겹치지 않습니다.
    """

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

    if db.engine.dialect.name == "postgresql":
        db.session.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                           {"key": SETUP_LOCK_KEY})
    try:
        db.create_all()
        migrate_cargo_lines(db)
        migrate_shipment_columns(db)
        migrate_cost_sources(db)
        migrate_requirement_documents(db)
        migrate_user_columns(db)
        migrate_buyer_columns(db)
        ensure_master_account(db, flask_app.config.get("MASTER_EMAIL", ""),
                              flask_app.config.get("MASTER_PASSWORD", ""))
    except (IntegrityError, ProgrammingError, OperationalError):
        # 자물쇠를 쓸 수 없는 곳(SQLite 등)에서 그래도 겹쳤다면, 다른 쪽이
        # 이미 만들어 둔 것입니다. 한 번 눈감고 있는 그대로 씁니다.
        db.session.rollback()
        flask_app.logger.warning("데이터베이스 준비가 겹쳤습니다. 다른 일꾼이 "
                                 "먼저 끝낸 것으로 보고 넘어갑니다.", exc_info=True)
        # 그러나 **진짜 실패**(ALTER 권한 없음·잠금 시간 초과)까지 삼키면 열이 빠진 채 떠서 모든 질의가
        # 500 이 됩니다(관리자 점검 2회차). 필요한 열이 실제로 있는지 다시 확인하고, 없으면 기동을 멈춥니다.
        missing = _missing_schema()
        if missing:
            raise RuntimeError("데이터베이스 준비에 실패했습니다 — 없는 열: " + ", ".join(missing))
    db.session.commit()          # 자물쇠는 여기서 풀립니다


def create_app(config_class: type[Config] = Config) -> Flask:
    """Create and configure the Flask application."""

    flask_app = Flask(__name__)
    flask_app.config.from_object(config_class)

    db_uri = flask_app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///") and ":memory:" not in db_uri:
        Path(db_uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

    db.init_app(flask_app)

    # 쿠키·출처 확인·횟수 제한·응답 머리글·비밀키 점검 (app/security.py)
    from app import security
    security.install(flask_app)

    from app import models  # noqa: F401  Registers model metadata.
    from app.routes import register_blueprints

    register_blueprints(flask_app)

    with flask_app.app_context():
        setup_database(flask_app)

    @flask_app.get("/health")
    def health():
        # DB 가 끊기거나 Render 무료 Postgres 가 만료돼도 늘 ok 였습니다 — 헬스체크가 재시작·알림의 신호가
        # 되려면 DB 를 한 번 물어봐야 합니다(관리자 점검 2회차).
        from sqlalchemy import text

        try:
            db.session.execute(text("SELECT 1"))
        except Exception:                          # noqa: BLE001 — 어떤 DB 오류든 '못 쓴다'입니다
            db.session.rollback()
            flask_app.logger.error("헬스체크: DB 에 닿지 못했습니다", exc_info=True)
            return jsonify({"status": "db_down"}), 503
        return jsonify({"status": "ok"})

    @flask_app.context_processor
    def inject_globals():
        # 고객상담 창은 모든 화면에 붙으므로 여기서 한 번만 준비합니다.
        from app.services import support_chat_service

        from app.routes.auth import current_user

        from app.routes import sidebar

        viewer = current_user()
        try:
            rail = sidebar.context(viewer)
        except Exception:                    # 오류 화면을 그리다 사이드바 때문에 또 깨지지 않게
            db.session.rollback()
            rail = {"links": [], "recent": []}
        return {"nav_active": request.blueprint or "", "static_url": static_url,
                "current_user": viewer, "sidebar": rail,
                "support_chat_intro": support_chat_service.intro(),
                "support_icon": support_icon(),
                "brand_logo": _pick_image("logo"),
                "brand_mark": _pick_image("logo_mark"),
                "home_locked": flask_app.config.get("HOME_LOCKED", False),
                "contract_on": flask_app.config.get("CONTRACT_CLAUSES_ON", False)}

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
        # /api 가 아닌 곳(/documents/start 등)에 JSON 을 보내다 500 이 나면 HTML 오류 페이지가 와서 화면의
        # response.json() 이 터졌습니다 — JSON 요청이면 JSON 으로 답합니다(관리자 점검 2회차).
        return (request.path.startswith("/api") or "/api/" in request.path or request.is_json
                or "application/json" in (request.headers.get("Accept") or ""))

    @flask_app.errorhandler(404)
    def not_found(_error):
        if _wants_json():
            return jsonify({"success": False, "error_code": "NOT_FOUND", "message": "요청한 리소스를 찾을 수 없습니다."}), 404
        return render_template("error.html", code=404, message="요청한 페이지를 찾을 수 없습니다."), 404

    @flask_app.errorhandler(405)
    def method_not_allowed(_error):
        # 영어 기본 "405 Method Not Allowed" 가 그대로 나갔습니다(사용성 점검 2회차) — 다른 오류처럼 우리 화면으로.
        message = "이 주소는 이런 방식으로는 열 수 없습니다. 화면의 단추나 메뉴로 들어와 주세요."
        if _wants_json():
            return jsonify({"success": False, "error_code": "METHOD_NOT_ALLOWED", "message": message}), 405
        return render_template("error.html", code=405, message=message), 405

    @flask_app.errorhandler(403)
    def forbidden(_error):
        message = "관리자(마스터) 계정만 쓸 수 있는 기능입니다."
        if _wants_json():
            return jsonify({"success": False, "error_code": "FORBIDDEN", "message": message}), 403
        return render_template("error.html", code=403, message=message), 403

    @flask_app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        if _wants_json():
            return jsonify({"success": False, "error_code": "SERVER_ERROR", "message": "일시적인 오류가 발생했습니다."}), 500
        return render_template("error.html", code=500, message="일시적인 오류가 발생했습니다."), 500

    return flask_app
