# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json

from odoo.exceptions import UserError

from .common import JsonImportTestCase


class TestJsonImportFileWizard(JsonImportTestCase):
    def _create_wizard(self, json_data, validate=True):
        """Helper: create wizard with base64-encoded JSON file."""
        content = json.dumps(json_data)
        file_data = base64.b64encode(content.encode("utf-8"))
        return self.env["json.import.file.wizard"].create(
            {
                "schema_id": self.schema.id,
                "file_data": file_data,
                "file_name": "test_import.json",
                "validate_before_import": validate,
            }
        )

    def test_wizard_standard_envelope(self):
        """Standard envelope {"records": [...]} works."""
        wizard = self._create_wizard(
            {"records": [{"name": "Wizard Test", "email": "wizard@test.com"}]}
        )
        result = wizard.action_import()
        self.assertEqual(wizard.state, "done")
        self.assertEqual(wizard.result_created, 1)
        self.assertEqual(result["type"], "ir.actions.act_window")

    def test_wizard_plain_array(self):
        """Plain array [...] auto-wrapped to envelope."""
        wizard = self._create_wizard(
            [{"name": "Array Test", "email": "array@test.com"}]
        )
        result = wizard.action_import()
        self.assertEqual(wizard.state, "done")
        self.assertEqual(wizard.result_created, 1)

    def test_wizard_single_object(self):
        """Single object {...} auto-wrapped to envelope."""
        wizard = self._create_wizard(
            {"name": "Single Test", "email": "single@test.com"}
        )
        result = wizard.action_import()
        self.assertEqual(wizard.state, "done")
        self.assertEqual(wizard.result_created, 1)

    def test_wizard_invalid_json(self):
        """Invalid JSON raises UserError."""
        file_data = base64.b64encode(b"not valid json{{{")
        wizard = self.env["json.import.file.wizard"].create(
            {
                "schema_id": self.schema.id,
                "file_data": file_data,
                "file_name": "bad.json",
            }
        )
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_wizard_validation_error(self):
        """Validation errors raise UserError when validate_before_import is True."""
        # Missing required field 'name'
        wizard = self._create_wizard(
            {"records": [{"email": "noname@test.com"}]}, validate=True
        )
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_wizard_results_displayed(self):
        """Results are properly set after import."""
        wizard = self._create_wizard(
            {
                "records": [
                    {"name": "Result Test 1", "email": "r1@test.com"},
                    {"name": "Result Test 2", "email": "r2@test.com"},
                ]
            }
        )
        wizard.action_import()
        self.assertEqual(wizard.state, "done")
        self.assertEqual(wizard.result_created, 2)
        self.assertEqual(wizard.result_updated, 0)
        self.assertEqual(wizard.result_failed, 0)
        self.assertTrue(wizard.result_summary)

    def test_wizard_no_file(self):
        """No file data raises UserError."""
        wizard = self.env["json.import.file.wizard"].create(
            {
                "schema_id": self.schema.id,
                "file_data": False,
                "file_name": "empty.json",
            }
        )
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_wizard_creates_log(self):
        """Wizard import creates a log entry with type 'wizard'."""
        log_count_before = self.env["json.import.log"].search_count(
            [("schema_id", "=", self.schema.id), ("log_type", "=", "wizard")]
        )
        wizard = self._create_wizard(
            {"records": [{"name": "Log Wizard Test", "email": "logw@test.com"}]}
        )
        wizard.action_import()
        log_count_after = self.env["json.import.log"].search_count(
            [("schema_id", "=", self.schema.id), ("log_type", "=", "wizard")]
        )
        self.assertEqual(log_count_after, log_count_before + 1)
