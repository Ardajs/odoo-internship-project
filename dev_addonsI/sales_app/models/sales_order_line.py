from odoo import models, fields, api


class SalesOrderLine(models.Model):
    _name = "sales.order.line"
    _description = "Sales Order Line"
    _order = "sequence, id"

    sequence = fields.Integer(string="Sequence", default=10)

    order_id = fields.Many2one(
        "sales.order.header",
        string="Order",
        required=True,
        ondelete="cascade"
    )

    product_id = fields.Many2one("product.product", string="Product", required=True)
    quantity = fields.Integer(string="Quantity", default=1)
    price_unit = fields.Float(string="Unit Price", required=True)
    discount = fields.Float(string="Discount (%)", default=0.0)
    tax_rate = fields.Float(string="Tax Rate (%)", default=20.0)

    subtotal = fields.Float(string="Subtotal", compute="_compute_amounts", store=True)
    tax_amount = fields.Float(string="Tax Amount", compute="_compute_amounts", store=True)
    total = fields.Float(string="Total", compute="_compute_amounts", store=True)

    @api.depends("quantity", "price_unit", "discount", "tax_rate")
    def _compute_amounts(self):
        for line in self:
            price = line.quantity * line.price_unit
            discount_amount = price * line.discount / 100
            line.subtotal = price - discount_amount
            line.tax_amount = line.subtotal * line.tax_rate / 100
            line.total = line.subtotal + line.tax_amount

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.lst_price