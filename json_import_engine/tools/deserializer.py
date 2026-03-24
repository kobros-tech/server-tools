# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import Command
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class JsonImportDeserializer:
    """Convert incoming JSON dicts into Odoo create()/write() calls
    using a jsonifier parser as the mapping definition."""

    def __init__(
        self,
        env,
        model_name,
        parser,
        import_mode="upsert",
        duplicate_detect_mode="none",
        duplicate_field_name=False,
        create_missing_related=False,
    ):
        self.env = env
        self.model_name = model_name
        self.parser = parser
        self.import_mode = import_mode
        self.duplicate_detect_mode = duplicate_detect_mode
        self.duplicate_field_name = duplicate_field_name
        self.create_missing_related = create_missing_related

    def import_records(self, records_data):
        """Process a list of JSON record dicts.

        Returns dict with created_ids, updated_ids, created_count,
        updated_count, skipped_count, failed_count, errors.
        """
        result = {
            "created_ids": [],
            "updated_ids": [],
            "created_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "errors": [],
        }
        for index, record_data in enumerate(records_data):
            try:
                self._import_single_record(record_data, index, result)
            except Exception as e:
                result["failed_count"] += 1
                result["errors"].append(
                    {
                        "index": index,
                        "data": str(record_data)[:500],
                        "error": str(e),
                    }
                )
                _logger.warning(
                    "Failed to import record %d for %s: %s",
                    index,
                    self.model_name,
                    e,
                )
        return result

    def _import_single_record(self, record_data, index, result):
        """Convert one JSON dict to vals, find existing record if duplicate
        detection is enabled, then create or write based on import_mode."""
        model = self.env[self.model_name]
        vals = self._json_to_vals(record_data, model, self.parser)
        existing = self._find_existing_record(record_data, vals)

        if existing:
            if self.import_mode == "create_only":
                result["skipped_count"] += 1
                return
            existing.write(vals)
            result["updated_ids"].append(existing.id)
            result["updated_count"] += 1
        else:
            if self.import_mode == "update_only":
                result["skipped_count"] += 1
                return
            new_record = model.create(vals)
            result["created_ids"].append(new_record.id)
            result["created_count"] += 1

    def _json_to_vals(self, data, model, parser):
        """Walk the parser structure and build Odoo-compatible vals dict."""
        vals = {}
        for item in parser:
            if isinstance(item, str):
                field_name = item
                if field_name == "id":
                    continue
                if field_name in data:
                    vals[field_name] = self._convert_simple_value(
                        model, field_name, data[field_name]
                    )
            elif isinstance(item, tuple) and len(item) == 2:
                field_name, sub_fields = item
                if field_name not in data:
                    continue
                if field_name not in model._fields:
                    continue
                field_obj = model._fields[field_name]
                value = data[field_name]
                if field_obj.type == "many2one":
                    vals[field_name] = self._resolve_many2one(
                        field_obj, value, sub_fields
                    )
                elif field_obj.type in ("one2many", "many2many"):
                    vals[field_name] = self._resolve_x2many(
                        field_obj, value, sub_fields
                    )
        return vals

    def _convert_simple_value(self, model, field_name, value):
        """Type coercion for simple field values."""
        if value is None:
            return False
        if field_name not in model._fields:
            return value
        field_obj = model._fields[field_name]
        if field_obj.type == "boolean":
            return bool(value)
        if field_obj.type == "integer":
            if isinstance(value, bool):
                return int(value)
            return int(value) if value is not False else 0
        if field_obj.type in ("float", "monetary"):
            if isinstance(value, bool):
                return float(value)
            return float(value) if value is not False else 0.0
        # date/datetime strings pass through as-is (Odoo handles ISO format)
        return value

    def _resolve_many2one(self, field_obj, value, sub_fields):
        """Resolve a many2one field value to a record ID.

        Strategies:
        - None → False (clear field)
        - int → use as record ID directly
        - dict → search by _rec_name, optionally create if missing
        """
        if value is None:
            return False
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
        if isinstance(value, dict):
            comodel = self.env[field_obj.comodel_name]
            # Determine search field: use _rec_name of the comodel
            rec_name = comodel._rec_name or "name"
            search_value = value.get(rec_name)
            if search_value:
                results = comodel.name_search(name=search_value, operator="=", limit=1)
                if results:
                    return results[0][0]
            if self.create_missing_related:
                sub_vals = self._json_to_vals(value, comodel, sub_fields)
                if sub_vals:
                    new_rec = comodel.create(sub_vals)
                    return new_rec.id
            if search_value:
                raise UserError(
                    "Could not find %s record with %s = '%s'"
                    % (field_obj.comodel_name, rec_name, search_value)
                )
            return False
        return False

    def _resolve_x2many(self, field_obj, value, sub_fields):
        """Resolve x2many field values to a list of ORM Commands.

        For each array item:
        - int → Command.link(id)
        - dict with 'id' key (int) → Command.update(id, sub_vals) or Command.link(id)
        - dict without ID → try name_search; if found m2m → Command.link(),
          o2m → Command.update(); if not found → Command.create(sub_vals)
        - empty list → Command.clear()
        """
        if not isinstance(value, list):
            return False
        if not value:
            return [Command.clear()]

        commands = []
        comodel = self.env[field_obj.comodel_name]
        for item in value:
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                commands.append(Command.link(int(item)))
            elif isinstance(item, dict):
                item_id = item.get("id")
                if isinstance(item_id, int):
                    sub_vals = self._json_to_vals(item, comodel, sub_fields)
                    if sub_vals:
                        commands.append(Command.update(item_id, sub_vals))
                    else:
                        commands.append(Command.link(item_id))
                else:
                    # Try to find existing record by rec_name
                    rec_name = comodel._rec_name or "name"
                    search_value = item.get(rec_name)
                    existing_id = False
                    if search_value:
                        results = comodel.name_search(
                            name=search_value, operator="=", limit=1
                        )
                        if results:
                            existing_id = results[0][0]
                    if existing_id:
                        if field_obj.type == "many2many":
                            commands.append(Command.link(existing_id))
                        else:
                            sub_vals = self._json_to_vals(
                                item, comodel, sub_fields
                            )
                            if sub_vals:
                                commands.append(
                                    Command.update(existing_id, sub_vals)
                                )
                            else:
                                commands.append(Command.link(existing_id))
                    else:
                        sub_vals = self._json_to_vals(item, comodel, sub_fields)
                        commands.append(Command.create(sub_vals))
        return commands

    def _find_existing_record(self, record_data, vals):
        """Find an existing record based on duplicate detection mode.

        Returns a recordset (empty if not found).
        """
        model = self.env[self.model_name]
        if self.duplicate_detect_mode == "none":
            return model.browse()
        if self.duplicate_detect_mode == "record_id":
            record_id = record_data.get("id")
            if record_id and isinstance(record_id, int):
                rec = model.browse(record_id).exists()
                return rec
            return model.browse()
        if self.duplicate_detect_mode == "field":
            if not self.duplicate_field_name:
                return model.browse()
            field_value = vals.get(self.duplicate_field_name)
            if field_value is None or field_value is False:
                # Also check original data in case the field is not in parser
                field_value = record_data.get(self.duplicate_field_name)
            if field_value is None or field_value is False:
                return model.browse()
            existing = model.search(
                [(self.duplicate_field_name, "=", field_value)], limit=1
            )
            return existing
        return model.browse()
