"""Local development entry point."""

from __future__ import annotations

from app import create_app

app = create_app()


if __name__ == "__main__":
    # 개발 중에는 파일을 고치면 자동으로 다시 읽도록 합니다. 이렇게 하지 않으면
    # 템플릿·파이썬 코드를 바꿔도 서버를 껐다 켜기 전까지 화면이 그대로입니다.
    app.run(host="0.0.0.0", port=app.config["PORT"],
            debug=app.config["DEBUG"], use_reloader=True)
