# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import hmac
import json

from odoo import http
from odoo.http import Response, request


class JsonImportController(http.Controller):
    @http.route(
        "/api/json_import/<path:path>",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    def import_data(self, path, **kwargs):
        """Receive and import JSON data via POST."""
        endpoint = self._find_endpoint(path)
        if not endpoint:
            return self._error_response(404, "Endpoint not found")

        if request.httprequest.method == "OPTIONS":
            return self._cors_preflight(endpoint)

        # Authenticate
        auth_error = self._check_auth(endpoint)
        if auth_error:
            return auth_error

        # Parse JSON body
        try:
            raw_data = request.httprequest.get_data(as_text=True)
            json_data = json.loads(raw_data)
        except (ValueError, TypeError) as e:
            return self._error_response(400, "Invalid JSON body: %s" % str(e))

        # Auto-normalize input format
        json_data = self._normalize_input(json_data)

        schema = endpoint.schema_id

        # Validate against schema if enabled
        if endpoint.validate_schema:
            errors = schema.sudo().action_validate_json(json_data)
            if errors:
                return self._json_response(
                    {
                        "success": False,
                        "error": {
                            "code": 422,
                            "message": "Validation failed",
                            "details": errors,
                        },
                    },
                    endpoint,
                    status=422,
                )

        # Import
        try:
            result = schema.sudo().action_import_records(
                json_data, log_type="api"
            )
        except Exception as e:
            return self._error_response(500, "Import failed: %s" % str(e))

        response_data = {
            "success": result["failed_count"] == 0,
            "data": {
                "created_count": result["created_count"],
                "updated_count": result["updated_count"],
                "skipped_count": result["skipped_count"],
                "failed_count": result["failed_count"],
                "created_ids": result["created_ids"],
                "updated_ids": result["updated_ids"],
            },
            "errors": result.get("errors", []),
            "meta": {
                "schema": schema.name,
                "model": schema.model_name,
                "duration_ms": result.get("duration_ms", 0),
            },
        }

        if result["failed_count"] > 0 and (
            result["created_count"] > 0 or result["updated_count"] > 0
        ):
            status = 207
        elif result["failed_count"] > 0:
            status = 207
        else:
            status = 200

        return self._json_response(response_data, endpoint, status=status)

    @http.route(
        "/api/json_import/<path:path>/schema",
        type="http",
        auth="public",
        methods=["GET", "OPTIONS"],
        csrf=False,
    )
    def import_schema(self, path, **kwargs):
        """Serve the expected input JSON Schema for an endpoint."""
        endpoint = self._find_endpoint(path)
        if not endpoint:
            return self._error_response(404, "Endpoint not found")

        if request.httprequest.method == "OPTIONS":
            return self._cors_preflight(endpoint)

        auth_error = self._check_auth(endpoint)
        if auth_error:
            return auth_error

        schema = endpoint.schema_id
        try:
            record_schema = schema.sudo()._generate_record_schema()
            import_schema = schema.sudo()._wrap_import_schema(record_schema)
            return self._json_response(import_schema, endpoint)
        except Exception:
            return self._error_response(500, "Failed to generate schema")

    def _find_endpoint(self, path):
        """Lookup active endpoint by route path."""
        path = path.strip("/")
        return (
            request.env["json.import.endpoint"]
            .sudo()
            .search(
                [
                    ("active", "=", True),
                    ("route_path", "=", path),
                    ("schema_id.active", "=", True),
                ],
                limit=1,
            )
        )

    def _check_auth(self, endpoint):
        """Validate authentication. Returns error response or None."""
        if endpoint.auth_type == "none":
            return None

        if endpoint.auth_type == "api_key":
            api_key = request.httprequest.headers.get("X-API-Key")
            if (
                not api_key
                or not endpoint.api_key
                or not hmac.compare_digest(api_key, endpoint.api_key)
            ):
                return self._error_response(401, "Invalid or missing API key")
            return None

        if endpoint.auth_type == "user":
            if request.env.user._is_public():
                return self._error_response(
                    401, "Authentication required. Please log in."
                )
            return None

        return self._error_response(403, "Unknown authentication type")

    def _normalize_input(self, json_data):
        """Auto-normalize input format to standard envelope.

        - Plain array [...] -> {"records": [...]}
        - Single object {...} without "records" key -> {"records": [{...}]}
        - Standard envelope {"records": [...]} -> pass through
        """
        if isinstance(json_data, list):
            return {"records": json_data}
        if isinstance(json_data, dict) and "records" not in json_data:
            return {"records": [json_data]}
        return json_data

    def _json_response(self, data, endpoint=None, status=200):
        """Build a JSON HTTP response with optional CORS headers."""
        body = json.dumps(data, ensure_ascii=False)
        headers = {"Content-Type": "application/json"}
        if endpoint and endpoint.cors_origin:
            headers.update(self._cors_headers(endpoint))
        return Response(body, status=status, headers=headers)

    def _error_response(self, code, message):
        """Build a JSON error response."""
        body = json.dumps(
            {"success": False, "error": {"code": code, "message": message}},
            ensure_ascii=False,
        )
        return Response(body, status=code, headers={"Content-Type": "application/json"})

    def _cors_preflight(self, endpoint):
        """Handle CORS OPTIONS preflight request."""
        headers = self._cors_headers(endpoint)
        headers["Access-Control-Max-Age"] = "86400"
        return Response("", status=204, headers=headers)

    def _cors_headers(self, endpoint):
        """Build CORS headers dict."""
        origin = endpoint.cors_origin or ""
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
        }
