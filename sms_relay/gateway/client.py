"""SMSGate gateway HTTP client.

Thin client over the SMSGate 3rd-party API (``{server}/api/3rdparty/v1``) that
SMS Relay talks to. Handles Basic or optional JWT (scoped access-token)
authentication, message dispatch, webhook self-registration, inbox refresh and
delivery-status polling.

The endpoint and payload shapes mirror the SMS Gateway for Android server and
are documented in ``docs/api-reference.md``.
"""

from datetime import timedelta, timezone

import requests
import frappe
from frappe.utils import cint, get_datetime

# Scopes requested when the gateway is configured to use JWT auth. Keep in sync
# with the server's supported scopes; if the server rejects the list, the
# client falls back to Basic authentication.
JWT_SCOPES = [
    "messages:send",
    "messages:list",
    "messages:read",
    "messages:export",
    "devices:list",
    "devices:delete",
    "webhooks:list",
    "webhooks:write",
    "settings:read",
    "settings:write",
    "inbox:list",
    "inbox:read",
    "logs:read",
]

# All webhook events the app can emit (WebHookEvent in the gateway source).
GATEWAY_WEBHOOK_EVENTS = [
    "sms:received",
    "sms:sent",
    "sms:delivered",
    "sms:failed",
    "system:ping",
    "sms:data-received",
    "mms:received",
    "mms:downloaded",
    "app:started",
    "sms:cancelled",
]

# Map gateway ProcessingState -> SMS Relay status values.
PROCESSING_STATE_MAP = {
    "Pending": "Queued",
    "Processed": "Sent",
    "Sent": "Sent",
    "Delivered": "Delivered",
    "Failed": "Failed",
    "Cancelling": "Cancelled",
    "Cancelled": "Cancelled",
}


def to_iso8601(value):
    """Return an ISO-8601 UTC string for a Frappe datetime value, else None."""
    if not value:
        return None
    try:
        dt = get_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        # Frappe stores naive datetime fields in UTC.
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GatewayClient:
    """Client for the SMSGate 3rd-party API of one SMS Device."""

    def __init__(self, device, base_url=None):
        self.device = device
        self.settings = frappe.get_single("SMS Gateway Settings")
        base = base_url or (device.server_url or "").rstrip("/")
        if not base:
            base = (self.settings.get("gateway_url") or "").rstrip("/")
        self.base_url = base
        self.username = device.username or ""
        self.password = device.get_password("password") or ""
        self.timeout = cint(self.settings.get("timeout")) or 15
        self.api_base = self._resolve_api_base()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _resolve_api_base(self):
        path = (self.settings.get("api_path") or "/api/3rdparty/v1/message").strip()
        if path.endswith("/message"):
            base = path[: -len("/message")].rstrip("/")
        else:
            base = path.rstrip("/")
        if not base:
            base = "/api/3rdparty/v1"
        if not base.startswith("/"):
            base = "/" + base
        return base

    def _url(self, path):
        if not self.base_url:
            return None
        if not path.startswith("/"):
            path = "/" + path
        return "{}{}{}".format(self.base_url, self.api_base, path)

    def _token_cache_key(self):
        return "sms_relay_jwt_{}".format(self.device.name)

    def _basic_auth(self):
        if not self.username:
            return None
        return requests.auth.HTTPBasicAuth(self.username, self.password)

    def _cache_token(self, data):
        expires_in = max(cint(self.settings.get("jwt_ttl")) or 3600, 3600)
        frappe.cache().set_value(
            self._token_cache_key(),
            (
                data.get("id"),
                data.get("access_token"),
                data.get("refresh_token"),
                data.get("expires_at"),
            ),
            expires_in_sec=expires_in,
        )

    def _get_access_token(self):
        cached = frappe.cache().get_value(self._token_cache_key())
        if cached:
            _, access_token, refresh_token, expires_at = cached
            try:
                if expires_at and get_datetime() < get_datetime(expires_at) - timedelta(seconds=60):
                    return access_token
            except (TypeError, ValueError):
                pass
            if refresh_token:
                token = self._refresh_access_token(refresh_token)
                if token:
                    return token
        return self._issue_access_token()

    def _issue_access_token(self):
        resp = self._request(
            "POST",
            "/auth/token",
            json={"ttl": cint(self.settings.get("jwt_ttl")) or 3600, "scopes": JWT_SCOPES},
            force_basic=True,
        )
        if resp is None or resp.status_code not in (200, 201):
            return None
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        access_token = data.get("access_token")
        if not access_token:
            return None
        self._cache_token(data)
        return access_token

    def _refresh_access_token(self, refresh_token):
        resp = self._request(
            "POST",
            "/auth/token/refresh",
            headers={"Authorization": "Bearer {}".format(refresh_token)},
            force_basic=False,
        )
        if resp is None or resp.status_code not in (200, 201):
            return None
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        access_token = data.get("access_token")
        if not access_token:
            return None
        self._cache_token(data)
        return access_token

    def revoke_access_token(self):
        """Revoke the cached JWT on the gateway (best effort)."""
        cached = frappe.cache().get_value(self._token_cache_key())
        frappe.cache().delete_value(self._token_cache_key())
        if not cached:
            return True
        jti = cached[0]
        if not jti:
            return True
        resp = self._request("DELETE", "/auth/token/{}".format(jti), force_basic=True)
        return resp is not None and resp.status_code in (200, 204)

    def _request(self, method, path, force_basic=False, **kwargs):
        url = self._url(path)
        if not url:
            return None
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("Content-Type", "application/json")
        kwargs.setdefault("timeout", self.timeout)

        auth = None
        use_jwt = bool(self.username) and not force_basic and cint(self.settings.get("use_jwt_auth"))
        if use_jwt:
            token = self._get_access_token()
            if token:
                headers["Authorization"] = "Bearer {}".format(token)
            else:
                auth = self._basic_auth()
        elif self.username:
            auth = self._basic_auth()

        request_fn = getattr(requests, method.lower())
        try:
            resp = request_fn(url, auth=auth, headers=headers, **kwargs)
            # A rejected token (401/403) may be stale: re-issue once, else fall
            # back to Basic so a token failure never blocks sending.
            if use_jwt and resp.status_code in (401, 403) and "Authorization" in headers:
                frappe.cache().delete_value(self._token_cache_key())
                token = self._get_access_token()
                headers = dict(headers)
                if token:
                    headers["Authorization"] = "Bearer {}".format(token)
                    resp = request_fn(url, headers=headers, **kwargs)
                else:
                    resp = request_fn(url, auth=self._basic_auth(), headers=headers, **kwargs)
            return resp
        except requests.exceptions.RequestException:
            return None

    def _parse_json(self, resp):
        if resp is None:
            return {}
        if not resp.headers.get("content-type", "").startswith("application/json"):
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------------ #
    # Messages
    # ------------------------------------------------------------------ #
    def send_message(
        self,
        phone_numbers,
        text=None,
        data=None,
        port=None,
        message_id=None,
        sim_number=None,
        schedule_at=None,
        valid_until=None,
        priority=None,
        with_delivery_report=True,
        device_id=None,
    ):
        """Send a text or data (binary) SMS to one or more recipients.

        Returns ``{"success": bool, "message_id": str|None, "error": str|None}``.
        """
        phones = [p for p in (phone_numbers or []) if p]
        if not phones:
            return {"success": False, "error": "Empty phone numbers list"}

        payload = {}
        if message_id:
            payload["id"] = message_id
        if data is not None:
            payload["dataMessage"] = {"data": data, "port": cint(port)}
        else:
            payload["textMessage"] = {"text": text or ""}
        payload["phoneNumbers"] = phones
        if sim_number:
            payload["simNumber"] = cint(sim_number)
        if with_delivery_report:
            payload["withDeliveryReport"] = True
        if device_id:
            payload["deviceId"] = device_id
        if priority is not None:
            payload["priority"] = priority

        iso_schedule = to_iso8601(schedule_at)
        if iso_schedule:
            payload["scheduleAt"] = iso_schedule
        iso_valid = to_iso8601(valid_until)
        if iso_valid:
            payload["validUntil"] = iso_valid

        resp = self._request("POST", "/message", json=payload)
        if resp is None:
            return {"success": False, "error": "Connection error"}
        if resp.status_code in (200, 201, 202):
            data2 = self._parse_json(resp)
            return {
                "success": True,
                "message_id": data2.get("id") or data2.get("messageId") or data2.get("requestId"),
            }
        return {"success": False, "error": "HTTP {}: {}".format(resp.status_code, (resp.text or "")[:200])}

    def get_message_status(self, message_id):
        """Return the gateway GetMessageResponse for a message, or None."""
        for path in ("/messages/{id}", "/message/{id}"):
            resp = self._request("GET", path.format(id=message_id))
            if resp is None:
                continue
            if resp.status_code == 200:
                return self._parse_json(resp)
            if resp.status_code != 404:
                return None
        return None

    # ------------------------------------------------------------------ #
    # Webhooks
    # ------------------------------------------------------------------ #
    def list_webhooks(self):
        resp = self._request("GET", "/webhooks")
        if resp is None or resp.status_code != 200:
            return []
        data = self._parse_json(resp)
        return data if isinstance(data, list) else []

    def create_webhook(self, event, url, device_id=None):
        body = {"event": event, "url": url}
        if device_id:
            body["device_id"] = device_id
        resp = self._request("POST", "/webhooks", json=body)
        if resp is None or resp.status_code not in (200, 201, 202):
            return None
        return self._parse_json(resp)

    def delete_webhook(self, webhook_id):
        if not webhook_id:
            return True
        resp = self._request("DELETE", "/webhooks/{}".format(webhook_id))
        return resp is not None and resp.status_code in (200, 204)

    # ------------------------------------------------------------------ #
    # Inbox
    # ------------------------------------------------------------------ #
    def refresh_inbox(self):
        resp = self._request("POST", "/inbox/refresh", json={})
        return resp is not None and resp.status_code in (200, 202, 204)

    def list_inbox(self, **params):
        if params:
            resp = self._request("GET", "/inbox", params=params)
        else:
            resp = self._request("GET", "/inbox")
        if resp is None or resp.status_code != 200:
            return []
        data = self._parse_json(resp)
        if isinstance(data, dict):
            data = data.get("messages") or data.get("data") or []
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------ #
    # Settings / logs / devices
    # ------------------------------------------------------------------ #
    def get_settings(self):
        resp = self._request("GET", "/settings")
        if resp is None or resp.status_code != 200:
            return None
        return self._parse_json(resp)

    def get_logs(self, limit=100):
        resp = self._request("GET", "/logs", params={"limit": cint(limit)})
        if resp is None or resp.status_code != 200:
            return []
        data = self._parse_json(resp)
        if isinstance(data, dict):
            data = data.get("logs") or data.get("data") or []
        return data if isinstance(data, list) else []

    def list_devices(self):
        resp = self._request("GET", "/devices")
        if resp is None or resp.status_code != 200:
            return []
        data = self._parse_json(resp)
        if isinstance(data, dict):
            data = data.get("devices") or data.get("data") or []
        return data if isinstance(data, list) else []
