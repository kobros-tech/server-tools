# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import re
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class JsonImportEndpoint(models.Model):
    _name = "json.import.endpoint"
    _description = "JSON Import REST Endpoint"
    _order = "name"

    name = fields.Char(required=True)
    schema_id = fields.Many2one(
        "json.import.schema",
        string="Import Schema",
        required=True,
        ondelete="cascade",
    )
    active = fields.Boolean(default=True)
    route_path = fields.Char(
        required=True,
        help="URL path segment, e.g. 'partners' will map to "
        "/api/json_import/partners",
    )
    full_url = fields.Char(
        compute="_compute_full_url",
        string="Import URL",
    )
    schema_url = fields.Char(
        compute="_compute_full_url",
        string="Schema URL",
    )
    auth_type = fields.Selection(
        [
            ("none", "No Authentication"),
            ("api_key", "API Key"),
            ("user", "Session (Logged-in User)"),
        ],
        default="api_key",
        required=True,
    )
    api_key = fields.Char(groups="json_import_engine.group_manager")
    api_key_generated_at = fields.Datetime(
        string="API Key Generated At",
        readonly=True,
        groups="json_import_engine.group_manager",
        help="Timestamp of the last API key generation, useful for rotation tracking.",
    )
    cors_origin = fields.Char(
        string="CORS Origin",
        help="Allowed CORS origin, e.g. * or https://example.com",
    )
    validate_schema = fields.Boolean(
        default=True,
        help="Validate incoming JSON against the schema before importing.",
    )

    @api.onchange("auth_type")
    def _onchange_auth_type(self):
        """Auto-generate an API key when switching to API Key auth."""
        if self.auth_type == "api_key" and not self.api_key:
            self.api_key = secrets.token_hex(32)
            self.api_key_generated_at = fields.Datetime.now()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("auth_type") == "api_key" and not vals.get("api_key"):
                vals["api_key"] = secrets.token_hex(32)
                vals["api_key_generated_at"] = fields.Datetime.now()
        return super().create(vals_list)

    @api.constrains("auth_type", "api_key")
    def _check_api_key_required(self):
        for rec in self:
            if rec.auth_type == "api_key" and not rec.api_key:
                raise ValidationError(
                    _(
                        "An API key is required when authentication"
                        " type is set to 'API Key'. Please generate one."
                    )
                )

    @api.depends("route_path")
    def _compute_full_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        for rec in self:
            if rec.route_path:
                path = rec.route_path.strip("/")
                rec.full_url = "%s/api/json_import/%s" % (base_url, path)
                rec.schema_url = "%s/api/json_import/%s/schema" % (base_url, path)
            else:
                rec.full_url = ""
                rec.schema_url = ""

    @api.constrains("route_path")
    def _check_route_path(self):
        for rec in self:
            if not rec.route_path:
                continue
            path = rec.route_path.strip("/")
            if not re.match(r"^[a-zA-Z0-9_/\-]+$", path):
                raise ValidationError(
                    _(
                        "Route path may only contain letters, numbers, "
                        "hyphens, underscores, and slashes."
                    )
                )
            # Check uniqueness among active endpoints
            duplicate = self.search(
                [
                    ("id", "!=", rec.id),
                    ("active", "=", True),
                    ("route_path", "=", path),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _(
                        "Route path '%(path)s' is already in use"
                        " by endpoint '%(endpoint)s'.",
                        path=path,
                        endpoint=duplicate.name,
                    )
                )

    def action_generate_api_key(self):
        """Generate a new random API key."""
        now = fields.Datetime.now()
        for rec in self:
            rec.api_key = secrets.token_hex(32)
            rec.api_key_generated_at = now
        return True
