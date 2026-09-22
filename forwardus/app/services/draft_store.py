"""올린 서류에서 읽은 값을 잠시 서버에 둡니다.

오퍼시트를 한 번 읽으면 그 값을 운송 계획·서류 작성 화면에서 이어 씁니다.
화면을 옮길 때마다 다시 올리고 다시 읽지 않게 하려는 자리입니다.

**은행 정보와 바이어 주소·연락처는 여기 들어오지 않습니다.**
부르는 쪽이 이미 빼고 넘기지만, 저장하는 순간에 한 번 더 걸러 냅니다.
실수로 한 번 섞여 들어와도 파일에는 남지 않게 하려는 것입니다.
그 값들은 이용자 브라우저에만 있고, PDF를 만들 때만 잠깐 서버를 지나갑니다.

바이어 **회사명**은 남깁니다. 뒤의 서류(상업송장·수출신고)에 계속 쓰입니다.

오래 두지 않습니다. KEEP_HOURS가 지나면 읽을 때 지웁니다.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from flask import current_app, has_app_context

# 서버에 두지 않는 칸. 어느 깊이에 있든 이름이 같으면 뺍니다.
SENSITIVE_KEYS = frozenset({
    "bank_info", "bank", "bank_account", "account_no", "swift", "iban",
    "buyer_address", "consignee_address", "buyer_email", "buyer_phone", "buyer_contact",
    "attention", "private",
})

KEEP_HOURS = 72
TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _root() -> Path:
    base = Path(current_app.instance_path) if has_app_context() else Path.cwd() / "instance"
    configured = current_app.config.get("OFFER_DRAFT_DIR") if has_app_context() else None
    root = Path(configured) if configured else base / "offer_drafts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def scrub(value):
    """민감한 칸을 뺀 사본. 목록과 사전 안쪽까지 봅니다.

    칸 이름이 사전의 **키**로 있을 때({"bank_info": "..."})뿐 아니라, 화면용 줄처럼
    **값**으로 있을 때({"key": "bank_info", "value": "..."})도 값을 지웁니다.
    """

    if isinstance(value, dict):
        if value.get("key") in SENSITIVE_KEYS:
            value = {**value, "value": ""}
        return {key: scrub(item) for key, item in value.items() if key not in SENSITIVE_KEYS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def save(data: dict) -> str:
    """저장하고 표(token)를 돌려줍니다. 이 표로만 다시 꺼낼 수 있습니다."""

    purge()
    token = uuid.uuid4().hex
    path = _root() / f"{token}.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"saved_at": time.time(), "data": scrub(data)},
                               ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    return token


def load(token: str) -> dict | None:
    """없거나, 모양이 이상하거나, 오래됐으면 None."""

    if not TOKEN.match(str(token or "")):
        return None                     # 경로를 조작하는 값이 들어와도 파일을 열지 않습니다.
    path = _root() / f"{token}.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(stored.get("saved_at", 0)) > KEEP_HOURS * 3600:
        path.unlink(missing_ok=True)
        return None
    return stored.get("data")


def delete(token: str) -> None:
    if TOKEN.match(str(token or "")):
        (_root() / f"{token}.json").unlink(missing_ok=True)


def purge() -> None:
    """오래된 것을 지웁니다."""

    cutoff = time.time() - KEEP_HOURS * 3600
    for path in _root().glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass
