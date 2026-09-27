"""바깥에서 받은 참고자료를 data/cache에 파일로 두고 다시 씁니다.

자주 바뀌지 않는 자료(HS 품목분류표, 연 단위 세율)만 둡니다. 서버를 다시 켜도
받아 둔 것을 그대로 쓰고, 기한이 지나면 새로 받되 받지 못하면 예전 것을 씁니다.

파일이 깨졌거나 쓸 수 없는 자리여도 조용히 "없음"으로 처리합니다. 캐시가
안 된다고 조회가 멈추면 안 됩니다.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from app.collectors.base_client import get_config
from config import Config


def cache_dir() -> Path:
    return Path(get_config("CACHE_DIR", Config.CACHE_DIR))


def _path(name: str) -> Path:
    return cache_dir() / f"{name}.json"


def read(name: str) -> tuple[Any, float] | None:
    """(내용, 받은 지 며칠). 파일이 없거나 깨졌으면 None."""

    path = _path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age_days = (time.time() - path.stat().st_mtime) / 86400
    except (OSError, ValueError):
        return None
    return data, age_days


def write(name: str, data: Any) -> None:
    """임시 파일에 다 쓴 뒤 바꿔 끼웁니다. 쓰다 끊겨도 반쯤 쓴 파일이 남지 않습니다."""

    path = _path(name)
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
