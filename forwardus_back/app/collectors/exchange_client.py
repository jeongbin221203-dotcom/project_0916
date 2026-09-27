"""Exchange rate provider (mock / configured values)."""

from __future__ import annotations

from app.collectors.base_client import get_config, load_mock, ok


def fetch_krw_rates() -> dict:
    """Return KRW per 1 unit of each supported currency."""

    # TODO: call the live provider via base_client.request_json when EXCHANGE_API_KEY is configured.

    rates = dict(load_mock("exchange_rates")["krw_per_unit"])
    rates["USD"] = float(get_config("EXCHANGE_RATE_USD_KRW", rates["USD"]))
    rates["KRW"] = 1.0
    return ok(rates, "mock")


def convert(amount: float, from_currency: str, to_currency: str, rates: dict) -> float:
    return amount * rates[from_currency] / rates[to_currency]
