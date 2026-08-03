"""Config flow for ICS Extranet."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import dt as dt_util

from .client import IcsAuthenticationError, IcsClient, IcsConnectionError
from .const import (
    CONF_GROUP,
    CONF_MONTHLY_PAYMENTS,
    CONF_UPDATE_INTERVAL_DAYS,
    DEFAULT_MONTHLY_PAYMENTS,
    DEFAULT_UPDATE_INTERVAL_DAYS,
    DOMAIN,
    UPDATE_INTERVAL_DAYS,
    normalize_monthly_payments,
    normalize_update_interval_days,
)
from .parser import IcsParseError


def _connection_schema(
    defaults: dict[str, Any] | None = None,
    *,
    include_update_interval: bool,
) -> vol.Schema:
    values = defaults or {}
    fields: dict[vol.Marker, object] = {
        vol.Required(CONF_USERNAME, default=values.get(CONF_USERNAME, "")): str,
        vol.Required(CONF_PASSWORD): _password_selector(),
        vol.Required(CONF_GROUP, default=values.get(CONF_GROUP, "")): str,
    }
    if include_update_interval:
        fields[
            vol.Required(
                CONF_UPDATE_INTERVAL_DAYS,
                default=str(
                    normalize_update_interval_days(
                        values.get(
                            CONF_UPDATE_INTERVAL_DAYS,
                            DEFAULT_UPDATE_INTERVAL_DAYS,
                        )
                    )
                ),
            )
        ] = _update_interval_selector()
        fields[
            vol.Required(
                CONF_MONTHLY_PAYMENTS,
                default=normalize_monthly_payments(
                    values.get(CONF_MONTHLY_PAYMENTS, DEFAULT_MONTHLY_PAYMENTS)
                ),
            )
        ] = selector.BooleanSelector()
    return vol.Schema(fields)


def _reconfigure_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_USERNAME,
                default=defaults[CONF_USERNAME],
            ): str,
            vol.Optional(CONF_PASSWORD): _password_selector(),
            vol.Required(CONF_GROUP, default=defaults[CONF_GROUP]): str,
            vol.Required(
                CONF_UPDATE_INTERVAL_DAYS,
                default=str(
                    normalize_update_interval_days(
                        defaults.get(
                            CONF_UPDATE_INTERVAL_DAYS,
                            DEFAULT_UPDATE_INTERVAL_DAYS,
                        )
                    )
                ),
            ): _update_interval_selector(),
            vol.Required(
                CONF_MONTHLY_PAYMENTS,
                default=normalize_monthly_payments(
                    defaults.get(CONF_MONTHLY_PAYMENTS, DEFAULT_MONTHLY_PAYMENTS)
                ),
            ): selector.BooleanSelector(),
        }
    )


def _password_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def _update_interval_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[str(days) for days in UPDATE_INTERVAL_DAYS],
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key=CONF_UPDATE_INTERVAL_DAYS,
        )
    )


def _normalize_settings(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_GROUP: str(user_input[CONF_GROUP]).strip().lower(),
        CONF_UPDATE_INTERVAL_DAYS: normalize_update_interval_days(
            user_input[CONF_UPDATE_INTERVAL_DAYS]
        ),
        CONF_MONTHLY_PAYMENTS: normalize_monthly_payments(
            user_input[CONF_MONTHLY_PAYMENTS]
        ),
    }


def _reconfigure_updates(user_input: dict[str, Any]) -> dict[str, Any]:
    updates = {
        CONF_USERNAME: str(user_input[CONF_USERNAME]).strip(),
        **_normalize_settings(user_input),
    }
    if new_password := user_input.get(CONF_PASSWORD):
        updates[CONF_PASSWORD] = new_password
    return updates


def _is_duplicate_account(
    flow: config_entries.ConfigFlow,
    *,
    username: str,
    group: str,
    current_entry_id: str | None = None,
) -> bool:
    normalized_username = username.strip().casefold()
    normalized_group = group.strip().casefold()
    return any(
        entry.entry_id != current_entry_id
        and str(entry.data.get(CONF_USERNAME, "")).strip().casefold()
        == normalized_username
        and str(entry.data.get(CONF_GROUP, "")).strip().casefold() == normalized_group
        for entry in flow.hass.config_entries.async_entries(DOMAIN)
    )


def _account_unique_id(username: str, group: str) -> str:
    normalized = f"{group.strip().casefold()}:{username.strip().casefold()}"
    return sha256(normalized.encode()).hexdigest()[:24]


async def _validate_input(hass, data: dict[str, Any]) -> None:
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    try:
        client = IcsClient(
            session=session,
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            group=data[CONF_GROUP],
            monthly_payments=normalize_monthly_payments(
                data.get(CONF_MONTHLY_PAYMENTS, DEFAULT_MONTHLY_PAYMENTS)
            ),
        )
        await client.async_fetch_summary(dt_util.now().date())
    finally:
        await session.close()


class IcsExtranetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an ICS Extranet config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data: dict[str, Any] = {
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                **_normalize_settings(user_input),
            }
            try:
                await _validate_input(self.hass, data)
            except (IcsConnectionError, IcsParseError, ValueError):
                errors["base"] = "cannot_connect"
            except IcsAuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    _account_unique_id(data[CONF_USERNAME], data[CONF_GROUP])
                )
                self._abort_if_unique_id_configured()
                if _is_duplicate_account(
                    self,
                    username=data[CONF_USERNAME],
                    group=data[CONF_GROUP],
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_create_entry(
                    title=f"ICS Extranet ({data[CONF_GROUP]})",
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(
                user_input,
                include_update_interval=True,
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow credentials and account settings to be changed."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            updates = _reconfigure_updates(user_input)
            data = {**entry.data, **updates}
            try:
                await _validate_input(self.hass, data)
            except (IcsConnectionError, IcsParseError, ValueError):
                errors["base"] = "cannot_connect"
            except IcsAuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "unknown"
            else:
                if _is_duplicate_account(
                    self,
                    username=data[CONF_USERNAME],
                    group=data[CONF_GROUP],
                    current_entry_id=entry.entry_id,
                ):
                    errors["base"] = "already_configured"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        title=f"ICS Extranet ({data[CONF_GROUP]})",
                        data_updates=updates,
                        reload_even_if_entry_is_unchanged=False,
                    )

        defaults = user_input or dict(entry.data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_schema(defaults),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start reauthentication."""
        entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm(
            {
                CONF_USERNAME: entry.data[CONF_USERNAME],
                CONF_GROUP: entry.data[CONF_GROUP],
            }
        )

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate and store replacement credentials."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None and CONF_PASSWORD in user_input:
            data = {
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_GROUP: user_input[CONF_GROUP].strip().lower(),
                CONF_UPDATE_INTERVAL_DAYS: normalize_update_interval_days(
                    entry.data.get(
                        CONF_UPDATE_INTERVAL_DAYS,
                        DEFAULT_UPDATE_INTERVAL_DAYS,
                    )
                ),
                CONF_MONTHLY_PAYMENTS: normalize_monthly_payments(
                    entry.data.get(
                        CONF_MONTHLY_PAYMENTS,
                        DEFAULT_MONTHLY_PAYMENTS,
                    )
                ),
            }
            try:
                await _validate_input(self.hass, data)
            except IcsAuthenticationError:
                errors["base"] = "invalid_auth"
            except (IcsConnectionError, IcsParseError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                if _is_duplicate_account(
                    self,
                    username=data[CONF_USERNAME],
                    group=data[CONF_GROUP],
                    current_entry_id=entry.entry_id,
                ):
                    errors["base"] = "already_configured"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        title=f"ICS Extranet ({data[CONF_GROUP]})",
                        data_updates=data,
                        reason="reauth_successful",
                    )

        defaults = user_input or {
            CONF_USERNAME: entry.data[CONF_USERNAME],
            CONF_GROUP: entry.data[CONF_GROUP],
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_connection_schema(
                defaults,
                include_update_interval=False,
            ),
            errors=errors,
        )
