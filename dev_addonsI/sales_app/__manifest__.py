{
    "name": "Sales App",
    "version": "1.0",
    "depends": ["base","mail", "product"],
    "data": [
        "security/ir.model.access.csv",
        "views/sales_app_order_header_views.xml",
        "views/sales_app_root_views.xml",
        "data/sales_order_sequence.xml"
    ],
    "installable": True,
    "application": True
}
