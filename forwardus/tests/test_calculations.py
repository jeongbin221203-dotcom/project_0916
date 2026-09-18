"""Calculation and validation tests."""

from __future__ import annotations

import unittest

from src.processors.cargo_calc import CargoValidationError, calculate_cargo_metrics
from src.processors.quote_engine import QuoteValidationError, build_quote, calculate_insurance_premium


class CargoCalculationTest(unittest.TestCase):
    def setUp(self):
        self.cargo = {
            "length_cm": 100,
            "width_cm": 100,
            "height_cm": 100,
            "box_count": 2,
            "weight_per_box_kg": 600,
            "declared_value_usd": 10_000,
        }

    def test_cbm_weight_and_revenue_ton(self):
        result = calculate_cargo_metrics(self.cargo)
        self.assertEqual(result["total_cbm"], 2.0)
        self.assertEqual(result["total_weight_kg"], 1200.0)
        self.assertEqual(result["revenue_ton"], 2.0)

    def test_air_chargeable_weight(self):
        result = calculate_cargo_metrics(self.cargo)
        self.assertEqual(result["chargeable_weight_kg"], 1200.0)

    def test_minimum_revenue_ton(self):
        small = dict(self.cargo, length_cm=10, width_cm=10, height_cm=10, box_count=1, weight_per_box_kg=1)
        self.assertEqual(calculate_cargo_metrics(small)["revenue_ton"], 1.0)

    def test_invalid_values(self):
        with self.assertRaises(CargoValidationError):
            calculate_cargo_metrics(dict(self.cargo, box_count=0))
        with self.assertRaises(CargoValidationError):
            calculate_cargo_metrics(dict(self.cargo, length_cm=-1))

    def test_insurance_minimum(self):
        self.assertGreaterEqual(calculate_insurance_premium(100, 10, 1380), 10_000)

    def test_air_incoterm_validation(self):
        payload = {
            "transport_mode": "air",
            "trade_direction": "export",
            "incoterm": "FOB",
            "cargo": self.cargo,
            "budget_krw": 5_000_000,
        }
        with self.assertRaises(QuoteValidationError):
            build_quote(payload)


if __name__ == "__main__":
    unittest.main()

