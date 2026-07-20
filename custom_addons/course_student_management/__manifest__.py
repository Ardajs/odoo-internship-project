# -*- coding: utf-8 -*-

{
    "name": "Course Student Management",
    "version": "19.0.1.0.0",
    "summary": "Manage courses, students, sessions, and attendance",
    "description": """
Course Student Management System
================================
This module manages courses, students, sessions, attendance,
certificates, reports, and future ERP training operations.
""",
    "category": "Education",
    "author": "Arda Alan",
    "website": "https://www.example.com",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/actions.xml",
        "views/course_views.xml",
        "views/session_views.xml",
        "views/menus.xml",

    ],
    "installable": True,
    "application": True,
}
