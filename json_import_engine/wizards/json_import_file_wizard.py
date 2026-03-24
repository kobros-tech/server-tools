# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json

from odoo import _, fields, models
from odoo.exceptions import UserError


class JsonImportFileWizard(models.TransientModel):
    _name = "json.import.file.wizard"
    _description = "JSON Import File Upload Wizard"

    schema_id = fields.Many2one(
        "json.import.schema",
        string="Import Schema",
        required=True,
    )
    file_data = fields.Binary(string="JSON File", required=True)
    file_name = fields.Char(string="File Name")
    validate_before_import = fields.Boolean(
        string="Validate Before Import", default=True
    )
    state = fields.Selection(
        [("upload", "Upload"), ("done", "Done")],
        default="upload",
    )
    result_summary = fields.Text(string="Summary", readonly=True)
    result_created = fields.Integer(string="Created", readonly=True)
    result_updated = fields.Integer(string="Updated", readonly=True)
    result_skipped = fields.Integer(string="Skipped", readonly=True)
    result_failed = fields.Integer(string="Failed", readonly=True)
    result_errors = fields.Text(string="Error Details", readonly=True)

    def action_import(self):
        """Import the uploaded JSON file."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please select a JSON file to import."))

        # Decode base64 file
        try:
            raw_content = base64.b64decode(self.file_data).decode("utf-8")
        except Exception as e:
            raise UserError(_("Could not read file: %s") % str(e)) from e

        # Parse JSON
        try:
            json_data = json.loads(raw_content)
        except (ValueError, TypeError) as e:
            raise UserError(_("Invalid JSON file: %s") % str(e)) from e

        # Auto-normalize input format
        if isinstance(json_data, list):
            json_data = {"records": json_data}
        elif isinstance(json_data, dict) and "records" not in json_data:
            json_data = {"records": [json_data]}

        # Validate if requested
        if self.validate_before_import:
            errors = self.schema_id.action_validate_json(json_data)
            if errors:
                raise UserError(
                    _("Validation errors:\n%s") % "\n".join("- %s" % e for e in errors)
                )

        # Import
        result = self.schema_id.action_import_records(json_data, log_type="wizard")

        # Build summary
        parts = []
        if result["created_count"]:
            parts.append(_("%d record(s) created") % result["created_count"])
        if result["updated_count"]:
            parts.append(_("%d record(s) updated") % result["updated_count"])
        if result["skipped_count"]:
            parts.append(_("%d record(s) skipped") % result["skipped_count"])
        if result["failed_count"]:
            parts.append(_("%d record(s) failed") % result["failed_count"])
        summary = ", ".join(parts) if parts else _("No records processed.")

        # Write results
        self.write(
            {
                "state": "done",
                "result_summary": summary,
                "result_created": result["created_count"],
                "result_updated": result["updated_count"],
                "result_skipped": result["skipped_count"],
                "result_failed": result["failed_count"],
                "result_errors": (
                    json.dumps(result["errors"], indent=2, ensure_ascii=False)
                    if result["errors"]
                    else False
                ),
            }
        )

        # Re-open wizard to show results
        return {
            "type": "ir.actions.act_window",
            "name": _("Import Results"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
