# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.tests.common import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestJsonImportController(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

        # Create ir.exports + lines for res.partner
        cls.partner_exporter = cls.env["ir.exports"].create(
            {
                "name": "Test Controller Import",
                "resource": "res.partner",
            }
        )
        for field_name in ["name", "email"]:
            cls.env["ir.exports.line"].create(
                {
                    "export_id": cls.partner_exporter.id,
                    "name": field_name,
                }
            )

        # Create schema
        cls.partner_model = cls.env.ref("base.model_res_partner")
        cls.schema = cls.env["json.import.schema"].create(
            {
                "name": "Controller Test Import",
                "model_id": cls.partner_model.id,
                "exporter_id": cls.partner_exporter.id,
                "import_mode": "create_only",
                "duplicate_detect_mode": "none",
            }
        )

        # Endpoint with no auth
        cls.endpoint_no_auth = cls.env["json.import.endpoint"].create(
            {
                "name": "No Auth Import",
                "schema_id": cls.schema.id,
                "route_path": "import-test-noauth",
                "auth_type": "none",
            }
        )

        # Endpoint with API key auth
        cls.endpoint_api_key = cls.env["json.import.endpoint"].create(
            {
                "name": "API Key Import",
                "schema_id": cls.schema.id,
                "route_path": "import-test-apikey",
                "auth_type": "api_key",
                "api_key": "test-import-key-12345",
            }
        )

        # Endpoint with CORS
        cls.endpoint_cors = cls.env["json.import.endpoint"].create(
            {
                "name": "CORS Import",
                "schema_id": cls.schema.id,
                "route_path": "import-test-cors",
                "auth_type": "none",
                "cors_origin": "*",
            }
        )

        # Endpoint with validation disabled
        cls.endpoint_no_validate = cls.env["json.import.endpoint"].create(
            {
                "name": "No Validate Import",
                "schema_id": cls.schema.id,
                "route_path": "import-test-novalidate",
                "auth_type": "none",
                "validate_schema": False,
            }
        )

    def _post(self, path, data, headers=None):
        """Helper to perform a POST request with JSON body."""
        url = "/api/json_import/%s" % path
        all_headers = {"Content-Type": "application/json"}
        if headers:
            all_headers.update(headers)
        return self.url_open(
            url,
            data=json.dumps(data),
            headers=all_headers,
        )

    def _get(self, path, headers=None):
        """Helper to perform a GET request."""
        url = "/api/json_import/%s" % path
        return self.url_open(url, headers=headers or {})

    # -- No auth tests --

    def test_import_no_auth_success(self):
        """POST with auth_type=none succeeds."""
        data = {"records": [{"name": "API Partner", "email": "api@test.com"}]}
        response = self._post("import-test-noauth", data)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["created_count"], 1)

    # -- API key auth tests --

    def test_import_api_key_valid(self):
        """POST with correct X-API-Key header succeeds."""
        data = {"records": [{"name": "Key Partner", "email": "key@test.com"}]}
        response = self._post(
            "import-test-apikey",
            data,
            headers={"X-API-Key": "test-import-key-12345"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["success"])

    def test_import_api_key_invalid(self):
        """POST with wrong key returns 401."""
        data = {"records": [{"name": "Test"}]}
        response = self._post(
            "import-test-apikey",
            data,
            headers={"X-API-Key": "wrong-key"},
        )
        self.assertEqual(response.status_code, 401)

    def test_import_api_key_missing(self):
        """POST without key returns 401."""
        data = {"records": [{"name": "Test"}]}
        response = self._post("import-test-apikey", data)
        self.assertEqual(response.status_code, 401)

    # -- Invalid JSON body --

    def test_import_invalid_json_body(self):
        """Invalid JSON body returns 400."""
        url = "/api/json_import/import-test-noauth"
        response = self.url_open(
            url,
            data="not valid json{{{",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)

    # -- Schema validation tests --

    def test_import_validation_failure(self):
        """Schema validation failure returns 422."""
        # Missing required 'name' field
        data = {"records": [{"email": "no-name@test.com"}]}
        response = self._post("import-test-noauth", data)
        self.assertEqual(response.status_code, 422)
        result = response.json()
        self.assertFalse(result["success"])
        self.assertIn("details", result["error"])

    # -- Success response structure --

    def test_import_response_structure(self):
        """Response has success, data, errors, meta keys."""
        data = {"records": [{"name": "Structure Test", "email": "st@test.com"}]}
        response = self._post("import-test-noauth", data)
        result = response.json()
        self.assertIn("success", result)
        self.assertIn("data", result)
        self.assertIn("errors", result)
        self.assertIn("meta", result)
        meta = result["meta"]
        self.assertIn("schema", meta)
        self.assertIn("model", meta)
        self.assertIn("duration_ms", meta)
        data_result = result["data"]
        self.assertIn("created_count", data_result)
        self.assertIn("updated_count", data_result)
        self.assertIn("created_ids", data_result)
        self.assertIn("updated_ids", data_result)

    # -- Partial success --

    def test_import_partial_success(self):
        """Partial success returns 207 with errors array."""
        # First record is good, second has bad country_id
        # Add country_id to the exporter
        self.env["ir.exports.line"].create(
            {
                "export_id": self.partner_exporter.id,
                "name": "country_id/name",
            }
        )
        data = {
            "records": [
                {"name": "Good Partner", "email": "good@test.com"},
                {"name": "Bad Partner", "country_id": {"name": "FakeCountryXYZ"}},
            ]
        }
        response = self._post("import-test-novalidate", data)
        self.assertEqual(response.status_code, 207)
        result = response.json()
        self.assertFalse(result["success"])
        self.assertTrue(len(result["errors"]) > 0)

    # -- Schema endpoint --

    def test_import_schema_endpoint(self):
        """GET .../schema returns expected input JSON Schema."""
        response = self._get("import-test-noauth/schema")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("$schema", data)
        self.assertIn("properties", data)
        self.assertIn("records", data["properties"])

    # -- Log creation --

    def test_import_creates_log(self):
        """API call creates a log entry."""
        log_count_before = self.env["json.import.log"].search_count(
            [("schema_id", "=", self.schema.id), ("log_type", "=", "api")]
        )
        data = {"records": [{"name": "Log Test", "email": "log@test.com"}]}
        self._post("import-test-noauth", data)
        log_count_after = self.env["json.import.log"].search_count(
            [("schema_id", "=", self.schema.id), ("log_type", "=", "api")]
        )
        self.assertEqual(log_count_after, log_count_before + 1)

    # -- CORS headers --

    def test_import_cors_headers(self):
        """CORS headers present when cors_origin is set."""
        data = {"records": [{"name": "CORS Test", "email": "cors@test.com"}]}
        response = self._post("import-test-cors", data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")

    # -- 404 test --

    def test_import_not_found(self):
        """Non-existent path returns 404."""
        data = {"records": [{"name": "Test"}]}
        response = self._post("nonexistent-import-path", data)
        self.assertEqual(response.status_code, 404)
