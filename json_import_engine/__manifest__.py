# Copyright 2026 KOBROS-TECH LTD (https://kobros-tech.com).
# @author Mohamed Alkobrosli <mohamed@kobros-tech.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "JSON Import Engine",
    "summary": "Schema-driven JSON import with REST API receivers, "
    "file upload, validation, and audit logging",
    "version": "16.0.1.0.0",
    "category": "Tools",
    "website": "https://github.com/OCA/server-tools",
    "author": "kobros-tech, Odoo Community Association (OCA)",
    "maintainers": ["kobros-tech"],
    "license": "AGPL-3",
    "development_status": "Alpha",
    "depends": [
        "base",
        "web",
        "jsonifier",
    ],
    "data": [
        "security/json_import_engine_security.xml",
        "security/ir.model.access.csv",
        "views/json_import_file_wizard_views.xml",
        "views/json_import_schema_views.xml",
        "views/json_import_endpoint_views.xml",
        "views/json_import_log_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
}
