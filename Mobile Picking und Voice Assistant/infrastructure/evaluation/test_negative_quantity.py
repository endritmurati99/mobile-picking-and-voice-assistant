"""Predeclared boundary check: explicitly negative quantities should be rejected.
One synthetic, unpicked line in the isolated database. No production writes.
"""
import asyncio,json,uuid
from pathlib import Path
import httpx
from app.config import settings
from app.services.odoo_client import OdooClient
assert settings.odoo_db=='evaluation'
async def main():
 f=json.loads(Path('/tmp/evaluation-fixtures-private.json').read_text());o=OdooClient();p=f['pickings']['invalid'];l=p['lines'][0];u=f['users'][0]
 async with httpx.AsyncClient(base_url='http://localhost:8000/api/',timeout=90) as c:
  r=await c.post('auth/picker-session',headers={'Origin':'https://evaluation.local'},json={'login':u['login'],'password':u['password'],'device_id':str(uuid.uuid4()),'odoo_instance':'local'});assert r.status_code==200
  c.headers.update({'Origin':'https://evaluation.local','X-CSRF-Token':r.json()['csrf_token'],'Cookie':settings.session_cookie_name+'='+r.cookies.get(settings.session_cookie_name)})
  r=await c.post(f"pickings/{p['id']}/claim",json={},headers={'Idempotency-Key':str(uuid.uuid4())});assert r.status_code==200
  fields={'fields':['quantity','picked']};before=(await o.execute_kw('stock.move.line','read',[[l['id']]],fields))[0]
  r=await c.post(f"pickings/{p['id']}/confirm-line",json={'move_line_id':l['id'],'quantity':-1,'scanned_barcode':l['barcode']},headers={'Idempotency-Key':str(uuid.uuid4())})
  after=(await o.execute_kw('stock.move.line','read',[[l['id']]],fields))[0]
  result={'case':'T2d_negative_quantity_validation','expectation':'reject explicit negative quantity without writing the line','submitted_quantity':-1,'http':r.status_code,'business_success':r.json().get('success'),'before':before,'after':after,'status':'pass' if r.status_code in [400,422] and before==after else 'fail'}
  print(json.dumps(result))
  if result['status'] != 'pass':raise AssertionError('negative quantity was accepted or changed Odoo state')
 await o._client.aclose()
asyncio.run(main())
