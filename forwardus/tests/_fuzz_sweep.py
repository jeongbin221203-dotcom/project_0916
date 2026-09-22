"""검증용 일회성 스윕. 모든 입력 자리에 이상한 값을 넣어 터지는 곳을 찾습니다.

이 파일은 회귀 테스트가 아니라 조사 도구입니다. 여기서 찾은 것만 골라
정식 테스트로 옮깁니다.

    python tests/_fuzz_sweep.py
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.validators import ValidationError
from app.services import ServiceError

# 사람이 실제로 넣을 수 있는 이상한 값들.
NASTY = [
    None, "", " ", "\t\n", "0", "-1", "-0.0001", "0.0", "1e309", "-1e309",
    "nan", "inf", "-inf", "NaN", "Infinity",
    "1,000", "1 000", "1_000", "١٢٣", "１２３", "12.3.4", "１,２３４",
    "abc", "12abc", "abc12", "<script>alert(1)</script>", "'; DROP TABLE x;--",
    "../../etc/passwd", "%00", "\x00", "‮", "😀", "가" * 1000, "x" * 10_000,
    True, False, 0, -1, 1.5, float("nan"), float("inf"), -float("inf"),
    10 ** 30, -(10 ** 30), [], {}, [1, 2], {"a": 1}, ["x"], object(),
]

# 숫자 칸에 들어가면 안 되는 값과, 들어가도 되는 값.
NUMBERS = ["1", "10", "100.5", "1,000", " 42 ", 7, 3.5]


class Sweep:
    def __init__(self):
        self.crashes: list[tuple[str, str, str]] = []
        self.checked = 0

    def run(self, label: str, fn, *args, **kwargs):
        """부르고, 우리가 정한 오류가 아닌 예외가 나면 기록합니다."""

        self.checked += 1
        try:
            fn(*args, **kwargs)
        except (ValidationError, ServiceError):
            pass                                  # 우리가 의도한 거절입니다.
        except Exception as error:                # noqa: BLE001 - 조사 도구입니다.
            where = traceback.extract_tb(error.__traceback__)[-1]
            self.crashes.append((label, f"{type(error).__name__}: {error}",
                                 f"{Path(where.filename).name}:{where.lineno}"))

    def report(self) -> int:
        print(f"\n{'=' * 70}\n검사 {self.checked:,}건 · 예상 못 한 예외 {len(self.crashes)}건\n{'=' * 70}")
        seen = {}
        for label, error, where in self.crashes:
            key = (error.split(":")[0], where)
            seen.setdefault(key, []).append((label, error))
        for (kind, where), rows in sorted(seen.items(), key=lambda x: -len(x[1])):
            print(f"\n[{len(rows):>4}건] {kind} @ {where}")
            for label, error in rows[:3]:
                print(f"        {label}")
                print(f"        -> {error[:160]}")
        return len(seen)


def sweep_validators(s: Sweep) -> None:
    from app.validators import cargo_validator as cv
    from app.validators import shipment_validator as sv
    from app.validators import document_validator as dv

    for value in NASTY:
        s.run(f"parse_number({value!r})", cv.parse_number, value, "값")
        s.run(f"parse_integer({value!r})", cv.parse_integer, value, "값")
        s.run(f"parse_date({value!r})", sv.parse_date, value, "날짜")
        s.run(f"require_text({value!r})", sv.require_text, value, "글")
        s.run(f"optional_text({value!r})", sv.optional_text, value)

    base = {"length_cm": 40, "width_cm": 30, "height_cm": 25, "quantity": 10,
            "weight_per_package_kg": 12, "package_type": "carton"}
    for field in list(base) + ["amount", "unit_price", "net_weight_kg", "un_number",
                               "dg_class", "packing_group", "proper_shipping_name",
                               "is_dangerous", "product_description", "hs_code"]:
        for value in NASTY:
            s.run(f"validate_cargo_input[{field}={value!r}]",
                  cv.validate_cargo_input, {**base, field: value}, strict=False)
            s.run(f"validate_cargo_input.strict[{field}={value!r}]",
                  cv.validate_cargo_input, {**base, field: value}, strict=True)

    terms = {"incoterms": "FOB", "currency": "USD", "invoice_value": "1000"}
    for field in list(terms) + ["incoterms_confirmed"]:
        for value in NASTY:
            for mode in ("SEA", "AIR", "", None):
                s.run(f"validate_trade_terms[{field}={value!r},{mode}]",
                      sv.validate_trade_terms, {**terms, field: value}, mode)

    route = {"project_name": "t", "transport_mode": "SEA", "sea_mode": "FCL",
             "origin_code": "KRPUS", "destination_code": "USLAX",
             "requested_departure_date": "2026-10-01"}
    for field in list(route) + ["buyer_required_date"]:
        for value in NASTY:
            s.run(f"validate_route[{field}={value!r}]", sv.validate_route, {**route, field: value})

    parties = {"exporter_name": "A", "exporter_address": "B", "buyer_name": "C",
               "buyer_country": "KR", "buyer_address": "D", "buyer_email": "a@b.c"}
    for field in list(parties) + ["notify_party"]:
        for value in NASTY:
            s.run(f"validate_parties[{field}={value!r}]", sv.validate_parties, {**parties, field: value})

    for value in NASTY:
        s.run(f"clean_document_fields({value!r})", dv.clean_document_fields, value, ["a"])
        s.run(f"clean_document_items({value!r})", dv.clean_document_items, {"item-0-a": value}, [{"a": ""}])


def sweep_processors(s: Sweep) -> None:
    from app.processors import cargo_calculator as cc
    from app.processors import cost_calculator as cost
    from app.processors import korean, export_requirements, dangerous_goods
    from app.processors import transit_calculator as tc

    for value in NASTY:
        for form in ("이", "로", "을", "와", "은"):
            s.run(f"particle({value!r},{form})", korean.particle, str(value)[:50], form)
        s.run(f"export_requirements.check({value!r})", export_requirements.check, value)
        s.run(f"un_search({value!r})", dangerous_goods.search_un_numbers, value)
        s.run(f"dg.guide({value!r})", dangerous_goods.guide, value, "SEA", "US")

    base = {"length_cm": 40, "width_cm": 30, "height_cm": 25, "quantity": 10,
            "weight_per_package_kg": 12, "package_type": "carton"}
    for container in ("20GP", "40GP", "40HC", "", None, "XX", 5):
        s.run(f"metrics[{container!r}]", cc.calculate_cargo_metrics, base, container, strict=False)
    s.run("lines([])", cc.calculate_cargo_lines, [], strict=False)
    s.run("lines([{}])", cc.calculate_cargo_lines, [{}], strict=False)
    s.run("lines(None)", cc.calculate_cargo_lines, None, strict=False)

    for km in (0, -1, 0.0001, 10 ** 9, float("inf"), float("nan")):
        for mode in ("FCL", "LCL", "", None):
            s.run(f"sea_transit({km},{mode})", tc.sea_transit, km, [], mode, direct=True, region="asia")
        s.run(f"air_transit({km})", tc.air_transit, km, transfers=0, minutes=None)

    metrics = cc.calculate_cargo_lines([base], strict=False)
    for incoterms in ("FOB", "EXW", "DDP", "", None, "XXX"):
        for mode, sea in (("SEA", "FCL"), ("SEA", "LCL"), ("AIR", None), ("", None)):
            s.run(f"cost[{incoterms},{mode},{sea}]", cost.calculate_logistics_cost,
                  transport_mode=mode, sea_mode=sea, incoterms=incoterms,
                  freight_usd=1000, freight_source="mock", invoice_value_usd=5000,
                  metrics=metrics, exchange_rate=1350, exchange_source="mock")


def sweep_services(app, s: Sweep) -> None:
    from app.services import planning_service as ps
    from app.services import container_tracking_service as cts
    from app.services import support_chat_service as sc

    with app.app_context():
        for value in NASTY:
            text = value if isinstance(value, str) else str(value)
            s.run(f"detect_kind({text!r})", cts.detect_kind, text)
            s.run(f"deadline_status({text!r})", cts.deadline_status, text, False)
            s.run(f"cargo_metrics[{value!r}]", ps.cargo_metrics, {"cargo": value})
            s.run(f"calculate_cargo[{value!r}]", ps.calculate_cargo, {"cargo": value})
            s.run(f"cargo_items[{value!r}]", ps.cargo_items, {"cargo": value})

        for origin, dest in itertools.product(
                ["KRPUS", "KRKAN", "ICN", "", "XXXXX", None, "krpus", 123],
                ["USLAX", "MXZLO", "MEX", "", "ZZZZZ", None]):
            s.run(f"transit_summary({origin!r},{dest!r})", ps.transit_summary, origin, dest)
            s.run(f"air_route_status({origin!r},{dest!r})", ps.air_route_status, origin, dest)
            s.run(f"schedule_outlook({origin!r},{dest!r})", ps.schedule_outlook, {
                "origin_code": origin, "destination_code": dest,
                "requested_departure_date": "2026-10-01"})

        for value in NASTY[:24]:
            s.run(f"support.ask({value!r})", sc.ask, value if isinstance(value, str) else str(value))


def sweep_routes(app, s: Sweep) -> None:
    client = app.test_client()
    gets = [
        "/", "/planning/new", "/shipments", "/dashboard", "/tracking/container",
        "/planning/api/locations", "/planning/api/countries", "/planning/api/unlocode",
        "/planning/api/hs-codes", "/planning/api/tariff", "/planning/api/destination-tariff",
        "/planning/api/exchange-rate", "/planning/api/un-numbers", "/planning/api/tariff-summary",
        "/planning/api/departure-check", "/planning/api/transit-estimate",
    ]
    params = ["", "?q=", "?q=%00", "?q=" + "x" * 3000, "?hs=&country=",
              "?hs=abc&country=ZZ", "?hs=" + "9" * 40, "?q=<script>",
              "?mode=&role=", "?mode=XX&role=YY", "?country=%ED%95%9C",
              "?origin=&destination=", "?year=abcd", "?q=%ED%8C%8C%EC%9D%BC"]
    for path, query in itertools.product(gets, params):
        s.run(f"GET {path}{query[:40]}", _expect_ok, client, "get", path + query)

    posts = [
        ("/planning/api/cargo", [{}, {"cargo": None}, {"cargo": []}, {"cargo": {"items": []}},
                                 {"cargo": {"items": [{}]}}, {"items": "x"}, []]),
        ("/planning/api/schedules", [{}, {"cargo": None}, {"origin_code": "X"}, []]),
        ("/planning/api/schedule-outlook", [{}, {"origin_code": None}, []]),
        ("/planning/api/dangerous-goods", [{}, {"dg_class": "99"}, []]),
        ("/planning/api/shipments", [{}, {"cargo": {}}, []]),
        ("/api/support-chat", [{}, {"question": ""}, {"question": "x" * 5000},
                               {"history": "x"}, {"history": [{"role": "system"}]}, []]),
    ]
    for path, bodies in posts:
        for body in bodies:
            s.run(f"POST {path} {str(body)[:40]}", _expect_ok, client, "post", path, body)
        s.run(f"POST {path} (깨진 JSON)", _expect_ok, client, "post_raw", path, "{oops")


def _expect_ok(client, how, path, body=None):
    if how == "get":
        response = client.get(path)
    elif how == "post":
        response = client.post(path, json=body)
    else:
        response = client.post(path, data=body, content_type="application/json")
    if response.status_code >= 500:
        raise AssertionError(f"HTTP {response.status_code} {response.get_data(as_text=True)[:200]}")


def block_outbound() -> None:
    """스윕이 실제 기관을 부르지 못하게 막습니다.

    예전에 이 스윕을 돌리다 관세청이 우리 IP를 방화벽에서 차단했습니다.
    호출 제한이 아니라 TCP 연결 자체가 막혀 브라우저로도 못 들어갔습니다.
    스윕은 우리 코드가 버티는지 보는 것이지 남의 서버를 시험하는 것이 아닙니다.

    실제 호출로 확인하려면 FORWARDUS_FUZZ_LIVE=1 을 주고 돌리세요.
    """

    import os

    if os.environ.get("FORWARDUS_FUZZ_LIVE") == "1":
        return

    import httpx

    def offline(*args, **kwargs):
        raise httpx.ConnectError("스윕에서는 바깥으로 나가지 않습니다.")

    httpx.request = offline


def main() -> int:
    block_outbound()
    app = create_app()
    app.config["TESTING"] = True
    s = Sweep()
    sweep_validators(s)
    sweep_processors(s)
    sweep_services(app, s)
    sweep_routes(app, s)
    return s.report()


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
