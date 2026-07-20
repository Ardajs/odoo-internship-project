# -*- coding: utf-8 -*-

from odoo import fields, models


class CourseSession(models.Model):
    _name = "course.session"
    _description = "Course Session"

    title = fields.Char(
        string="Session Title",
        required=True,
    )
    course_id = fields.Many2one(
        comodel_name="course.course",
        string="Course",
        required=True,
        ondelete="cascade",
    )
    session_date = fields.Date(
        string="Session Date",
        required=True,
    )
    duration = fields.Float(
        string="Duration (Hours)",
        required=True,
        default=1.0,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
    )
    active = fields.Boolean(
        string="Active",
        default=True,
    )