import json,secrets
from pathlib import Path
assert env.cr.dbname=='evaluation'
env['ir.config_parameter'].sudo().set_param('picking_assistant.instance_name','local')
kind=env['stock.picking.type'].search([('code','=','outgoing')],limit=1)
assert kind
parent=kind.default_location_src_id
src=env['stock.location'].create({'name':'EVAL-20260910','usage':'internal','location_id':parent.id,'company_id':kind.company_id.id})
dest=kind.default_location_dest_id or env.ref('stock.stock_location_customers')
partner=env['res.partner'].create({'name':'Evaluation Testkunde','street':'Teststrasse 1','zip':'00000','city':'Testort','country_id':env.ref('base.de').id})
products=[]
for suffix in ['A','B']:
 p=env['product.product'].create({'name':'EVAL Artikel '+suffix,'default_code':'EVAL20260910'+suffix,'barcode':'EVAL20260910'+suffix,'type':'consu','is_storable':True,'tracking':'none'})
 env['stock.quant']._update_available_quantity(p,src,200)
 products.append(p)
users=[]
for i in range(2):
 pwd=secrets.token_urlsafe(24);groups=[env.ref('base.group_user').id,env.ref('stock.group_stock_user').id,env.ref('picking_assistant_integration.group_picker').id]
 groupfield='group_ids' if 'group_ids' in env['res.users']._fields else 'groups_id'
 user=env['res.users'].with_context(no_reset_password=True).create({'name':'Evaluation Picker '+str(i+1),'login':'evaluation-picker-'+str(i+1),'password':pwd,groupfield:[(6,0,groups)],'company_id':kind.company_id.id,'company_ids':[(6,0,[kind.company_id.id])]})
 users.append({'login':user.login,'password':pwd,'id':user.id})
pickings={}
for case in ['standard','shortage','overage','idempotency','parallel','invalid','failure','batch_a','batch_b']:
 moves=[(0,0,{'product_id':p.id,'product_uom_qty':5,'product_uom':p.uom_id.id,'location_id':src.id,'location_dest_id':dest.id}) for p in products]
 p=env['stock.picking'].create({'picking_type_id':kind.id,'location_id':src.id,'location_dest_id':dest.id,'partner_id':partner.id,'origin':'EVAL-20260910-'+case,'move_ids':moves})
 p.action_confirm();p.action_assign()
 assert len(p.move_line_ids)==2,(case,len(p.move_line_ids))
 pickings[case]={'id':p.id,'lines':[{'id':l.id,'product_id':l.product_id.id,'barcode':l.product_id.barcode,'quantity':l.quantity,'move_id':l.move_id.id} for l in p.move_line_ids]}
private={'users':users,'pickings':pickings,'location_id':src.id,'products':[p.id for p in products]}
Path('/tmp/evaluation-fixtures-private.json').write_text(json.dumps(private))
env.cr.commit()
print('EVAL_PUBLIC '+json.dumps({k:v for k,v in private.items() if k!='users'}))
