"""기관에서 받아 낸 답을 남겨 두었다가, 기관이 막혔을 때 그것으로 답합니다.

왜 필요한가
  2026-09-25 현재 관세청 UNI-PASS는 38010·443·80 어느 포트로도 닿지 않습니다.
  선사 목록도, 항공사 목록도, 관세환율도 그동안 통째로 비었습니다. 어제까지
  잘 받아 두었던 값인데도 서버를 다시 켜면 그마저 사라집니다.

  기관이 살아 있을 때 받은 답을 파일로 남겨 두면, 막힌 동안에도 **실제로 받았던
  값**으로 답할 수 있습니다. 예시 데이터를 지어내는 것과는 다릅니다.

무엇을 지키나
  - **받아 낸 것만 남깁니다.** source가 "api"인 답만 저장합니다. 예시(mock)나
    내부 표(internal)를 저장하면 그것이 다시 "저장된 실제 값"인 척하게 됩니다.
  - **언제 받은 값인지 함께 돌려줍니다.** 화면은 그것을 반드시 적어야 합니다.
  - **너무 오래된 것은 안 씁니다.** 자료마다 수명이 다릅니다(아래 MAX_DAYS).
  - 파일이 깨졌거나 쓸 수 없어도 조용히 넘어갑니다. 저장이 안 된다고 조회가
    멈추면 안 됩니다.

무엇을 남기지 않나
  **화물 추적은 저장하지 않습니다.** 어제 "부산 출항"이었다고 오늘도 그렇게
  답하면 거짓말이 됩니다. 움직이는 값은 못 받으면 못 받았다고 해야 합니다.
  운임·관세율처럼 돈이 걸린 값도 마찬가지입니다.
"""

from __future__ import annotations

from app.collectors import file_cache
from app.collectors.base_client import ok

# 자료마다 믿고 쓸 수 있는 날수. 바뀌는 속도로 정합니다.
#
#   선사·항공사·포워더 등록부  거의 안 바뀝니다. 새 선사가 생겨도 기존 것은 그대로.
#   항만·무역 통계           월 단위로 나옵니다. 한 달 지난 값도 "지난달 실적"으로 뜻이 있습니다.
#   세관장확인대상 법령       법이 바뀔 때만 바뀝니다.
MAX_DAYS = {
    "registry": 180,
    "stats": 45,
    "law": 90,
}
DEFAULT_MAX_DAYS = 30


def remember(name: str, result: dict) -> dict:
    """받아 낸 답을 남깁니다. 그대로 돌려주므로 `return remember(...)`로 씁니다.

    기관에서 실제로 온 답(source == "api")이고 내용이 있을 때만 남깁니다.
    """

    if not (result.get("success") and result.get("source") == "api"):
        return result
    data = result.get("data")
    if data in (None, [], {}, ""):
        return result
    file_cache.write(_key(name), {"data": data,
                                  "extra": {key: value for key, value in result.items()
                                            if key not in ("success", "data", "source",
                                                           "error_code", "message")}})
    return result


def recall(name: str, kind: str = "") -> dict | None:
    """남겨 둔 답. 없거나 너무 오래됐으면 None.

    돌려주는 답의 source는 "stored"입니다. 부르는 쪽은 이것을 "api"와 같이
    다루면 안 됩니다. 화면에 며칠 전 값인지 적어야 합니다.
    """

    found = file_cache.read(_key(name))
    if not found:
        return None
    saved, age_days = found
    data = (saved or {}).get("data")
    if data in (None, [], {}, ""):
        return None
    if age_days > MAX_DAYS.get(kind, DEFAULT_MAX_DAYS):
        return None
    return {**ok(data, "stored"), **(saved.get("extra") or {}),
            "stored_days": round(age_days),
            "stored_note": f"{round(age_days)}일 전에 받아 둔 값입니다. "
                           "기관이 답하지 않아 그때 받은 것을 보여 드립니다."}


def _key(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    return f"snap_{safe}"
