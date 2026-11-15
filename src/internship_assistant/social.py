"""LinkedIn URL-only discovery. This module never requests LinkedIn content."""
import re
from urllib.parse import urlsplit
from .core import now


def is_linkedin(url):
    host=(urlsplit(url).hostname or '').lower()
    return host=='linkedin.com' or host.endswith('.linkedin.com') or host=='lnkd.in'


def linkedin_identity(url):
    p=urlsplit(url)
    if not is_linkedin(url) or p.scheme!='https' or p.username or p.password:
        raise ValueError('A public HTTPS LinkedIn URL is required')
    if p.hostname=='lnkd.in':
        if not p.path.strip('/'):raise ValueError('A specific short link is required')
        return 'linkedin:short:'+p.path.strip('/')
    if '/jobs/view/' in p.path:
        tail=p.path.split('/jobs/view/',1)[1].strip('/')
        if not tail:raise ValueError('A specific job URL is required')
        id=re.search(r'(\d+)$',tail)
        return 'linkedin:job:'+(id[1] if id else tail)
    id=re.search(r'(?:activity[-:]|urn:li:activity:)(\d+)',p.path)
    if id:return 'linkedin:post:'+id[1]
    if p.path.startswith(('/posts/','/feed/update/')) or re.fullmatch(r'/company/[^/]+/posts/?',p.path):
        return 'linkedin:post:'+p.path.rstrip('/')
    raise ValueError('Use a public job/post URL, not LinkedIn search, login or profile automation')


def ingest_linkedin(state,hit,config):
    from .discovery_store import clean_url
    from .evidence import internship_role
    linkedin_identity(hit['url'])
    url=clean_url(hit['url'])
    source=hit.get('source_url') or hit.get('discovered_from') or url
    for field in ('title','company_name','location_hint','source_url'):
        if field in hit and (not isinstance(hit[field],str) or len(hit[field])>2000):raise ValueError('Invalid lead metadata')
    if hit.get('source_url'):clean_url(hit['source_url'])
    if not isinstance(hit.get('title',''),str) or len(hit.get('title',''))>1000:raise ValueError('Invalid lead title')
    applications=hit.get('application_urls',[])
    if not isinstance(applications,list) or len(applications)>10:raise ValueError('At most ten published application links')
    for target in applications:
        from .network import diagnostic_url
        diagnostic_url(target)
    candidate=state.enqueue(dict(hit,kind='linkedin_lead',authority='unverified',
        record_class='potential_lead',verification_status='Unverified LinkedIn URL; manual review required'),config)
    if candidate is None:return None
    title=hit.get('title','')
    if title and internship_role(title,hit.get('requirements','')):
        state.store.upsert({'company':hit.get('company_name') or 'Unknown employer (LinkedIn lead)',
            'title':title,'city':'Unknown','location_hint':hit.get('location_hint','Unknown'),
            'source_url':url,'source_observed_only':True,'discovery_method':'linkedin_lead',
            'external_id':linkedin_identity(url),
            'record_class':'potential_lead','availability':'Unknown','eligibility':'Unknown','evidence':'',
            'verification_status':'Unverified LinkedIn lead; content and employer identity not verified',
            'advertised_status':'Public URL only; no proof that applications are open',
            'employer_identity':'Unverified claim','apply_url':'','closes':'','opens':'',
            'attribution_url':source,'observed_at':now()})
    # Follow separately supplied/published official links as unverified candidates, with no
    # employer trust inherited from a social claim. The destination must verify itself.
    for target in hit.get('application_urls',[])[:10]:
        if not is_linkedin(target):
            state.enqueue({'url':target,'provider':'linkedin-associated-link','source_url':source,
                'title':title,'authority':'unverified'},config)
    candidate.update(record_class='potential_lead',verification_status='Unverified LinkedIn URL; manual review required')
    state.finish(candidate,config,'needs_review',fetched=False)
    return candidate


def import_linkedin_leads(store,leads,config=None):
    from .discovery import load_config
    from .discovery_store import DiscoveryStore
    if not isinstance(leads,list) or len(leads)>100:raise ValueError('Import at most 100 public URL leads')
    state=DiscoveryStore(store);config=config or load_config();accepted=[];errors=[]
    for index,lead in enumerate(leads):
        try:
            if not isinstance(lead,dict):raise ValueError('Each lead must be an object')
            allowed={k:lead[k] for k in ('url','title','company_name','location_hint','application_urls','source_url') if k in lead}
            allowed['provider']='permitted-url-import'
            candidate=ingest_linkedin(state,allowed,config)
            if candidate:accepted.append(candidate['id'])
        except (ValueError,KeyError,TypeError):
            errors.append({'index':index,'error':'Invalid public LinkedIn lead or application URL'})
    return {'accepted':accepted,'errors':errors,'note':'URL-only leads; no LinkedIn requests, notifications or applications performed'}
