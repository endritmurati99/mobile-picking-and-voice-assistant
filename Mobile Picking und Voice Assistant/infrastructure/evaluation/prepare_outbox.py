"""Test-fixture preparation only: quarantine unrelated work in isolated DB copy.
This is not a production recovery operation or measured delivery result.
"""
import asyncio,json
from app.config import settings
from app.services.odoo_client import OdooClient
assert settings.odoo_db=='evaluation' and 'bachelor-eval-odoo' in settings.odoo_url
async def main():
 o=OdooClient()
 alerts=await o.search_read('quality.alert.custom',[('description','ilike','EVAL-20260910-')],['id'],limit=100)
 jobs=await o.search_read('picking.assistant.integration.job',[('aggregate_model','=','quality.alert.custom'),('aggregate_res_id','in',[a['id'] for a in alerts])],['id'],limit=100)
 rows=await o.search_read('picking.assistant.outbox',[('state','in',['pending','leased']),('job_record_id','not in',[j['id'] for j in jobs])],['id'],limit=100000)
 if rows:await o.write('picking.assistant.outbox',[r['id'] for r in rows],{'state':'dead'})
 print(json.dumps({'fixture_preparation':'quarantine non-selected active rows in isolated copy only','rows_quarantined':len(rows),'selected_quality_jobs':len(jobs),'scope':'baseline copied events and unrelated synthetic shipping events excluded from T8'}))
 await o._client.aclose()
asyncio.run(main())
