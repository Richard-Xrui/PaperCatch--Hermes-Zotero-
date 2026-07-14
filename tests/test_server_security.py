"""Security and request-boundary regression tests for PaperCatch."""

import http.client
import json
import sys
import unittest
from unittest.mock import Mock, patch

from tests.server_harness import IsolatedServerTestCase, zotero_server


class ServerSecurityTests(IsolatedServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.secret_path = self.root / "config.local.json"
        self.secret_marker = "TEST-SECRET-MUST-NOT-LEAK"
        self.secret_path.write_text(self.secret_marker, encoding="utf-8")

    def assert_json_error(self, status, headers, body, expected_status, expected_code):
        self.assertEqual(expected_status, status)
        self.assertTrue(headers["content-type"].startswith("application/json"))
        payload = json.loads(body.decode("utf-8"))
        self.assertFalse(payload["success"])
        self.assertIsInstance(payload["error"], dict)
        self.assertEqual(expected_code, payload["error"]["code"])

    def request_or_fail(self, method, path, body=None, headers=None):
        try:
            return self.request(method, path, body=body, headers=headers)
        except http.client.RemoteDisconnected as exc:
            self.fail(f"server disconnected instead of returning an HTTP response: {exc}")

    def test_plain_path_traversal_cannot_read_outside_viewer(self):
        status, _, body = self.request("GET", "/../config.local.json")

        self.assertEqual(404, status)
        self.assertNotIn(self.secret_marker, body.decode("utf-8", errors="replace"))

    def test_encoded_path_traversal_cannot_read_outside_viewer(self):
        status, _, body = self.request("GET", "/%2e%2e/config.local.json")

        self.assertEqual(404, status)
        self.assertNotIn(self.secret_marker, body.decode("utf-8", errors="replace"))

    def test_encoded_backslash_traversal_cannot_read_outside_viewer(self):
        status, _, body = self.request("GET", "/..%5cconfig.local.json")

        self.assertEqual(404, status)
        self.assertNotIn(self.secret_marker, body.decode("utf-8", errors="replace"))

    def test_missing_static_file_returns_404(self):
        status, _, body = self.request("GET", "/missing.js")

        self.assertEqual(404, status)
        self.assertNotIn("PaperCatch Test", body.decode("utf-8", errors="replace"))

    def test_null_byte_static_path_returns_404(self):
        response = self.request_or_fail("GET", "/%00")

        self.assertEqual(404, response[0])

    def test_unknown_get_api_returns_json_404(self):
        response = self.request("GET", "/api/config/status")

        self.assert_json_error(*response, 404, "not_found")

    def test_get_rejects_non_local_host(self):
        status, headers, body = self.request(
            "GET",
            "/api/papers",
            headers={"Host": "attacker.example:8765"},
        )

        self.assert_json_error(status, headers, body, 403, "invalid_host")
        self.assertNotIn("Paper A", body.decode("utf-8"))

    def test_unknown_post_api_returns_json_404(self):
        response = self.request("POST", "/api/not-real", {})

        self.assert_json_error(*response, 404, "not_found")

    def test_unknown_delete_api_returns_json_404(self):
        response = self.request("DELETE", "/api/not-real", {})

        self.assert_json_error(*response, 404, "not_found")

    def test_invalid_config_json_returns_400_without_overwrite(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()

        response = self.request(
            "POST",
            "/api/config",
            b'{"days":',
            {"Content-Type": "application/json"},
        )

        self.assert_json_error(*response, 400, "invalid_json")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_invalid_utf8_json_returns_400_without_overwrite(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()

        response = self.request(
            "POST",
            "/api/config",
            b"\xff",
            {"Content-Type": "application/json"},
        )

        self.assert_json_error(*response, 400, "invalid_json")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_invalid_content_length_returns_400_without_overwrite(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()

        response = self.request(
            "POST",
            "/api/config",
            b"{}",
            {"Content-Type": "application/json", "Content-Length": "invalid"},
        )

        self.assert_json_error(*response, 400, "invalid_json")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_empty_config_body_returns_400_without_overwrite(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()

        response = self.request(
            "POST", "/api/config", b"", {"Content-Type": "application/json"}
        )

        self.assert_json_error(*response, 400, "invalid_json")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_config_body_must_be_an_object(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()

        response = self.request("POST", "/api/config", ["not", "an", "object"])

        self.assert_json_error(*response, 400, "invalid_request")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_object_routes_reject_array_bodies(self):
        for path in ("/hermes/search", "/hermes/ask", "/hermes/notes", "/api/enrich", "/zotero/add", "/api/integrations"):
            with self.subTest(path=path):
                response = self.request_or_fail("POST", path, [])

                self.assert_json_error(*response, 400, "invalid_request")

    def test_delete_route_rejects_array_body(self):
        response = self.request_or_fail("DELETE", "/api/papers", [])

        self.assert_json_error(*response, 400, "invalid_request")

    def test_hermes_message_must_be_a_string(self):
        response = self.request_or_fail("POST", "/hermes/search", {"message": 7})

        self.assert_json_error(*response, 400, "invalid_request")

    def test_hermes_sources_must_be_supported_non_empty_strings(self):
        cases = [
            {"message": "agent", "sources": []},
            {"message": "agent", "sources": ["bad-source"]},
            {"message": "agent", "sources": [7]},
            {"message": "agent", "sources": ["   "]},
        ]
        for body in cases:
            with self.subTest(body=body), patch.object(
                zotero_server, "arxiv_search"
            ) as arxiv_search_mock, patch.object(
                zotero_server, "search_all_sources"
            ) as multi_source_mock:
                response = self.request_or_fail("POST", "/hermes/search", body)

                self.assert_json_error(*response, 400, "invalid_request")
                arxiv_search_mock.assert_not_called()
                multi_source_mock.assert_not_called()

    def test_enrich_items_must_be_objects(self):
        response = self.request_or_fail("POST", "/api/enrich", {"items": [1]})

        self.assert_json_error(*response, 400, "invalid_request")

    def test_delete_ids_must_be_strings(self):
        response = self.request_or_fail(
            "DELETE", "/api/papers", {"arxiv_ids": [{"bad": "id"}]}
        )

        self.assert_json_error(*response, 400, "invalid_request")

    def test_mutation_requires_json_content_type(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()

        response = self.request_or_fail(
            "POST",
            "/api/config",
            self.initial_config,
            {
                "Content-Type": "text/plain",
                "Origin": "https://attacker.example",
                "Host": f"127.0.0.1:{self.port}",
            },
        )

        self.assert_json_error(*response, 415, "unsupported_media_type")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_mutation_rejects_non_local_host(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()

        response = self.request_or_fail(
            "POST",
            "/api/config",
            self.initial_config,
            {"Content-Type": "application/json", "Host": "attacker.example:8765"},
        )

        self.assert_json_error(*response, 403, "invalid_host")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_mutation_rejects_non_local_origin(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()

        response = self.request_or_fail(
            "POST",
            "/api/config",
            self.initial_config,
            {
                "Content-Type": "application/json",
                "Origin": "https://attacker.example",
            },
        )

        self.assert_json_error(*response, 403, "invalid_origin")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_zotero_collections_not_configured_has_structured_error(self):
        response = self.request("GET", "/zotero/collections")

        self.assert_json_error(*response, 200, "not_configured")

    def test_zotero_collections_failure_has_structured_error(self):
        with patch.object(zotero_server, "ZOTERO_API_KEY", "test-key"), patch.object(
            zotero_server, "ZOTERO_USER_ID", "test-user"
        ), patch.object(
            zotero_server,
            "list_zotero_collections",
            side_effect=RuntimeError("mock collection failure"),
        ):
            response = self.request("GET", "/zotero/collections")

        self.assert_json_error(*response, 502, "upstream_error")

    def test_arxiv_failure_has_structured_error(self):
        with patch.object(zotero_server, "llm_parse_query", return_value=None), patch.object(
            zotero_server,
            "arxiv_search",
            side_effect=RuntimeError("mock arxiv failure"),
        ):
            response = self.request(
                "POST", "/hermes/search", {"message": "recent agent papers"}
            )

        self.assert_json_error(*response, 502, "upstream_error")

    def test_zotero_add_failure_has_structured_error(self):
        with patch.object(zotero_server, "ZOTERO_API_KEY", "test-key"), patch.object(
            zotero_server, "ZOTERO_USER_ID", "test-user"
        ), patch.object(
            zotero_server.Handler,
            "_zotero_add_ids",
            side_effect=RuntimeError("mock zotero failure"),
        ):
            response = self.request(
                "POST", "/zotero/add", {"arxiv_ids": ["2401.00001"]}
            )

        self.assert_json_error(*response, 502, "upstream_error")

    def test_config_rejects_unknown_fields_without_overwrite(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()
        invalid = {**self.initial_config, "unexpected": True}

        response = self.request("POST", "/api/config", invalid)

        self.assert_json_error(*response, 400, "invalid_request")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_config_rejects_invalid_categories_without_overwrite(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()
        invalid = {**self.initial_config, "categories": ["cs.AI", "not a category"]}

        response = self.request("POST", "/api/config", invalid)

        self.assert_json_error(*response, 400, "invalid_request")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_config_rejects_invalid_keywords_without_overwrite(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()
        invalid = {**self.initial_config, "keywords": ["agent"]}

        response = self.request("POST", "/api/config", invalid)

        self.assert_json_error(*response, 400, "invalid_request")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_config_rejects_invalid_sources_without_overwrite(self):
        config_before = self.config_path.read_bytes()
        viewer_config_before = self.viewer_config_path.read_bytes()
        invalid = {**self.initial_config, "sources": ["arxiv", "random_web_scraper"]}

        response = self.request("POST", "/api/config", invalid)

        self.assert_json_error(*response, 400, "invalid_request")
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(viewer_config_before, self.viewer_config_path.read_bytes())

    def test_config_rejects_out_of_range_numbers_without_overwrite(self):
        for field, value in (("max_per_cat", 0), ("max_per_cat", 101), ("days", -1), ("days", 31)):
            with self.subTest(field=field, value=value):
                self.write_json(self.config_path, self.initial_config)
                self.write_json(self.viewer_config_path, self.initial_config)
                invalid = {**self.initial_config, field: value}

                response = self.request("POST", "/api/config", invalid)

                self.assert_json_error(*response, 400, "invalid_request")
                self.assertEqual(self.initial_config, self.read_json(self.config_path))
                self.assertEqual(self.initial_config, self.read_json(self.viewer_config_path))

    def test_categories_config_rejects_invalid_items_without_overwrite(self):
        categories_before = self.cats_path.read_bytes()
        invalid = [{"id": "", "label": 7, "keywords": []}]

        response = self.request("POST", "/api/categories", invalid)

        self.assert_json_error(*response, 400, "invalid_request")
        self.assertEqual(categories_before, self.cats_path.read_bytes())

    def test_json_response_has_no_wildcard_cors(self):
        status, headers, _ = self.request(
            "GET", "/health", headers={"Origin": "https://example.invalid"}
        )

        self.assertEqual(200, status)
        self.assertNotIn("access-control-allow-origin", headers)

    def test_options_has_no_wildcard_cors(self):
        status, headers, _ = self.request(
            "OPTIONS", "/api/config", headers={"Origin": "https://example.invalid"}
        )

        self.assertEqual(204, status)
        self.assertNotIn("access-control-allow-origin", headers)


class DefaultBindingTests(unittest.TestCase):
    def test_main_binds_loopback_by_default(self):
        fake_server = Mock()
        fake_server.serve_forever.side_effect = KeyboardInterrupt

        with patch.object(
            zotero_server, "ThreadingHTTPServer", return_value=fake_server
        ) as server_class, patch.object(
            sys, "argv", ["zotero_server.py", "--port", "0"]
        ):
            zotero_server.main()

        address = server_class.call_args.args[0]
        self.assertEqual("127.0.0.1", address[0])


if __name__ == "__main__":
    unittest.main()
