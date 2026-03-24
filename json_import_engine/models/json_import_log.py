# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class JsonImportLog(models.Model):
    _name = "json.import.log"
    _description = "JSON Import Log"
    _order = "create_date desc"

    schema_id = fields.Many2one(
        "json.import.schema",
        string="Import Schema",
        required=True,
        ondelete="cascade",
        index=True,
    )
    log_type = fields.Selection(
        [
            ("api", "API Call"),
            ("manual", "Manual Import"),
            ("wizard", "File Upload"),
        ],
        required=True,
        index=True,
    )
    status = fields.Selection(
        [
            ("success", "Success"),
            ("partial", "Partial"),
            ("error", "Error"),
        ],
        required=True,
    )
    records_created = fields.Integer(string="Created")
    records_updated = fields.Integer(string="Updated")
    records_skipped = fields.Integer(string="Skipped")
    records_failed = fields.Integer(string="Failed")
    duration_ms = fields.Integer(string="Duration (ms)")
    error_message = fields.Text()
    error_details = fields.Text(
        help="JSON array of per-record errors: [{index, data, error}]",
    )
    request_info = fields.Text(
        help="JSON with additional context about the request.",
    )
