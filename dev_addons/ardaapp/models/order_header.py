from odoo import models, fields, api

class OrderHeader(models.Model):
    _name = 'order.header'
    _description = 'Order Header'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Order Name', required=True, Tracking=True)
    customer_id = fields.Many2one('res.partner', string='Customer', required=True, Tracking=True)
    order_date = fields.Datetime(string='Order Date', default=fields.Datetime.now, Tracking=True)

    order_line_ids = fields.One2many('order.line', 'order_id', string='Order Lines')