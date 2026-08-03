# AGENTS.md

## Project scope

This repository contains a public Home Assistant custom integration and a manual
Python POC for the ICS Extranet V5 website. Keep the integration installable with
HACS and compatible with the Home Assistant version targeted by the project.

## Communication and authorization

- Work step by step and communicate with the user in French.
- Do not push, create a tag, publish a release, or perform another external write
  unless the user explicitly asks for it.

## Privacy and security

- The repository is public. Never commit personal email addresses, passwords,
  session cookies, account URLs, ledger labels, captured authenticated HTML, or
  other account data.
- Never log or expose the stored ICS password. Diagnostics must redact the
  username and password and omit sensitive transaction labels.
- Credentials must be validated against ICS before a config-flow change is saved.
- In the reconfiguration form, never prefill the password. An empty password field
  must preserve the currently stored password.

## Home Assistant integration rules

- The integration domain is `ics_extranet`.
- Use the native `async_step_reconfigure` flow for editable credentials and
  settings. Keep username, optional replacement password, agency group, polling
  interval, and monthly-payment mode editable after installation.
- Use `FlowResult` from `homeassistant.data_entry_flow`; `ConfigFlowResult` is not
  available from that module in Home Assistant 2026.7.
- Polling choices are two or three days only, with two days as the default and
  minimum.
- Support both monthly and quarterly payment modes. Monthly mode splits the
  quarterly charge call into three payments; quarterly mode keeps the remaining
  amount undivided.
- Payment detection must remain conservative: known payment wording can confirm a
  receipt, refunds and unrelated credits must be excluded, and ambiguous receipts
  must not automatically mark a month as paid.
- Keep `strings.json`, `translations/en.json`, and `translations/fr.json` aligned
  whenever config-flow fields, errors, or entity names change.
- Keep the local brand icon under
  `custom_components/ics_extranet/brand/icon.png`.

## Manual CLI rules

- Keep `ics_poc.py` usable without Home Assistant or third-party Python packages.
- Keep the interactive setup understandable for non-technical users. Explain the
  ICS group and accept either the raw group name or the complete ICS login URL.
- Keep password input masked and do not persist it.
- Preserve `--json` for machine-readable output and the existing environment
  variable support.

## Validation

Before presenting a change as complete, run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components ics_poc.py
python3 -m json.tool custom_components/ics_extranet/manifest.json >/dev/null
git diff --check
```

Also validate every changed translation JSON file. Run Ruff checks when Ruff is
available. Add or update tests for changed parsing, payment, configuration,
translation, CLI, and version behavior.

## Versions and releases

- Use semantic versions and keep the same version in:
  - `custom_components/ics_extranet/manifest.json`
  - `custom_components/ics_extranet/client.py` (`USER_AGENT`)
  - `ics_poc.py` (`USER_AGENT`)
- A normal push to `main` must not create a release.
- Releases are triggered only by pushing a semantic-version tag such as `v0.6.0`.
- `.github/workflows/release.yml` creates the matching GitHub Release, lists the
  commits between the new tag and the preceding tag, and links to the complete
  GitHub comparison.
- Before tagging, ensure the worktree is clean, tests pass, `main` is synchronized
  with `origin/main`, and the tag version matches the project version.
- Publish in this order:

```bash
git push origin main
git tag -a vX.Y.Z -m "ICS Extranet vX.Y.Z"
git push origin vX.Y.Z
```

- After pushing the tag, verify that the GitHub Actions run succeeded and that the
  release is published with the expected changelog.
