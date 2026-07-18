"""AppDaemon app: send SMS through the OVH API from a Home Assistant event.

Listens for a HA event (``ovh_sms_send`` by default) and sends the message to the
recipients via the OVH SMS API. The API's HMAC signature is fully handled by the
official ``ovh`` library, so the user never has to sign anything.

See the README for configuration (apps.yaml) and how to create the OVH keys.
"""

from __future__ import annotations

from typing import Any

import hassapi as hass
import ovh

# --- Configuration defaults ------------------------------------------------
DEFAULT_ENDPOINT = "ovh-eu"
DEFAULT_EVENT_NAME = "ovh_sms_send"
DEFAULT_RESULT_EVENT = "ovh_sms_result"
DEFAULT_ERROR_EVENT = "ovh_sms_error"
DEFAULT_NO_STOP_CLAUSE = True

# Mandatory configuration keys (provided via !secret in apps.yaml).
REQUIRED_KEYS = ("application_key", "application_secret", "consumer_key")


class OvhSms(hass.Hass):
    """Relays a HA event to the OVH SMS API."""

    def initialize(self) -> None:
        """Validate config, build the OVH client and wire the event listener."""
        # Check the 3 keys up front: fail clearly and immediately if any is missing.
        missing = [k for k in REQUIRED_KEYS if not self.args.get(k)]
        if missing:
            self.log(
                "Incomplete configuration: missing keys %s. "
                "Provide them via !secret in apps.yaml.",
                ", ".join(missing),
                level="ERROR",
            )
            return

        self.endpoint: str = self.args.get("endpoint", DEFAULT_ENDPOINT)
        self.sender: str | None = self.args.get("sender")
        self.no_stop_clause: bool = self.args.get(
            "no_stop_clause", DEFAULT_NO_STOP_CLAUSE
        )
        self.default_receivers: list[str] = self._as_list(
            self.args.get("default_receivers")
        )
        self.result_event: str = self.args.get("result_event", DEFAULT_RESULT_EVENT)
        self.error_event: str = self.args.get("error_event", DEFAULT_ERROR_EVENT)

        self.client = ovh.Client(
            endpoint=self.endpoint,
            application_key=self.args["application_key"],
            application_secret=self.args["application_secret"],
            consumer_key=self.args["consumer_key"],
        )

        # Resolve the SMS service (e.g. "sms-ab12345-1"), otherwise bail out cleanly.
        self.service_name: str | None = self.args.get("service_name") or self._resolve_service()
        if not self.service_name:
            return

        event_name = self.args.get("event_name", DEFAULT_EVENT_NAME)
        self.listen_event(self._send, event_name)
        self.log(
            "OVH SMS ready — endpoint=%s, service=%s, key=%s, listening for event '%s'.",
            self.endpoint,
            self.service_name,
            self._mask(self.args["application_key"]),
            event_name,
        )

    def _resolve_service(self) -> str | None:
        """Auto-detect the SMS service name via ``GET /sms``."""
        try:
            services = self.client.get("/sms")
        except ovh.exceptions.APIError as err:
            self.log(
                "Unable to list SMS services (%s). "
                "The consumer key needs the GET /sms right — beware, GET /sms/* "
                "does NOT cover it. Recreate the token with GET /sms, or set "
                "'service_name' in apps.yaml to skip auto-detection.",
                self._describe(err),
                level="ERROR",
            )
            return None

        if not services:
            self.log("No SMS service found on this OVH account.", level="ERROR")
            return None
        if len(services) > 1:
            # Several services: pick the first one but ask the user to be explicit.
            self.log(
                "Several SMS services detected %s; using '%s'. "
                "Set 'service_name' in apps.yaml to remove the ambiguity.",
                services,
                services[0],
                level="WARNING",
            )
        return services[0]

    def _send(self, event_name: str, data: dict[str, Any], kwargs: dict[str, Any]) -> None:
        """Event callback: build and send the SMS."""
        message = data.get("message")
        if not message:
            self._fail("missing_message", "Event received without a 'message' field.")
            return

        receivers = self._as_list(data.get("receivers")) or self.default_receivers
        if not receivers:
            self._fail(
                "no_recipients",
                "No recipient: provide 'receivers' in the event "
                "or 'default_receivers' in apps.yaml.",
            )
            return

        # Payload for POST /sms/{service}/jobs (see OVH API docs).
        payload: dict[str, Any] = {
            "message": message,
            "receivers": receivers,
            "noStopClause": self.no_stop_clause,
            "charset": "UTF-8",
            "priority": "high",
        }
        sender = data.get("sender", self.sender)
        if sender:
            payload["sender"] = sender

        try:
            result = self.client.post(f"/sms/{self.service_name}/jobs", **payload)
        except ovh.exceptions.InvalidCredential as err:
            self._fail(
                "invalid_credentials",
                "Invalid OVH keys or unvalidated consumer key — check the "
                f"GET/POST rights on /sms/* ({self._describe(err)}).",
            )
            return
        # HTTPError/NetworkError inherit from APIError: catch them first to tell a
        # network problem apart from an application-level rejection by OVH.
        except (ovh.exceptions.HTTPError, ovh.exceptions.NetworkError) as err:
            self._fail("network", f"OVH API unreachable: {self._describe(err)}.")
            return
        except ovh.exceptions.APIError as err:
            self._fail("api_error", f"OVH API rejected the request: {self._describe(err)}.")
            return

        self._handle_result(message, receivers, result)

    def _handle_result(
        self, message: str, receivers: list[str], result: dict[str, Any]
    ) -> None:
        """Parse the OVH response: clear log + result event back into HA."""
        invalid = result.get("invalidReceivers") or []
        valid = result.get("validReceivers") or []
        credits_removed = result.get("totalCreditsRemoved", 0)

        if invalid:
            self.log(
                "Invalid number(s) ignored: %s (expected format +33...).",
                invalid,
                level="WARNING",
            )

        # OVH accepted the request but rejected every recipient: nobody was reached.
        if not valid:
            self._fail(
                "all_receivers_invalid",
                f"No SMS sent: all recipients were rejected by OVH ({invalid}). "
                "Use the international format +33...",
            )
            return

        # No credit consumed while there were valid recipients: typically an
        # exhausted SMS balance.
        if credits_removed == 0:
            self._fail(
                "insufficient_credits",
                "Send rejected: not enough SMS credits on the OVH account.",
            )
            return

        self.log(
            "SMS sent to %s recipient(s) — ids=%s, credits used=%s.",
            len(valid),
            result.get("ids"),
            credits_removed,
        )
        self.fire_event(
            self.result_event,
            message=message,
            valid_receivers=valid,
            invalid_receivers=invalid,
            ids=result.get("ids"),
            credits_removed=credits_removed,
        )

    def _fail(self, reason: str, detail: str) -> None:
        """Log an explicit error and emit the failure event into HA."""
        self.log(detail, level="ERROR")
        self.fire_event(self.error_event, reason=reason, detail=detail)

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        """Normalize a value to a list: accepts None, a string or a list."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return list(value)

    @staticmethod
    def _mask(secret: str) -> str:
        """Mask a secret for logs: keep only the last 4 characters."""
        return f"****{secret[-4:]}" if len(secret) > 4 else "****"

    @staticmethod
    def _describe(err: Exception) -> str:
        """Short, readable message for an exception."""
        return str(err) or err.__class__.__name__
