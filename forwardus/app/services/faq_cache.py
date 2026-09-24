"""같은 질문에 같은 답을 다시 만들지 않습니다. (프로세스 안 메모리 캐시)

무엇을 담나
  개인 이야기가 섞이지 않은 일반 질문의 답만 담습니다. 앞 대화(history)나 지난 상담
  요약(memory)이 붙은 질문은 담지 않습니다 — 그 답은 그 사람 맥락에 매인 답이라
  다른 사람에게 보이면 안 됩니다.

열쇠에 무엇이 들어가나
  표준형 질문 + 답변 길이 모드(brief) + 지식베이스 버전(kb_version).
  FAQ를 고치면 kb_version이 올라가고, 예전 답은 저절로 버려집니다.

언제 버리나
  freshness가 `실시간 확인 필요`면 담지 않습니다. `정기 확인 필요`는 짧게,
  `안정적 지식`은 길게 둡니다. 관세율·운임처럼 움직이는 값은 캐시가 독입니다.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict

MAX_ENTRIES = 500
TTL_BY_FRESHNESS = {
    "안정적 지식": 7 * 24 * 3600,
    "정기 확인 필요": 12 * 3600,
    "실시간 확인 필요": 0,          # 담지 않습니다
}
DEFAULT_TTL = 6 * 3600

# 사람·회사가 드러나는 질문은 담지 않습니다. (전화·이메일·사업자번호·계좌·긴 숫자)
# \b 는 한글 앞뒤에서 경계가 되지 않습니다("110123456789로"). 숫자 자체로 경계를 봅니다.
PERSONAL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|(?<!\d)01[016-9][- ]?\d{3,4}[- ]?\d{4}(?!\d)"
                      r"|(?<!\d)\d{3}-?\d{2}-?\d{5}(?!\d)|(?<!\d)\d{6,}(?!\d)")

_lock = threading.Lock()
_store: "OrderedDict[str, dict]" = OrderedDict()
_stats = {"hit": 0, "miss": 0, "store": 0, "skip": 0}


def knowledge_version() -> str:
    """캐시 열쇠에 들어가는 지식 버전. FAQ 내용(kb_version) + 승인 상태(approval_version).

    승인을 취소하면 approval_version이 올라가고, 그 승인으로 만들어 둔 답은 저절로 버려집니다.
    """

    from app.services import faq_index

    meta = faq_index.load().get("meta", {})
    return f"{meta.get('kb_version', '0')}.{meta.get('approval_version', '0')}"


def _key(question_norm: str, brief: bool, kb_version: str, conditions: dict | None = None) -> str:
    """답이 달라지는 조건까지 열쇠에 넣습니다.

    "미국에 화장품"과 "베트남에 화장품"은 같은 문장 구조라도 답이 다릅니다.
    조건을 빼면 앞사람 답이 뒷사람에게 나갑니다.
    """

    marks = ""
    if conditions:
        marks = "|".join([",".join(conditions.get("countries") or []),
                          ",".join(conditions.get("items") or []),
                          ",".join(conditions.get("terms") or []),
                          ",".join(conditions.get("payments") or []),
                          conditions.get("hs10") or conditions.get("hs6") or ""])
    return f"{kb_version}|{'brief' if brief else 'full'}|{marks}|{question_norm}"


def cacheable(question: str, history: list | None, memory: str) -> bool:
    """담아도 되는 질문인지. 한 사람의 맥락이 섞였으면 담지 않습니다."""

    if history or (memory or "").strip():
        return False
    return not PERSONAL.search(question or "")


def get(question_norm: str, brief: bool, kb_version: str, conditions: dict | None = None):
    now = time.time()
    key = _key(question_norm, brief, kb_version, conditions)
    with _lock:
        entry = _store.get(key)
        if entry is None:
            _stats["miss"] += 1
            return None
        if entry["expires_at"] <= now:
            _store.pop(key, None)
            _stats["miss"] += 1
            return None
        _store.move_to_end(key)
        _stats["hit"] += 1
        return entry["payload"]


def put(question_norm: str, brief: bool, kb_version: str, payload: dict,
        freshness: str = "", conditions: dict | None = None) -> None:
    ttl = TTL_BY_FRESHNESS.get(freshness, DEFAULT_TTL)
    if ttl <= 0:
        with _lock:
            _stats["skip"] += 1
        return
    key = _key(question_norm, brief, kb_version, conditions)
    with _lock:
        _store[key] = {"expires_at": time.time() + ttl, "payload": payload}
        _store.move_to_end(key)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)
        _stats["store"] += 1


def stats() -> dict:
    with _lock:
        total = _stats["hit"] + _stats["miss"]
        return {**_stats, "entries": len(_store),
                "hit_rate": round(_stats["hit"] / total, 4) if total else 0.0}


def clear() -> None:
    with _lock:
        _store.clear()
        for key in _stats:
            _stats[key] = 0
