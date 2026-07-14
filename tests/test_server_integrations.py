"""Isolated tests for the local integrations configuration API."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from .server_harness import IsolatedServerTestCase, zotero_server


ZOTERO_ENV = {
    "ZOTERO_API_KEY": "",
    "ZOTERO_USER_ID": "",
    "ZOTERO_DEFAULT_COLLECTION": "",
}


class ServerIntegrationsTests(IsolatedServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.local_config_path = self.root / "config.local.json"

    def test_get_returns_only_redacted_zotero_status(self):
        with patch.object(zotero_server, "ZOTERO_API_KEY", "never-return-this"), patch.object(
            zotero_server, "ZOTERO_USER_ID", "24680"
        ), patch.object(
            zotero_server, "DEFAULT_COLLECTION", "PaperCatch/Configured"
        ):
            status, _, payload = self.request_json("GET", "/api/integrations")

        self.assertEqual(200, status)
        self.assertEqual(
            {
                "zotero": {
                    "configured": True,
                    "user_id": "24680",
                    "default_collection": "PaperCatch/Configured",
                }
            },
            payload,
        )
        self.assertNotIn("api_key", json.dumps(payload))
        self.assertNotIn("never-return-this", json.dumps(payload))

    def test_post_atomically_saves_and_updates_runtime_state(self):
        self.write_json(
            self.local_config_path,
            {
                "zotero": {
                    "api_key": "old-key",
                    "user_id": "100",
                    "default_collection": "Old Collection",
                    "local_data_dir": "D:/Zotero",
                },
                "hermes": {"command": "hermes-command"},
            },
        )
        body = {
            "zotero": {
                "api_key": "new-api-key_123",
                "user_id": "24680",
                "default_collection": "PaperCatch/Research",
            }
        }

        with patch.dict(os.environ, ZOTERO_ENV):
            status, _, payload = self.request_json(
                "POST", "/api/integrations", body
            )

        self.assertEqual(200, status)
        self.assertEqual(
            {
                "success": True,
                "zotero": {
                    "configured": True,
                    "user_id": "24680",
                    "default_collection": "PaperCatch/Research",
                },
            },
            payload,
        )
        saved = self.read_json(self.local_config_path)
        self.assertEqual("new-api-key_123", saved["zotero"]["api_key"])
        self.assertEqual("24680", saved["zotero"]["user_id"])
        self.assertEqual(
            "PaperCatch/Research", saved["zotero"]["default_collection"]
        )
        self.assertEqual("D:/Zotero", saved["zotero"]["local_data_dir"])
        self.assertEqual("hermes-command", saved["hermes"]["command"])
        self.assertEqual("new-api-key_123", zotero_server.ZOTERO_API_KEY)
        self.assertEqual("24680", zotero_server.ZOTERO_USER_ID)
        self.assertEqual(
            "https://api.zotero.org/users/24680", zotero_server.ZOTERO_API_ROOT
        )
        self.assertEqual("PaperCatch/Research", zotero_server.DEFAULT_COLLECTION)
        self.assertEqual("24680", zotero_server.APP_CONFIG["zotero"]["user_id"])
        self.assertNotIn("api_key", json.dumps(payload))

    def test_empty_api_key_preserves_existing_secret(self):
        self.write_json(
            self.local_config_path,
            {
                "zotero": {
                    "api_key": "existing-secret",
                    "user_id": "100",
                    "default_collection": "Old Collection",
                }
            },
        )

        with patch.dict(os.environ, ZOTERO_ENV):
            status, _, payload = self.request_json(
                "POST",
                "/api/integrations",
                {
                    "zotero": {
                        "api_key": "",
                        "user_id": "200",
                        "default_collection": "New Collection",
                    }
                },
            )

        self.assertEqual(200, status)
        self.assertTrue(payload["zotero"]["configured"])
        self.assertEqual(
            "existing-secret",
            self.read_json(self.local_config_path)["zotero"]["api_key"],
        )
        self.assertEqual("existing-secret", zotero_server.ZOTERO_API_KEY)
        self.assertNotIn("existing-secret", json.dumps(payload))

    def test_environment_values_remain_runtime_precedence_after_save(self):
        self.write_json(
            self.local_config_path,
            {
                "zotero": {
                    "api_key": "old-file-key",
                    "user_id": "100",
                    "default_collection": "Old File Collection",
                }
            },
        )
        environment = {
            "ZOTERO_API_KEY": "environment-key",
            "ZOTERO_USER_ID": "98765",
            "ZOTERO_DEFAULT_COLLECTION": "Environment Collection",
        }

        with patch.dict(os.environ, environment):
            status, _, payload = self.request_json(
                "POST",
                "/api/integrations",
                {
                    "zotero": {
                        "api_key": "new-file-key",
                        "user_id": "24680",
                        "default_collection": "New File Collection",
                    }
                },
            )

        self.assertEqual(200, status)
        self.assertEqual("98765", payload["zotero"]["user_id"])
        self.assertEqual(
            "Environment Collection", payload["zotero"]["default_collection"]
        )
        saved = self.read_json(self.local_config_path)["zotero"]
        self.assertEqual("new-file-key", saved["api_key"])
        self.assertEqual("24680", saved["user_id"])
        self.assertEqual("New File Collection", saved["default_collection"])
        self.assertEqual("environment-key", zotero_server.ZOTERO_API_KEY)
        self.assertEqual("98765", zotero_server.ZOTERO_USER_ID)
        self.assertEqual("Environment Collection", zotero_server.DEFAULT_COLLECTION)

    def test_invalid_schema_does_not_create_or_change_config(self):
        initial = {
            "zotero": {
                "api_key": "existing-secret",
                "user_id": "100",
                "default_collection": "Original Collection",
            },
            "hermes": {"command": "keep-me"},
        }
        self.write_json(self.local_config_path, initial)
        original_bytes = self.local_config_path.read_bytes()
        invalid_bodies = [
            {},
            {"unexpected": {}},
            {"zotero": []},
            {
                "zotero": {
                    "api_key": "key",
                    "user_id": "100",
                    "default_collection": "Collection",
                    "unexpected": True,
                }
            },
            {
                "zotero": {
                    "api_key": 123,
                    "user_id": "100",
                    "default_collection": "Collection",
                }
            },
            {
                "zotero": {
                    "api_key": "invalid key with spaces",
                    "user_id": "100",
                    "default_collection": "Collection",
                }
            },
            {
                "zotero": {
                    "api_key": "",
                    "user_id": "not-numeric",
                    "default_collection": "Collection",
                }
            },
            {
                "zotero": {
                    "api_key": "",
                    "user_id": "100",
                    "default_collection": "",
                }
            },
            {
                "zotero": {
                    "api_key": "",
                    "user_id": "100",
                }
            },
        ]

        for body in invalid_bodies:
            with self.subTest(body=body):
                status, _, payload = self.request_json(
                    "POST", "/api/integrations", body
                )
                self.assertEqual(400, status)
                self.assertEqual("invalid_request", payload["error"]["code"])
                self.assertEqual(original_bytes, self.local_config_path.read_bytes())


if __name__ == "__main__":
    import unittest

    unittest.main()
