{
    "name": "Internship Logbook",
    "version": "19.0.3.0.0",
    "summary": "Manage internship programs and daily internship records",
    "description": """
Internship Logbook Management
=============================

This module allows companies to manage:

* Intern students
* Internship programs
* Daily internship entries
* Supervisor approvals
* Internship reports
    """,
    "author": "Arda Alan",
    "category": "Human Resources",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "auth_signup",
        "portal",
        "website",
    ],
    "data": [
    "security/internship_security.xml",
    "security/ir.model.access.csv",

    "data/internship_student_sequence.xml",
    "data/self_registration_mail_template.xml",
    "data/mail_templates.xml",

    "views/internship_student_views.xml",
    "views/internship_program_views.xml",
    "views/internship_daily_entry_views.xml",
    "wizard/ai_assistant_wizard_views.xml",
    "views/internship_menus.xml",

    "report/internship_paperformat.xml",
    "report/internship_report_template.xml",
    "report/internship_report.xml",

    "views/self_registration_templates.xml",
    "views/internship_portal_templates.xml",

    ],
    "assets": {
        "web.assets_frontend": [
            "internship_logbook/static/src/js/verification_token.js",
        ],
    },
    "application": True,
    "installable": True,
    "auto_install": False,
}
