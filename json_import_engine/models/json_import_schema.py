# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..tools.deserializer import JsonImportDeserializer
from ..tools.resolver import IrExportsResolver

_logger = logging.getLogger(__name__)


class JsonImportSchema(models.Model):
    _name = "json.import.schema"
    _description = "JSON Import Schema"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        required=True,
        ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    model_name = fields.Char(
        related="model_id.model", store=True, readonly=True, index=True
    )
    exporter_id = fields.Many2one("ir.exports", string="Field Selector")
    description = fields.Text()
    import_mode = fields.Selection(
        [
            ("create_only", "Create Only"),
            ("update_only", "Update Only"),
            ("upsert", "Create or Update"),
        ],
        default="upsert",
        required=True,
    )
    duplicate_detect_mode = fields.Selection(
        [
            ("none", "None"),
            ("record_id", "By Record ID"),
            ("field", "By Field Value"),
        ],
        default="none",
        required=True,
    )
    duplicate_field_id = fields.Many2one(
        "ir.model.fields",
        string="Duplicate Detection Field",
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
    )
    create_missing_related = fields.Boolean(
        default=False,
        help="Automatically create missing related records (many2one) "
        "when they cannot be found by name.",
    )
    json_schema = fields.Text(
        compute="_compute_json_schema", string="Expected JSON Schema"
    )
    endpoint_ids = fields.One2many("json.import.endpoint", "schema_id")
    log_ids = fields.One2many("json.import.log", "schema_id")
    log_count = fields.Integer(compute="_compute_log_count", string="Logs")

    @api.constrains("duplicate_detect_mode", "duplicate_field_id")
    def _check_duplicate_field_required(self):
        for rec in self:
            if rec.duplicate_detect_mode == "field" and not rec.duplicate_field_id:
                raise ValidationError(
                    _(
                        "A duplicate detection field is required when "
                        "duplicate detection mode is set to 'By Field Value'."
                    )
                )

    @api.depends("log_ids")
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.log_ids)

    # -- Odoo field type -> JSON Schema type mapping --
    FIELD_TYPE_MAP = {
        "char": {"type": "string"},
        "text": {"type": "string"},
        "html": {"type": "string"},
        "integer": {"type": "integer"},
        "float": {"type": "number"},
        "monetary": {"type": "number"},
        "boolean": {"type": "boolean"},
        "date": {"type": "string", "format": "date"},
        "datetime": {"type": "string", "format": "date-time"},
        "binary": {"type": "string", "contentEncoding": "base64"},
        "selection": {"type": "string"},
        "reference": {"type": "string"},
    }

    @api.depends("model_id", "exporter_id")
    def _compute_json_schema(self):
        for rec in self:
            if not rec.model_id or not rec.exporter_id:
                rec.json_schema = ""
                continue
            try:
                record_schema = rec._generate_record_schema()
                import_schema = rec._wrap_import_schema(record_schema)
                rec.json_schema = json.dumps(
                    import_schema, indent=2, ensure_ascii=False
                )
            except Exception as e:
                rec.json_schema = json.dumps(
                    {"error": str(e)}, indent=2, ensure_ascii=False
                )

    def _wrap_import_schema(self, record_schema):
        """Wrap a record-level schema in the import envelope."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "%s - Import Envelope" % record_schema.get("title", "Import"),
            "description": "Expected JSON input format. Submit an object with a "
            "'records' array, a plain array, or a single object.",
            "type": "object",
            "required": ["records"],
            "additionalProperties": False,
            "properties": {
                "records": {
                    "type": "array",
                    "description": "List of records to import.",
                    "items": record_schema,
                },
            },
        }

    def _generate_record_schema(self):
        """Generate a JSON Schema (draft-07) for a single record
        from the resolved parser and model fields."""
        self.ensure_one()
        parser = self._get_parser()
        model = self.env[self.model_name]
        properties, required = self._parser_to_schema_properties(parser, model)
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": self.name,
            "description": "Auto-generated schema for %s (%s)"
            % (self.name, self.model_name),
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    def _parser_to_schema_properties(self, parser, model):
        """Convert a jsonify parser list into JSON Schema properties dict."""
        properties = {}
        required = []
        for item in parser:
            if isinstance(item, str):
                field_name = item
                if field_name in model._fields:
                    field_obj = model._fields[field_name]
                    properties[field_name] = self._field_to_schema(field_obj)
                    if field_obj.required:
                        required.append(field_name)
                elif field_name == "id":
                    properties["id"] = {
                        "type": "integer",
                        "description": "Record ID",
                    }
            elif isinstance(item, tuple) and len(item) == 2:
                field_name, sub_fields = item
                if field_name in model._fields:
                    field_obj = model._fields[field_name]
                    properties[field_name] = self._relational_field_to_schema(
                        field_obj, sub_fields
                    )
                    if field_obj.required:
                        required.append(field_name)
        return properties, required

    def _field_to_schema(self, field_obj):
        """Convert a single Odoo field to a JSON Schema property."""
        schema = {}
        field_type = field_obj.type

        if field_type in self.FIELD_TYPE_MAP:
            schema.update(self.FIELD_TYPE_MAP[field_type])
        elif field_type == "many2one":
            schema = {"type": "integer", "description": "Related record ID"}
        elif field_type in ("one2many", "many2many"):
            schema = {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of related record IDs",
            }
        else:
            schema = {"type": "string"}

        if field_obj.string:
            schema["title"] = field_obj.string
        if field_obj.help:
            schema["description"] = field_obj.help

        if field_type == "selection" and field_obj.selection:
            try:
                choices = field_obj.selection
                if callable(choices):
                    choices = choices(self.env[field_obj.model_name])
                schema["enum"] = [key for key, _label in choices]
            except Exception:
                _logger.debug(
                    "Could not resolve selection choices for field %s",
                    field_obj.name,
                    exc_info=True,
                )

        if not field_obj.required:
            schema = {"anyOf": [schema, {"type": "null"}]}

        return schema

    def _relational_field_to_schema(self, field_obj, sub_fields):
        """Convert a relational field with sub-fields to a JSON Schema property."""
        comodel_name = field_obj.comodel_name
        if comodel_name not in self.env:
            return {"type": "string"}

        comodel = self.env[comodel_name]
        sub_properties, sub_required = self._parser_to_schema_properties(
            sub_fields, comodel
        )

        item_schema = {
            "type": "object",
            "properties": sub_properties,
            "additionalProperties": False,
        }
        if sub_required:
            item_schema["required"] = sub_required

        if field_obj.type == "many2one":
            schema = {
                "anyOf": [item_schema, {"type": "null"}],
                "title": field_obj.string or field_obj.name,
            }
        else:
            schema = {
                "type": "array",
                "items": item_schema,
                "title": field_obj.string or field_obj.name,
            }
        return schema

    def _get_parser(self):
        """Resolve the ir.exports field selection into a jsonify-compatible parser."""
        self.ensure_one()
        if not self.exporter_id:
            raise UserError(_("Please select a field selector (exporter) first."))
        bad_lines = self.exporter_id.export_fields.filtered(lambda l: not l.name)
        if bad_lines:
            bad_lines.unlink()
        raw_parser = self.exporter_id.get_json_parser()
        resolved = IrExportsResolver(raw_parser).resolved_parser
        return resolved

    def action_import_records(self, json_data, log_type="manual"):
        """Core entry point: import JSON data using this schema's configuration.

        :param json_data: dict with 'records' key containing a list of dicts
        :param log_type: 'api', 'manual', or 'wizard'
        :returns: dict with import results
        """
        self.ensure_one()
        start_time = time.time()
        try:
            parser = self._get_parser()
            duplicate_field_name = (
                self.duplicate_field_id.name if self.duplicate_field_id else False
            )
            deserializer = JsonImportDeserializer(
                env=self.env,
                model_name=self.model_name,
                parser=parser,
                import_mode=self.import_mode,
                duplicate_detect_mode=self.duplicate_detect_mode,
                duplicate_field_name=duplicate_field_name,
                create_missing_related=self.create_missing_related,
            )
            records_data = json_data.get("records", [])
            result = deserializer.import_records(records_data)

            duration = int((time.time() - start_time) * 1000)
            result["duration_ms"] = duration

            # Determine status
            if result["failed_count"] == 0:
                status = "success"
            elif result["created_count"] > 0 or result["updated_count"] > 0:
                status = "partial"
            else:
                status = "error"

            self._create_log(
                log_type=log_type,
                status=status,
                records_created=result["created_count"],
                records_updated=result["updated_count"],
                records_skipped=result["skipped_count"],
                records_failed=result["failed_count"],
                duration_ms=duration,
                error_details=(
                    json.dumps(result["errors"]) if result["errors"] else False
                ),
            )
            return result
        except Exception as e:
            duration = int((time.time() - start_time) * 1000)
            self._create_log(
                log_type=log_type,
                status="error",
                duration_ms=duration,
                error_message=str(e),
            )
            raise

    def action_validate_json(self, json_data):
        """Validate JSON data against expected structure.

        Returns a list of error strings. Empty list means valid.
        """
        self.ensure_one()
        errors = []
        if not isinstance(json_data, dict):
            errors.append("Input must be a JSON object.")
            return errors
        records = json_data.get("records")
        if records is None:
            errors.append("Missing required key 'records'.")
            return errors
        if not isinstance(records, list):
            errors.append("'records' must be an array.")
            return errors

        parser = self._get_parser()
        model = self.env[self.model_name]
        expected_fields = set()
        for item in parser:
            if isinstance(item, str):
                expected_fields.add(item)
            elif isinstance(item, tuple) and len(item) == 2:
                expected_fields.add(item[0])

        for idx, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append("Record at index %d must be a JSON object." % idx)
                continue
            # Check required fields
            for item in parser:
                field_name = item if isinstance(item, str) else item[0]
                if field_name == "id":
                    continue
                if field_name in model._fields and model._fields[field_name].required:
                    if field_name not in record:
                        errors.append(
                            "Record at index %d: missing required field '%s'."
                            % (idx, field_name)
                        )
        return errors

    def action_open_import_wizard(self):
        """Open the file upload wizard."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Import JSON File"),
            "res_model": "json.import.file.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_schema_id": self.id},
        }

    def action_view_logs(self):
        """Open log entries for this schema."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Import Logs"),
            "res_model": "json.import.log",
            "view_mode": "tree,form",
            "domain": [("schema_id", "=", self.id)],
            "context": {"default_schema_id": self.id},
        }

    def _create_log(
        self,
        log_type,
        status,
        records_created=0,
        records_updated=0,
        records_skipped=0,
        records_failed=0,
        duration_ms=0,
        error_message=None,
        error_details=None,
        request_info=None,
    ):
        """Helper to create a log entry."""
        self.ensure_one()
        return (
            self.env["json.import.log"]
            .sudo()
            .create(
                {
                    "schema_id": self.id,
                    "log_type": log_type,
                    "status": status,
                    "records_created": records_created,
                    "records_updated": records_updated,
                    "records_skipped": records_skipped,
                    "records_failed": records_failed,
                    "duration_ms": duration_ms,
                    "error_message": error_message,
                    "error_details": error_details,
                    "request_info": request_info,
                }
            )
        )
