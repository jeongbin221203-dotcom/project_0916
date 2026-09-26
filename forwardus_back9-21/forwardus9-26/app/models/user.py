"""회원 계정."""

from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, utc_now


ADMIN_ROLES = frozenset({"master", "admin"})


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    name = db.Column(db.String(100), nullable=False, default="")
    # 비밀번호는 원문을 두지 않고 해시만 둡니다.
    password_hash = db.Column(db.String(255), nullable=False)
    # 마스터 계정은 모든 사용자의 Shipment를 봅니다. 일반 회원은 자기 것만 봅니다.
    is_master = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    # 화면과 API가 나누는 권한 이름. 칸을 따로 두지 않고 is_master에서 읽습니다.
    #   master  모든 사용자의 Shipment를 보고, 상태를 바꾸고, 내려받습니다. ("admin"과 같게 봅니다)
    #   user    자기가 만든 Shipment만 봅니다.
    @property
    def role(self) -> str:
        return "master" if self.is_master else "user"

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
