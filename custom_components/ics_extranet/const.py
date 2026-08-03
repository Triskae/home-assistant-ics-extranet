"""Constants for the ICS Extranet integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ics_extranet"
CONF_GROUP: Final = "group"

ICS_ORIGIN: Final = "https://extranet2.ics.fr/"
ICS_VERSION: Final = "V5"
DEFAULT_UPDATE_INTERVAL: Final = timedelta(hours=6)
REQUEST_TIMEOUT_SECONDS: Final = 30

ATTR_ACCOUNT_PERIOD: Final = "account_period"
ATTR_DETECTED_RECEIPTS: Final = "detected_receipts"
ATTR_MONTH: Final = "month"
ATTR_PLANNED_AMOUNT: Final = "planned_amount"
ATTR_STATUS: Final = "status"
ATTR_TRANSACTION_COUNT: Final = "transaction_count"
