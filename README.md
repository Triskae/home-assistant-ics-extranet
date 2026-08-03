# ICS Extranet for Home Assistant

Unofficial Home Assistant custom integration for property-management portals
hosted on `extranet2.ics.fr` (ICS Extranet V5).

Source code and issue tracker: [Triskae/home-assistant-ics-extranet](https://github.com/Triskae/home-assistant-ics-extranet)

> [!WARNING]
> This project is not affiliated with or endorsed by ICS. It reads the same
> server-rendered HTML pages that an authenticated user can access. A future
> change to the portal may require an integration update.

## Features

- UI-based setup through **Settings → Devices & services**.
- Dedicated cookie session; no browser automation is required.
- Balance due and recommended payment sensors in EUR.
- User-selectable monthly or quarterly charge-payment mode.
- Date of the latest account operation.
- Three automatically checked payment indicators for the current quarter.
- Configurable polling every two or three days, with one coordinated request
  cycle for all entities.
- Reconfiguration of credentials and account settings after installation.
- Reauthentication flow when ICS rejects stored credentials.
- Diagnostics with username and password redacted and ledger labels omitted.
- English and French translations.
- Local ICS brand icon for Home Assistant and HACS.

## Installation for local testing

1. Copy `custom_components/ics_extranet` into the Home Assistant
   `/config/custom_components/` directory.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration**.
4. Search for **ICS Extranet**.
5. Enter the ICS username, password and agency group.
6. Choose whether ICS should be checked every two or three days. Two days is
   the default and fastest supported interval.
7. Indicate whether the quarterly charges are paid in three monthly
   instalments.

The agency group is the value after `groupe=` in the public login URL. For
example, the group is `agency-name` in:

```text
https://extranet2.ics.fr/V5/connexion.php?groupe=agency-name
```

## Entities

| Entity | Purpose |
|---|---|
| Balance due | Current positive balance shown by ICS |
| Recommended monthly payment | Remaining balance divided over unpaid months of the current quarter |
| Last account operation | Date of the latest parsed ledger operation |
| Payment `YYYY-MM` (three entities) | Automatically on when a transfer for that month is detected or the month is otherwise settled |

In monthly mode, the integration detects the current `Appel trimestriel`, takes
the account balance at the end of that charge-call date, and divides it into
three instalments. Positive receipts containing payment terms such as
`virement`, `prélèvement`, `règlement` or `paiement` automatically mark the
corresponding months as paid. Refunds and adjustments are excluded, while an
unknown receipt is kept as ambiguous and never checked automatically. In
quarterly mode, the recommended payment stays undivided until the account is
settled. ICS remains the source of truth for the legally payable amount.

## Privacy and security

- No account, address, e-mail, phone number, balance or authenticated URL is
  included in this repository or its test fixtures.
- Credentials are stored in the Home Assistant config entry, like credentials
  for other UI-configured integrations. Protect Home Assistant backups and
  restrict access to the `/config` directory.
- Passwords and usernames are redacted from diagnostics.
- Raw HTML, cookies, credentials and ledger labels are never logged.
- The client validates TLS certificates and only connects to the fixed
  `https://extranet2.ics.fr` origin.

## Manual CLI probe

The original manual probe remains available for troubleshooting and uses only
the Python standard library:

```bash
python3 ics_poc.py
```

The guided prompts explain where to find the agency group. You can enter either
the value after `groupe=` or paste the complete ICS login URL and let the script
extract it. Environment variables `ICS_GROUP` and `ICS_USERNAME` may provide the
two non-secret prompts. Avoid putting `ICS_PASSWORD` in shell history or
committed environment files.

## Reconfiguration

Open **Settings → Devices & services → ICS Extranet**, select the integration's
menu, then choose **Reconfigure**. The username, optional replacement password,
agency group, polling interval and monthly-payment choice can be changed without
removing the integration. Leaving the password field empty keeps the stored
password. Home Assistant validates the resulting credentials against ICS and
reloads the integration automatically.

## Development

Run unit tests:

```bash
python3 -m unittest discover -s tests -v
```

## Releases

Pushing a semantic-version tag such as `v0.5.0` automatically creates the
matching GitHub release. Its notes list the commits between the new tag and the
previous tag and link to the complete GitHub comparison. Keep the version in
`custom_components/ics_extranet/manifest.json` and the client user-agent aligned
with the tag.

```bash
git tag v0.5.0
git push origin v0.5.0
```

Run formatting and lint checks:

```bash
ruff format --check .
ruff check .
```

The repository layout already follows the HACS requirement of one integration
under `custom_components/`.
