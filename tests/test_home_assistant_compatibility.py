import importlib
import importlib.util
import unittest

HOME_ASSISTANT_AVAILABLE = importlib.util.find_spec("homeassistant") is not None


@unittest.skipUnless(
    HOME_ASSISTANT_AVAILABLE,
    "Home Assistant is installed only in the CI compatibility environment",
)
class HomeAssistantCompatibilityTest(unittest.TestCase):
    def test_all_integration_modules_import_with_target_home_assistant(self) -> None:
        modules = (
            "custom_components.ics_extranet",
            "custom_components.ics_extranet.binary_sensor",
            "custom_components.ics_extranet.client",
            "custom_components.ics_extranet.config_flow",
            "custom_components.ics_extranet.const",
            "custom_components.ics_extranet.coordinator",
            "custom_components.ics_extranet.diagnostics",
            "custom_components.ics_extranet.entity",
            "custom_components.ics_extranet.parser",
            "custom_components.ics_extranet.sensor",
        )

        for module in modules:
            with self.subTest(module=module):
                importlib.import_module(module)


if __name__ == "__main__":
    unittest.main()
