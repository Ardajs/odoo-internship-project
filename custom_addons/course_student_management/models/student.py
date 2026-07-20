from odoo import models, fields, api


class Student(models.Model):
    _name = 'student.student_management'
    _description = 'Student Management'

    name = fields.Char(string='Student Name', required=True)
    email = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    session_ids = fields.One2many(
        comodel_name='session.student_management',
        inverse_name='student_id',
        string='Sessions'
    )

    @api.model
    def create(self, vals):
        if vals.get('email'):
            vals['email'] = vals['email'].lower()
        return super().create(vals)

    def write(self, vals):
        if vals.get('email'):
            vals['email'] = vals['email'].lower()
        return super().write(vals)