import importlib.util
import json
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

INTEGRATION_PATH = Path(__file__).parents[1] / "custom_components" / "ics_extranet"


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

    def test_reconfigure_credentials_are_translated(self) -> None:
        expected_labels = {
            "strings.json": ("Username", "New password (optional)"),
            "translations/en.json": ("Username", "New password (optional)"),
            "translations/fr.json": (
                "Identifiant ou adresse email",
                "Nouveau mot de passe (facultatif)",
            ),
        }
        for relative_path, labels in expected_labels.items():
            with self.subTest(relative_path=relative_path):
                content = json.loads(
                    (INTEGRATION_PATH / relative_path).read_text(encoding="utf-8")
                )
                step = content["config"]["step"]["reconfigure"]
                self.assertEqual(step["data"]["username"], labels[0])
                self.assertEqual(step["data"]["password"], labels[1])
                self.assertIn("password", step["data_description"])

    def test_manifest_and_client_versions_are_aligned(self) -> None:
        manifest = json.loads(
            (INTEGRATION_PATH / "manifest.json").read_text(encoding="utf-8")
        )
        client_source = (INTEGRATION_PATH / "client.py").read_text(encoding="utf-8")
        self.assertIn(
            f'USER_AGENT: Final = "Home-Assistant-ICS-Extranet/{manifest["version"]}"',
            client_source,
        )


if __name__ == "__main__":
    unittest.main()
