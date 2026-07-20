from odoo import models, fields, api
from odoo.exceptions import UserError

class SalesOrderHeader(models.Model):
    _name = "sales.order.header"
    _description = "Sales Order Header"
    _inherit = ['mail.thread', "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Sales Order Name", required=True, default= "new", readonly= True, tracking=True)
    customer_id = fields.Many2one('res.partner', string="Customer", required=True, tracking=True)
    salesperson_id = fields.Many2one('res.users', string="Salesperson", default=lambda self: self.env.user, tracking=True)
    customer_phone = fields.Char(string="Customer Phone", related="customer_id.phone", readonly=True)
    customer_email = fields.Char(string="Customer Email", related="customer_id.email", readonly=True)
    order_date = fields.Datetime(string="Order Date", default=fields.Datetime.now, tracking=True)

    note =fields.Text(string="Note")
    order_line_ids = fields.One2many("sales.order.line", "order_id",string="Order Lines" )

    untaxed_amount = fields.Float(string="Untaxed Amount", compute="_compute_amount", store=True)
    tax_amount = fields.Float(string="Tax Amount", compute="_compute_amount", store=True)


    total_amount = fields.Float(string="Total Amount", compute="_compute_amount", store=True)

    _sql_constraints = [("unique_sales_order_name", "unique(name)", "Sales Order Name must be unique!")]


    @api.depends(
        "order_line_ids.subtotal",
        "order_line_ids.tax_amount",
        "order_line_ids.total"
    )
    def _compute_amount(self):
        for order in self:
            order.untaxed_amount = sum(order.order_line_ids.mapped("subtotal"))
            order.tax_amount = sum(order.order_line_ids.mapped("tax_amount"))
            order.total_amount = sum(order.order_line_ids.mapped("total"))

    state = fields.Selection([ #Burada state alanı, satış siparişinin durumunu belirtir. Bu alan, 'draft', 'confirmed' ve 'cancelled' olmak üzere üç farklı durumu temsil eder.
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled')
    ],
    string='Status',
    default='draft',
    tracking=True
    )

    def action_confirm(self): #Bu fonksiyon, satış siparişini onaylamak için kullanılır. Eğer siparişin durumu 'draft' ise, durumu 'confirmed' olarak değiştirir.
        for order in self:
            if not order.customer_id:
                raise UserError("Please select a customer before confirming the order.")
            if not order.order_line_ids:
                raise UserError("Please add at least one order line before confirming the order.")
            if order.total_amount <= 0:
                raise UserError("Total amount must be greater than zero to confirm the order.")
            order.state = 'confirmed'


    def action_cancel(self): #Bu fonksiyon, satış siparişini iptal etmek için kullanılır. Eğer siparişin durumu 'confirmed' ise, durumu 'cancelled' olarak değiştirir.
        for order in self:
            if order.state == 'confirmed':
                order.state = 'cancelled'


    def action_set_to_draft(self): #Bu fonksiyon, satış siparişini taslak durumuna geri döndürmek için kullanılır. Eğer siparişin durumu 'cancelled' ise, durumu 'draft' olarak değiştirir.
        for order in self:
            if order.state == 'cancelled':
                order.state = 'draft'



    @api.model_create_multi
    def create(self, vals_list): #Bu fonksiyon, yeni bir satış siparişi oluşturulduğunda çağrılır. Eğer name alanı 'new' ise, name alanına bir sıra numarası atanır.
        for vals in vals_list:
            if vals.get('name', 'new') == 'new':
                vals['name'] = self.env['ir.sequence'].next_by_code('sales.order.header') or 'new'
        return super().create(vals_list)


    def unlink(self):
        for order in self:
            order.order_line_ids.unlink()
        return super().unlink()
