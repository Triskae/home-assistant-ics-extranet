"""Config flow for ICS Extranet."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import ConfigFlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import dt as dt_util

from .client import IcsAuthenticationError, IcsClient, IcsConnectionError
from .const import CONF_GROUP, DOMAIN
from .parser import IcsParseError


def _schema(defaults: dict[str, str] | None = None) -> vol.Schema:
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=values.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_GROUP, default=values.get(CONF_GROUP, "")): str,
        }
    )


def _account_unique_id(username: str, group: str) -> str:
    normalized = f"{group.strip().casefold()}:{username.strip().casefold()}"
    return sha256(normalized.encode()).hexdigest()[:24]


async def _validate_input(hass, data: dict[str, str]) -> None:
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    try:
        client = IcsClient(
            session=session,
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            group=data[CONF_GROUP],
        )
        await client.async_fetch_summary(dt_util.now().date())
    finally:
        await session.close()


class IcsExtranetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an ICS Extranet config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_GROUP: user_input[CONF_GROUP].strip().lower(),
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
                return self.async_create_entry(
                    title=f"ICS Extranet ({data[CONF_GROUP]})",
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
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
    ) -> ConfigFlowResult:
        """Validate and store replacement credentials."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None and CONF_PASSWORD in user_input:
            data = {
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_GROUP: user_input[CONF_GROUP].strip().lower(),
            }
            try:
                await _validate_input(self.hass, data)
            except IcsAuthenticationError:
                errors["base"] = "invalid_auth"
            except (IcsConnectionError, IcsParseError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    _account_unique_id(data[CONF_USERNAME], data[CONF_GROUP])
                )
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=data,
                    reason="reauth_successful",
                )

        defaults = user_input or {
            CONF_USERNAME: entry.data[CONF_USERNAME],
            CONF_GROUP: entry.data[CONF_GROUP],
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_schema(defaults),
            errors=errors,
        )
