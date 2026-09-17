"""운임 데이터 수집(모사)·전처리·시계열 생성 모듈.

- collect_freight_rates: 출발항 × 목적국 × 운송모드 × 규격 반복 수집 (API 연동 전 샘플 모사)
- preprocess_rate_table: 결측 필드 대체 및 대체 이력 기록
- build_rate_series, calculate_trend_stats: 월별 운임 추이와 분기·전년 대비 통계 산출
"""

from functools import lru_cache
import math

import config
from format_values import format_number, round_half_up

UINT32_MASK = 0xFFFFFFFF


def to_int32(value: int) -> int:
    """정수를 부호 있는 32비트 범위로 변환."""
    value &= UINT32_MASK
    return value - 0x1_0000_0000 if value & 0x8000_0000 else value


def multiply_int32(left: int, right: int) -> int:
    """32비트 정수 곱셈 (JavaScript Math.imul과 동일 결과)."""
    return to_int32((left & UINT32_MASK) * (right & UINT32_MASK))


def hash_text(text: str) -> int:
    """FNV-1a 32비트 해시 산출 (항로별 시계열 시드 생성용)."""
    hash_value = 2166136261
    for character in text:
        hash_value = to_int32(hash_value ^ ord(character))
        hash_value = multiply_int32(hash_value, 16777619)
    return hash_value & UINT32_MASK


def create_seeded_random(seed: int):
    """Mulberry32 기반 결정적 난수 생성 함수 반환 (HTML 초안과 동일 수열)."""
    state = seed or 1

    def generate_random() -> float:
        nonlocal state
        state = to_int32(state + 0x6D2B79F5)
        mixed = multiply_int32(state ^ ((state & UINT32_MASK) >> 15), 1 | state)
        mixed = to_int32(to_int32(mixed + multiply_int32(mixed ^ ((mixed & UINT32_MASK) >> 7), 61 | mixed)) ^ mixed)
        return ((mixed ^ ((mixed & UINT32_MASK) >> 14)) & UINT32_MASK) / 4294967296

    return generate_random


def calculate_mean(values: list[float]) -> float:
    """산술평균 산출 (빈 목록은 0)."""
    return sum(values) / len(values) if values else 0.0


def calculate_median(values: list[float]) -> float | None:
    """중앙값 산출 (빈 목록은 None)."""
    if not values:
        return None
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2


def is_valid_number(value) -> bool:
    """유효한 유한 숫자 여부 판정."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def collect_freight_rates() -> list[dict]:
    """출발항 × 목적국 × 운송모드 × 규격 반복 수집 결과 반환 (샘플 모사).

    실제 구현 시 반복문 내부의 기준 운임 조회를 API 호출로 대체하며,
    수집에 실패한 필드는 None으로 적재함.
    """
    raw_records = []
    for origin in config.SEA_ORIGIN_CODES:
        for dest in config.DEST_ORDER:
            base_table = config.BASE_SEA_RATES[dest]
            rate_factor = config.ORIGIN_RATE_FACTORS[origin][dest]
            transit_offset = config.ORIGIN_TRANSIT_OFFSETS[origin][dest]
            for unit in config.CONTAINER_TYPES:
                base_rate, surcharge_a, surcharge_b = base_table["fcl"][unit]
                surcharge_parts = [
                    f"{name} {format_number(round_half_up(amount * rate_factor))}"
                    for name, amount in zip(base_table["surcharge_names"], (surcharge_a, surcharge_b))
                    if amount > 0
                ]
                raw_records.append({
                    "origin": origin, "dest": dest, "mode": "FCL", "unit": unit,
                    "base_usd": round_half_up(base_rate * rate_factor),
                    "surcharge_usd": round_half_up((surcharge_a + surcharge_b) * rate_factor),
                    "surcharge_label": " + ".join(surcharge_parts),
                    "transit_days": base_table["transit_days"]["FCL"] + transit_offset,
                    "min_charge_usd": None,
                })
            lcl_base, lcl_surcharge = base_table["lcl"]
            reference_rates = base_table["fcl"]["40GP"]
            raw_records.append({
                "origin": origin, "dest": dest, "mode": "LCL", "unit": "RT",
                "base_usd": round_half_up(lcl_base * rate_factor, 1),
                "surcharge_usd": round_half_up(lcl_surcharge * rate_factor, 1),
                "surcharge_label": "·".join(name for index, name in enumerate(base_table["surcharge_names"]) if reference_rates[index + 1] > 0),
                "transit_days": base_table["transit_days"]["LCL"] + transit_offset,
                "min_charge_usd": None,
            })
    for dest in config.DEST_ORDER:
        air_table = config.BASE_AIR_RATES[dest]
        raw_records.append({
            "origin": "ICN", "dest": dest, "mode": "AIR", "unit": "KG",
            "base_usd": air_table["rate_per_kg"],
            "surcharge_usd": round_half_up(air_table["fsc_per_kg"] + air_table["ssc_per_kg"], 2),
            "surcharge_label": f"FSC {air_table['fsc_per_kg']} + SSC {air_table['ssc_per_kg']}",
            "transit_days": air_table["transit_days"],
            "min_charge_usd": air_table["min_charge"],
        })
    for gap in config.COLLECTION_GAPS:
        for record in raw_records:
            if all(record[key] == gap[key] for key in ("origin", "dest", "mode", "unit")):
                record[gap["field"]] = None
    return raw_records


def impute_missing_value(record: dict, field: str, records: list[dict]) -> tuple[float, str]:
    """결측 필드 대체값과 대체 방식 반환.

    운송기간은 동일 항로·운송모드의 다른 규격 중앙값, 운임 계열은
    동일 목적국·운송모드·규격의 다른 출발항 값을 기본운임 비율로 보정한 중앙값 사용.
    """
    if field == "transit_days":
        same_route_values = [
            peer[field] for peer in records
            if peer is not record and peer["origin"] == record["origin"] and peer["dest"] == record["dest"]
            and peer["mode"] == record["mode"] and is_valid_number(peer[field])
        ]
        if same_route_values:
            return round_half_up(calculate_median(same_route_values)), "동일 항로·운송모드 중앙값"
    scaled_values = [
        peer[field] * (record["base_usd"] / peer["base_usd"]) for peer in records
        if peer is not record and peer["dest"] == record["dest"] and peer["mode"] == record["mode"]
        and peer["unit"] == record["unit"] and is_valid_number(peer[field]) and is_valid_number(peer["base_usd"])
    ]
    if scaled_values:
        return round_half_up(calculate_median(scaled_values), 1), "동일 목적국·운송모드 중앙값 (기본운임 비례 보정)"
    return 0.0, "대체 불가 · 0 처리"


def preprocess_rate_table(raw_records: list[dict]) -> list[dict]:
    """결측 필드 대체 후 대체 이력(imputed_fields)이 포함된 운임표 반환."""
    cleaned_records = [{**record, "imputed_fields": []} for record in raw_records]
    for record in cleaned_records:
        for field in ("base_usd", "surcharge_usd", "transit_days"):
            if is_valid_number(record[field]):
                continue
            value, method = impute_missing_value(record, field, cleaned_records)
            record[field] = value
            record["imputed_fields"].append({"field": field, "method": method})
    return cleaned_records


@lru_cache(maxsize=1)
def load_rate_table() -> tuple[dict, ...]:
    """수집·전처리가 끝난 운임표 반환 (프로세스 단위 캐시)."""
    return tuple(preprocess_rate_table(collect_freight_rates()))


def count_imputed_records() -> int:
    """결측 대체가 적용된 운임 레코드 수 반환."""
    return sum(1 for record in load_rate_table() if record["imputed_fields"])


def find_rate_record(origin: str, dest: str, mode: str, unit: str) -> dict:
    """출발지·목적국·운송모드·단위에 해당하는 운임 레코드 반환."""
    for record in load_rate_table():
        if record["origin"] == origin and record["dest"] == dest and record["mode"] == mode and record["unit"] == unit:
            return record
    raise KeyError(f"운임 레코드 없음: {origin}-{dest}-{mode}-{unit}")


def shift_month(period: tuple[int, int], offset: int) -> tuple[int, int]:
    """(연, 월) 기준 월 이동 결과 반환."""
    year, month = period
    total_months = year * 12 + (month - 1) + offset
    return total_months // 12, total_months % 12 + 1


def get_quarter(month: int) -> int:
    """월에 해당하는 분기 번호 반환."""
    return (month + 2) // 3


def build_rate_series(origin: str, dest: str, mode: str, unit: str) -> list[dict]:
    """최근 24개월 운임(기본운임 + 할증료) 시계열 생성 (계절성·추세·잡음 모사)."""
    record = find_rate_record(origin, dest, mode, unit)
    current_value = record["base_usd"] + record["surcharge_usd"]
    profile_key = "AIR" if mode == "AIR" else config.DESTINATIONS[dest]["season_profile"]
    season_factors = config.SEASON_PROFILES[profile_key]
    amplitude = 0.6 if mode == "LCL" else 1.0
    annual_trend = config.ANNUAL_TRENDS[profile_key]
    generate_random = create_seeded_random(hash_text(f"{origin}|{dest}|{mode}|{unit}"))
    anchor_factor = season_factors[config.SERIES_END[1] - 1]
    points = []
    for index in range(config.SERIES_LENGTH):
        months_back = config.SERIES_LENGTH - 1 - index
        year, month = shift_month(config.SERIES_END, -months_back)
        season_factor = 1 + (season_factors[month - 1] / anchor_factor - 1) * amplitude
        trend_factor = (1 + annual_trend) ** (-months_back / 12)
        noise_factor = 1 + (generate_random() - 0.5) * 0.03
        value = current_value if months_back == 0 else current_value * season_factor * trend_factor * noise_factor
        points.append({"year": year, "month": month, "value": round_half_up(value, 0 if mode == "FCL" else 2)})
    return points


def calculate_trend_stats(points: list[dict]) -> dict:
    """현재값·분기 평균·전분기 대비·전년 동월 대비·12개월 범위 산출."""
    last_point = points[-1]
    current_quarter = get_quarter(last_point["month"])
    current_start_index = next(
        index for index, point in enumerate(points)
        if point["year"] == last_point["year"] and get_quarter(point["month"]) == current_quarter
    )
    current_quarter_values = [point["value"] for point in points[current_start_index:]]
    previous_quarter_values = [point["value"] for point in points[max(0, current_start_index - 3):current_start_index]]
    current_quarter_avg = calculate_mean(current_quarter_values)
    previous_quarter_avg = calculate_mean(previous_quarter_values)
    recent_values = [point["value"] for point in points[-12:]]
    previous_quarter_number = 4 if current_quarter == 1 else current_quarter - 1
    return {
        "current_value": last_point["value"],
        "current_quarter_avg": current_quarter_avg,
        "previous_quarter_avg": previous_quarter_avg,
        "qoq_change": current_quarter_avg / previous_quarter_avg - 1 if previous_quarter_avg else 0.0,
        "yoy_change": last_point["value"] / points[-13]["value"] - 1 if len(points) > 12 else 0.0,
        "min_12m": min(recent_values),
        "max_12m": max(recent_values),
        "current_quarter_label": f"{current_quarter}분기",
        "previous_quarter_label": f"{previous_quarter_number}분기",
        "current_start_index": current_start_index,
    }
