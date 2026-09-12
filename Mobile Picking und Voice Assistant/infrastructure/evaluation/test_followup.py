"""Additional real-Odoo scenario checks; one explicitly injected lost write response."""
import asyncio,json,uuid
from pathlib import Path
import httpx
from app.config import settings
from app.services.odoo_client import OdooClient
assert settings.odoo_db=='evaluation'
F=json.loads(Path('/tmp/evaluation-fixtures-private.json').read_text());RESULT=[]
async def main():
 o=OdooClient();c=httpx.AsyncClient(base_url='http://localhost:8000/api/',timeout=90)
 u=F['users'][0]
 r=await c.post('auth/picker-session',headers={'Origin':'https://evaluation.local'},json={'login':u['login'],'password':u['password'],'device_id':str(uuid.uuid4()),'odoo_instance':'local'});assert r.status_code==200
 headers={'Origin':'https://evaluation.local','X-CSRF-Token':r.json()['csrf_token'],'Cookie':settings.session_cookie_name+'='+r.cookies.get(settings.session_cookie_name)};c.headers.update(headers)
 async def post(path,**kw):return await c.post(path,headers={'Idempotency-Key':str(uuid.uuid4())},**kw)
 async def getlines(key):return await o.execute_kw('stock.move.line','read',[[l['id'] for l in F['pickings'][key]['lines']]],{'fields':['id','quantity','picked','result_package_id']})
 async def claim(key):
  r=await post(f"pickings/{F['pickings'][key]['id']}/claim",json={});assert r.status_code==200,('claim',r.status_code)
 async def quantity_completion():
  await claim('shortage');p=F['pickings']['shortage'];l=p['lines'][1]
  r=await post(f"pickings/{p['id']}/confirm-line",json={'move_line_id':l['id'],'quantity':5,'scanned_barcode':l['barcode']})
  st=(await o.execute_kw('stock.picking','read',[[p['id']]],{'fields':['state']}))[0]
  back=await o.search_read('stock.picking',[('backorder_id','=',p['id'])],['id','state','move_ids'])
  residual=[]
  for b in back:
   moves=await o.execute_kw('stock.move','read',[b['move_ids']],{'fields':['product_id','product_uom_qty','state']});residual.extend({'product_id':m['product_id'][0],'quantity_demand':m['product_uom_qty'],'state':m['state']} for m in moves)
  return {'case':'T2c_partial_completion_and_backorder','status':'observed','http':r.status_code,'picking_complete':r.json().get('picking_complete'),'picking_state':st['state'],'backorder_count':len(back),'residual_moves':residual}
 RESULT.append(await quantity_completion())
 # Controlled transport failure AFTER the real stock.move.line.write has committed.
 from app.main import create_app
 from app.dependencies import get_picking_service
 from app.services.picking_service import PickingService
 app=create_app(settings);service=PickingService(o,None);original=o.write;injected=False
 async def lost_response(model,ids,vals):
  nonlocal injected
  value=await original(model,ids,vals)
  if model=='stock.move.line' and not injected:
   injected=True;raise httpx.ReadTimeout('EVAL injected response loss AFTER committed write')
  return value
 o.write=lost_response
 app.dependency_overrides[get_picking_service]=lambda:service
 await claim('failure');p=F['pickings']['failure'];l=p['lines'][0];key=str(uuid.uuid4());body={'move_line_id':l['id'],'quantity':5,'scanned_barcode':l['barcode']}
 async with app.router.lifespan_context(app):
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='https://evaluation.local/api/',headers=headers,timeout=90) as ac:
   r=await ac.post(f"pickings/{p['id']}/confirm-line",headers={'Idempotency-Key':key},json=body);after_failure=await getlines('failure')
   retry=await ac.post(f"pickings/{p['id']}/confirm-line",headers={'Idempotency-Key':key},json=body);after_retry=await getlines('failure')
 assert injected and r.status_code==500 and after_failure[0]['picked'] is True,'expected committed write with lost response'
 assert retry.status_code==200 and retry.json().get('success') is True and after_failure==after_retry,'retry changed already written line'
 RESULT.append({'case':'T7b_lost_response_after_committed_write','status':'pass','boundary':'FastAPI ASGI + real Odoo RPC, injected ReadTimeout immediately after write returns; no Caddy/browser','first_http':r.status_code,'persisted_despite_error':after_failure[0]['picked'],'retry_http':retry.status_code,'unchanged_on_retry':after_failure==after_retry,'scope':'non-final line; no general exactly-once guarantee'})
 # No claims before batch creation: that is deliberately rejected by its guard.
 ids=[F['pickings'][k]['id'] for k in ['batch_a','batch_b']]
 r=await post('cluster/batches',json={'picking_ids':ids});body=r.json()
 if r.status_code!=200:
  RESULT.append({'case':'T9b_batch_complete','status':'blocked','http':r.status_code,'reason':body.get('detail')})
 else:
  Path('/tmp/evaluation-batch-created.json').write_text(json.dumps(body));bid=body.get('batch_id') or body.get('id')
  assert bid,'batch id missing; inspect synthetic response keys'
  cases=[]
  # Check another picker cannot read the owner-bound batch.
  async with httpx.AsyncClient(base_url='http://localhost:8000/api/',timeout=90) as other:
   u2=F['users'][1];lr=await other.post('auth/picker-session',headers={'Origin':'https://evaluation.local'},json={'login':u2['login'],'password':u2['password'],'device_id':str(uuid.uuid4()),'odoo_instance':'local'});assert lr.status_code==200
   other.headers.update({'Origin':'https://evaluation.local','Cookie':settings.session_cookie_name+'='+lr.cookies.get(settings.session_cookie_name)})
   denied=await other.get(f'cluster/batches/{bid}')
  for k in ['batch_a','batch_b']:
   rows=await getlines(k)
   for i,l in enumerate(rows):
    base={'picking_id':F['pickings'][k]['id'],'move_line_id':l['id'],'scanned_barcode':F['pickings'][k]['lines'][i]['barcode'],'quantity':5,'scanned_package':str(l['result_package_id'][0])}
    if not cases:
     bad=await post(f'cluster/batches/{bid}/confirm-line',json={**base,'scanned_package':'EVAL-WRONG-BOX'})
     cases.append({'wrong_carton_http':bad.status_code,'wrong_carton_rejected':bad.json().get('success') is False})
    ok=await post(f'cluster/batches/{bid}/confirm-line',json=base);cases.append({'http':ok.status_code,'success':ok.json().get('success')})
  end=await post(f'cluster/batches/{bid}/validate',json={})
  pickings=await o.execute_kw('stock.picking','read',[ids],{'fields':['id','state']});lines=[l for k in ['batch_a','batch_b'] for l in await getlines(k)]
  per_picking=[{l['result_package_id'][0] for l in await getlines(k)} for k in ['batch_a','batch_b']]
  separate=len(per_picking[0])==len(per_picking[1])==1 and per_picking[0].isdisjoint(per_picking[1])
  good=denied.status_code==403 and cases[0]['wrong_carton_rejected'] and all(x['state']=='done' for x in pickings) and separate
  RESULT.append({'case':'T9b_batch_complete','status':'pass' if good else 'fail','creation_http':r.status_code,'batch_id':bid,'non_owner_read_http':denied.status_code,'line_checks':cases,'validate_http':end.status_code,'picking_states':[x['state'] for x in pickings],'distinct_packages_per_picking':separate,'scope':'two orders, four lines; no serial-tracked goods'})
 Path('/tmp/evaluation-followup-results.json').write_text(json.dumps(RESULT,indent=2))
 for result in RESULT:print(json.dumps(result))
 await c.aclose();await o._client.aclose()
 if any(result.get('status') in {'fail','failed','error','blocked'} for result in RESULT):raise AssertionError('followup case failed or remained blocked')
asyncio.run(main())
