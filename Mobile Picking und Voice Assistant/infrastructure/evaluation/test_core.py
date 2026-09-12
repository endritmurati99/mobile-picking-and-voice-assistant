"""Scenario evaluation against isolated backend + actual Odoo/PostgreSQL.
Run inside bachelor-eval-backend only. Fixtures are synthetic and private login
material lives only in the disposable containers. No human measurements.
"""
import asyncio,base64,json,time,uuid,logging
from pathlib import Path
import httpx
from app.services.odoo_client import OdooClient,OdooAPIError
from app.config import settings
assert settings.odoo_db=='evaluation' and 'bachelor-eval-odoo' in settings.odoo_url
F=json.loads(Path('/tmp/evaluation-fixtures-private.json').read_text())
RESULT=[]
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
class Session:
 def __init__(self,user):self.user=user;self.c=httpx.AsyncClient(base_url='http://localhost:8000/api/',timeout=90);self.csrf=''
 async def login(self):
  r=await self.c.post('auth/picker-session',headers={'Origin':'https://evaluation.local'},json={'login':self.user['login'],'password':self.user['password'],'device_id':str(uuid.uuid4()),'odoo_instance':'local'})
  assert r.status_code==200,'Synthetic picker login failed: '+str(r.status_code)
  self.csrf=r.json()['csrf_token'];self.c.headers.update({'Origin':'https://evaluation.local','X-CSRF-Token':self.csrf,'Cookie':settings.session_cookie_name+'='+r.cookies.get(settings.session_cookie_name)})
 async def post(self,path,key=None,**kw):return await self.c.post(path,headers={'Idempotency-Key':key or str(uuid.uuid4())},**kw)
async def case(name,fn):
 start=time.perf_counter()
 try:
  evidence=await fn();r={'case':name,'status':'observed' if name=='T2b_overpick_observation' else 'pass','evidence':evidence}
 except AssertionError as e:r={'case':name,'status':'fail','reason':str(e)}
 except Exception as e:r={'case':name,'status':'error','exception_type':type(e).__name__}
 r['elapsed_ms']=round((time.perf_counter()-start)*1000,1);RESULT.append(r);print(json.dumps(r),flush=True)
async def main():
 o=OdooClient();a=Session(F['users'][0]);b=Session(F['users'][1]);await a.login();await b.login()
 async def state(case):
  p=F['pickings'][case];rows=await o.execute_kw('stock.move.line','read',[[l['id'] for l in p['lines']]],{'fields':['id','quantity','picked']});pick=(await o.execute_kw('stock.picking','read',[[p['id']]],{'fields':['state']}))[0]
  return {'picking_state':pick['state'],'lines':rows}
 async def claim(case,s=a):
  r=await s.post(f"pickings/{F['pickings'][case]['id']}/claim",json={});assert r.status_code==200,'claim HTTP '+str(r.status_code);return r
 def payload(line,qty=5):return {'move_line_id':line['id'],'scanned_barcode':line['barcode'],'quantity':qty}
 async def confirm(case,idx=0,qty=5,s=a,key=None,body=None):return await s.post(f"pickings/{F['pickings'][case]['id']}/confirm-line",key=key,json=body or payload(F['pickings'][case]['lines'][idx],qty))
 async def security():
  path=f"pickings/{F['pickings']['invalid']['id']}/claim";codes={}
  async with httpx.AsyncClient(base_url='http://localhost:8000/api/') as c:
   r=await c.post(path,json={});codes['no_session']=r.status_code
  for name,headers in [('bad_origin',{'Origin':'https://untrusted.invalid','Idempotency-Key':str(uuid.uuid4())}),('no_csrf',{'X-CSRF-Token':'','Idempotency-Key':str(uuid.uuid4())}),('no_idempotency',{})]:
   r=await a.c.post(path,json={},headers=headers);codes[name]=r.status_code
  assert codes['no_session']==401,codes
  assert codes['bad_origin']==403 and codes['no_csrf']==403,codes
  assert codes['no_idempotency'] in [400,422],codes
  return codes
 await case('S1_session_origin_csrf_idempotency',security)
 async def standard():
  await claim('standard');r1=await confirm('standard');r2=await confirm('standard',1);st=await state('standard')
  assert r1.status_code==200 and r1.json().get('success') is True,'first line rejected'
  assert r2.status_code==200 and r2.json().get('picking_complete') is True,'last line did not complete picking: '+str(st)
  assert st['picking_state']=='done' and all(l['picked'] and l['quantity']==5 for l in st['lines']),st
  return {'http':[r1.status_code,r2.status_code],'final':st}
 await case('T1_standard_two_lines',standard)
 async def shortage():
  await claim('shortage');r=await confirm('shortage',qty=2);st=await state('shortage');assert r.status_code==200 and r.json().get('success') is True,'quantity deviation rejected'
  assert st['lines'][0]['quantity']==2 and st['lines'][0]['picked'] is True,st
  return {'http':r.status_code,'submitted_quantity':2,'demand':5,'final':st,'scope':'API only; no freely editable PWA actual-quantity field'}
 await case('T2a_partial_quantity_api',shortage)
 async def overage():
  await claim('overage');r=await confirm('overage',qty=6);st=await state('overage')
  return {'http':r.status_code,'success':r.json().get('success'),'submitted_quantity':6,'demand':5,'final':st,'assessment':'observation; specification must define overpick policy'}
 await case('T2b_overpick_observation',overage)
 async def alert(photo=False):
  desc='EVAL-20260910-'+('photo' if photo else 'text');data={'description':desc,'priority':'1','picking_id':str(F['pickings']['invalid']['id']),'product_id':str(F['products'][0]),'location_id':str(F['location_id'])}
  kw={'data':data}
  if photo:kw['files']=[('photos',('eval.png',PNG,'image/png'))]
  r=await a.post('quality-alerts',**kw);assert r.status_code==200,'quality HTTP '+str(r.status_code)
  records=await o.search_read('quality.alert.custom',[('description','=',desc)],['id','description','picking_id','product_id','ai_evaluation_status']);assert len(records)==1,'expected one alert'
  at=await o.search_read('ir.attachment',[('res_model','=','quality.alert.custom'),('res_id','=',records[0]['id'])],['id','mimetype','res_field'])
  assert records[0]['picking_id'][0]==F['pickings']['invalid']['id'],'picking reference mismatch'
  if photo:assert any(x['mimetype']=='image/png' for x in at),'PNG attachment missing'
  return {'http':r.status_code,'alert_id':records[0]['id'],'status':records[0]['ai_evaluation_status'],'attachment_count':len(at),'image_png_present':any(x['mimetype']=='image/png' for x in at)}
 await case('T3_quality_without_photo',lambda:alert(False));await case('T4a_quality_with_png',lambda:alert(True))
 async def rollback():
  desc='EVAL-20260910-rollback';before=await o.execute_kw('ir.attachment','search_count',[[('name','=','EVAL-rollback-first.png')]])
  failed=False
  try:await o.execute_kw('quality.alert.custom','api_create_alert',[{'description':desc,'photos':[{'filename':'EVAL-rollback-first.png','data_b64':base64.b64encode(PNG).decode()},{'filename':'EVAL-rollback-broken.png'}]}])
  except OdooAPIError:failed=True
  count=await o.execute_kw('quality.alert.custom','search_count',[[('description','=',desc)]])
  after=await o.execute_kw('ir.attachment','search_count',[[('name','=','EVAL-rollback-first.png')]])
  assert failed and count==0 and before==after,{'fault':failed,'alerts':count,'attachments_delta':after-before}
  return {'boundary':'direct real Odoo RPC; second photo deliberately lacks data_b64 after first attachment creation','rpc_rejected':failed,'alerts_retained':count,'attachments_delta':after-before}
 await case('T4b_transaction_rollback',rollback)
 async def replay():
  await claim('idempotency');key=str(uuid.uuid4());r=await confirm('idempotency',key=key);responses=await asyncio.gather(*(confirm('idempotency',key=key) for _ in range(10)));st=await state('idempotency')
  assert r.status_code==200 and r.json().get('success') is True,'initial booking failed'
  assert all(x.status_code==200 and x.json()==r.json() for x in responses),'replay payload/status mismatch'
  conflict=await confirm('idempotency',qty=4,key=key);assert conflict.status_code==409,'different-payload key reuse must conflict'
  assert st['lines'][0]['quantity']==5 and len(st['lines'])==2,st
  return {'replays':10,'matching_responses':10,'changed_payload_http':conflict.status_code,'final':st}
 await case('T5_same_key_replay_and_conflict',replay)
 async def parallel():
  p=F['pickings']['parallel'];r=await asyncio.gather(a.post(f"pickings/{p['id']}/claim",json={}),b.post(f"pickings/{p['id']}/claim",json={}));codes=[x.status_code for x in r];assert sorted(codes)==[200,409],codes
  owner=a if codes[0]==200 else b;other=b if owner is a else a
  denied=await confirm('parallel',s=other);hb=await other.post(f"pickings/{p['id']}/heartbeat",json={});ok=await confirm('parallel',s=owner)
  assert denied.status_code==409 and hb.status_code==409 and ok.status_code==200,{'denied':denied.status_code,'heartbeat':hb.status_code,'owner':ok.status_code}
  return {'simultaneous_claim_http':codes,'non_owner_write_http':denied.status_code,'non_owner_heartbeat_http':hb.status_code,'owner_write_http':ok.status_code,'final':await state('parallel')}
 await case('T6_two_picker_claim_race',parallel)
 async def wrong_barcode():
  await claim('invalid');before=await state('invalid');body=payload(F['pickings']['invalid']['lines'][0]);body['scanned_barcode']='EVAL-WRONG';r=await confirm('invalid',body=body);after=await state('invalid');assert r.status_code==200 and r.json().get('success') is False and before==after,'wrong barcode changed stock or was not rejected'
  return {'http':r.status_code,'business_success':False,'unchanged':True}
 await case('T7a_business_rejection_wrong_barcode',wrong_barcode)
 # Batch evidence is observed separately, without treating HTTP 200 as business completion.
 async def batch():
  ids=[F['pickings'][k]['id'] for k in ['batch_a','batch_b']]
  for k in ['batch_a','batch_b']:await claim(k)
  r=await a.post('cluster/batches',json={'picking_ids':ids});body=r.json()
  Path('/tmp/evaluation-batch-response.json').write_text(json.dumps(body))
  assert r.status_code==409,'preclaimed pickings should block batch creation'
  return {'http':r.status_code,'active_claims_block_batch_creation':True,'scope':'guard check; full batch flow follows after release'}
 await case('T9a_active_claims_block_batch',batch)
 for name in ['shortage','overage','idempotency','invalid','batch_a','batch_b']:
  released=await a.post(f"pickings/{F['pickings'][name]['id']}/release",json={})
  assert released.status_code==200,'fixture cleanup release failed: '+name
 Path('/tmp/evaluation-core-results.json').write_text(json.dumps(RESULT,indent=2))
 await a.c.aclose();await b.c.aclose();await o._client.aclose()
asyncio.run(main())
