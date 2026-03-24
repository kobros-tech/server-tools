# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


class JsonImportTestCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

        # Create ir.exports + lines for res.partner
        cls.partner_exporter = cls.env["ir.exports"].create(
            {
                "name": "Test Partner Import",
                "resource": "res.partner",
            }
        )
        for field_name in ["name", "email", "phone"]:
            cls.env["ir.exports.line"].create(
                {
                    "export_id": cls.partner_exporter.id,
                    "name": field_name,
                }
            )
        # Relational lines for country_id
        cls.env["ir.exports.line"].create(
            {
                "export_id": cls.partner_exporter.id,
                "name": "country_id/name",
            }
        )
        cls.env["ir.exports.line"].create(
            {
                "export_id": cls.partner_exporter.id,
                "name": "country_id/code",
            }
        )

        # Create schema
        cls.partner_model = cls.env.ref("base.model_res_partner")
        cls.schema = cls.env["json.import.schema"].create(
            {
                "name": "Test Partner Import",
                "model_id": cls.partner_model.id,
                "exporter_id": cls.partner_exporter.id,
                "import_mode": "upsert",
                "duplicate_detect_mode": "none",
            }
        )

        # Reference country for testing
        cls.country_us = cls.env.ref("base.us")

        # Existing partner for duplicate detection tests
        cls.existing_partner = cls.env["res.partner"].create(
            {
                "name": "Existing Partner",
                "email": "existing@example.com",
                "phone": "+1111111111",
                "country_id": cls.country_us.id,
            }
        )
