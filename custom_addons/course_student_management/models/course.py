# -*- coding: utf-8 -*-

from odoo import api, fields, models


class Course(models.Model):
    _name = "course.course"
    _description = "Course"

    name = fields.Char(
        string="Course Name",
        required=True,
    )
    code = fields.Char(
        string="Course Code",
        required=True,
    )
    description = fields.Text(
        string="Description",
    )
    duration = fields.Integer(
        string="Duration (Hours)",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
    )
    session_ids = fields.One2many(
    comodel_name="course.session",
    inverse_name="course_id",
    string="Sessions",
    )

    def action_view_sessions(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Sessions",
            "res_model": "course.session",
            "view_mode": "list,form",
            "domain": [
                ("course_id", "=", self.id),
            ],
            "context": {
                "default_course_id": self.id,
            },
        }

    session_count = fields.Integer(
    string="Session Count",
    compute="_compute_session_count",
    )


    @api.depends("session_ids")
    def _compute_session_count(self):
        for course in self:
            course.session_count = len(course.session_ids)
