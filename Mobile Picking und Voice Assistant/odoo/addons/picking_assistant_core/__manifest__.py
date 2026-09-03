{
    "name": "Picking Assistant Core",
    "version": "19.0.2.0.0",
    "author": "Mobile Picking Assistant",
    "category": "Inventory/Barcode",
    "summary": "Mobile claim and scoped idempotency support",
    "depends": [
        "stock",
        "stock_picking_batch",
        "picking_assistant_integration",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/decimal_precision.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
