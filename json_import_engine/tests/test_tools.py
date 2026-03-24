# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import Command
from odoo.exceptions import UserError

from .common import JsonImportTestCase


class TestJsonImportDeserializer(JsonImportTestCase):
    """Tests for the JsonImportDeserializer tool."""

    def _get_deserializer(self, **kwargs):
        from ..tools.deserializer import JsonImportDeserializer

        defaults = {
            "env": self.env,
            "model_name": "res.partner",
            "parser": self.schema._get_parser(),
            "import_mode": "upsert",
            "duplicate_detect_mode": "none",
            "duplicate_field_name": False,
            "create_missing_related": False,
        }
        defaults.update(kwargs)
        return JsonImportDeserializer(**defaults)

    # -- Simple field conversion tests --

    def test_convert_simple_string(self):
        """String values pass through."""
        d = self._get_deserializer()
        model = self.env["res.partner"]
        val = d._convert_simple_value(model, "name", "Test Name")
        self.assertEqual(val, "Test Name")

    def test_convert_simple_none_to_false(self):
        """None converts to False."""
        d = self._get_deserializer()
        model = self.env["res.partner"]
        val = d._convert_simple_value(model, "name", None)
        self.assertFalse(val)

    def test_convert_simple_integer(self):
        """Integer field values are coerced."""
        d = self._get_deserializer()
        model = self.env["res.partner"]
        val = d._convert_simple_value(model, "color", 5)
        self.assertEqual(val, 5)
        self.assertIsInstance(val, int)

    def test_convert_simple_boolean(self):
        """Boolean field values are coerced."""
        d = self._get_deserializer()
        model = self.env["res.partner"]
        val = d._convert_simple_value(model, "active", True)
        self.assertTrue(val)
        self.assertIsInstance(val, bool)

    def test_convert_simple_float(self):
        """Float values are coerced."""
        d = self._get_deserializer()
        model = self.env["res.partner"]
        # partner_latitude is a float field
        val = d._convert_simple_value(model, "partner_latitude", 12.5)
        self.assertEqual(val, 12.5)
        self.assertIsInstance(val, float)

    # -- Many2one resolution tests --

    def test_resolve_many2one_by_name(self):
        """Many2one resolved by name search."""
        d = self._get_deserializer()
        field_obj = self.env["res.partner"]._fields["country_id"]
        result = d._resolve_many2one(
            field_obj, {"name": "United States"}, ["name", "code"]
        )
        self.assertEqual(result, self.country_us.id)

    def test_resolve_many2one_not_found_raises(self):
        """Many2one raises UserError when not found and create_missing is False."""
        d = self._get_deserializer(create_missing_related=False)
        field_obj = self.env["res.partner"]._fields["country_id"]
        with self.assertRaises(UserError):
            d._resolve_many2one(
                field_obj, {"name": "NonExistentCountryXYZ"}, ["name", "code"]
            )

    def test_resolve_many2one_create_missing(self):
        """Many2one creates new record when create_missing_related is True."""
        d = self._get_deserializer(create_missing_related=True)
        field_obj = self.env["res.partner"]._fields["title"]
        result = d._resolve_many2one(
            field_obj, {"name": "TestAutoTitle"}, ["name"]
        )
        self.assertTrue(result)
        title = self.env["res.partner.title"].browse(result)
        self.assertEqual(title.name, "TestAutoTitle")

    def test_resolve_many2one_by_int(self):
        """Many2one by integer returns the ID directly."""
        d = self._get_deserializer()
        field_obj = self.env["res.partner"]._fields["country_id"]
        result = d._resolve_many2one(
            field_obj, self.country_us.id, ["name", "code"]
        )
        self.assertEqual(result, self.country_us.id)

    def test_resolve_many2one_none(self):
        """Many2one None clears the field."""
        d = self._get_deserializer()
        field_obj = self.env["res.partner"]._fields["country_id"]
        result = d._resolve_many2one(field_obj, None, ["name", "code"])
        self.assertFalse(result)

    # -- x2many resolution tests --

    def test_resolve_x2many_empty_list(self):
        """Empty list produces Command.clear()."""
        d = self._get_deserializer()
        field_obj = self.env["res.partner"]._fields["child_ids"]
        result = d._resolve_x2many(field_obj, [], ["name"])
        self.assertEqual(len(result), 1)
        # Command.clear() is (5, 0, 0)
        self.assertEqual(result[0][0], Command.CLEAR)

    def test_resolve_x2many_int_items(self):
        """Integer items produce Command.link()."""
        d = self._get_deserializer()
        field_obj = self.env["res.partner"]._fields["category_id"]
        cat = self.env["res.partner.category"].create({"name": "TestCat"})
        result = d._resolve_x2many(field_obj, [cat.id], ["name"])
        self.assertEqual(len(result), 1)
        # Command.link() is (4, id, 0)
        self.assertEqual(result[0][0], Command.LINK)
        self.assertEqual(result[0][1], cat.id)

    def test_resolve_x2many_dict_create(self):
        """Dict items without ID produce Command.create()."""
        d = self._get_deserializer()
        field_obj = self.env["res.partner"]._fields["child_ids"]
        result = d._resolve_x2many(
            field_obj,
            [{"name": "New Child", "email": "child@example.com"}],
            ["name", "email"],
        )
        self.assertEqual(len(result), 1)
        # Command.create() is (0, 0, vals)
        self.assertEqual(result[0][0], Command.CREATE)
        self.assertIn("name", result[0][2])

    def test_resolve_x2many_dict_with_id(self):
        """Dict items with 'id' key produce Command.update()."""
        d = self._get_deserializer()
        field_obj = self.env["res.partner"]._fields["child_ids"]
        child = self.env["res.partner"].create(
            {"name": "Existing Child", "parent_id": self.existing_partner.id}
        )
        result = d._resolve_x2many(
            field_obj,
            [{"id": child.id, "name": "Updated Child"}],
            ["name", "email"],
        )
        self.assertEqual(len(result), 1)
        # Command.update() is (1, id, vals)
        self.assertEqual(result[0][0], Command.UPDATE)
        self.assertEqual(result[0][1], child.id)

    # -- id field skipping --

    def test_id_field_skipped_in_vals(self):
        """The 'id' key in JSON data is not included in vals dict."""
        d = self._get_deserializer()
        model = self.env["res.partner"]
        parser = ["id", "name", "email"]
        vals = d._json_to_vals(
            {"id": 999, "name": "Test", "email": "test@test.com"}, model, parser
        )
        self.assertNotIn("id", vals)
        self.assertEqual(vals["name"], "Test")

    # -- Batch import with error isolation --

    def test_batch_import_error_isolation(self):
        """Per-record error isolation: one bad record doesn't stop others."""
        d = self._get_deserializer()
        records_data = [
            {"name": "Good 1", "email": "good1@test.com"},
            {"name": "Bad", "country_id": {"name": "NonExistentCountryXYZ"}},
            {"name": "Good 2", "email": "good2@test.com"},
        ]
        result = d.import_records(records_data)
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["index"], 1)

    # -- Duplicate detection modes --

    def test_find_existing_none_mode(self):
        """duplicate_detect_mode='none' always returns empty recordset."""
        d = self._get_deserializer(duplicate_detect_mode="none")
        existing = d._find_existing_record({"id": self.existing_partner.id}, {})
        self.assertFalse(existing)

    def test_find_existing_record_id_mode(self):
        """duplicate_detect_mode='record_id' finds by ID."""
        d = self._get_deserializer(duplicate_detect_mode="record_id")
        existing = d._find_existing_record(
            {"id": self.existing_partner.id}, {}
        )
        self.assertEqual(existing.id, self.existing_partner.id)

    def test_find_existing_field_mode(self):
        """duplicate_detect_mode='field' finds by field value."""
        d = self._get_deserializer(
            duplicate_detect_mode="field",
            duplicate_field_name="email",
        )
        existing = d._find_existing_record(
            {}, {"email": "existing@example.com"}
        )
        self.assertEqual(existing.id, self.existing_partner.id)

    def test_find_existing_field_mode_not_found(self):
        """duplicate_detect_mode='field' returns empty when not found."""
        d = self._get_deserializer(
            duplicate_detect_mode="field",
            duplicate_field_name="email",
        )
        existing = d._find_existing_record(
            {}, {"email": "nonexistent@example.com"}
        )
        self.assertFalse(existing)


class TestIrExportsResolver(JsonImportTestCase):
    """Tests for the IrExportsResolver tool."""

    def test_resolver_simple_fields(self):
        from ..tools.resolver import IrExportsResolver

        parser = {
            "fields": [{"name": "name"}, {"name": "email"}],
        }
        resolved = IrExportsResolver(parser).resolved_parser
        self.assertEqual(resolved, ["name", "email"])

    def test_resolver_relational_fields(self):
        from ..tools.resolver import IrExportsResolver

        parser = {
            "fields": [
                {"name": "name"},
                ({"name": "country_id"}, [{"name": "name"}, {"name": "code"}]),
            ],
        }
        resolved = IrExportsResolver(parser).resolved_parser
        self.assertIn("name", resolved)
        relational = [item for item in resolved if isinstance(item, tuple)]
        self.assertTrue(relational)
        self.assertEqual(relational[0], ("country_id", ["name", "code"]))

    def test_resolver_empty_parser(self):
        from ..tools.resolver import IrExportsResolver

        resolved = IrExportsResolver({}).resolved_parser
        self.assertEqual(resolved, [])
