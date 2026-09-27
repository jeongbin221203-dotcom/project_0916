"""퍼즈 스크립트가 쓸 앱을 만듭니다. **반드시 버리는 DB에서만** 돕니다.

왜 이 파일이 따로 있나
  예전에는 스크립트마다 이렇게 적었습니다.

      app = create_app()
      app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

  이 두 줄은 아무 일도 하지 않습니다. Flask-SQLAlchemy 3.1은 `init_app()`에서
  엔진을 이미 만들어 두기 때문에, 그 뒤에 설정을 바꿔도 엔진은 그대로입니다.
  그래서 스크립트는 메모리에 쓴다고 믿은 채 **개발용 실제 DB**
  (`instance/forwardus.db`)에 썼습니다.

  결과: 주인 없는 Shipment가 154건 쌓여 관리자 화면이 "(작성자 없음)"으로 덮였습니다.
  퍼즈는 일부러 이상한 값을 넣어 보는 스크립트라, 그 흔적이 실제 자료에 남으면 안 됩니다.
  (2026-09-25 확인)

  설정은 `create_app()`에 **넘겨야** 합니다. 넘긴 뒤에도 정말 메모리인지 확인하고,
  아니면 한 줄도 쓰지 않고 멈춥니다. 조용히 실DB에 쓰는 것보다 멈추는 편이 낫습니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app                                        # noqa: E402
from app.extensions import db                                     # noqa: E402
from config import TestConfig                                     # noqa: E402


def build_app():
    """메모리 DB 위에 올린 앱. 표까지 만들어 돌려줍니다."""

    app = create_app(TestConfig)
    with app.app_context():
        url = str(db.engine.url)
        if ":memory:" not in url:
            raise SystemExit(
                f"퍼즈는 버리는 DB에서만 돕니다. 지금 엔진이 가리키는 곳: {url}\n"
                "실제 자료에 시험 흔적을 남기지 않으려고 여기서 멈춥니다.")
        db.create_all()
    return app
