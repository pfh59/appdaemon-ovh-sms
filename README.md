# AppDaemon OVH SMS

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/pfh59/appdaemon-ovh-sms/actions/workflows/validate.yml/badge.svg)](https://github.com/pfh59/appdaemon-ovh-sms/actions/workflows/validate.yml)
![License](https://img.shields.io/badge/license-MIT-green.svg)

Send an **SMS through the OVH API** from **any Home Assistant automation** by firing a
simple event. All the OVH API complexity (HMAC signature, clock synchronization) is
handled for you — you never write a single line of code.

Typical use case: get an SMS alert when a mobile push notification fails or goes
unnoticed (water leak, intrusion, fire, power outage…).

---

## Table of contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Step 1 — Create your OVH keys](#step-1--create-your-ovh-keys)
4. [Step 2 — Install via HACS](#step-2--install-via-hacs)
5. [Step 3 — Install the `ovh` dependency](#step-3--install-the-ovh-dependency)
6. [Step 4 — Store your keys securely](#step-4--store-your-keys-securely)
7. [Step 5 — Configure the app](#step-5--configure-the-app)
8. [Step 6 — Test](#step-6--test)
9. [Use in an automation](#use-in-an-automation)
10. [Configuration reference](#configuration-reference)
11. [Result events](#result-events)
12. [Troubleshooting](#troubleshooting)

---

## Features

- 📩 SMS sending triggered by a **HA event** (`ovh_sms_send` by default).
- 👥 **Recipients overridable** at send time (through the event data).
- ↩️ **Result events** in HA (`ovh_sms_result` on success, `ovh_sms_error` on failure)
  so your automations can react.
- 🧭 **Auto-detection** of the OVH SMS service name.
- 🔐 API keys protected via `!secret`, **never printed** in clear text in the logs.
- 🪵 **Clear error messages** in the AppDaemon logs (invalid key, rejected signature,
  exhausted credits, invalid number).

## Requirements

- Home Assistant with **AppDaemon running** (add-on or standalone install).
- **HACS** installed.
- An **OVH account** with an active **SMS service** and credits.

---

## Step 1 — Create your OVH keys

1. Go to **<https://api.ovh.com/createToken/>** (logged into your OVH account).
2. Set the following rights (mandatory):

   | Method | Path      |
   |--------|-----------|
   | GET    | `/sms`    |
   | GET    | `/sms/*`  |
   | POST   | `/sms/*`  |

   > ⚠️ `GET /sms` (without `/*`) is required for the service auto-detection:
   > in the OVH API, `/sms/*` covers the sub-paths but **not** `/sms` itself.

3. Leave the validity as *Unlimited* (or a long duration).
4. Confirm: OVH shows you **three values** — write them down, they won't be shown again:
   - **Application Key**
   - **Application Secret**
   - **Consumer Key**

> Pick the endpoint matching your account: `ovh-eu` (Europe), `ovh-ca` (Canada) or
> `ovh-us` (United States).

---

## Step 2 — Install via HACS

> ⚠️ **HACS ≥ 2.0**: AppDaemon apps are disabled by default. Enable them first in
> HACS → ⋮ menu → **Settings** → check **AppDaemon apps discovery & tracking**,
> otherwise the repository won't show up.

As long as the repository is not in the official catalog, add it as a **custom repository**:

1. HACS → ⋮ menu (top right) → **Custom repositories**.
2. URL: `https://github.com/pfh59/appdaemon-ovh-sms`
3. Category: **AppDaemon**.
4. **Add**, then open the card and click **Download**.

HACS automatically copies the app folder into `appdaemon/apps/ovh_sms/`.
No Python file to copy by hand.

---

## Step 3 — Install the `ovh` dependency

This app uses the official `ovh` Python library. HACS **does not install** Python
dependencies, so you add it once.

- **AppDaemon add-on (Home Assistant OS / supervised)**:
  Settings → Add-ons → **AppDaemon** → **Configuration** tab → add `ovh` to the
  **`python_packages`** option:

  ```yaml
  python_packages:
    - ovh
  ```

  Then **restart** the add-on.

- **Docker (official `acockburn/appdaemon` image)**:
  the container installs the packages listed in `requirements.txt` at the root of
  the mounted conf directory on every start. Create (or edit) that file next to
  your `appdaemon.yaml`:

  ```
  config/appdaemon/requirements.txt
  ```

  with the single line:

  ```
  ovh
  ```

  then restart the container: `docker compose restart appdaemon`.

  <details>
  <summary>Docker Compose example (Home Assistant + AppDaemon)</summary>

  ```yaml
  services:
    homeassistant:
      container_name: homeassistant
      image: ghcr.io/home-assistant/home-assistant:stable
      network_mode: host
      volumes:
        - ./config:/config
      environment:
        - TZ=Europe/Paris
      restart: unless-stopped

    appdaemon:
      container_name: appdaemon
      image: acockburn/appdaemon:latest
      network_mode: host          # same network as HA, HA_URL can use 127.0.0.1
      volumes:
        - ./config/appdaemon:/conf
      environment:
        - TZ=Europe/Paris
        - HA_URL=http://127.0.0.1:8123
        - TOKEN=${APPDAEMON_HA_TOKEN}   # HA long-lived access token
      restart: unless-stopped
      depends_on:
        - homeassistant
  ```

  With this layout, HACS (running in the HA container) downloads AppDaemon apps
  into `/config/appdaemon/apps/`, which the AppDaemon container sees as
  `/conf/apps/` — no manual copy needed. The `ovh` dependency goes into
  `./config/appdaemon/requirements.txt` as described above.
  </details>

- **Standalone AppDaemon install** (venv):

  ```bash
  pip install ovh
  ```

---

## Step 4 — Store your keys securely

⚠️ **Never write your keys in clear text in `apps.yaml`.** Use `!secret`.

Open (or create) `appdaemon/secrets.yaml` and add:

```yaml
ovh_application_key: "your_application_key"
ovh_application_secret: "your_application_secret"
ovh_consumer_key: "your_consumer_key"
```

> 🔒 If you version your configuration, **add `secrets.yaml` to your `.gitignore`**
> so you never publish your keys by mistake.

A template is provided: [`secrets.yaml.example`](secrets.yaml.example).

---

## Step 5 — Configure the app

Add this block to your `appdaemon/apps/apps.yaml` (full template:
[`apps.yaml.example`](apps.yaml.example)):

```yaml
ovh_sms:
  module: ovh_sms
  class: OvhSms
  application_key: !secret ovh_application_key
  application_secret: !secret ovh_application_secret
  consumer_key: !secret ovh_consumer_key
  endpoint: ovh-eu
  default_receivers:
    - "+33612345678"
```

AppDaemon reloads the app automatically. In the AppDaemon logs you should see:

```
OVH SMS ready — endpoint=ovh-eu, service=sms-ab12345-1, key=****ab12, listening for event 'ovh_sms_send'.
```

---

## Step 6 — Test

Without writing an automation, in Home Assistant:

1. **Developer Tools → Events**.
2. Event type: `ovh_sms_send`.
3. Event data:

   ```yaml
   message: "Test from Home Assistant"
   receivers:
     - "+33612345678"
   ```

4. **Fire event**.

You should receive the SMS and see in the AppDaemon logs:
`SMS sent to 1 recipient(s) — ids=[...], credits used=1`.

---

## Use in an automation

`receivers` is **optional**: without it, the `default_receivers` from the config are used.

```yaml
automation:
  - alias: "Water leak SMS alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.kitchen_leak_sensor
        to: "on"
    action:
      - event: ovh_sms_send
        event_data:
          message: "🚨 Water leak detected in the kitchen!"
          # receivers omitted -> sent to default_receivers
```

Override recipients for a specific alert:

```yaml
      - event: ovh_sms_send
        event_data:
          message: "The gate was left open."
          receivers:
            - "+33611111111"   # only this person
```

---

## Configuration reference

| Key | Required | Default | Description |
|-----|:--------:|---------|-------------|
| `module` | ✅ | — | `ovh_sms` |
| `class` | ✅ | — | `OvhSms` |
| `application_key` | ✅ | — | OVH application key (via `!secret`) |
| `application_secret` | ✅ | — | OVH application secret (via `!secret`) |
| `consumer_key` | ✅ | — | OVH consumer key (via `!secret`) |
| `endpoint` | ❌ | `ovh-eu` | `ovh-eu`, `ovh-ca` or `ovh-us` |
| `service_name` | ❌ | auto | SMS service name (e.g. `sms-ab12345-1`) |
| `sender` | ❌ | OVH default | Sender registered with OVH |
| `no_stop_clause` | ❌ | `true` | `true` for alerts (no "STOP" mention) |
| `default_receivers` | ❌ | `[]` | List of numbers in `+33...` format |
| `event_name` | ❌ | `ovh_sms_send` | HA event listened to |
| `result_event` | ❌ | `ovh_sms_result` | Event emitted on success |
| `error_event` | ❌ | `ovh_sms_error` | Event emitted on failure |

**Event data** (`event_data`): `message` (required), `receivers` (optional, list or
single string), `sender` (optional).

---

## Result events

**`ovh_sms_result`** (success):

| Field | Description |
|-------|-------------|
| `message` | The sent message |
| `valid_receivers` | Accepted numbers |
| `invalid_receivers` | Rejected numbers |
| `ids` | OVH job identifiers |
| `credits_removed` | SMS credits used |

**`ovh_sms_error`** (failure):

| Field | Description |
|-------|-------------|
| `reason` | Short code (`invalid_credentials`, `insufficient_credits`, `no_recipients`, …) |
| `detail` | Human-readable message |

Example: send a push notification if the SMS fails.

```yaml
automation:
  - alias: "SMS failed -> notification"
    trigger:
      - platform: event
        event_type: ovh_sms_error
    action:
      - service: notify.mobile_app
        data:
          message: "SMS send failed: {{ trigger.event.data.detail }}"
```

---

## Troubleshooting

| Symptom (AppDaemon log) | Likely cause | Fix |
|-------------------------|--------------|-----|
| `Incomplete configuration: missing keys …` | Key absent from `apps.yaml` | Check the 3 keys and the `!secret` references |
| `Unable to list SMS services (This call has not been granted…)` | Token created without `GET /sms` (`/sms/*` doesn't cover it) | Recreate the token with the 3 rights of [Step 1](#step-1--create-your-ovh-keys), or set `service_name` |
| `Invalid OVH keys or unvalidated consumer key` | Wrong key / missing rights | Recreate the token with the 3 rights of [Step 1](#step-1--create-your-ovh-keys) |
| `OVH API rejected the request` | Clock skew or wrong secret | Check the server time and the `application_secret` |
| `not enough SMS credits` | Exhausted SMS balance | Top up your OVH SMS credit |
| `Invalid number(s) ignored` | Wrong format | Use the international format `+33…` |
| `No SMS service found` | No active SMS service | Enable an SMS service at OVH |
| `ModuleNotFoundError: No module named 'ovh'` | Dependency not installed | See [Step 3](#step-3--install-the-ovh-dependency) |

---

## Development

Run the unit tests locally (no OVH account or AppDaemon install needed — the `ovh`
and `hassapi` modules are stubbed by the test suite):

```bash
pip install -r requirements-dev.txt
pytest
```

CI runs HACS validation, Python compilation and the unit tests on every push
(see `.github/workflows/validate.yml`).

## Contributing / releases

Versions follow [semantic versioning](https://semver.org/) and are published via
tagged **GitHub releases** (e.g. `v1.0.0`), a prerequisite for a future submission to
the official HACS catalog.

## License

[MIT](LICENSE).
