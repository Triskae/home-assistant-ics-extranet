"""Diagnostics support for ICS Extranet."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import IcsDataUpdateCoordinator

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics with credentials and ledger labels excluded."""
    del hass
    coordinator: IcsDataUpdateCoordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "summary": {
            "balance_due": str(data.balance_due),
            "monthly_recommendation": str(data.monthly_recommendation),
            "account_period": data.account_period,
            "last_operation_date": (
                data.last_operation_date.isoformat()
                if data.last_operation_date is not None
                else None
            ),
            "transaction_count": data.transaction_count,
            "fetched_at": data.fetched_at.isoformat(),
            "payments": [
                {
                    "month": payment.month,
                    "amount": str(payment.amount),
                    "status": payment.status.value,
                    "detected_receipts": str(payment.detected_receipts),
                }
                for payment in data.payments
            ],
        },
    }
