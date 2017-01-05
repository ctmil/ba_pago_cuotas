# -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from openerp.osv import osv
from openerp.exceptions import except_orm, ValidationError
from StringIO import StringIO
import urllib2, httplib, urlparse, gzip, requests, json
import openerp.addons.decimal_precision as dp
import logging
import datetime
from openerp.fields import Date as newdate
from datetime import datetime,date

#Get the logger
_logger = logging.getLogger(__name__)

class account_journal(models.Model):
	_inherit = 'account.journal'

	is_credit_card = fields.Boolean(string='Es tarjeta de crédito')

class account_bank_statement_line(models.Model):
	_inherit = 'account.bank.statement.line'

	cuotas_id = fields.Many2one('sale.cuotas',string='Plan de cuotas')	
	nro_cupon = fields.Char('Nro cupon')
	nro_tarjeta = fields.Char('Nro tarjeta')	

class pos_config_journal(models.Model):
	_name = 'pos.config.journal'
	_description = 'Describe la relacion de medio de pago, journal, sesion'

	@api.one
	def _compute_next_printer_number(self):
		return_value = 0
		if self.journal_type == 'sale':	
			if self.journal_id.journal_class_id.document_class_id.name == 'A':
				return_value = self.config_id.journal_id.last_a_sale_document_completed + 1
			else:
				return_value = self.config_id.journal_id.last_b_sale_document_completed + 1
		self.next_printer_number = return_value

	@api.one
	def sync_numbers(self):
		if self.next_sequence_number != self.next_printer_number:
			vals = {
				'number_next_actual': self.next_printer_number 
				}
			sequence = self.journal_id.sequence_id
			sequence.write(vals)
	

	config_id = fields.Many2one('pos.config',string='Sesión',required=True)	
	responsability_id = fields.Many2one('afip.responsability',string='Responsabilidad AFIP',required=True)
	journal_id = fields.Many2one('account.journal',string='Diario',domain=[('type','in',['sale','sale_refund'])])
	journal_type = fields.Selection(selection=[('sale', 'Sale'),('sale_refund','Sale Refund'), ('purchase', 'Purchase'), ('purchase_refund','Purchase Refund'), ('cash', 'Cash'), ('bank', 'Bank and Checks'), ('general', 'General'), ('situation', 'Opening/Closing Situation')],related='journal_id.type')
	next_sequence_number = fields.Integer(string='Sig.Nro.Secuencia',related='journal_id.sequence_id.number_next_actual')
	next_printer_number = fields.Integer(string='Sig.Nro.Impresora',compute=_compute_next_printer_number)


class pos_config(models.Model):
	_inherit = 'pos.config'

	sale_journals = fields.One2many(comodel_name='pos.config.journal',inverse_name='config_id')
	point_of_sale = fields.Integer(string='Punto de Venta',required=True)

class pos_make_payment(models.TransientModel):
        _inherit = 'pos.make.payment'

	nro_cupon = fields.Char('Nro cupon')
	nro_tarjeta = fields.Char('Nro tarjeta')	
        order_amount = fields.Float('Monto del pedido')
        cuotas = fields.Integer('Cuotas')
        monto_recargo = fields.Float('Monto Recargo')
        total_amount = fields.Float('Monto total con recargos')
        journal_id = fields.Many2one('account.journal',string='Payment Mode',required=True,domain=[('journal_user','=',True)])
	cuotas_id = fields.Many2one('sale.cuotas',string='Plan de cuotas')	
	is_credit_card = fields.Boolean(string='Es tarjeta de crédito',related='journal_id.is_credit_card')
	
        @api.onchange('cuotas_id')
        def change_cuotas_id(self):
                if self.cuotas_id:
                        if self.cuotas_id.coeficiente:
				if self.cuotas_id.product_id.taxes_id:
					if len(self.cuotas_id.product_id.taxes_id) > 1:
						raise ValidationError('El plan de cuotas tiene multiples impuestos configurados')
					tax_amount = self.cuotas_id.product_id.taxes_id.amount
                                self.cuotas = self.cuotas_id.cuotas
				self.monto_recargo = self.amount * self.cuotas_id.coeficiente * ( 1 + tax_amount)
                                self.total_amount = self.amount + self.monto_recargo
				vals = {
					'cuotas': self.cuotas,
					'monto_recargo': self.monto_recargo,
					'total_amount': self.total_amount,
					}
				self.write(vals)
	
                        else:
                                self.cuotas = 0
                                self.monto_recargo = 0
                                self.total_amount = self.amount
                else:
                        self.cuotas = 0
                        self.monto_recargo = 0
                        self.total_amount = self.amount
	


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

        @api.multi
        def name_get(self):
                res = super(sale_cuotas,self).name_get()
                data = []
                min_qty = 0
                for sale_cuota in self:
			if sale_cuota.journal_id and sale_cuota.bank_id and sale_cuota.cuotas:
                                display_value = sale_cuota.journal_id.name + ' - ' + sale_cuota.bank_id.bic + ' - ' + str(sale_cuota.cuotas)
                        data.append((sale_cuota.id,display_value))
                return data

	@api.one
	def _compute_name(self):
		if self.journal_id and self.bank_id and self.cuotas:
			self.name = self.journal_id.name + ' - ' + self.bank_id.bic + ' - ' + str(self.cuotas)
	
	@api.one
	@api.constrains('cuotas')
	def _check_cuotas(self):
		import pdb;pdb.set_trace()
		if self.cuotas > 36 or self.cuotas < 1:
			raise ValidationError('La cantidad de cuotas ingresada debe ser menor a 36')

	@api.one
	@api.constrains('coeficiente')
	def _check_coeficiente(self):
		if self.coeficiente > 5 or self.coeficiente < 0:
			raise ValidationError('El coeficiente ingresado debe ser entre 0 y 5')

	@api.one
	@api.constrains('bank_id','journal_id','cuotas')
	def _check_unique(self):
		cuotas = self.search([('journal_id','=',self.journal_id.id),\
				('bank_id','=',self.bank_id.id),('cuotas','=',self.cuotas)])
		if len(cuotas) > 1:
			raise ValidationError('El plan de cuotas ya esta ingresado')
	
	name = fields.Char('Nombre',readonly=True,compute=_compute_name)
	bank_id = fields.Many2one('res.bank',string='Banco',required=True)
	journal_id = fields.Many2one('account.journal',string='Diario',domain=[('type','in',('cash','banks'))],required=True)
	cuotas = fields.Integer(string='Cuotas',help='Cantidad de cuotas, debe ser menor a 36')
	product_id = fields.Many2one('product.product',string='Producto')
	monto = fields.Float(string='Monto')
	coeficiente = fields.Float(string='Coeficiente',help='Porcentaje de coeficiente, debe ser un valor entre 0 y 5')

class pos_order(models.Model):
	_inherit = 'pos.order'

	@api.one
	def _compute_nro_factura(self):
		return_value = 'N/A'
		if self.invoice_id:
			return_value = self.invoice_id.number
		self.nro_factura = return_value

	nro_factura = fields.Char(string='Nro Factura',compute=_compute_nro_factura)

class pos_session(models.Model):
	_inherit = 'pos.session'

	@api.multi
	def bank_deposit(self):
		user_id = self.env.context['uid']
		vals = {
			'user_id': user_id,
			'session_id': self.id,
			'date': str(date.today())
			}
		wizard = self.env['bank.deposit.pdv'].create(vals)	
		if wizard:
			wizard_id = wizard.id
                        res = {
                                "name": "bank.deposit."+str(wizard_id),
                                "type": "ir.actions.act_window",
                                "res_model": "bank.deposit.pdv",
                                "view_type": "form",
                                "view_mode": "form",
                                #"view_id": "product.product_supplierinfo_form_view",
                                "res_id": wizard_id,
				"target": "new",
                                "nodestroy": True,
                                }
                        return res

