import json
import subprocess
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from cc_switch_reader import Provider, find_node, read_snapshot
from cc_switch_quota import query_quota
from widget import UsageWidget, format_balance, format_ball_balance, format_compact_number


class ReaderTests(unittest.TestCase):
    def make_database(self) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        path = Path(handle.name)
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE providers (
              id TEXT, app_type TEXT, name TEXT, settings_config TEXT,
              meta TEXT, is_current INTEGER
            );
            CREATE TABLE proxy_request_logs (
              request_id TEXT, app_type TEXT, session_id TEXT,
              input_tokens INTEGER, output_tokens INTEGER,
              cache_read_tokens INTEGER, cache_creation_tokens INTEGER,
              total_cost_usd TEXT, created_at INTEGER
            );
            """
        )
        connection.execute(
            "INSERT INTO providers VALUES (?, ?, ?, ?, ?, 1)",
            ("codex-1", "codex", "测试 Codex", json.dumps({}), json.dumps({})),
        )
        connection.execute(
            "INSERT INTO providers VALUES (?, ?, ?, ?, ?, 1)",
            ("claude-1", "claude", "测试 Claude", json.dumps({}), json.dumps({})),
        )
        connection.executemany(
            "INSERT INTO proxy_request_logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("old", "codex", "old-session", 1, 2, 3, 4, "0.10", 1000),
                ("new-1", "claude", "new-session", 100, 20, 30, 4, "0.25", 2000),
                ("new-2", "claude", "new-session", 50, 10, 5, 1, "0.125", 3000),
                ("no-session", "claude", None, 999, 999, 999, 999, "99", 4000),
            ],
        )
        connection.commit()
        connection.close()
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_reads_current_providers_and_latest_session(self) -> None:
        snapshot = read_snapshot(self.make_database())
        self.assertIsNone(snapshot.error)
        self.assertEqual(snapshot.providers["codex"].name, "测试 Codex")
        self.assertEqual(snapshot.latest_session.app_type, "claude")
        self.assertEqual(snapshot.latest_session.session_id, "new-session")
        self.assertEqual(snapshot.latest_session.input_tokens, 150)
        self.assertEqual(snapshot.latest_session.output_tokens, 30)
        self.assertEqual(snapshot.latest_session.cache_read_tokens, 35)
        self.assertEqual(snapshot.latest_session.cache_creation_tokens, 5)
        self.assertEqual(str(snapshot.latest_session.total_cost_usd), "0.375")

    def test_missing_session_is_supported(self) -> None:
        path = self.make_database()
        connection = sqlite3.connect(path)
        connection.execute("DELETE FROM proxy_request_logs")
        connection.commit()
        connection.close()
        snapshot = read_snapshot(path)
        self.assertIsNone(snapshot.latest_session)

    def test_unconfigured_quota_is_explicit(self) -> None:
        snapshot = read_snapshot(self.make_database())
        result = query_quota(snapshot.providers["codex"], node_path="missing-node")
        self.assertEqual(result.status, "unconfigured")
        self.assertEqual(result.message, "余额查询未配置")

    def test_display_formatting_stays_compact(self) -> None:
        self.assertEqual(format_compact_number(863406), "863K")
        self.assertEqual(format_compact_number(21708), "21.7K")
        self.assertEqual(format_balance(4.99946724, "USD"), "USD 5.00")
        self.assertEqual(format_ball_balance(query_quota(Provider("codex", "id", "name", {}, {}), node_path="missing-node")), ("--", "余额"))

    def test_resize_edges_and_minimums_are_deterministic(self) -> None:
        widget = UsageWidget.__new__(UsageWidget)

        class Root:
            def winfo_width(self) -> int:
                return 320

            def winfo_height(self) -> int:
                return 190

        widget.root = Root()
        self.assertEqual(widget._resize_edges_for(1, 1), ("left", "top"))
        self.assertEqual(widget._resize_edges_for(319, 189), ("right", "bottom"))
        self.assertEqual(widget._resize_edges_for(160, 95), ())

    def test_quota_timeout_and_script_error_are_reported(self) -> None:
        provider = Provider(
            app_type="codex", provider_id="test", name="Test",
            settings_config={},
            meta={"usage_script": {"enabled": True, "language": "javascript", "code": "({request:{url:'https://example.invalid'}})"}},
        )
        with patch("cc_switch_quota.subprocess.run", side_effect=subprocess.TimeoutExpired("node", 1)):
            result = query_quota(provider, node_path="node")
        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "余额查询超时")

        completed = subprocess.CompletedProcess("node", 1, stdout=json.dumps({"ok": False, "error": "余额接口返回 HTTP 500"}), stderr="")
        with patch("cc_switch_quota.subprocess.run", return_value=completed):
            result = query_quota(provider, node_path="node")
        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "余额接口返回 HTTP 500")

    def test_javascript_quota_script(self) -> None:
        node = find_node()
        if not node:
            self.skipTest("Node.js is not installed")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.headers.get("Authorization") != "Bearer test-secret":
                    self.send_response(401)
                    self.end_headers()
                    return
                payload = json.dumps({"remaining": 12.5, "unit": "USD"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        provider = Provider(
            app_type="claude",
            provider_id="test",
            name="Test",
            settings_config={
                "env": {
                    "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "ANTHROPIC_AUTH_TOKEN": "test-secret",
                }
            },
            meta={
                "usage_script": {
                    "enabled": True,
                    "language": "javascript",
                    "timeout": 5,
                    "code": """({
                      request: { url: "{{baseUrl}}/usage", headers: { Authorization: "Bearer {{apiKey}}" } },
                      extractor: response => ({ remaining: response.remaining, unit: response.unit, isValid: true })
                    })""",
                }
            },
        )
        result = query_quota(provider, node_path=node)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.remaining, 12.5)
        self.assertEqual(result.unit, "USD")


if __name__ == "__main__":
    unittest.main()
