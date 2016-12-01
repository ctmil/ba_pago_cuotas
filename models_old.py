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
	        amount = order.amount_total - order.amount_paid
        	data = self.read(cr, uid, ids, context=context)[0]

		if data['journal_id']:
			journal = self.pool.get('account.journal').browse(cr,uid,data['journal_id'][0])
			if journal.sale_cuotas_id:
				vals_line = {
					'product_id': journal.sale_cuotas_id.product_id.id,
					'order_id': context['active_id'],
					'display_name': journal.sale_cuotas_id.name,
					'qty': 1,
					'price_unit': journal.sale_cuotas_id.monto,
					'price_subtotal': journal.sale_cuotas_id.monto,
					}
				line_id = self.pool.get('pos.order.line').create(cr,uid,vals_line)
		res = super(pos_make_payment,self).check(cr,uid,ids,context)
		return {'type': 'ir.actions.act_window_close'}

