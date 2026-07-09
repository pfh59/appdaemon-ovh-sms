# AppDaemon OVH SMS

Send an SMS through the **OVH API** from any Home Assistant automation by firing a
simple event — the API's HMAC signature is handled for you.

- 📩 Event-driven (`ovh_sms_send`)
- 👥 Recipients overridable at send time
- ↩️ Result events back into HA (`ovh_sms_result` / `ovh_sms_error`)
- 🔐 Keys stored via `!secret`
- 🧭 OVH SMS service auto-detection

> ⚠️ Requires the `ovh` Python dependency (add it to the AppDaemon add-on
> `python_packages` option). See the README for a <15 minute install.
