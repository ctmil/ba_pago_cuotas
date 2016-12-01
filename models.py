from openerp import models, fields, api, _
from openerp.osv import osv
from openerp.exceptions import except_orm, ValidationError
from StringIO import StringIO
import urllib2, httplib, urlparse, gzip, requests, json
import openerp.addons.decimal_precision as dp
import logging
import datetime
from openerp.fields import Date as newdate
from datetime import datetime

#Get the logger
_logger = logging.getLogger(__name__)

class pos_make_payment(models.TransientModel):
        _inherit = 'pos.make.payment'

        order_amount = fields.Float('Monto del pedido')
        #cuotas = fields.Integer('Cuotas')
        monto_recargo = fields.Float('Monto Recargo')
        total_amount = fields.Float('Monto total con recargos')
        journal_id = fields.Many2one('account.journal',string='Payment Mode',required=True,domain=[('journal_user','=',True)])
	cuotas_id = fields.Many2one('sale.cuotas',string='Plan de cuotas')	

	"""
        @api.onchange('journal_id')
        def change_journal_id(self):
                if self.journal_id.sale_cuotas_id:
                        if self.journal_id.sale_cuotas_id.monto:
                                self.cuotas = self.journal_id.sale_cuotas_id.cuotas
                                self.monto_recargo = self.journal_id.sale_cuotas_id.monto
                                self.total_amount = self.amount + self.journal_id.sale_cuotas_id.monto
                        else:
                                self.cuotas = 0
                                self.monto_recargo = 0
                                self.total_amount = self.amount
                else:
                        self.cuotas = 0
                        self.monto_recargo = 0
                        self.total_amount = self.amount
	"""


class sale_order(models.Model):
	_inherit = 'sale.order'

	@api.multi
	def add_cuotas(self):
		return {'type': 'ir.actions.act_window',
                        'name': 'Agregar cuotas',
                        'res_model': 'add.sale.order.cuotas',
                        'view_type': 'form',
                        'view_mode': 'form',
                        #'view_id': view_id,
                        'target': 'new',
                        'nodestroy': True,
                        }



class sale_cuotas(models.Model):
	_name = 'sale.cuotas'
	_description = 'Permite indicar que monto agregar por cobro en cuotas'

	name = fields.Char('Nombre')
	bank_id = fields.Many2one('res.bank',string='Banco')
	journal_id = fields.Many2one('account.journal',string='Diario',domain=[('type','in',('cash','banks'))])
	cuotas = fields.Integer(string='Cuotas')
	product_id = fields.Many2one('product.product',string='Producto')
	monto = fields.Float(string='Monto')
	coeficiente = fields.Float(string='Coeficiente')
