"""Test setup: stub the ``hassapi`` and ``ovh`` modules and expose helpers.

The app imports ``hassapi`` (AppDaemon) and ``ovh`` at module load time. Neither
is needed to test our logic, so we register lightweight fakes in ``sys.modules``
*before* importing the app. This keeps the suite fast and hermetic (no AppDaemon
install, no OVH account, no network).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

# --- Make the app importable as ``ovh_sms`` --------------------------------
APP_DIR = Path(__file__).resolve().parent.parent / "apps" / "ovh_sms"
sys.path.insert(0, str(APP_DIR))


# --- Fake ``hassapi`` -------------------------------------------------------
class _FakeHass:
    """Minimal stand-in for ``hassapi.Hass`` that records interactions."""

    def __init__(self) -> None:
        self.args: dict[str, Any] = {}
        self.logs: list[tuple[str, str]] = []          # (level, message)
        self.events: list[tuple[str, dict[str, Any]]] = []  # (event, data)
        self.listeners: list[tuple[str, Any]] = []      # (event, callback)

    def log(self, msg: str, *args: Any, level: str = "INFO", **_: Any) -> None:
        # AppDaemon uses %-style formatting; mirror it so we can assert on text.
        self.logs.append((level, msg % args if args else msg))

    def listen_event(self, callback: Any, event: str, **_: Any) -> None:
        self.listeners.append((event, callback))

    def fire_event(self, event: str, **data: Any) -> None:
        self.events.append((event, data))


_hassapi = types.ModuleType("hassapi")
_hassapi.Hass = _FakeHass
sys.modules["hassapi"] = _hassapi


# --- Fake ``ovh`` (exception hierarchy mirrors the real library) -----------
_ovh = types.ModuleType("ovh")
_exceptions = types.ModuleType("ovh.exceptions")


class APIError(Exception):
    """Base OVH error — all specific errors inherit from it (as in the real lib)."""


class HTTPError(APIError):
    pass


class NetworkError(APIError):
    pass


class InvalidCredential(APIError):
    pass


for _exc in (APIError, HTTPError, NetworkError, InvalidCredential):
    setattr(_exceptions, _exc.__name__, _exc)


class _PlaceholderClient:
    """Default client; individual tests monkeypatch ``ovh.Client`` instead."""

    def __init__(self, **kwargs: Any) -> None:  # pragma: no cover - not exercised
        raise AssertionError("ovh.Client must be patched in tests")


_ovh.exceptions = _exceptions
_ovh.Client = _PlaceholderClient
sys.modules["ovh"] = _ovh
sys.modules["ovh.exceptions"] = _exceptions


# --- Shared fixtures / helpers ---------------------------------------------
class FakeClient:
    """Configurable fake OVH client.

    ``get`` returns ``services`` (or raises ``get_exc``); ``post`` records the
    call and returns ``post_result`` (or raises ``post_exc``).
    """

    def __init__(
        self,
        services: list[str] | None = None,
        post_result: dict[str, Any] | None = None,
        get_exc: Exception | None = None,
        post_exc: Exception | None = None,
    ) -> None:
        self.services = services if services is not None else ["sms-ab12345-1"]
        self.post_result = post_result or {}
        self.get_exc = get_exc
        self.post_exc = post_exc
        self.posted: tuple[str, dict[str, Any]] | None = None

    def get(self, path: str) -> Any:
        if self.get_exc:
            raise self.get_exc
        return self.services

    def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.posted = (path, kwargs)
        if self.post_exc:
            raise self.post_exc
        return self.post_result


@pytest.fixture
def ovh_sms():
    """Import the app module under test (fakes already registered above)."""
    import ovh_sms as module

    return module


@pytest.fixture
def make_app(ovh_sms, monkeypatch):
    """Build an ``OvhSms`` instance wired to a given FakeClient.

    Returns the initialized app; ``ovh.Client(...)`` yields ``client``.
    """

    def _make(args: dict[str, Any], client: FakeClient | None = None) -> Any:
        client = client if client is not None else FakeClient()
        monkeypatch.setattr(ovh_sms.ovh, "Client", lambda **_: client)
        app = ovh_sms.OvhSms()
        app.args = args
        app.initialize()
        app._client = client  # convenience handle for assertions
        return app

    return _make


@pytest.fixture
def base_args() -> dict[str, Any]:
    """Valid minimal configuration."""
    return {
        "application_key": "AK_abcd",
        "application_secret": "AS_wxyz",
        "consumer_key": "CK_1234",
        "service_name": "sms-ab12345-1",
    }
