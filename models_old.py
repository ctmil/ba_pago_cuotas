import logging
import psycopg2
import time
from datetime import datetime

from openerp import tools
from openerp.osv import fields, osv
from openerp.tools import float_is_zero
from openerp.tools.translate import _

import openerp.addons.decimal_precision as dp
import openerp.addons.product.product
import math

class pos_order(osv.osv):
	_inherit = 'pos.order'

	def test_paid(self, cr, uid, ids, context=None):
        	"""A Point of Sale is paid when the sum
	        @return: True
        	"""

		for order in self.browse(cr, uid, ids, context=context):
			if order.lines and not order.amount_total:
				return True
			if (not order.lines) or (not order.statement_ids) or \
				(abs(order.amount_total-order.amount_paid) > 0.1):
				return False
		return True



class pos_make_payment(osv.osv_memory):
	_inherit = 'pos.make.payment'

	_columns = {
		'total_amount': fields.float('Monto total con recargos')
		}

	def check(self, cr, uid, ids, context=None):
		context = context or {}
	        order_obj = self.pool.get('pos.order')
        	active_id = context and context.get('active_id', False)

	        order = order_obj.browse(cr, uid, active_id, context=context)
		if not order.partner_id:
			raise osv.except_osv(_('Error!'), _('Debe ingresar el cliente!'))
	        amount = order.amount_total - order.amount_paid
        	data = self.read(cr, uid, ids, context=context)[0]
		cuotas = None
		is_credit_card = data.get('is_credit_card',False)
		if is_credit_card:
			cuotas_id = data.get('cuotas_id',False)
			nro_tarjeta = data.get('nro_tarjeta',False)
			nro_cupon = data.get('nro_cupon',False)
			if not cuotas_id or not nro_cupon or not nro_tarjeta:
				raise osv.except_osv(_('Error!'), _('Debe ingresar informacion del cupon/tarjeta!'))

		if data['cuotas_id']:
			cuotas = self.pool.get('sale.cuotas').browse(cr,uid,data['cuotas_id'][0])
			if cuotas:
				tax_amount = 1
				if cuotas.product_id.taxes_id.amount:
					tax_amount = 1 + cuotas.product_id.taxes_id.amount
				vals_line = {
					'product_id': cuotas.product_id.id,
					'order_id': context['active_id'],
					'display_name': cuotas.name,
					'qty': 1,
					'price_unit': amount * cuotas.coeficiente,
					'price_subtotal': amount * cuotas.coeficiente,
					}
				line_id = self.pool.get('pos.order.line').create(cr,uid,vals_line)
				if cuotas.coeficiente > 0:
					surcharge_amount = amount * cuotas.coeficiente
					tax_surcharge = surcharge_amount * cuotas.product_id.taxes_id.amount
					total_amount = amount * ( 1 + cuotas.coeficiente ) + tax_surcharge
					vals = {
						'amount': amount * (1+cuotas.coeficiente) + tax_surcharge
						}
					data['amount'] = amount * (1+cuotas.coeficiente) + tax_surcharge
					return_id = self.pool.get('pos.make.payment').write(cr,uid,ids,vals)
		res = super(pos_make_payment,self).check(cr,uid,ids,context)
		if cuotas:
			total_amount = amount * ( 1 + cuotas.coeficiente )
			statement_id = self.pool.get('account.bank.statement.line').\
				search(cr,uid,[('pos_statement_id','=',context['active_id']),\
					('journal_id','=',data['journal_id'][0])],order='id desc',limit=1)
			if statement_id:
				statement = self.pool.get('account.bank.statement.line').browse(cr,uid,statement_id)
				#if math.floor(statement.amount) == math.floor(total_amount):
				vals = {
					'nro_cupon': data.get('nro_cupon','N/A'),				
					'nro_tarjeta': data.get('nro_tarjeta','N/A'),				
					}
				return_id = self.pool.get('account.bank.statement.line').write(cr,uid,statement_id,vals)
		if order.test_paid():
			if order.sale_journal.type == 'sale':
				# Creates invoice
				self.pool.get('pos.order').create_from_ui_v2(cr,uid,[order.id])
				order.action_invoice()
				if order.invoice_id:
					invoice = order.invoice_id
					journal_ids = self.pool.get('pos.config.journal').search(cr,uid,[('config_id','=',order.session_id.config_id.id),\
							('journal_type','=','sale'),('responsability_id','=',order.partner_id.responsability_id.id)])
					if journal_ids:
						journal_id = self.pool.get('pos.config.journal').browse(cr,uid,journal_ids[0])
						journal = journal_id.journal_id.id
						self.pool.get('account.invoice').write(cr,uid,order.invoice_id.id,{'journal_id': journal})
						invoice.signal_workflow('invoice_open')
			else:
				# Creates refund
				self.pool.get('pos.order').create_refund_from_ui_v2(cr,uid,[order.id])
				order.action_invoice()
		return {'type': 'ir.actions.act_window_close'}

