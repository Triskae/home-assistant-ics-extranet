"""Constants for the ICS Extranet integration."""

from typing import Final

DOMAIN: Final = "ics_extranet"
CONF_GROUP: Final = "group"
CONF_MONTHLY_PAYMENTS: Final = "monthly_payments"
CONF_UPDATE_INTERVAL_DAYS: Final = "update_interval_days"

ICS_ORIGIN: Final = "https://extranet2.ics.fr/"
ICS_VERSION: Final = "V5"
UPDATE_INTERVAL_DAYS: Final = (2, 3)
DEFAULT_UPDATE_INTERVAL_DAYS: Final = 2
DEFAULT_MONTHLY_PAYMENTS: Final = True
REQUEST_TIMEOUT_SECONDS: Final = 30

ATTR_ACCOUNT_PERIOD: Final = "account_period"
ATTR_CHARGE_CALL_DATE: Final = "charge_call_date"
ATTR_DETECTED_RECEIPTS: Final = "detected_receipts"
ATTR_MONTH: Final = "month"
ATTR_PAYMENT_MODE: Final = "payment_mode"
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


def normalize_monthly_payments(value: object) -> bool:
    """Return a valid payment mode, preserving monthly mode for old entries."""
    if isinstance(value, bool):
        return value
    return DEFAULT_MONTHLY_PAYMENTS
