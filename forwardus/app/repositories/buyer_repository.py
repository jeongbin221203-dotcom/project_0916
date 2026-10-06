"""Buyer persistence."""

from __future__ import annotations

from app.extensions import db
from app.models import Buyer


def list_buyers() -> list[Buyer]:
    return Buyer.query.order_by(Buyer.name).all()


def get_or_create(name: str, country: str, address: str, contact_email: str,
                  user_id: int | None = None) -> Buyer:
    """같은 회원의 같은 이름·나라 바이어를 다시 씁니다. 주소·이메일이 **다르면 새 줄**입니다.

    전에는 이름+나라만 보는 전역 한 줄이라 두 가지가 깨졌습니다(전수 점검 1회차).
      · 다른 회원이 같은 바이어를 쓰면 주소·이메일이 덮어써져, 먼저 만든 회원의 서류가 어긋나고
        다른 회원의 이메일이 새어 나갔습니다.
      · 같은 회원이 주소를 바꿔 새 건을 만들면 **이전 건의 수하인 주소도** 바뀌었습니다.
    이제 회원별로 찾고, 빈칸만 채우며, 값이 다르면 새 줄을 만들어 옛 건은 그대로 둡니다.
    """

    candidates = (Buyer.query.filter_by(name=name, country=country, user_id=user_id)
                  .order_by(Buyer.id.desc()).all())
    for buyer in candidates:
        same_address = not address or not buyer.address or buyer.address == address
        same_email = not contact_email or not buyer.contact_email or buyer.contact_email == contact_email
        if same_address and same_email:
            if address and not buyer.address:
                buyer.address = address
            if contact_email and not buyer.contact_email:
                buyer.contact_email = contact_email
            return buyer
    buyer = Buyer(name=name, country=country, address=address, contact_email=contact_email,
                  user_id=user_id)
    db.session.add(buyer)
    db.session.flush()
    return buyer
