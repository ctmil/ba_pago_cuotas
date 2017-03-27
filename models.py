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

from openerp.addons.l10n_ar_fpoc.invoice import document_type_map, responsability_map

#Get the logger
_logger = logging.getLogger(__name__)

class account_journal(models.Model):
    _inherit = 'account.journal'

    is_credit_card = fields.Boolean(string='Es tarjeta de crédito')
    is_cta_cte = fields.Boolean(string='Es cta cte')

class account_bank_statement_line(models.Model):
    _inherit = 'account.bank.statement.line'

    cuotas_id = fields.Many2one('sale.cuotas',string='Plan de cuotas')    
    nro_cupon = fields.Char('Nro cupon')
    nro_tarjeta = fields.Char('Nro tarjeta')
    installment_ids = fields.One2many(comodel_name='pos.order.installment',inverse_name='statement_line_id')    

class pos_order_installment(models.Model):
    _name = 'pos.order.installment'
    _description = 'Describe las cuotas asociadas a un pedido'

    @api.one
    def _compute_journal_id(self):
        if self.statement_line_id:
            self.journal_id = self.statement_line_id.journal_id.id

    order_id = fields.Many2one('pos.order',string='Pedido')
    statement_line_id = fields.Many2one('account.bank.statement.line',string='Medio de pago')
    journal_id = fields.Many2one('account.journal',string='Medio de Pago',compute='_compute_journal_id')
    nro_cuota = fields.Integer('Cuota')
    monto_capital = fields.Float('Monto Capital',digits_compute=dp.get_precision('Account'))
    monto_interes = fields.Float('Monto Interes',digits_compute=dp.get_precision('Account'))



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
    bank_account = fields.Many2one('account.account',string='Cuenta Contable Bancos')
    cash_journal = fields.Many2one('account.journal',string='Metodo de Pago Caja',domain=[('type','=','cash')])

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
    _order = "journal_id , bank_id , cuotas asc"



    # @api.multi
    # def name_get(self):
    #     res = super(sale_cuotas,self).name_get()
    #     data = []
    #     min_qty = 0
    #     for sale_cuota in self:
    #         if sale_cuota.journal_id and sale_cuota.bank_id and sale_cuota.cuotas:
    #             display_value = sale_cuota.journal_id.name + ' - ' + sale_cuota.bank_id.bic + ' - ' + str(sale_cuota.cuotas)
    #         elif self.journal_id  and self.cuotas:
    #             display_value = self.journal_id.name + ' - ' + str(self.cuotas)

    #         data.append((sale_cuota.id,display_value))
    #     return data

    @api.one
    @api.depends('journal_id','bank_id','cuotas')
    def _compute_name(self):
        if self.journal_id and self.bank_id and self.cuotas:
            self.name = self.journal_id.name + ' - ' + self.bank_id.bic + ' - ' + str(self.cuotas)
        elif self.journal_id  and self.cuotas:
            self.name = self.journal_id.name + ' - ' + str(self.cuotas)
        else :
            self.name = 'N/A'


    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        args = args or []
        recs = self.browse()
        if name:
            name = name.replace(' ', '%')
            recs = self.search([('name', operator, name)] + args, limit=limit)
        return recs.name_get()

    
    #@api.one
    #@api.constrains('cuotas')
    #def _check_cuotas(self):
    #    if self.cuotas > 36 or self.cuotas < 1:
    #        raise ValidationError('La cantidad de cuotas ingresada debe ser menor a 36')

    #@api.one
    #@api.constrains('coeficiente')
    #def _check_coeficiente(self):
    #    if self.coeficiente > 5 or self.coeficiente < 0:
    #        raise ValidationError('El coeficiente ingresado debe ser entre 0 y 5')

    #@api.one
    #@api.constrains('bank_id','journal_id','cuotas')
    #def _check_unique(self):
    #    cuotas = self.search([('journal_id','=',self.journal_id.id),\
    #            ('bank_id','=',self.bank_id.id),('cuotas','=',self.cuotas)])
    #    if len(cuotas) > 1:
    #        raise ValidationError('El plan de cuotas ya esta ingresado')
    
    name = fields.Char('Nombre',compute=_compute_name,store=True)

    bank_id = fields.Many2one('res.bank',string='Banco')
    journal_id = fields.Many2one('account.journal',string='Diario',domain=[('type','=','banks')])
    cuotas = fields.Integer(string='Cuotas',help='Cantidad de cuotas, debe ser menor a 36')
    product_id = fields.Many2one('product.product',string='Producto')
    monto = fields.Float(string='Monto')
    coeficiente = fields.Float(string='Coeficiente',help='Porcentaje de coeficiente, debe ser un valor entre 0 y 5')

    sale_order_default = fields.Boolean('Disponible por defecto en presupuestos')
    tipo = fields.Selection([('credito', 'Credito'),('debito', 'Debito')],default='credito')
    active = fields.Boolean('Activo',default=True)
    fantasy_name = fields.Char('Nombre fantasia')
    ctf = fields.Float(string='C.T.F.',help='Costo total financiado')
    tea = fields.Float(string='TEA',help='Taza Anual')



class pos_order(models.Model):
    _inherit = 'pos.order'

    @api.one
    def _compute_nro_factura(self):
        return_value = 'N/A'
        if self.invoice_id:
            return_value = self.invoice_id.number
        self.nro_factura = return_value

    nro_factura = fields.Char(string='Nro Factura',compute=_compute_nro_factura)
    installment_ids = fields.One2many(comodel_name='pos.order.installment',inverse_name='order_id')
    return_ids = fields.One2many(comodel_name='pos.return',inverse_name='origin_id')

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

    deposit_ids = fields.One2many(comodel_name='pos.session.deposit',inverse_name='session_id')

class pos_session_deposit(models.Model):
	_name = 'pos.session.deposit'

	name = fields.Char('Nombre')
	statement_line_id = fields.Many2one('account.bank.statement.line',string='Statement Line')
	date = fields.Date('Fecha')
	user_id = fields.Many2one('res.users',string='Usuario')
	amount = fields.Float('Monto')
	nro_deposito = fields.Char('Nro Deposito')
	session_id = fields.Many2one('pos.session')

class pos_return(models.Model):
        _name = 'pos.return'
        _description = 'Devoluciones PDV'

        name = fields.Char('Nombre', readonly=True)
        partner_id = fields.Many2one('res.partner',string='Cliente', states={'done':[('readonly', True)], 'draft':[('readonly',False)], 'used':[('used',True)]})
        origin_id = fields.Many2one('pos.order',domain="[('partner_id','=',partner_id)]", states={'done':[('readonly', True)], 'draft':[('readonly',False)], 'used':[('used',True)]})
        date = fields.Date('Fecha',default=date.today(),readonly=True)
	return_line = fields.One2many(comodel_name='pos.return.line',inverse_name='return_id', states={'done':[('readonly', True)], 'draft':[('readonly',False)], 'used':[('used',True)]})
	state = fields.Selection(selection=[('draft','Borrador'),('done','Confirmado'),('used','Consumido')],default="draft")
	session_id = fields.Many2one('pos.session',domain=[('state','=','opened')],required=True, states={'done':[('readonly', True)], 'draft':[('readonly',False)], 'used':[('used',True)]})
	journal_id = fields.Many2one('account.journal',domain=[('journal_user','=',True)],required=True, states={'done':[('readonly', True)], 'draft':[('readonly',False)], 'used':[('used',True)]})
	statement_id = fields.Many2one('account.bank.statement.line','Pago',readonly=True)
	picking_id = fields.Many2one('stock.picking',string='Remito',readonly=True)
	invoice_id = fields.Many2one('account.invoice',string='Nota de Crédito')
	
	@api.one
	def confirm_refund(self):
		# creates bank statement line
		my_sequence = self.env['ir.sequence'].get('pos.return')
		if not self.journal_id or not self.return_line:
			raise ValidationError('Debe seleccionarse medio de pago y completar los productos')
		statement_id = self.env['account.bank.statement'].search([('journal_id','=',self.journal_id.id),\
				('pos_session_id','=',self.session_id.id)])
		if not statement_id:
			raise ValidationError('No existe medio de pago en la sesion de PDV')
		amount = 0
		for line in self.return_line:
			amount = amount + line.price_subtotal
		if not statement_id.journal_id.is_cta_cte:
			vals_statement_line = {
				'name': 'Pago devolucion ' + my_sequence,
				'journal_id': self.journal_id.id,
				'statement_id': statement_id.id,
				'amount': amount * (-1)
				}	
			statement_line_id = self.env['account.bank.statement.line'].create(vals_statement_line)
		else:
			statement_line_id = None
		# creates picking
		picking_type_id = self.env['stock.picking.type'].search([('code','=','incoming')])
		vals_picking = {
			'partner_id': self.partner_id.id,
			'date': self.date,
			'origin': my_sequence,
			'picking_type_id': picking_type_id.id,
			}

		# searches for journal
		journal_id = None
		journal_ids = self.env['pos.config.journal'].search([('responsability_id','=',self.partner_id.responsability_id.id)])
		for journal in journal_ids:
			if journal.journal_type == 'sale_refund' and  self.session_id.config_id.id == journal.config_id.id:
				journal_id = journal
				break
		if not journal_id:
			raise ValidationError('No hay journal definido para las devoluciones')
		#import pdb;pdb.set_trace()
		vals_invoice = {
			'date_invoice': self.date,
			'partner_id': self.partner_id.id,
			'journal_id': journal_id.journal_id.id,
			'origin': self.origin_id.nro_factura or 'N/A',
			'account_id': self.partner_id.property_account_receivable.id,
			'type': 'out_refund'
			}
		invoice_id = self.env['account.invoice'].create(vals_invoice)

		picking_id = self.env['stock.picking'].create(vals_picking)
		source_location = self.env['stock.location'].search([('usage','=','customer')])
		if not source_location:
			raise ValidationError('No esta definida ubicacion de clientes.\nContactese con administrador')
		for line in self.return_line:
			vals_move = {
				'date': self.date,
				'picking_id': picking_id.id,
				'product_id': line.product_id.id,
				'product_uom': 1,
				'product_uom_qty': line.qty,
				'name': my_sequence,
				'location_id': source_location.id,
				'location_dest_id': self.session_id.config_id.stock_location_id.id,
				'picking_type_id': picking_type_id.id,
				}
			move_id = self.env['stock.move'].create(vals_move)
	
			vals_invoice_line = {
				'invoice_id': invoice_id.id,
				'product_id': line.product_id.id,
				'name': line.product_id.name,
				'quantity': line.qty,
				'price_unit': line.price_unit,
				'account_id': line.product_id.property_account_income.id,
				'invoice_line_tax_id': [(6,0,line.product_id.taxes_id.ids)]
				}
			line_id = self.env['account.invoice.line'].create(vals_invoice_line)
		
		invoice_id.signal_workflow('invoice_open')

                picking_id.action_confirm()
                picking_id.force_assign()
                picking_id.action_done()

		# creates refund
		vals = {
			'name': my_sequence,
			'picking_id': picking_id.id,
			'state': 'done',
			'statement_id': statement_line_id.id,
			'invoice_id': invoice_id.id,
			}
		self.write(vals)

		# prints refund
		session = self.session_id
		journal = session.config_id.journal_id
		user = self.create_uid

		if not journal.use_fiscal_printer:
			raise ValidationError('You must set a fiscal printer for the journal')

		if not journal.fiscal_printer_id:
			raise ValidationError('You must set a fiscal printer for the journal')

		if not journal.fiscal_printer_state in ['ready']:
                	raise ValidationError('Printer is not ready to print.')

		if not journal.fiscal_printer_fiscal_state in ['open']:
                	raise ValidationError('You can\'t print in a closed printer.')

		if not journal.fiscal_printer_anon_partner_id:
                	raise ValidationError('You must set anonymous partner to the journal.')

		partner = self.partner_id
		if not partner:
                	partner = journal.fiscal_printer_anon_partner_id


		total_amount_w_tax = 0
		total_amount = 0

		#for line in self.return_line:
		#	total_amount = total_amount + line.price_subtotal
		#	total_amount_w_tax = total_amount + line.price_subtotal_w_tax
		#if total_amount > 0:
		#	tax_rate = (total_amount_w_tax / total_amount) - 1

		ticket={
                	"turist_ticket": False,
	                "debit_note": False,
        	        "partner": {
                	    "name": partner.name,
	                    "name_2": "",
        	            "address": partner.street,
                	    "address_2": partner.city,
	                    "address_3": partner.country_id.name,
        	            "document_type": document_type_map.get(partner.document_type_id.code, "D"),
                	    "document_number": partner.document_number,
	                    "responsability": responsability_map.get(partner.responsability_id.code, "F"),
        	        },
	                #"related_document": self.name or _("No related doc"),
	                "related_document": _("No picking"),
	                "related_document_2": "",
        	        "turist_check": "",
                	"lines": [ ],
	                "payments": [ ],
        	        "cut_paper": True,
                	"electronic_answer": False,
	                "print_return_attribute": False,
        	        "current_account_automatic_pay": False,
                	"print_quantities": True,
	                "tail_no": 1 if user.name else 0,
        	        "tail_text": _("Saleman: %s") % user.name if user.name else "",
                	"tail_no_2": 0,
	                "tail_text_2": "",
        	        "tail_no_3": 0,
                	"tail_text_3": "",
			"origin_document": self.origin_id.nro_factura or 'N/A'
	            }
       		#for op1, op2, line in data['lines']:
		for line in self.return_line:
                	product = line.product_id
	                ticket["lines"].append({
        	            "item_action": "sale_item",
                	    "as_gross": False,
	                    "send_subtotal": True,
        	            "check_item": False,
                	    "collect_type": "q",
	                    "large_label": "",
        	            "first_line_label": "",
                	    "description": "",
	                    "description_2": "",
        	            "description_3": "",
                	    "description_4": "",
	                    "item_description": product.name,
        	            #"quantity": line['qty'],
                	    #"unit_price": line['price_unit'],
	                    "quantity": line.qty,
        	            "unit_price": line.price_unit,
                	    "vat_rate": round(line.tax_rate,2), # TODO
	                    "fixed_taxes": 0,
        	            "taxes_rate": 0
                	})
		for pay in self.statement_id:
                	payment_journal = pay.journal_id
	                ticket["payments"].append({
        	            "type": "pay",
                	    "extra_description": "",
	                    "description": payment_journal.name,
        	            "amount": pay.amount * (-1),
                	})

                ticket_resp = journal.make_fiscal_refund_ticket(ticket)



	@api.one
	def fill_products(self):
		for line in self.return_line:
			line.unlink()
		if self.origin_id:
			for line in self.origin_id.lines:
				vals = {
					'return_id': self.id,
					'origin_id': self.origin_id.id,
					'product_id': line.product_id.id,
					'qty': line.qty,
					'price_unit': line.price_unit,
					'price_subtotal': line.price_subtotal,
					'price_subtotal_w_tax': line.price_subtotal_incl,
					}
				return_id = self.env['pos.return.line'].create(vals)

class pos_return_line(models.Model):
	_name = 'pos.return.line'
	_description = 'Linea Devolucion PDV'

	@api.one
	def _compute_tax_rate(self):
		if self.price_subtotal > 0:
			self.tax_rate = (self.price_subtotal_w_tax / self.price_subtotal) - 1

	return_id = fields.Many2one('pos.return')
	origin_id = fields.Many2one('pos.order')
	product_id = fields.Many2one('product.product',string='Producto')
	qty  = fields.Float('Cantidad')
	price_unit = fields.Float('Precio Unitario')
	price_subtotal = fields.Float('Subtotal (s/impuestos)')
	price_subtotal_w_tax = fields.Float('Subtotal (c/impuestos)')
	tax_rate = fields.Float('% Tax',compute=_compute_tax_rate)
