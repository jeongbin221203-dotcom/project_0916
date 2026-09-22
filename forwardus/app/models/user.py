"""회원 계정."""

from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, utc_now


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    name = db.Column(db.String(100), nullable=False, default="")
    # 비밀번호는 원문을 두지 않고 해시만 둡니다.
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
