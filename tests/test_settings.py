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
CI_WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW_PATH = (
    Path(__file__).parents[1] / ".github" / "workflows" / "release.yml"
)


class IcsSettingsTest(unittest.TestCase):
    def _assert_workflow_quality_gate(self, workflow: str) -> None:
        self.assertIn("uses: actions/checkout@v6", workflow)
        self.assertIn("uses: actions/setup-python@v6", workflow)
        self.assertIn(
            "uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9",
            workflow,
        )
        self.assertIn('PYTHON_VERSION: "3.14.6"', workflow)
        self.assertIn('HOME_ASSISTANT_VERSION: "2026.7.4"', workflow)
        self.assertIn("pytest==9.1.1", workflow)
        self.assertIn("homeassistant==$HOME_ASSISTANT_VERSION", workflow)
        self.assertIn("python -m pytest -q", workflow)
        self.assertIn("ruff==0.16.1", workflow)
        self.assertIn("ruff check custom_components tests ics_poc.py", workflow)
        self.assertIn(
            "ruff format --check custom_components tests ics_poc.py",
            workflow,
        )
        self.assertIn(
            "python3 -m compileall -q custom_components tests ics_poc.py",
            workflow,
        )
        self.assertIn('python3 -m json.tool "$file"', workflow)
        self.assertIn("test -s custom_components/ics_extranet/brand/icon.png", workflow)

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

    def test_ci_workflow_validates_main_and_pull_requests(self) -> None:
        workflow = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("push:\n    branches:\n      - main", workflow)
        self.assertIn("pull_request:\n    branches:\n      - main", workflow)
        self._assert_workflow_quality_gate(workflow)
        self.assertNotIn("gh release create", workflow)

    def test_release_workflow_tests_before_publishing(self) -> None:
        workflow = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn('tags:\n      - "v*.*.*"', workflow)
        self.assertIn("release:\n    needs: tests", workflow)
        self._assert_workflow_quality_gate(workflow)
        self.assertIn('tag_version="${GITHUB_REF_NAME#v}"', workflow)
        self.assertIn('test "$tag_version" = "$manifest_version"', workflow)
        self.assertIn("previous_tag=$(git describe --tags", workflow)
        self.assertIn(
            "/compare/$previous_tag...$GITHUB_REF_NAME",
            workflow,
        )
        self.assertIn('gh release create "$GITHUB_REF_NAME"', workflow)


if __name__ == "__main__":
    unittest.main()
