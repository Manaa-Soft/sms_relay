import json

import frappe
from unittest.mock import patch, MagicMock
from sms_relay.tests.conftest import SMSRelayTestCase
from sms_relay.gateway.client import (
    GatewayClient,
    GATEWAY_WEBHOOK_EVENTS,
    PROCESSING_STATE_MAP,
    to_iso8601,
)
from sms_relay.gateway.webhooks import provision_webhooks, reconcile_webhooks
from sms_relay.gateway.inbox import sync_device_inbox
from sms_relay.gateway.status import _apply_status, sync_delivery_status


def _json_response(status_code, payload, text=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = payload
    resp.text = text if text is not None else json.dumps(payload)
    return resp


class TestToIso8601(SMSRelayTestCase):
    def test_naive_datetime_returns_utc_z(self):
        from frappe.utils import get_datetime
        result = to_iso8601(get_datetime("2026-08-05 12:00:00"))
        self.assertEqual(result, "2026-08-05T12:00:00Z")

    def test_empty_value_returns_none(self):
        self.assertIsNone(to_iso8601(None))
        self.assertIsNone(to_iso8601(""))


class TestGatewayClientJWT(SMSRelayTestCase):
    def setUp(self):
        super().setUp()
        frappe.db.set_value("SMS Gateway Settings", "SMS Gateway Settings", "use_jwt_auth", 1)
        frappe.db.set_value("SMS Gateway Settings", "SMS Gateway Settings", "jwt_ttl", 3600)
        frappe.db.commit()
        frappe.cache().delete_value("sms_relay_jwt_Test Phone")

    def test_issue_token_and_cache(self):
        token_payload = {
            "id": "jti-1",
            "access_token": "token-abc",
            "refresh_token": "refresh-xyz",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        with patch("sms_relay.gateway.client.requests.post") as mock_post:
            mock_post.return_value = _json_response(200, token_payload)

            client = GatewayClient(frappe.get_doc("SMS Device", "Test Phone"))
            token = client._get_access_token()
            self.assertEqual(token, "token-abc")
            cached = frappe.cache().get_value("sms_relay_jwt_Test Phone")
            self.assertEqual(cached[1], "token-abc")
            self.assertEqual(cached[2], "refresh-xyz")

    def test_jwt_fallback_to_basic_on_token_failure(self):
        def route(url, *args, **kwargs):
            if url.endswith("/auth/token"):
                return _json_response(401, {}, text="Unauthorized")
            return _json_response(202, {"id": "m1"})

        with patch("sms_relay.gateway.client.requests.post", side_effect=route) as mock_post:
            client = GatewayClient(frappe.get_doc("SMS Device", "Test Phone"))
            result = client.send_message(["+15551234567"], text="Hello")
            self.assertTrue(result["success"])
            self.assertEqual(result["message_id"], "m1")
            auth = mock_post.call_args.kwargs.get("auth")
            self.assertIsNotNone(auth)

    def test_send_message_payload(self):
        with patch("sms_relay.gateway.client.requests.post") as mock_post:
            mock_post.return_value = _json_response(202, {"id": "m-9"})
            client = GatewayClient(frappe.get_doc("SMS Device", "Test Phone"))
            result = client.send_message(
                ["+15551234567", "+15557654321"],
                text="Hi",
                message_id="m-9",
                sim_number=1,
                priority=100,
                schedule_at=frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=10),
                valid_until=frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=1),
            )
            self.assertTrue(result["success"])
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["phoneNumbers"], ["+15551234567", "+15557654321"])
            self.assertEqual(payload["simNumber"], 1)
            self.assertEqual(payload["priority"], 100)
            self.assertIn("scheduleAt", payload)
            self.assertIn("validUntil", payload)


class TestWebhookProvisioning(SMSRelayTestCase):
    def _device(self):
        return frappe.get_doc("SMS Device", "Test Phone")

    def test_provision_creates_missing_webhooks(self):
        with patch("sms_relay.gateway.client.requests.get") as mock_get, \
             patch("sms_relay.gateway.client.requests.post") as mock_post:
            mock_get.return_value = _json_response(200, [])
            mock_post.return_value = _json_response(201, {"id": "wh-1"})

            result = provision_webhooks(self._device())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["webhooks"]), len(GATEWAY_WEBHOOK_EVENTS))
            self.assertEqual(mock_post.call_count, len(GATEWAY_WEBHOOK_EVENTS))

            self._device().reload()
            registrations = json.loads(self._device().webhook_registrations)
            self.assertEqual(len(registrations), len(GATEWAY_WEBHOOK_EVENTS))

    def test_provision_is_idempotent(self):
        url = frappe.utils.get_url("/api/method/sms_relay.api.webhook_receiver.incoming_webhook")
        existing = [{"id": "wh-1", "event": "sms:received", "url": url}]
        with patch("sms_relay.gateway.client.requests.get") as mock_get, \
             patch("sms_relay.gateway.client.requests.post") as mock_post:
            mock_get.return_value = _json_response(200, existing)
            mock_post.return_value = _json_response(201, {"id": "wh-new"})

            result = provision_webhooks(self._device())
            self.assertEqual(len(result["webhooks"]), len(GATEWAY_WEBHOOK_EVENTS))
            self.assertEqual(mock_post.call_count, len(GATEWAY_WEBHOOK_EVENTS) - 1)

            mock_get.return_value = _json_response(200, existing + [
                {"id": "wh-new", "event": event, "url": url}
                for event in GATEWAY_WEBHOOK_EVENTS if event != "sms:received"
            ])
            mock_post.reset_mock()
            result = provision_webhooks(self._device())
            self.assertEqual(mock_post.call_count, 0)

    def test_reconcile_removes_stray_webhook(self):
        url = frappe.utils.get_url("/api/method/sms_relay.api.webhook_receiver.incoming_webhook")
        stray = {"id": "wh-stray", "event": "sms:received", "url": "http://old.example/cb"}
        with patch("sms_relay.gateway.client.requests.get") as mock_get, \
             patch("sms_relay.gateway.client.requests.post") as mock_post, \
             patch("sms_relay.gateway.client.requests.delete") as mock_delete:
            mock_get.return_value = _json_response(200, [stray])
            mock_post.return_value = _json_response(201, {"id": "wh-1"})
            mock_delete.return_value = _json_response(204, None)

            reconcile_webhooks(self._device())
            delete_url = mock_delete.call_args.args[0]
            self.assertTrue(delete_url.endswith("/webhooks/wh-stray"))


class TestInboxSync(SMSRelayTestCase):
    def _inbox_payload(self, messages):
        return _json_response(200, {"messages": messages})

    def test_sync_creates_queue_entry(self):
        msg = {"id": "in-1", "sender": "+15551234567", "recipient": "+19990000000",
               "contentPreview": "Hello back", "simNumber": 1}
        with patch("sms_relay.gateway.client.requests.get") as mock_get:
            mock_get.return_value = self._inbox_payload([msg])
            result = sync_device_inbox(frappe.get_doc("SMS Device", "Test Phone"))
            self.assertEqual(result["created"], 1)
            queue = frappe.db.exists("SMS Queue", {"inbox_message_id": "in-1"})
            self.assertTrue(queue)
            doc = frappe.get_doc("SMS Queue", queue)
            self.assertEqual(doc.status, "Received")
            self.assertEqual(doc.recipient, "+15551234567")
            self.assertEqual(doc.message, "Hello back")

    def test_sync_dedupes(self):
        msg = {"id": "in-2", "sender": "+15551234567", "contentPreview": "Again"}
        with patch("sms_relay.gateway.client.requests.get") as mock_get:
            mock_get.return_value = self._inbox_payload([msg])
            sync_device_inbox(frappe.get_doc("SMS Device", "Test Phone"))
            result = sync_device_inbox(frappe.get_doc("SMS Device", "Test Phone"))
            self.assertEqual(result["created"], 0)


class TestStatusSync(SMSRelayTestCase):
    def test_apply_status_updates_queue_and_log(self):
        queue = frappe.new_doc("SMS Queue")
        queue.recipient = "+15551234567"
        queue.message = "Status test"
        queue.status = "Sent"
        queue.gateway_message_id = "gw-1"
        queue.insert(ignore_permissions=True)

        log = frappe.new_doc("SMS Log")
        log.phone = "+15551234567"
        log.message = "Status test"
        log.status = "Sent"
        log.gateway_message_id = "gw-1"
        log.insert(ignore_permissions=True)
        frappe.db.commit()

        _apply_status(queue.name, "gw-1", "Delivered", "Delivered", {})
        frappe.db.commit()

        self.assertEqual(frappe.db.get_value("SMS Queue", queue.name, "delivery_status"), "Delivered")
        self.assertEqual(frappe.db.get_value("SMS Log", log.name, "delivery_status"), "Delivered")
        self.assertIsNotNone(frappe.db.get_value("SMS Log", log.name, "delivered_at"))

    def test_process_state_map_covers_gateway_states(self):
        for state in ["Pending", "Cancelling", "Cancelled", "Processed", "Sent", "Delivered", "Failed"]:
            self.assertIn(PROCESSING_STATE_MAP[state], ["Queued", "Sent", "Delivered", "Failed", "Cancelled"])

    def test_sync_delivery_status_disabled(self):
        frappe.db.set_value("SMS Gateway Settings", "SMS Gateway Settings", "status_sync_enabled", 0)
        frappe.db.commit()
        result = sync_delivery_status()
        self.assertEqual(result["status"], "disabled")
