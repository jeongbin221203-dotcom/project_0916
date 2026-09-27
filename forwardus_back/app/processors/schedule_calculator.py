"""Schedule date calculations, including the reverse schedule planner."""

from __future__ import annotations

from datetime import date, timedelta

# Default lead times in days. Kept as constants so they can be tuned per route later.
LEAD_TIMES = {
    "SEA": {"final_delivery": 2, "import_customs": 2, "cut_off": 2, "export_customs": 2},
    "AIR": {"final_delivery": 1, "import_customs": 1, "cut_off": 1, "export_customs": 1},
}
DEFAULT_TRANSIT_DAYS = {"SEA": 14, "AIR": 2}


def calculate_eta(etd: date, transit_days: int) -> date:
    return etd + timedelta(days=transit_days)


def calculate_cargo_ready_date(etd: date, transport_mode: str) -> date:
    """Latest cargo ready date for a given ETD (cut-off + export customs before ETD)."""

    lead = LEAD_TIMES["AIR" if transport_mode == "AIR" else "SEA"]
    return etd - timedelta(days=lead["cut_off"] + lead["export_customs"])


def calculate_reverse_schedule(
    buyer_required_date: date,
    transport_mode: str,
    transit_days: int | None = None,
) -> dict:
    """Work backward from the buyer's required date to the cargo ready date.

    Buyer Required Date → Final Delivery → Import Customs → ETA →
    International Transport → ETD → Cut-off → Export Customs → Cargo Ready Date
    """

    mode = "AIR" if transport_mode == "AIR" else "SEA"
    lead = LEAD_TIMES[mode]
    transit = transit_days if transit_days and transit_days > 0 else DEFAULT_TRANSIT_DAYS[mode]

    eta = buyer_required_date - timedelta(days=lead["final_delivery"] + lead["import_customs"])
    etd = eta - timedelta(days=transit)
    cut_off = etd - timedelta(days=lead["cut_off"])
    cargo_ready = cut_off - timedelta(days=lead["export_customs"])

    steps = [
        {"key": "buyer_required_date", "label": "Buyer Required Date", "date": buyer_required_date},
        {"key": "final_delivery", "label": "Final Delivery", "days": lead["final_delivery"]},
        {"key": "import_customs", "label": "Import Customs", "days": lead["import_customs"]},
        {"key": "eta", "label": "ETA", "date": eta},
        {"key": "international_transport", "label": "International Transport", "days": transit},
        {"key": "etd", "label": "ETD", "date": etd},
        {"key": "cut_off", "label": "CY / Cargo Cut-off", "date": cut_off, "days": lead["cut_off"]},
        {"key": "export_customs", "label": "Export Customs", "days": lead["export_customs"]},
        {"key": "cargo_ready_date", "label": "Cargo Ready Date", "date": cargo_ready},
    ]
    return {
        "buyer_required_date": buyer_required_date,
        "recommended_eta": eta,
        "recommended_etd": etd,
        "cut_off_date": cut_off,
        "cargo_ready_date": cargo_ready,
        "transit_days": transit,
        "steps": steps,
        "source": "calculated",
    }


def check_buyer_deadline(eta: date, buyer_required_date: date | None, transport_mode: str) -> dict | None:
    """Return whether the ETA leaves enough time for import customs and delivery."""

    if not buyer_required_date:
        return None
    lead = LEAD_TIMES["AIR" if transport_mode == "AIR" else "SEA"]
    latest_eta = buyer_required_date - timedelta(days=lead["final_delivery"] + lead["import_customs"])
    margin = (latest_eta - eta).days
    return {"latest_eta": latest_eta, "margin_days": margin, "on_time": margin >= 0}
