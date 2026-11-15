import copy
import json
import os
import sqlite3
from pathlib import Path
import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from internship_assistant.core import Store
from internship_assistant.discovery import load_config, run_discovery, run_search, refresh_discovered
from internship_assistant.discovery_store import DiscoveryStore, clean_url, host_key, url_key
from internship_assistant.extraction import extract_opportunities, public_contacts, organizations, page_links, date_value
from internship_assistant.search import APITransport, BraveSearch, WikidataSearch, ProviderError, query_tasks
from internship_assistant.sources import Fetcher
from internship_assistant.integrations import notify, message
from internship_assistant.api import app


@pytest.fixture
def config():
    c = load_config()
    c.update(providers=['wikidata','brave'],locations=['Jeddah','Riyadh'],sectors=['bank','hospital'],fields=['AI'],internship_terms=['COOP'],
             priority_targets=['KAUST Thuwal','KACST Riyadh','Wadi Jeddah'],extra_queries=[],
             search_requests_per_run=2,pages_per_run=10)
    return c


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','false')
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.delenv('AI_API_KEY',raising=False)
    s = Store()
    yield s
    s.db.close()


class FakeProvider:
    available = True
    def __init__(self,hits):
        self.hits,self.calls = hits,[]
    def search(self,task,page,count):
        self.calls.append((task,page,count))
        return copy.deepcopy(self.hits),False


class FakeFetcher:
    def __init__(self,pages):
        self.pages,self.calls = pages,[]
    def page(self,url):
        self.calls.append(url)
        if url not in self.pages:
            raise ValueError('Fixture has no page')
        return BeautifulSoup(self.pages[url],'html.parser')


def job_html(title='AI COOP Internship',employer='Research Org',employer_url='https://org.example/',city='Riyadh',identifier='role-42'):
    return '<script type="application/ld+json">'+json.dumps({
        '@context':'https://schema.org','@type':'JobPosting','title':title,
        'description':'COOP students in AI may apply. Exact training dates depend on the university.',
        'hiringOrganization':{'@type':'Organization','name':employer,'url':employer_url},
        'jobLocation':{'address':{'addressLocality':city}},'identifier':{'value':identifier},
        'datePosted':'2026-11-01','validThrough':'2027-03-15T23:59:00+03:00'})+'</script><a href="/apply/42">Apply</a><p>Apply by email to <a href="mailto:careers@org.example">careers@org.example</a></p>'


def company(store):
    return store.company({'url':'https://org.example/','name':'Research Org','authority':'reviewed','city':'Riyadh'})


def test_query_coverage(config):
    tasks = query_tasks(config,'brave')
    text = '\n'.join(t['query'] for t in tasks)
    for term in ['Jeddah','Riyadh','bank','hospital','COOP','AI','KAUST','KACST','Wadi']:
        assert term in text
    assert len(query_tasks(config,'wikidata')) == 2


def test_brave_official_api_auth_pagination(monkeypatch):
    monkeypatch.setenv('ENABLE_BRAVE_SEARCH','true')
    monkeypatch.setenv('BRAVE_SEARCH_API_KEY','fixture-key-not-real')
    def handler(request):
        assert request.url.host == 'api.search.brave.com'
        assert request.headers['X-Subscription-Token'] == 'fixture-key-not-real'
        assert request.url.params['offset'] == '2'
        return httpx.Response(200,json={'web':{'results':[{'url':'https://org.example/job','title':'COOP','description':'search snippet'}]},'query':{'more_results_available':False}})
    transport = APITransport(client=httpx.Client(transport=httpx.MockTransport(handler)),sleep=lambda _:None)
    hits,more = BraveSearch(transport).search({'query':'Riyadh AI COOP','location':'Riyadh'},2,10)
    assert not more and hits[0]['authority'] == 'unverified'
    assert hits[0]['provider'] == 'brave'


def test_wikidata_no_key_and_safe_query():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'results':{'bindings':[{
            'website':{'value':'https://org.example/'},'orgLabel':{'value':'Research Org'},
            'org':{'value':'http://www.wikidata.org/entity/Q123'}}]}})
    p = WikidataSearch(APITransport(client=httpx.Client(transport=httpx.MockTransport(handler)),sleep=lambda _:None))
    hits,_ = p.search({'query':'Organizations','location':'Riyadh" } UNION { ?a ?b ?c'},1,10)
    query = requests[0].url.params['query']
    assert 'OFFSET 10' in query and '\\"' in query
    assert hits[0]['authority'] == 'wikidata_website_claim'
    assert p.available


def test_provider_retry_after_and_sanitized_failure(monkeypatch):
    sleeps,calls = [],[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'3'}) if len(calls)==1 else httpx.Response(200,json={'ok':True})
    transport = APITransport(client=httpx.Client(transport=httpx.MockTransport(handler)),sleep=sleeps.append)
    assert transport.get('test','https://api.example/') == {'ok':True}
    assert 3 in sleeps and len(calls)==2
    transport.client = httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(401,text='secret response')))
    with pytest.raises(ProviderError,match='HTTP 401') as error:
        transport.get('test','https://api.example/',headers={'Authorization':'secret header'})
    assert 'secret' not in str(error.value)


def test_long_retry_after_does_not_retry_early():
    calls=[]
    transport = APITransport(client=httpx.Client(transport=httpx.MockTransport(lambda r:(calls.append(r) or httpx.Response(429,headers={'Retry-After':'3600'})))),sleep=lambda _:None)
    with pytest.raises(ProviderError,match='cooldown'):
        transport.get('test','https://api.example/')
    assert len(calls)==1


def test_incremental_query_rotation_and_persisted_pages(store,config):
    state = DiscoveryStore(store)
    fake = FakeProvider([{'url':'https://org.example/','title':'Org','provider':'test'}])
    config['providers']=['wikidata']
    config['search_requests_per_run']=2
    run_search(state,config,{'wikidata':fake})
    assert len(fake.calls)==2
    assert len(state.candidates())==1  # same hit from two city queries
    run_search(state,config,{'wikidata':fake})
    assert len(fake.calls)==2  # completed queries retain their refresh TTL
    assert state.candidates()[0]['first_seen'] <= state.candidates()[0]['last_seen']
    fake.search=lambda task,page,count: ([],True)
    for row in store.db.execute('SELECT id FROM discovery_state').fetchall():
        state.set_state(row[0],{})
    run_search(state,config,{'wikidata':fake})
    assert all(json.loads(r[0])['page']==1 for r in store.db.execute('SELECT payload FROM discovery_state'))


def test_missing_brave_is_explicit_and_fallback_still_runs(store,config,monkeypatch):
    monkeypatch.setenv('ENABLE_BRAVE_SEARCH','true')
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    monkeypatch.delenv('BRAVE_SEARCH_API_KEY',raising=False)
    wiki = FakeProvider([])
    result = run_discovery(store,config,{'wikidata':wiki,'brave':BraveSearch(APITransport())},FakeFetcher({}))
    assert result['status']=='partial'
    assert result['providers']['brave']['status']=='missing_credentials'
    assert result['providers']['wikidata']['status']=='ok'
    assert wiki.calls
    assert DiscoveryStore(store).status()['last_run']['status']=='partial'


def test_demo_disables_all_network(store,config,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','true')
    def forbidden(*args,**kwargs):
        pytest.fail('network accessed in demo')
    monkeypatch.setattr('internship_assistant.discovery.seed_frontier',forbidden)
    assert run_discovery(store,config)['status']=='disabled'


def test_automatic_pipeline_no_hardcoded_company_list(store,config,monkeypatch):
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    config['providers']=['wikidata']
    fake = FakeProvider([{'url':'https://org.example/','title':'Research Org','location_hint':'Riyadh','provider':'wikidata','authority':'wikidata_website_claim','entity_id':'Q123'}])
    pages = FakeFetcher({'https://org.example/':'<h1>Research Org</h1><a href="/careers">Careers</a><a href="/contact">Contact</a>',
        'https://org.example/careers':job_html(),'https://org.example/contact':'<p>General enquiries <a href="mailto:info@org.example">Contact</a></p>'})
    first = run_discovery(store,config,{'wikidata':fake},pages)
    assert first['companies_updated']==1 and not store.all()
    assert len(store.all('companies'))==1  # no vacancy needed to retain employer
    second = refresh_discovered(store,config,pages)
    assert second['opportunities_upserted']==1
    item=store.all()[0]
    assert item['kind']=='COOP' and item['eligibility']=='Unknown'
    assert item['closes']=='2027-03-15' and item['opens']==''
    assert item['city']=='Riyadh' and item['email_kind']=='recruitment'
    assert item['recommendation']['method']=='local'
    assert item['verified_at'] and item['source_url']=='https://org.example/careers'
    assert any(c['kind']=='general' for c in store.all('companies')[0]['contacts'])
    assert second['errors']==[]
    before=len(pages.calls)
    refresh_discovered(store,config,pages)
    assert len(pages.calls)==before  # TTL refresh avoids repeat fetches


def test_unverified_search_site_not_promoted_as_official(store,config,monkeypatch):
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    config['providers']=['brave']
    fake=FakeProvider([{'url':'https://org.example/','title':'Search title','provider':'brave','authority':'unverified'}])
    html='<script type="application/ld+json">'+json.dumps({'@type':'Organization','name':'Research Org','url':'https://org.example/'})+'</script>'+job_html()
    result=run_discovery(store,config,{'brave':fake},FakeFetcher({'https://org.example/':html}))
    c=store.all('companies')[0]
    assert c['authority']=='self_identified'
    assert store.all()[0]['email_kind']=='general'  # ownership not verified => never recruitment sending
    assert 'unconfirmed' in message(store.all()[0])
    assert DiscoveryStore(store).candidates()[0]['state']=='needs_review'


def test_aggregator_exposes_employer_lead_without_inventing_vacancy(store,config,monkeypatch):
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    config['providers']=['brave']
    fake=FakeProvider([{'url':'https://board.example/job','provider':'brave','authority':'unverified'}])
    result=run_discovery(store,config,{'brave':fake},FakeFetcher({'https://board.example/job':job_html()}))
    assert result['needs_review']==1 and store.all()==[]
    assert any(c['url']=='https://org.example/' for c in DiscoveryStore(store).candidates())


def test_ats_employer_mismatch_rejected(store):
    c=company(store)
    for html in [job_html(employer='Other Employer',employer_url='https://other.example/'),
                 '<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'AI Internship'})+'</script>']:
        result=extract_opportunities(BeautifulSoup(html,'html.parser'),'https://ats.example/job',c,True,['Riyadh'])
        assert result==[]
    result=extract_opportunities(BeautifulSoup(job_html(),'html.parser'),'https://ats.example/job',c,True,['Riyadh'])
    assert len(result)==1


def test_generic_pages_not_invented_vacancies_and_html_uncertain(store):
    c=company(store)
    generic=BeautifulSoup('<h1>Careers</h1><p>We welcome internship enquiries</p>','html.parser')
    assert extract_opportunities(generic,'https://org.example/careers',c,True,['Riyadh'])==[]
    detail=BeautifulSoup('<main><h1>AI Summer Internship Program</h1><a href="/apply">Apply</a></main>','html.parser')
    item=extract_opportunities(detail,'https://org.example/program',c,True,['Riyadh'])[0]
    assert item['eligibility']=='Unknown' and item['closes']=='' and 'unconfirmed' in item['verification_status']
    assert item['city']=='Unknown'


def test_contacts_and_dates_never_guessed():
    page=BeautifulSoup('<p>General contact <a href="mailto:info@org.example">Email</a></p><p>Apply by email to <a href="mailto:recruit@org.example">recruit@org.example</a></p><p>careers@imagined.example is not a published mailto</p>','html.parser')
    contacts=public_contacts(page,'https://org.example/',True)
    assert {c['email']:c['kind'] for c in contacts}=={'info@org.example':'general','recruit@org.example':'recruitment'}
    assert all(c['kind']=='general' for c in public_contacts(page,'https://org.example/',False))
    assert date_value('15/03/2027')==''
    assert date_value('2027-02-30')==''
    assert date_value('2027-03-15T12:00:00Z')=='2027-03-15'


def test_cross_source_dedup_keeps_status_application_and_new_cohort(store):
    original={'company':'Research Org','company_url':'https://org.example/','title':'AI COOP Internship','city':'Riyadh',
        'source_url':'https://org.example/careers/42','external_id':'42','posted_at':'2026-01-01'}
    first=store.upsert(original)
    store.status(first['id'],'Interview','2027-01-01')
    second=store.upsert(dict(original,source_url='https://ats.example/jobs/42?utm_source=search'))
    assert second['id']==first['id'] and second['status']=='Interview'
    assert second['follow_up']=='2027-01-01'
    assert len(store.all())==1 and len(second['source_urls'])==2
    newer=store.upsert(dict(original,posted_at='2027-01-01'))
    assert newer['id']!=first['id'] and newer['status']=='Not Applied'
    assert len(store.all())==2
    assert store.upsert(dict(original,posted_at='2027-01-01'))['id']==newer['id']


def test_company_domain_aliases_and_query_params(store):
    a=store.company({'name':'Research Org','url':'https://www.org.example/','provenance':[{'provider':'one'}]})
    b=store.company({'name':'Research Org','url':'https://org.example/','provenance':[{'provider':'two'}]})
    assert a['id']==b['id'] and len(store.all('companies'))==1
    assert len(b['provenance'])==2
    assert url_key('https://www.org.example/path/?utm_campaign=x&id=42#anchor')==url_key('https://org.example/path?id=42')
    assert url_key('https://org.example/path?id=42')!=url_key('https://org.example/path?id=43')
    with pytest.raises(ValueError):
        clean_url('https://user:password@org.example/')


def test_error_backoff_and_no_fake_verification_timestamp(store,config):
    state=DiscoveryStore(store)
    state.enqueue({'url':'https://org.example/','provider':'test'},config)
    result=refresh_discovered(store,config,FakeFetcher({}))
    candidate=state.candidates()[0]
    assert result['errors'] and candidate['state']=='error'
    assert not candidate.get('verified_at') and candidate['last_attempt']
    assert state.status()['due']==0


def test_company_notifications_dedup_even_after_reverification(store,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','true')
    company(store)
    assert len(notify(store))==1
    c=store.all('companies')[0]
    store.company(dict(c,verified_at='2099-01-01',last_attempt='2099-01-01'))
    assert notify(store)==[]


def test_discovery_api_auth_and_bounded_candidates(store,monkeypatch):
    monkeypatch.setenv('API_TOKEN','fixture-api-token')
    client=TestClient(app)
    assert client.get('/discovery/status').status_code==401
    headers={'Authorization':'Bearer fixture-api-token'}
    assert client.get('/discovery/status',headers=headers).json()['last_run'] is None
    assert client.get('/discovery/candidates?limit=1001',headers=headers).status_code==422


def test_config_validation(tmp_path,monkeypatch):
    c=load_config(); c['pages_per_run']=1000000
    path=tmp_path/'config.json'; path.write_text(json.dumps(c))
    monkeypatch.setenv('DISCOVERY_CONFIG',str(path))
    with pytest.raises(ValueError,match='pages_per_run'):
        load_config()


def test_fetcher_redirect_checks_robots_for_destination(monkeypatch):
    fetcher=Fetcher()
    monkeypatch.setattr(fetcher,'safe',lambda _:None)
    monkeypatch.setattr('internship_assistant.sources.time.sleep',lambda _:None)
    calls=[]
    def request(url):
        calls.append(url)
        if url.endswith('/robots.txt'):
            return httpx.Response(200,text='User-agent: *\nDisallow: /blocked',request=httpx.Request('GET',url))
        return httpx.Response(302,headers={'Location':'https://other.example/blocked'},request=httpx.Request('GET',url))
    monkeypatch.setattr(fetcher,'request',request)
    with pytest.raises(ValueError,match='robots'):
        fetcher.page('https://org.example/start')
    assert calls==['https://org.example/robots.txt','https://org.example/start','https://other.example/robots.txt']


def test_fetcher_stream_limit_and_404_robots(monkeypatch):
    f=Fetcher()
    monkeypatch.setattr(f,'safe',lambda _:None)
    monkeypatch.setattr('internship_assistant.sources.time.sleep',lambda _:None)
    def handler(request):
        if request.url.path=='/robots.txt':
            return httpx.Response(404)
        return httpx.Response(200,headers={'Content-Type':'text/html'},text='<h1>Company</h1>')
    f.client=httpx.Client(transport=httpx.MockTransport(handler))
    assert f.page('https://org.example/').h1.text=='Company'
    f.client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=b'x'*2_000_001)))
    with pytest.raises(ValueError,match='2 MB'):
        f.request('https://org.example/large')


def test_legacy_migration_preserves_ids_statuses_and_applications(tmp_path):
    path=tmp_path/'legacy.sqlite'
    db=sqlite3.connect(path)
    db.executescript('CREATE TABLE opportunities(id TEXT PRIMARY KEY,payload TEXT NOT NULL,fingerprint TEXT NOT NULL); CREATE TABLE applications(id TEXT PRIMARY KEY,payload TEXT NOT NULL);')
    old={'id':'legacy-id','company':'Org','title':'AI COOP','city':'Riyadh','source_url':'https://org.example/job',
         'apply_url':'https://org.example/apply/42','status':'Interview','follow_up':'2027-01-01','fingerprint':'old'}
    db.execute('INSERT INTO opportunities VALUES(?,?,?)',('legacy-id',json.dumps(old),'old'))
    db.execute('INSERT INTO applications VALUES(?,?)',('legacy-id',json.dumps({'id':'legacy-id','state':'draft'})))
    db.commit();db.close()
    store=Store(path)
    updated=store.upsert(dict(old,source_url='https://ats.example/job/42'))
    assert updated['id']=='legacy-id' and updated['status']=='Interview'
    assert updated['follow_up']=='2027-01-01' and len(store.all())==1
    assert store.all('applications')[0]['id']=='legacy-id'
    assert store.db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0]==1
    store.db.close()
    restored=Store(path)
    assert restored.get('legacy-id')['status']=='Interview'
    restored.db.close()


def test_source_timestamps_and_advisory_ai_dont_repeat_alerts(store,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','true')
    item={'company':'Org','title':'AI COOP','source_url':'https://org.example/job','external_id':'42',
          'recommendation':{'score':40,'method':'local'}}
    first=store.upsert(item)
    assert len(notify(store))==1
    second=store.upsert(dict(item,source_url='https://ats.example/42',recommendation={'score':60,'method':'AI'}))
    assert first['id']==second['id'] and len(second['source_verifications'])==2
    assert second['last_verified_source_url']=='https://ats.example/42'
    assert second['fingerprint']==first['fingerprint']
    assert notify(store)==[]


def test_company_alert_budget_and_search_html_rejection(store,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','true')
    monkeypatch.setenv('COMPANY_ALERTS_PER_RUN','1')
    for host in ('one','two'):
        store.company({'name':host,'url':f'https://{host}.example/'})
    assert len(notify(store))==1
    assert len(notify(store))==1
    assert notify(store)==[]
    for url in ('https://www.google.com/search?q=test','https://duckduckgo.com/?q=test'):
        with pytest.raises(ValueError,match='Search result HTML'):
            clean_url(url)


def test_ai_outage_does_not_lose_discovered_listing(store,config,monkeypatch):
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    monkeypatch.setattr('internship_assistant.integrations.recommendation',lambda _:(_ for _ in ()).throw(ValueError('provider unavailable')))
    config['providers']=['wikidata']
    provider=FakeProvider([{'url':'https://org.example/','title':'Research Org','provider':'wikidata','authority':'wikidata_website_claim'}])
    report=run_discovery(store,config,{'wikidata':provider},FakeFetcher({'https://org.example/':job_html()}))
    assert report['opportunities_upserted']==1
    assert store.all()[0]['recommendation']['method']=='unavailable'


def test_google_sync_includes_discovery_and_company_methods(store,monkeypatch):
    from internship_assistant.integrations import sheet_sync
    company(store)
    state=DiscoveryStore(store)
    state.enqueue({'url':'https://org.example/','provider':'test'},load_config())
    monkeypatch.setenv('GOOGLE_SHEET_ID','fixture-sheet')
    monkeypatch.setattr('google.auth.default',lambda **kwargs:(object(),None))
    posts=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'sheets':[]}
    class Session:
        def __init__(self,*args): pass
        def get(self,*args,**kwargs): return Response()
        def post(self,url,**kwargs):
            posts.append((url,kwargs['json']))
            return Response()
    monkeypatch.setattr('google.auth.transport.requests.AuthorizedSession',Session)
    result=sheet_sync(store)
    assert 'DiscoveryCandidates' in result['tabs'] and 'CompanyMethods' in result['tabs']
    write=next(data for url,data in posts if url.endswith('/values:batchUpdate'))
    assert write['valueInputOption']=='RAW'
    assert any(d['range']=='DiscoveryCandidates!A1' and len(d['values'])==2 for d in write['data'])


def test_candidate_cap_and_new_trusted_review(store,config):
    state=DiscoveryStore(store)
    config['max_candidates']=1
    first=state.enqueue({'url':'https://org.example/','provider':'brave'},config)
    state.finish(first,config,'needs_review')
    assert state.enqueue({'url':'https://other.example/'},config) is None
    assert state.status()['due']==0
    state.enqueue({'url':'https://org.example/','title':'Org','authority':'reviewed'},config)
    assert state.status()['due']==1


def test_explicit_new_cohort_across_sources_after_old_reimport(store):
    old={'company':'Org','title':'AI COOP','source_url':'https://org.example/job','external_id':'42','posted_at':'2026-01-01'}
    previous=store.upsert(old)
    new=store.upsert(dict(old,posted_at='2027-01-01'))
    store.upsert(old)
    copy_new=store.upsert(dict(old,posted_at='2027-01-01',source_url='https://ats.example/42'))
    assert copy_new['id']==new['id'] and copy_new['id']!=previous['id']
    assert len(store.all())==2


def test_multiple_jobs_same_page_dont_merge_different_locations_or_ids(store):
    base={'company':'Org','title':'AI COOP','source_url':'https://org.example/careers','city':'Riyadh','external_id':'role-1'}
    a=store.upsert(base)
    b=store.upsert(dict(base,city='Jeddah',external_id='role-2'))
    c=store.upsert(dict(base,external_id='role-3'))
    assert len({a['id'],b['id'],c['id']})==3
    assert len(store.all())==3
    assert store.upsert(dict(base,city='Jeddah',external_id='role-2'))['id']==b['id']


def test_wikidata_corroboration_promotes_self_identified_target(store,config,monkeypatch):
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    config['providers']=['brave']
    page='<script type="application/ld+json">'+json.dumps({'@type':'Organization','name':'Research Org','url':'https://org.example/'})+'</script>'+job_html()
    fetcher=FakeFetcher({'https://org.example/':page})
    run_discovery(store,config,{'brave':FakeProvider([{'url':'https://org.example/','provider':'brave'}])},fetcher)
    assert store.all('companies')[0]['authority']=='self_identified'
    state=DiscoveryStore(store)
    state.enqueue({'url':'https://org.example/','title':'Research Org','provider':'wikidata','authority':'wikidata_website_claim'},config)
    result=refresh_discovered(store,config,fetcher)
    assert result['pages_verified']==1
    assert store.all('companies')[0]['authority']=='wikidata_website_claim'
    assert store.all()[0]['email_kind']=='recruitment'


def test_ambiguous_identifier_reuse_with_different_titles_is_not_merged(store):
    base={'company':'Org','title':'AI COOP','source_url':'https://org.example/ai','external_id':'42'}
    first=store.upsert(base)
    other=store.upsert(dict(base,title='Software Internship',source_url='https://ats.example/software'))
    assert first['id']!=other['id'] and len(store.all())==2


def test_tracking_updates_do_not_repeat_discovery_alerts(store,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','true')
    raw={'company':'Org','title':'AI COOP','source_url':'https://org.example/job'}
    item=store.upsert(raw)
    assert len(notify(store))==1
    store.status(item['id'],'Applied','2027-01-01')
    updated=store.upsert(raw)
    assert updated['status']=='Applied' and updated['follow_up']=='2027-01-01'
    assert notify(store)==[]


def test_configured_priority_seeds_are_not_automatically_official(store,config,monkeypatch):
    source={'name':'Priority Org','city':'Thuwal','url':'https://org.example/'}
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[source])
    config['providers']=[]
    fetcher=FakeFetcher({'https://org.example/':job_html(employer='Priority Org')})
    run_discovery(store,config,{},fetcher)
    assert store.all('companies')[0]['authority']=='configured'
    assert store.all()[0]['email_kind']=='general'
    before=len(fetcher.calls)
    run_discovery(store,config,{},fetcher)
    assert len(fetcher.calls)==before  # repeated seeds do not defeat refresh TTL
    source['reviewed']=True
    run_discovery(store,config,{},fetcher)
    assert store.all('companies')[0]['authority']=='reviewed'
    assert store.all()[0]['email_kind']=='recruitment'
