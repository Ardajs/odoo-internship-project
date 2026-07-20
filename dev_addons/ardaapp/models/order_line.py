from odoo import models, fields, api

class OrderLine(models.Model):
    _name = 'order.line'
    _description = 'Order Line'

    order_id = fields.Many2one('order.header', string='Order', required=True)
    quantity = fields.Integer(string='Quantity', default=1)
    price_unit = fields.Float(string='Unit Price', required=True)
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)
