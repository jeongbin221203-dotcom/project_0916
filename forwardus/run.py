"""Local development entry point."""

from __future__ import annotations

from app import create_app

app = create_app()

# use_reloader는 .py 파일만 지켜봅니다. 화면 파일(templates/*.html)은 Jinja가
# 한 번 읽어 기억해 두기 때문에, 화면만 고치면 서버를 껐다 켜기 전까지 바뀐
# 것이 보이지 않습니다. 개발 중에는 고친 대로 바로 보이는 편이 낫습니다.
# (운영 설정은 건드리지 않습니다. 여기는 개발용 진입점입니다)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


if __name__ == "__main__":
    # 개발 중에는 파일을 고치면 자동으로 다시 읽도록 합니다. 이렇게 하지 않으면
    # 템플릿·파이썬 코드를 바꿔도 서버를 껐다 켜기 전까지 화면이 그대로입니다.
    app.run(host="0.0.0.0", port=app.config["PORT"],
            debug=app.config["DEBUG"], use_reloader=True)


