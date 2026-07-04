{
    "name": "Quality Alert Custom",
    "version": "19.0.1.1.0",
    "author": "Mobile Picking Assistant",
    "category": "Inventory/Quality",
    "summary": "Leichtgewichtiges Quality-Alert-Modul für Community Edition",
    "depends": ["stock", "mail"],
    "data": [
        "security/quality_alert_security.xml",
        "security/ir.model.access.csv",
        "data/quality_alert_data.xml",
        "views/quality_alert_views.xml",
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
