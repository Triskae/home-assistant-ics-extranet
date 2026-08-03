import importlib.util
import sys
import unittest
from pathlib import Path

CONST_PATH = (
    Path(__file__).parents[1] / "custom_components" / "ics_extranet" / "const.py"
)
SPEC = importlib.util.spec_from_file_location("ics_extranet_const", CONST_PATH)
assert SPEC is not None and SPEC.loader is not None
const = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = const
SPEC.loader.exec_module(const)


class IcsSettingsTest(unittest.TestCase):
    def test_supported_polling_intervals(self) -> None:
        self.assertEqual(const.normalize_update_interval_days("2"), 2)
        self.assertEqual(const.normalize_update_interval_days(3), 3)

    def test_too_frequent_polling_falls_back_to_two_days(self) -> None:
        self.assertEqual(const.normalize_update_interval_days(1), 2)

    def test_invalid_polling_falls_back_to_two_days(self) -> None:
        self.assertEqual(const.normalize_update_interval_days("invalid"), 2)

    def test_monthly_payment_mode_defaults_to_enabled(self) -> None:
        self.assertTrue(const.normalize_monthly_payments(None))
        self.assertTrue(const.normalize_monthly_payments(True))
        self.assertFalse(const.normalize_monthly_payments(False))


if __name__ == "__main__":
    unittest.main()
