"""Incremental search → evidence queue → official-site extraction pipeline."""
import hashlib
import json
import os
import time
import socket
import httpx
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from .core import demo, now
from .discovery_store import DiscoveryStore, host_key, url_key, later
from .search import APITransport, BraveSearch, WikidataSearch, query_tasks, ProviderError
from .extraction import organizations, page_links, public_contacts, extract_opportunities, structured, matching_employer, types
from .sources import Fetcher, sources


BOUNDS = {
    'search_requests_per_run':(0,50), 'results_per_page':(1,20), 'max_pages_per_query':(1,10),
    'provider_interval_seconds':(1,60), 'pages_per_run':(0,100), 'links_per_page':(1,50),
    'max_depth':(0,5), 'max_candidates':(1,100000), 'page_refresh_hours':(1,720),
    'search_refresh_hours':(1,720), 'error_retry_hours':(1,168), 'max_errors_per_run':(1,100),
    'run_budget_seconds':(10,600),
}


def load_config():
    with open(os.getenv('DISCOVERY_CONFIG','config/discovery.json')) as f:
        config = json.load(f)
    for name,(minimum,maximum) in BOUNDS.items():
        if type(config.get(name)) is not int or not minimum <= config[name] <= maximum:
            raise ValueError(f'Discovery config {name} must be {minimum}..{maximum}')
    for name in ('locations','sectors','fields','internship_terms','priority_targets','extra_queries','providers'):
        value = config.get(name)
        if not isinstance(value,list) or not all(isinstance(v,str) and 0 < len(v) <= 300 for v in value) or len(value) > 100:
            raise ValueError(f'Discovery config {name}: expected at most 100 nonempty strings')
    if not config['locations'] or not set(config['providers']) <= {'wikidata','brave'}:
        raise ValueError('Configure locations and only supported providers: wikidata, brave')
    combinations = len(config['locations']) * (len(config['sectors']) + len(config['fields']) * len(config['internship_terms']))
    if combinations + len(config['priority_targets']) + len(config['extra_queries']) > 10000:
        raise ValueError('Discovery query matrix exceeds 10,000 tasks; narrow configuration')
    return config


def seed_frontier(state, config):
    for source in sources():
        previous = next((c for c in state.store.all('companies') if url_key(c['url']) == url_key(source['url'])), {})
        authority = 'reviewed' if source.get('reviewed') is True else previous.get('authority','configured')
        company = state.store.company(dict(source, authority=authority,
            verification_status=previous.get('verification_status','Configured target; website verification pending')))
        state.enqueue({'url':source['url'],'title':source['name'],'location_hint':source['city'],
                       'sector':source.get('sector','Unknown'),'provider':'configured', 'authority':authority},config,company)


def run_search(state, config, providers, deadline=float('inf')):
    statuses, errors = {}, []
    tasks = {}
    for name in config['providers']:
        provider = providers[name]
        statuses[name] = {'status':'ready' if provider.available else 'missing_credentials','requests':0,'hits':0}
        if not provider.available:
            statuses[name]['detail'] = 'Set BRAVE_SEARCH_API_KEY securely; credential-free Wikidata remains independent'
            continue
        tasks[name] = query_tasks(config,name)
    added = 0
    names = list(tasks)
    # Round-robin providers; least-recently-attempted tasks within each provider.
    for slot in range(config['search_requests_per_run']):
        if not names or time.monotonic() >= deadline:
            break
        name = names[slot % len(names)]
        options = []
        for rank, task in enumerate(tasks[name]):
            id = 'search:' + name + ':' + hashlib.sha256(task['query'].encode()).hexdigest()
            progress = state.state(id)
            if progress.get('next_check','') <= now():
                options.append((progress.get('last_attempt',''),id,task,progress,rank))
        if not options:
            if not statuses[name]['requests']:
                blocked = [state.state('search:' + name + ':' + hashlib.sha256(t['query'].encode()).hexdigest()) for t in tasks[name]]
                statuses[name]['status'] = 'cooldown' if any(p.get('error') for p in blocked) else 'not_due'
            continue
        _, id, task, progress, _ = min(options,key=lambda entry:(entry[0],entry[4]))
        statuses[name]['requests'] += 1
        try:
            hits, more = providers[name].search(task,progress.get('page',0),config['results_per_page'])
            for hit in hits:
                try:
                    if state.enqueue(hit,config):
                        added += 1
                except (ValueError,TypeError):
                    # Unsupported/non-public URLs never become fetch targets.
                    statuses[name]['rejected_urls'] = statuses[name].get('rejected_urls',0) + 1
            statuses[name]['hits'] += len(hits)
            statuses[name]['status'] = 'ok'
            page = progress.get('page',0) + 1
            complete = not more or page >= config['max_pages_per_query']
            state.set_state(id,{'last_attempt':now(),'last_success':now(), 'page':0 if complete else page,
                                'next_check':later(config['search_refresh_hours']) if complete else now(), 'query':task['query']})
        except Exception as e:
            # Never persist arbitrary provider exception text, which may include API headers.
            error = str(e) if isinstance(e,ProviderError) else name + ': unexpected provider failure'
            statuses[name]['status'] = 'error'
            errors.append({'provider':name,'error':error})
            state.set_state(id,{**progress,'last_attempt':now(),'next_check':later(config['error_retry_hours']), 'error':error})
    return statuses, errors, added


def _company_by_id(store, id):
    return next((c for c in store.all('companies') if c['id'] == id),None)


def identify_company(store, candidate, page, config):
    url = candidate['url']
    def promote(company):
        ranks = {'unverified':0,'self_identified':1,'official_link':1,'wikidata_website_claim':2,'reviewed':3}
        authority = candidate.get('authority','unverified')
        if ranks.get(authority,0) > ranks.get(company.get('authority'),0) and authority in ('reviewed','wikidata_website_claim'):
            return store.company(dict(company,authority=authority,provenance=candidate['provenance'],
                name_aliases=[candidate.get('organization_name') or company['name']]))
        return company
    if candidate.get('company_id'):
        company = _company_by_id(store,candidate['company_id'])
        if company:
            return promote(company)
    # A known website cannot lose its identity when rediscovered through another provider.
    existing = next((c for c in store.all('companies') if host_key(c['url']) == host_key(url)),None)
    if existing:
        return promote(existing)
    orgs = organizations(page,url)
    self_identified = next((org for org in orgs if host_key(org['url']) == host_key(url)),None)
    authority = candidate.get('authority','unverified')
    if authority in ('reviewed','wikidata_website_claim') or self_identified:
        # Wikidata asserts the website; a search-only self-identification still needs ownership review.
        name = candidate.get('organization_name') or (self_identified or {}).get('name')
        if not name:
            return None
        home = urlunsplit(('https',urlsplit(url).netloc,'/','',''))
        return store.company({'name':name,'name_aliases':[self_identified['name']] if self_identified else [],
            'url':home,'city':'Unknown','location_hint':candidate.get('location_hint','Unknown'),
            'sector':candidate.get('sector','Unknown'),'entity_id':candidate.get('entity_id',''),
            'authority':authority if authority != 'unverified' else 'self_identified',
            'verification_status':'Website ownership unconfirmed' if authority == 'unverified' else 'Website claimed by ' + authority,
            'provenance':candidate['provenance'],'first_seen':candidate['first_seen'],
            'technical_department':'Unknown; potential outreach target', 'priority':1 if any(
                p.casefold() in (name + ' ' + candidate.get('location_hint','')).casefold() for p in config['priority_targets']) else 2})
    return None


def process_frontier(state, config, fetcher, deadline=float('inf')):
    counts = {'pages_fetched':0, 'pages_verified':0, 'companies_updated':0, 'opportunities_upserted':0, 'needs_review':0}
    errors = []
    # Bounded initial snapshot: newly discovered links are processed in the next incremental run.
    for candidate in state.candidates(config['pages_per_run'],due=True):
        if time.monotonic() >= deadline:
            break
        url = candidate['url']
        try:
            page = fetcher.page(url)
            counts['pages_fetched'] += 1
            url = getattr(page, 'source_url', None) or url
            candidate['resolved_url'] = url
            # Job boards/directories can publish employer websites even when they also
            # self-identify as an organization. Always stage those associations as leads.
            for org in organizations(page,url)[:config['links_per_page']]:
                if url_key(org['url']) != url_key(url):
                    state.enqueue({'url':org['url'],'title':org['name'],'provider':'structured-employer',
                        'source_url':url,'authority':'unverified'},config)
            company = identify_company(state.store,candidate,page,config)
            if company is None:
                # A third-party page may expose the employer's URL in public JSON-LD; stage it only.
                state.finish(candidate,config,'needs_review')
                counts['needs_review'] += 1
                continue
            trusted = company.get('authority') in ('reviewed','wikidata_website_claim')
            same_site = host_key(url) == host_key(company['url'])
            employer_matches = [matching_employer(n,company) for n in structured(page) if 'JobPosting' in types(n)]
            if not same_site and employer_matches and True not in employer_matches:
                state.finish(candidate,config,'needs_review')
                counts['needs_review'] += 1
                continue
            links = page_links(page,url,config['links_per_page'])
            contacts = public_contacts(page,url,trusted and (same_site or True in employer_matches))
            company = state.store.company(dict(company, last_attempt=now(), verified_at=now(), error='',
                verification_status='Official-source content fetched; website identity: ' + company['authority'] if trusted else 'Page fetched; website ownership unconfirmed',
                career_links=[l['url'] for l in links if l['career']],
                contact_emails=[c['email'] for c in contacts], contacts=contacts,
                provenance=candidate['provenance']))
            counts['companies_updated'] += 1
            if candidate.get('depth',0) < config['max_depth']:
                for link in links:
                    if url_key(link['url']) == url_key(url):
                        continue
                    # External career links are trusted only when actually linked by a known employer.
                    if host_key(url) != host_key(company['url']) and host_key(link['url']) != host_key(url):
                        continue
                    state.enqueue(dict(link,provider='official-link' if trusted else 'self-identified-link',
                        source_url=url,authority='unverified'),config,company,candidate.get('depth',0)+1)
            opportunities = extract_opportunities(page,url,company,trusted,config['locations'])
            for item in opportunities:
                try:
                    from .integrations import recommendation
                    item['recommendation'] = recommendation(item)
                except Exception:
                    # A model outage cannot discard a verified listing or block other sources.
                    item['recommendation'] = {'method':'unavailable','explanation':'AI analysis failed; listing retained'}
                state.store.upsert(item)
                counts['opportunities_upserted'] += 1
            candidate['company_id'] = company['id']
            state.finish(candidate,config,'verified' if trusted else 'needs_review')
            counts['pages_verified'] += int(trusted)
        except Exception as e:
            # Do not store exception URLs/headers. URL is already a validated public candidate.
            error = f'{type(e).__name__}: source fetch/extraction failed; review robots, URL and content'
            if isinstance(e,httpx.HTTPStatusError):
                error = f'HTTP {e.response.status_code}: source unavailable or access denied'
            elif isinstance(e,socket.gaierror):
                error = 'Public source DNS resolution failed'
            elif isinstance(e,httpx.ProxyError):
                error = 'Proxy transport unavailable; check outbound policy and proxy readiness'
            if isinstance(e,ValueError) and str(e) in ('robots.txt disallows source','Private network destination refused','Expected HTML','Source exceeds 2 MB limit'):
                error = str(e)
            state.finish(candidate,config,'error',error)
            errors.append({'source_url':url,'error':error})
            if len(errors) >= config['max_errors_per_run']:
                break
    return counts,errors


def run_discovery(store, config=None, providers=None, fetcher=None):
    if demo():
        return {'demo':True,'status':'disabled','note':'Live discovery is disabled in demo; no search/provider requests made'}
    config = config or load_config()
    deadline = time.monotonic() + config['run_budget_seconds']
    state = DiscoveryStore(store)
    seed_frontier(state,config)
    if providers is None:
        transport = APITransport(config['provider_interval_seconds'])
        providers = {'brave':BraveSearch(transport),'wikidata':WikidataSearch(transport)}
    statuses, errors, hits = run_search(state,config,providers,deadline)
    counts, page_errors = process_frontier(state,config,fetcher or Fetcher(),deadline)
    errors.extend(page_errors)
    partial = bool(errors) or any(s['status'] in ('error','missing_credentials','cooldown') for s in statuses.values())
    return state.report({'demo':False,'status':'partial' if partial else 'ok','providers':statuses,
        'candidate_hits_processed':hits,**counts,'errors':errors,'queue':state.status()['candidate_counts'],
        'budget_exhausted':time.monotonic() >= deadline,
        'queue_at_capacity':state.db.execute('SELECT count(*) FROM discovery_candidates').fetchone()[0] >= config['max_candidates']})


def refresh_discovered(store, config=None, fetcher=None):
    if demo():
        return {'demo':True,'status':'disabled'}
    state = DiscoveryStore(store)
    config = config or load_config()
    counts,errors = process_frontier(state,config,fetcher or Fetcher(),time.monotonic() + config['run_budget_seconds'])
    return {**counts,'errors':errors,'queue':state.status()['candidate_counts']}
