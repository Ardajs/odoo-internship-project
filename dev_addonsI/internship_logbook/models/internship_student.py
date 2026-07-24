from odoo import api, fields, models


class InternshipStudent(models.Model):
    _name = "internship.student"
    _description = "Internship Student"
    _order = "name asc"


    _student_number_unique = models.Constraint(
        "UNIQUE(student_number)",
        "The student number must be unique.",
    )

    _user_unique = models.Constraint(
        "UNIQUE(user_id)",
        "A user can be linked to only one internship student profile.",
    )

    name = fields.Char(
        string="Full Name",
        required=True,
    )

    student_number = fields.Char(
        string="Student Number",
        required=True,
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "internship.student"
        ),
    )

    user_id = fields.Many2one(
    comodel_name="res.users",
    string="Related User",
    ondelete="set null",
    index=True,
    )

    university = fields.Char(
        string="University",
        help="Complete this field before creating an internship program.",
    )

    faculty = fields.Char(
        string="Faculty",
    )

    department = fields.Char(
        string="Department",
        help="Complete this field before creating an internship program.",
    )

    class_year = fields.Selection(
        selection=[
            ("1", "1st Year"),
            ("2", "2nd Year"),
            ("3", "3rd Year"),
            ("4", "4th Year"),
            ("graduate", "Graduate"),
        ],
        string="Class Year",
    )

    email = fields.Char(
        string="Email",
    )

    phone = fields.Char(
        string="Phone",
    )

    notes = fields.Text(
        string="Notes",
    )

    program_ids = fields.One2many(
        comodel_name="internship.program",
        inverse_name="student_id",
        string="Internship Programs",
    )

    program_count = fields.Integer(
    string="Program Count",
    compute="_compute_program_count",
    )

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    @api.depends("program_ids")
    def _compute_program_count(self):
        for student in self:
            student.program_count = len(student.program_ids)

    def action_view_programs(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Internship Programs",
            "res_model": "internship.program",
            "view_mode": "list,form",
            "domain": [
                ("student_id", "=", self.id),
            ],
            "context": {
                "default_student_id": self.id,
            },
        }
