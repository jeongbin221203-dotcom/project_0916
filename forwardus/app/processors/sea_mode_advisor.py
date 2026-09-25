"""CBM 기준으로 LCL과 FCL 중 무엇이 맞는지 정합니다.

왜 기준이 필요한가
  같은 화물을 LCL(혼재)로 보내면 운임톤(R/T)당으로 내고, FCL(단독)로 보내면 컨테이너
  한 대 값을 냅니다. 짐이 적으면 LCL이 싸고, 어느 선을 넘으면 컨테이너를 통째로 쓰는
  편이 쌉니다. 그 선을 사람이 감으로 잡으면 매번 달라집니다.

기준은 세 가지를 같이 봅니다.

  1) 운임톤(R/T) = max(CBM, 총중량 t)
     LCL은 부피와 무게 중 **큰 쪽**으로 값을 매깁니다. 20 CBM이어도 25톤이면 25 R/T입니다.
     그래서 CBM만 보면 무거운 화물에서 틀립니다.
  2) 20피트 컨테이너(20GP)로 옮겨 탈 지점
     20GP는 28 CBM·21톤이 한계이고, 실제로는 빈틈이 생겨 24~25 CBM쯤 실립니다.
     업계에서는 대체로 **15 R/T 안팎**을 LCL과 FCL이 뒤집히는 구간으로 봅니다.
  3) 컨테이너를 얼마나 채우는가
     28 CBM에 가까우면 LCL로 보낼 이유가 없습니다. 반대로 한 대를 절반도 못 채우면
     FCL은 빈자리 값을 내는 셈입니다.

여기서 내는 것은 **권고**입니다. 실제 운임은 구간·시기·선사에 따라 뒤집힐 수 있어,
경계 구간에서는 "둘 다 받아 비교하세요"라고 말합니다. 값은 화면에서 실제 견적으로
다시 비교합니다. (cost_calculator)
"""

from __future__ import annotations

from app.processors.cargo_calculator import (CONTAINER_SPECS, calculate_container_quantity,
                                             calculate_revenue_ton)

# FCL로 갈 때 먼저 보는 컨테이너 순서. 작은 것부터 맞는 것을 고릅니다.
# LCL과 견주는 상대는 가장 작은 컨테이너(20GP)입니다. 그보다 큰 것을 기준으로 잡으면
# 빈자리가 많아 보여 FCL이 늘 손해처럼 보입니다.
CONTAINER_ORDER = ("20GP", "40GP", "40HC")

# 이 아래는 LCL이 거의 늘 쌉니다. (컨테이너 한 대 값을 낼 만큼 짐이 없습니다)
LCL_CLEAR_RT = 12.0
# 이 위는 FCL이 거의 늘 쌉니다. 사이(12~15)는 견적을 받아 비교하는 구간입니다.
FCL_CLEAR_RT = 15.0
# 20GP에 실제로 실리는 양. 규격은 28 CBM이지만 빈틈이 생겨 이 정도가 한계입니다.
PRACTICAL_FILL = 0.88
# 1 CBM에 이보다 무거우면 LCL 운임이 무게로 매겨져 빨리 불리해집니다.
DENSE_T_PER_CBM = 1.0
# 컨테이너를 이만큼도 못 채우면 FCL은 빈자리 값을 내는 셈입니다.
LOW_FILL_RATE = 0.5


def _fill_rate(total_cbm: float, containers: int, container_type: str) -> float:
    """고른 컨테이너를 얼마나 채우는가. (1.0이면 규격 한계까지)"""

    capacity = CONTAINER_SPECS[container_type]["max_cbm"] * max(1, containers)
    return round(total_cbm / capacity, 3) if capacity else 0.0


def best_container(total_cbm: float, total_weight_t: float) -> str:
    """이 짐을 담을 가장 작은 컨테이너. 한 대에 안 들어가면 가장 큰 것으로 여러 대 씁니다."""

    for name in CONTAINER_ORDER:
        spec = CONTAINER_SPECS[name]
        if total_cbm <= spec["max_cbm"] * PRACTICAL_FILL and total_weight_t * 1000 <= spec["max_weight_kg"]:
            return name
    return CONTAINER_ORDER[-1]


def recommend(total_cbm: float, total_weight_kg: float = 0.0,
              container_type: str = "") -> dict:
    """LCL·FCL 권고. 숫자가 없으면 판단하지 않고 그렇다고 말합니다.

    돌려주는 것
      mode        "LCL" | "FCL" | ""   (""는 판단 보류)
      confidence  "clear"(분명함) | "close"(경계 구간) | "none"
      revenue_ton 운임톤 = max(CBM, 총중량 t)
      containers  FCL로 갈 때 필요한 대수 · fill_rate 채움률
      reason      한 줄 이유 (화면에 그대로 씁니다)
      notes       함께 볼 것 (무거운 화물·빈자리 등)
    """

    try:
        cbm = max(0.0, float(total_cbm or 0))
        weight_t = max(0.0, float(total_weight_kg or 0)) / 1000
    except (TypeError, ValueError):
        cbm = weight_t = 0.0

    # 컨테이너를 정하지 않았으면 짐에 맞는 가장 작은 것을 씁니다.
    if container_type not in CONTAINER_SPECS:
        container_type = best_container(cbm, weight_t)
    spec = CONTAINER_SPECS[container_type]
    result = {"mode": "", "confidence": "none", "container_type": container_type,
              "total_cbm": round(cbm, 3), "total_weight_t": round(weight_t, 3),
              "revenue_ton": 0.0, "containers": 0, "fill_rate": 0.0,
              "break_even_rt": FCL_CLEAR_RT, "reason": "", "notes": []}
    if cbm <= 0:
        result["reason"] = "화물 치수와 개수를 넣으면 LCL·FCL 중 어느 쪽이 맞는지 알려 드립니다."
        return result

    revenue_ton = calculate_revenue_ton(cbm, weight_t * 1000)
    containers = calculate_container_quantity(cbm, weight_t * 1000, container_type)
    fill = _fill_rate(cbm, containers, container_type)
    result.update({"revenue_ton": round(revenue_ton, 3), "containers": containers,
                   "fill_rate": fill})

    dense = weight_t > 0 and cbm > 0 and (weight_t / cbm) > DENSE_T_PER_CBM
    practical_cbm = spec["max_cbm"] * PRACTICAL_FILL

    if revenue_ton >= FCL_CLEAR_RT or cbm >= practical_cbm or containers > 1:
        result["mode"] = "FCL"
        result["confidence"] = "clear"
        if containers > 1:
            result["reason"] = (f"{cbm:g} CBM이라 {container_type} {containers}대가 필요합니다. "
                                "이 정도면 컨테이너를 통째로 쓰는 편이 쌉니다.")
        else:
            result["reason"] = (f"운임톤 {revenue_ton:g} R/T로 기준({FCL_CLEAR_RT:g} R/T)을 넘었습니다. "
                                f"{container_type} 한 대에 담는 편이 대체로 쌉니다.")
    elif revenue_ton <= LCL_CLEAR_RT and not dense:
        result["mode"] = "LCL"
        result["confidence"] = "clear"
        result["reason"] = (f"운임톤 {revenue_ton:g} R/T로 컨테이너 한 대를 채우지 못합니다. "
                            "혼재(LCL)로 보내면 쓴 만큼만 냅니다.")
    elif dense:
        # 부피는 적어도 무게로 값이 매겨져 LCL이 빨리 불리해집니다.
        result["mode"] = "FCL"
        result["confidence"] = "close"
        result["reason"] = (f"부피는 {cbm:g} CBM이지만 무게가 {weight_t:g}톤이라 운임톤이 "
                            f"{revenue_ton:g} R/T입니다. 무거운 화물은 LCL 운임이 무게로 매겨져 "
                            f"{container_type} 한 대 값과 견줘 봐야 합니다.")
    else:
        result["mode"] = "LCL"
        result["confidence"] = "close"
        result["reason"] = (f"운임톤 {revenue_ton:g} R/T는 LCL과 FCL이 뒤집히는 구간"
                            f"({LCL_CLEAR_RT:g}~{FCL_CLEAR_RT:g} R/T)입니다. "
                            "두 가지로 견적을 받아 비교하세요.")

    if dense:
        result["notes"].append(
            f"1 CBM당 {weight_t / cbm:.1f}톤으로 무거운 화물입니다. LCL은 부피와 무게 중 "
            "큰 쪽으로 값을 매겨, 부피가 작아도 운임이 무게로 올라갑니다.")
    if result["mode"] == "FCL" and fill and fill < LOW_FILL_RATE:
        result["notes"].append(
            f"{container_type} 공간의 {fill * 100:.0f}%만 채웁니다. 빈자리 값을 내는 셈이라 "
            "LCL 견적도 함께 받아 보세요.")
    if result["mode"] == "LCL":
        result["notes"].append("LCL은 출발지에서 혼재하고 도착지에서 적출하느라 "
                               "FCL보다 일주일쯤 더 걸립니다.")
    return result


def summary_line(result: dict) -> str:
    """한 줄로. (대화·서류 화면에서 그대로 보여 줍니다)"""

    if not result or not result.get("mode"):
        return ""
    head = f"{result['mode']} 권장" if result["confidence"] == "clear" else f"{result['mode']} 쪽 (경계)"
    return f"{head} · {result['reason']}"
