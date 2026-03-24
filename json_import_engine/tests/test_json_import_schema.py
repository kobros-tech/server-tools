# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.exceptions import UserError, ValidationError

from .common import JsonImportTestCase


class TestJsonImportSchema(JsonImportTestCase):
    # -- Parser tests --

    def test_get_parser(self):
        """Parser resolves from ir.exports."""
        parser = self.schema._get_parser()
        self.assertIsInstance(parser, list)
        self.assertIn("name", parser)
        self.assertIn("email", parser)
        self.assertIn("phone", parser)
        # Relational field should be a tuple
        relational = [item for item in parser if isinstance(item, tuple)]
        self.assertTrue(relational, "Should have at least one relational field")
        country_tuple = relational[0]
        self.assertEqual(country_tuple[0], "country_id")
        self.assertIn("name", country_tuple[1])
        self.assertIn("code", country_tuple[1])

    def test_get_parser_no_exporter(self):
        """Raises UserError when no exporter is set."""
        schema_no_exp = self.env["json.import.schema"].create(
            {
                "name": "No Exporter",
                "model_id": self.partner_model.id,
                "import_mode": "upsert",
                "duplicate_detect_mode": "none",
            }
        )
        with self.assertRaises(UserError):
            schema_no_exp._get_parser()

    # -- JSON Schema generation tests --

    def test_compute_json_schema(self):
        """Computed json_schema shows the import envelope."""
        self.assertTrue(self.schema.json_schema)
        parsed = json.loads(self.schema.json_schema)
        self.assertIn("$schema", parsed)
        props = parsed["properties"]
        self.assertIn("records", props)
        self.assertEqual(props["records"]["type"], "array")
        # Record schema nested under records.items
        self.assertIn("properties", props["records"]["items"])

    def test_generate_record_schema(self):
        """Record schema has correct draft-07 structure."""
        record_schema = self.schema._generate_record_schema()
        self.assertEqual(
            record_schema["$schema"], "http://json-schema.org/draft-07/schema#"
        )
        self.assertEqual(record_schema["type"], "object")
        self.assertIn("properties", record_schema)
        self.assertIn("name", record_schema["properties"])

    def test_json_schema_relational_many2one(self):
        """Many2one with sub-fields -> anyOf[object, null]."""
        record_schema = self.schema._generate_record_schema()
        props = record_schema["properties"]
        country_prop = props.get("country_id", {})
        self.assertIn("anyOf", country_prop)
        types = [t.get("type") for t in country_prop["anyOf"]]
        self.assertIn("object", types)
        self.assertIn("null", types)

    # -- Import tests: create_only mode --

    def test_import_create_only(self):
        """create_only mode creates new records."""
        self.schema.import_mode = "create_only"
        self.schema.duplicate_detect_mode = "none"
        json_data = {
            "records": [
                {"name": "New Partner 1", "email": "new1@example.com"},
                {"name": "New Partner 2", "email": "new2@example.com"},
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(len(result["created_ids"]), 2)

    def test_import_create_only_skips_existing(self):
        """create_only mode skips existing records when duplicate detection is on."""
        self.schema.import_mode = "create_only"
        self.schema.duplicate_detect_mode = "field"
        email_field = self.env["ir.model.fields"].search(
            [("model_id", "=", self.partner_model.id), ("name", "=", "email")],
            limit=1,
        )
        self.schema.duplicate_field_id = email_field
        json_data = {
            "records": [
                {"name": "Existing Partner", "email": "existing@example.com"},
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["skipped_count"], 1)

    # -- Import tests: update_only mode --

    def test_import_update_only(self):
        """update_only mode updates existing records."""
        self.schema.import_mode = "update_only"
        self.schema.duplicate_detect_mode = "record_id"
        json_data = {
            "records": [
                {
                    "id": self.existing_partner.id,
                    "name": "Updated Name",
                    "email": "updated@example.com",
                },
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["created_count"], 0)
        self.existing_partner.invalidate_cache()
        self.assertEqual(self.existing_partner.name, "Updated Name")

    def test_import_update_only_skips_new(self):
        """update_only mode skips records that don't exist."""
        self.schema.import_mode = "update_only"
        self.schema.duplicate_detect_mode = "none"
        json_data = {
            "records": [
                {"name": "Brand New", "email": "brand@example.com"},
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["created_count"], 0)

    # -- Import tests: upsert mode --

    def test_import_upsert_creates_new(self):
        """upsert mode creates records when no match found."""
        self.schema.import_mode = "upsert"
        self.schema.duplicate_detect_mode = "field"
        email_field = self.env["ir.model.fields"].search(
            [("model_id", "=", self.partner_model.id), ("name", "=", "email")],
            limit=1,
        )
        self.schema.duplicate_field_id = email_field
        json_data = {
            "records": [
                {"name": "Upsert New", "email": "upsert-new@example.com"},
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["created_count"], 1)

    def test_import_upsert_updates_existing(self):
        """upsert mode updates existing records when match found."""
        self.schema.import_mode = "upsert"
        self.schema.duplicate_detect_mode = "field"
        email_field = self.env["ir.model.fields"].search(
            [("model_id", "=", self.partner_model.id), ("name", "=", "email")],
            limit=1,
        )
        self.schema.duplicate_field_id = email_field
        json_data = {
            "records": [
                {"name": "Upsert Existing", "email": "existing@example.com"},
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["updated_count"], 1)
        self.existing_partner.invalidate_cache()
        self.assertEqual(self.existing_partner.name, "Upsert Existing")

    # -- Duplicate detection tests --

    def test_duplicate_detect_by_record_id(self):
        """Duplicate detection by record_id finds existing record."""
        self.schema.duplicate_detect_mode = "record_id"
        self.schema.import_mode = "upsert"
        json_data = {
            "records": [
                {
                    "id": self.existing_partner.id,
                    "name": "ID Update",
                    "email": "id-update@example.com",
                },
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["updated_count"], 1)
        self.existing_partner.invalidate_cache()
        self.assertEqual(self.existing_partner.name, "ID Update")

    def test_duplicate_detect_by_field(self):
        """Duplicate detection by field finds existing record."""
        self.schema.duplicate_detect_mode = "field"
        email_field = self.env["ir.model.fields"].search(
            [("model_id", "=", self.partner_model.id), ("name", "=", "email")],
            limit=1,
        )
        self.schema.duplicate_field_id = email_field
        self.schema.import_mode = "upsert"
        json_data = {
            "records": [
                {"name": "Field Update", "email": "existing@example.com"},
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["updated_count"], 1)
        self.existing_partner.invalidate_cache()
        self.assertEqual(self.existing_partner.name, "Field Update")

    # -- Error handling tests --

    def test_import_bad_data_does_not_stop_batch(self):
        """One bad record does not abort the entire batch."""
        self.schema.import_mode = "create_only"
        self.schema.duplicate_detect_mode = "none"
        json_data = {
            "records": [
                {"name": "Good Record", "email": "good@example.com"},
                # Bad record: country_id dict with name that won't match
                {"name": "Bad Record", "country_id": {"name": "NonExistentCountryXYZ"}},
                {"name": "Another Good", "email": "good2@example.com"},
            ]
        }
        result = self.schema.action_import_records(json_data)
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["index"], 1)

    # -- Log creation tests --

    def test_create_log_success(self):
        """Successful import creates log with status 'success'."""
        json_data = {
            "records": [{"name": "Log Test Partner", "email": "log@example.com"}]
        }
        self.schema.action_import_records(json_data)
        log = self.env["json.import.log"].search(
            [("schema_id", "=", self.schema.id)], order="id desc", limit=1
        )
        self.assertEqual(log.status, "success")
        self.assertEqual(log.records_created, 1)

    def test_create_log_partial(self):
        """Partial success creates log with status 'partial'."""
        json_data = {
            "records": [
                {"name": "Good", "email": "good@example.com"},
                {"name": "Bad", "country_id": {"name": "NonExistentCountryXYZ"}},
            ]
        }
        self.schema.action_import_records(json_data)
        log = self.env["json.import.log"].search(
            [("schema_id", "=", self.schema.id)], order="id desc", limit=1
        )
        self.assertEqual(log.status, "partial")

    def test_compute_log_count(self):
        """Log count matches actual log records."""
        self.schema._create_log("manual", "success")
        self.schema._create_log("api", "error", error_message="test error")
        self.schema.invalidate_cache()
        self.assertEqual(self.schema.log_count, 2)

    def test_action_view_logs(self):
        """Returns correct action dict."""
        result = self.schema.action_view_logs()
        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "json.import.log")
        self.assertIn(("schema_id", "=", self.schema.id), result["domain"])

    # -- Constraint tests --

    def test_constraint_duplicate_field_required(self):
        """Raises ValidationError when duplicate_detect_mode=field without field."""
        with self.assertRaises(ValidationError):
            self.env["json.import.schema"].create(
                {
                    "name": "Bad Schema",
                    "model_id": self.partner_model.id,
                    "exporter_id": self.partner_exporter.id,
                    "import_mode": "upsert",
                    "duplicate_detect_mode": "field",
                    # No duplicate_field_id
                }
            )

    # -- Validation tests --

    def test_validate_json_valid(self):
        """Valid JSON passes validation."""
        json_data = {
            "records": [{"name": "Test", "email": "test@example.com"}]
        }
        errors = self.schema.action_validate_json(json_data)
        self.assertEqual(errors, [])

    def test_validate_json_missing_records_key(self):
        """Missing 'records' key returns error."""
        errors = self.schema.action_validate_json({"data": []})
        self.assertTrue(any("records" in e for e in errors))

    def test_validate_json_records_not_array(self):
        """'records' not being an array returns error."""
        errors = self.schema.action_validate_json({"records": "not a list"})
        self.assertTrue(any("array" in e for e in errors))

    def test_validate_json_missing_required_field(self):
        """Missing required field in record returns error."""
        json_data = {"records": [{"email": "test@example.com"}]}
        errors = self.schema.action_validate_json(json_data)
        # 'name' is required on res.partner
        self.assertTrue(any("name" in e for e in errors))

    # -- Wizard action test --

    def test_action_open_import_wizard(self):
        """Returns correct wizard action dict."""
        result = self.schema.action_open_import_wizard()
        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "json.import.file.wizard")
        self.assertEqual(result["target"], "new")
