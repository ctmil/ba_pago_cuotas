{
    'name': 'Blancoamor Pagos en cuotas',
    'category': 'Sales',
    'version': '0.1',
    'depends': ['base','product','sale','account','point_of_sale','account','l10n_ar_fpoc_pos'],
    'data': [
	'security/ir.model.access.csv',
	'security/security.xml',
	'wizard/wizard_view.xml',
	'sale_view.xml',
	'report/pos_order_details.xml',
	'report/pos_session_detail.xml',
	'report/pos_session_resume.xml',
	'report/pos_small_report.xml',
	'report/pos_order_installments.xml'
    ],
    'demo': [],
    'qweb': [],
    'installable': True,
}
