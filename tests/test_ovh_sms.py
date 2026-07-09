"""Unit tests for the OVH SMS AppDaemon app."""

from __future__ import annotations

import pytest

from conftest import FakeClient


# --- Helpers ----------------------------------------------------------------
def levels(app) -> list[str]:
    return [level for level, _ in app.logs]


def last_event(app):
    return app.events[-1] if app.events else None


def send(app, **data) -> None:
    """Invoke the event callback directly."""
    app._send("ovh_sms_send", data, {})


# --- initialize -------------------------------------------------------------
@pytest.mark.parametrize("missing", ["application_key", "application_secret", "consumer_key"])
def test_initialize_missing_key_logs_error_and_no_listener(make_app, base_args, missing):
    args = dict(base_args)
    del args[missing]

    app = make_app(args)

    assert "ERROR" in levels(app)
    assert app.listeners == []


def test_initialize_success_registers_listener_and_masks_key(make_app, base_args):
    app = make_app(base_args)

    assert app.listeners == [("ovh_sms_send", app._send)]
    startup = app.logs[-1][1]
    assert "ready" in startup
    # The raw application key must never appear; only the masked form.
    assert "AK_abcd" not in startup
    assert "****abcd" in startup


def test_initialize_custom_event_name(make_app, base_args):
    app = make_app({**base_args, "event_name": "fire_alert"})

    assert app.listeners[0][0] == "fire_alert"


def test_initialize_auto_detects_service(make_app, base_args):
    args = dict(base_args)
    del args["service_name"]
    client = FakeClient(services=["sms-auto-1"])

    app = make_app(args, client)

    assert app.service_name == "sms-auto-1"
    assert app.listeners  # listener wired once service resolved


def test_initialize_multiple_services_warns_and_picks_first(make_app, base_args):
    args = dict(base_args)
    del args["service_name"]
    client = FakeClient(services=["sms-1", "sms-2"])

    app = make_app(args, client)

    assert app.service_name == "sms-1"
    assert "WARNING" in levels(app)


def test_initialize_service_lookup_error_bails_out(make_app, base_args, ovh_sms):
    args = dict(base_args)
    del args["service_name"]
    client = FakeClient(get_exc=ovh_sms.ovh.exceptions.APIError("boom"))

    app = make_app(args, client)

    assert app.service_name is None
    assert app.listeners == []
    assert "ERROR" in levels(app)


def test_initialize_no_service_bails_out(make_app, base_args):
    args = dict(base_args)
    del args["service_name"]

    app = make_app(args, FakeClient(services=[]))

    assert app.service_name is None
    assert app.listeners == []


# --- _send: validation ------------------------------------------------------
def test_send_without_message_fails(make_app, base_args):
    app = make_app(base_args)

    send(app, receivers=["+33612345678"])

    event, data = last_event(app)
    assert event == "ovh_sms_error"
    assert data["reason"] == "missing_message"
    assert app._client.posted is None  # nothing sent


def test_send_without_recipient_fails(make_app, base_args):
    app = make_app(base_args)

    send(app, message="hello")

    _, data = last_event(app)
    assert data["reason"] == "no_recipients"


def test_send_uses_default_receivers(make_app, base_args):
    app = make_app({**base_args, "default_receivers": ["+33600000000"]})

    send(app, message="hello")

    _, kwargs = app._client.posted
    assert kwargs["receivers"] == ["+33600000000"]


def test_send_receivers_string_is_normalized_to_list(make_app, base_args):
    app = make_app(base_args)

    send(app, message="hello", receivers="+33611111111")

    _, kwargs = app._client.posted
    assert kwargs["receivers"] == ["+33611111111"]


# --- _send: payload ---------------------------------------------------------
def test_send_builds_expected_payload(make_app, base_args):
    client = FakeClient(post_result={"validReceivers": ["+33612345678"], "totalCreditsRemoved": 1})
    app = make_app(base_args, client)

    send(app, message="hi", receivers=["+33612345678"])

    path, kwargs = app._client.posted
    assert path == "/sms/sms-ab12345-1/jobs"
    assert kwargs["message"] == "hi"
    assert kwargs["noStopClause"] is True
    assert kwargs["charset"] == "UTF-8"
    assert kwargs["priority"] == "high"
    assert "sender" not in kwargs  # no sender configured


def test_send_event_sender_overrides_config(make_app, base_args):
    client = FakeClient(post_result={"validReceivers": ["+33612345678"], "totalCreditsRemoved": 1})
    app = make_app({**base_args, "sender": "ConfigSender"}, client)

    send(app, message="hi", receivers=["+33612345678"], sender="EventSender")

    _, kwargs = app._client.posted
    assert kwargs["sender"] == "EventSender"


def test_send_no_stop_clause_false(make_app, base_args):
    client = FakeClient(post_result={"validReceivers": ["+33612345678"], "totalCreditsRemoved": 1})
    app = make_app({**base_args, "no_stop_clause": False}, client)

    send(app, message="hi", receivers=["+33612345678"])

    _, kwargs = app._client.posted
    assert kwargs["noStopClause"] is False


# --- _send: result handling -------------------------------------------------
def test_send_success_fires_result_event(make_app, base_args):
    client = FakeClient(
        post_result={
            "validReceivers": ["+33612345678"],
            "invalidReceivers": [],
            "ids": [42],
            "totalCreditsRemoved": 1,
        }
    )
    app = make_app(base_args, client)

    send(app, message="hi", receivers=["+33612345678"])

    event, data = last_event(app)
    assert event == "ovh_sms_result"
    assert data["ids"] == [42]
    assert data["credits_removed"] == 1
    assert data["valid_receivers"] == ["+33612345678"]


def test_send_invalid_receivers_logs_warning(make_app, base_args):
    client = FakeClient(
        post_result={
            "validReceivers": ["+33612345678"],
            "invalidReceivers": ["+33000"],
            "totalCreditsRemoved": 1,
        }
    )
    app = make_app(base_args, client)

    send(app, message="hi", receivers=["+33612345678", "+33000"])

    assert "WARNING" in levels(app)
    assert last_event(app)[0] == "ovh_sms_result"


def test_send_zero_credits_with_valid_receivers_reports_insufficient(make_app, base_args):
    client = FakeClient(
        post_result={"validReceivers": ["+33612345678"], "totalCreditsRemoved": 0}
    )
    app = make_app(base_args, client)

    send(app, message="hi", receivers=["+33612345678"])

    event, data = last_event(app)
    assert event == "ovh_sms_error"
    assert data["reason"] == "insufficient_credits"


# --- _send: error mapping ---------------------------------------------------
def test_send_invalid_credentials(make_app, base_args, ovh_sms):
    exc = ovh_sms.ovh.exceptions.InvalidCredential("bad key")
    app = make_app(base_args, FakeClient(post_exc=exc))

    send(app, message="hi", receivers=["+33612345678"])

    _, data = last_event(app)
    assert data["reason"] == "invalid_credentials"


def test_send_network_error(make_app, base_args, ovh_sms):
    exc = ovh_sms.ovh.exceptions.NetworkError("timeout")
    app = make_app(base_args, FakeClient(post_exc=exc))

    send(app, message="hi", receivers=["+33612345678"])

    _, data = last_event(app)
    assert data["reason"] == "network"


def test_send_generic_api_error(make_app, base_args, ovh_sms):
    exc = ovh_sms.ovh.exceptions.APIError("nope")
    app = make_app(base_args, FakeClient(post_exc=exc))

    send(app, message="hi", receivers=["+33612345678"])

    _, data = last_event(app)
    assert data["reason"] == "api_error"


# --- static helpers ---------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, []),
        ("+33612345678", ["+33612345678"]),
        (["+331", "+332"], ["+331", "+332"]),
    ],
)
def test_as_list(ovh_sms, value, expected):
    assert ovh_sms.OvhSms._as_list(value) == expected


@pytest.mark.parametrize(
    "secret,expected",
    [
        ("AK_abcd", "****abcd"),
        ("abc", "****"),  # too short to reveal anything
    ],
)
def test_mask(ovh_sms, secret, expected):
    assert ovh_sms.OvhSms._mask(secret) == expected
