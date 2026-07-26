{
    "name": "Picking Assistant Integration",
    "version": "18.0.1.0.0",
    "author": "Mobile Picking Assistant",
    "category": "Inventory/Technical",
    "summary": "Secure sessions and durable integration primitives (Odoo 18 port)",
    "depends": ["base"],
    "data": [
        "security/integration_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
