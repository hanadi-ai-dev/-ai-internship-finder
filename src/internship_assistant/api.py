import os
import secrets
from threading import Lock
from fastapi import FastAPI, Header, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from .core import Store, demo
from .sources import discover, monitor
from .integrations import notify, sheet_sync, recommendation
from . import applications

app = FastAPI(title='AI Internship Assistant', version='0.4.0')
lock = Lock()

def auth(authorization: str = Header(default='')):
    token = os.getenv('API_TOKEN', '')
    if not token or not secrets.compare_digest(authorization, 'Bearer ' + token):
        raise HTTPException(401, 'A configured bearer token is required')

def run(fn):
    with lock:
        store = Store()
        try:
            return fn(store)
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e)) from None
        except Exception:
            raise HTTPException(502, 'Integration failed. Check configuration and provider status; credentials are never included in responses.') from None
        finally:
            store.db.close()

@app.get('/health')
def health():
    return {'status':'ok', 'demo':demo(), 'email_sending_enabled':not demo() and os.getenv('EMAIL_SENDING_ENABLED', 'false').lower() == 'true'}

@app.get('/opportunities', dependencies=[Depends(auth)])
def opportunities():
    return run(lambda s:s.all())

@app.get('/companies', dependencies=[Depends(auth)])
def companies():
    return run(lambda s:sorted(s.all('companies'),key=lambda c:-c.get('priority_score',30)))

@app.get('/discovery/status', dependencies=[Depends(auth)])
def discovery_status():
    from .discovery_store import DiscoveryStore
    return run(lambda s: DiscoveryStore(s).status())

@app.get('/discovery/candidates', dependencies=[Depends(auth)])
def discovery_candidates(limit: int = Query(default=100, ge=1, le=1000)):
    from .discovery_store import DiscoveryStore
    return run(lambda s: DiscoveryStore(s).candidates(limit))

class LeadImport(BaseModel):
    leads: list[dict] = Field(max_length=100)

@app.post('/discovery/leads', dependencies=[Depends(auth)])
def lead_import(body:LeadImport):
    from .social import import_linkedin_leads
    return run(lambda s:import_linkedin_leads(s,body.leads))

@app.post('/discovery/diagnose', dependencies=[Depends(auth)])
def priority_diagnostics():
    if demo():return {'demo':True,'status':'disabled','targets':[]}
    from .network import diagnose_targets
    return diagnose_targets()

@app.post('/discover', dependencies=[Depends(auth)])
def discovery():
    if demo():
        return {'demo':True, 'companies':[], 'note':'Live discovery disabled in demo'}
    return run(discover)

@app.post('/monitor', dependencies=[Depends(auth)])
def monitoring():
    if demo():
        from .cli import load_demo
        return run(load_demo)
    return run(monitor)

@app.post('/notify/{mode}', dependencies=[Depends(auth)])
def notifications(mode: str):
    return run(lambda s:notify(s, mode))

@app.post('/sync', dependencies=[Depends(auth)])
def sync():
    return run(sheet_sync)

class Tracking(BaseModel):
    status: str
    follow_up: str = ''

@app.patch('/opportunities/{id}', dependencies=[Depends(auth)])
def tracking(id:str, body:Tracking):
    return run(lambda s:s.status(id, body.status, body.follow_up))

@app.get('/opportunities/{id}/recommendation', dependencies=[Depends(auth)])
def recommend(id:str):
    def action(s):
        item = s.get(id)
        if not item:
            raise ValueError('Unknown opportunity')
        return recommendation(item)
    return run(action)

class Draft(BaseModel):
    opportunity_id: str
    applicant_summary: str = Field(min_length=1, max_length=5000)

@app.post('/applications/draft', dependencies=[Depends(auth)])
def draft(body:Draft):
    return run(lambda s:applications.draft(s, body.opportunity_id, body.applicant_summary))

@app.post('/applications/{id}/approve', dependencies=[Depends(auth)])
def approve(id:str):
    return run(lambda s:applications.approve(s, id))

@app.post('/applications/{id}/send', dependencies=[Depends(auth)])
def send(id:str):
    return run(lambda s:applications.send(s, id))

@app.get('/applications', dependencies=[Depends(auth)])
def application_list():
    return run(lambda s:s.all('applications'))
