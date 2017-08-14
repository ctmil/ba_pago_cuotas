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


class pos_session(osv.osv):
	_inherit = 'pos.session'

	def wkf_action_close(self, cr, uid, ids, context=None):
        	r = super(pos_session, self).wkf_action_close(cr, uid, ids, context=context)
		for session_id in ids:
			session = self.pool.get('pos.session').browse(cr,uid,session_id)
			for order in session.order_ids:
				move_line_invoice = None
				if order.invoice_id:
					if order.invoice_id.move_id:
						move_line_invoice = None
						for move_line in order.invoice_id.move_id.line_id:
							if move_line.debit > 0:							
								move_line_invoice = move_line.id
					if order.statement_ids and move_line_invoice:
						for statement in order.statement_ids:
							if statement.journal_entry_id:
								for move_line in statement.journal_entry_id.line_id:
									if move_line.credit > 0:
										move_line_statement = move_line.id
										rec_ids = [move_line_invoice,move_line_statement]	
										#import pdb;pdb.set_trace()
										#return_id = self.pool.get('account.move.line').\
										#	partial_reconcile(cr,uid,rec_ids)
										return_id = self.pool.get('account.move.line').\
											reconcile_partial(cr,uid,rec_ids,type='manual')
								
	        return r


	def create(self, cr, uid, values, context=None):
		session_id = super(pos_session, self).create(cr, uid, values, context=context)
		session = self.pool.get('pos.session').browse(cr,uid,session_id)
		old_session = self.pool.get('pos.session').search(cr,uid,[('config_id','=',session.config_id.id),
					('state','=','closed')],order='id desc',limit=1)
		if old_session:
			if session.statement_ids:
				for statement in session.statement_ids:
					old_statement = self.pool.get('account.bank.statement').\
						search(cr,uid,[('pos_session_id','=',old_session[0]),('journal_id','=',statement.journal_id.id)])
					if old_statement:
						old_statement = self.pool.get('account.bank.statement').browse(cr,uid,old_statement[0])
						vals = {
							'balance_start': old_statement.balance_end_real,
							}							
						return_id = self.pool.get('account.bank.statement').write(cr,uid,statement.id,vals)
		return session_id

	def _confirm_orders(self, cr, uid, ids, context=None):
		res = super(pos_session, self)._confirm_orders(cr, uid, ids, context=context)
		for session_id in ids:
			session = self.pool.get('pos.session').browse(cr,uid,session_id)
			if session.config_id.journal_id:
				account_move_ids = self.pool.get('account.move').search(cr,uid,[('state','=','draft'),('journal_id','=',session.config_id.journal_id.id)])
				if account_move_ids:
					return_id = self.pool.get('account.move').unlink(cr,uid,account_move_ids)
		return res

pos_session()

class account_bank_statement_line(osv.osv):
	_inherit = 'account.bank.statement.line'

	def unlink(self, cr, uid, ids, context=None):
		for stmt_id in ids:
			bank_stmt_line = self.pool.get('account.bank.statement.line').browse(cr,uid,stmt_id)
			if bank_stmt_line.return_id:
				vals = {
					'state': 'done'
					}
				return_id = self.pool.get('pos.return').write(cr,uid,bank_stmt_line.return_id.id,vals)
		return super(account_bank_statement_line, self).unlink(cr,uid,ids,context)

account_bank_statement_line()

class pos_order_line(osv.osv):
	_inherit = 'pos.order.line'

	def onchange_qty(self, cr, uid, ids, product, discount, qty, price_unit, context=None):
	        result = {}
        	if not product:
	            return result
        	account_tax_obj = self.pool.get('account.tax')
	        cur_obj = self.pool.get('res.currency')

        	prod = self.pool.get('product.product').browse(cr, uid, product, context=context)

	        price = price_unit * (1 - (discount or 0.0) / 100.0)
        	taxes = account_tax_obj.compute_all(cr, uid, prod.taxes_id, price, qty, product=prod, partner=False)

	        result['price_subtotal'] = taxes['total']
        	result['price_subtotal_incl'] = taxes['total_included']
	        return {'value': result}

pos_order_line()

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


	def check(self, cr,uid, ids, context=None):
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
		if cuotas and cuotas.cuotas > 0:
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
				range_cuotas = range(1,cuotas.cuotas)
				monto_capital = amount / cuotas.cuotas
				monto_interes = (total_amount - amount) / cuotas.cuotas	
				for cuota in range_cuotas:
					vals_cuotas = {
						'order_id': context['active_id'],
						'statement_line_id': statement_id[0],
						'nro_cuota': cuota,
						'monto_capital': monto_capital,
						'monto_interes': monto_interes
						}
					return_id = self.pool.get('pos.order.installment').create(cr,uid,vals_cuotas)				
		return_id = data.get('return_id',None)
		if return_id:
			statement_id = self.pool.get('account.bank.statement.line').\
				search(cr,uid,[('pos_statement_id','=',context['active_id']),\
					('journal_id','=',data['journal_id'][0])],order='id desc',limit=1)
			if statement_id:
				vals = {
					'return_id': return_id[0]
					}
				ret_id = self.pool.get('account.bank.statement.line').write(cr,uid,statement_id,vals)
				vals_return = {
					'state': 'used'
					}
				return_move = self.pool.get('pos.return').write(cr,uid,return_id[0],vals_return)

			
		if order.test_paid():
			if order.sale_journal.type == 'sale':
				# Creates invoice
				import pdb;pdb.set_trace()
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

