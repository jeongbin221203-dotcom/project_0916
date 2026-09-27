"""일꾼 둘이 동시에 뜰 때 마스터 계정 만들기. (2026-09-27)

왜 있나
  Render 에 올리자마자 502 가 났습니다. gunicorn 일꾼 둘이 같은 순간에 뜨면서
  둘 다 마스터 계정을 만들려 했고, 뒤늦은 쪽이 UNIQUE 에 걸려 죽었습니다.
  일꾼 하나가 죽으면 gunicorn 이 "Worker failed to boot" 로 **앱 전체를
  내립니다.** 첫 화면조차 안 떴습니다.

  로컬에서는 한 번도 안 보였습니다 — `python run.py` 는 일꾼이 하나입니다.
  **일꾼이 둘 이상인 곳에서만** 나서 배포하고서야 드러났습니다.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app import ensure_master_account
from app.extensions import db
from app.models import User


def test_다른_일꾼이_먼저_만들었어도_죽지_않는다(app, monkeypatch):
    """commit 이 UNIQUE 로 터지는 순간을 흉내 냅니다.

    그 사이 다른 일꾼이 같은 계정을 만들어 둔 상황입니다. 되돌리고 다시
    찾아보면 있으므로, 조용히 넘어가야 합니다.
    """

    email = "race-test@forwardus.example"
    real_commit = db.session.commit
    state = {"tried": False}

    def commit_once_conflicting():
        if not state["tried"]:
            state["tried"] = True
            # 다른 일꾼이 먼저 넣은 셈 치고, 이 일꾼의 시도는 터뜨립니다.
            db.session.rollback()
            other = User(email=email, name="먼저 만든 쪽", is_master=True)
            other.set_password("x" * 12)
            db.session.add(other)
            real_commit()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        return real_commit()

    monkeypatch.setattr(db.session, "commit", commit_once_conflicting)
    # 여기서 예외가 올라오면 일꾼이 죽고 앱이 안 뜹니다.
    ensure_master_account(db, email, "some-password-12")

    found = User.query.filter_by(email=email).all()
    assert len(found) == 1, f"계정이 {len(found)}개 생겼습니다"


def test_정말_못_만들면_숨기지_않는다(app, monkeypatch):
    """겹친 것이 아니라 진짜 실패면 그대로 올려야 합니다.

    조용히 넘기면 마스터 계정이 없는 채로 서버가 떠서, 아무도 전체 화물을
    못 봅니다. 그 편이 더 나쁩니다.
    """

    def always_fails():
        db.session.rollback()
        raise IntegrityError("INSERT", {}, Exception("뭔가 다른 문제"))

    monkeypatch.setattr(db.session, "commit", always_fails)
    with pytest.raises(IntegrityError):
        ensure_master_account(db, "never-created@forwardus.example", "some-password-12")
