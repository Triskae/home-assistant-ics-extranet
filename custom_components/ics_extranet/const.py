"""Constants for the ICS Extranet integration."""

from typing import Final

DOMAIN: Final = "ics_extranet"
CONF_GROUP: Final = "group"
CONF_UPDATE_INTERVAL_DAYS: Final = "update_interval_days"

ICS_ORIGIN: Final = "https://extranet2.ics.fr/"
ICS_VERSION: Final = "V5"
UPDATE_INTERVAL_DAYS: Final = (2, 3)
DEFAULT_UPDATE_INTERVAL_DAYS: Final = 2
REQUEST_TIMEOUT_SECONDS: Final = 30

ATTR_ACCOUNT_PERIOD: Final = "account_period"
ATTR_DETECTED_RECEIPTS: Final = "detected_receipts"
ATTR_MONTH: Final = "month"
ATTR_PLANNED_AMOUNT: Final = "planned_amount"
ATTR_STATUS: Final = "status"
ATTR_TRANSACTION_COUNT: Final = "transaction_count"


def normalize_update_interval_days(value: object) -> int:
    """Return a supported polling interval, defaulting safely to two days."""
    if not isinstance(value, int | str):
        return DEFAULT_UPDATE_INTERVAL_DAYS
    try:
        days = int(value)
    except ValueError:
        return DEFAULT_UPDATE_INTERVAL_DAYS
    if days not in UPDATE_INTERVAL_DAYS:
        return DEFAULT_UPDATE_INTERVAL_DAYS
    return days
