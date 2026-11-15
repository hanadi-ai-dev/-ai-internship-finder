import io
import json
import zipfile
from pathlib import Path
import httpx
import pytest
from bs4 import BeautifulSoup
from internship_assistant.core import Store
from internship_assistant.discovery import load_config,run_discovery,refresh_discovered,run_search,ingest_public_hit
from internship_assistant.discovery_store import DiscoveryStore
from internship_assistant.free_sources import (PublicSources,WikimediaSearch,parse_directory_archive,
    parse_internship_table,parse_feed,resource_hits,ats_resource,location_match)
from internship_assistant.search import APITransport,BraveSearch,query_tasks
from internship_assistant.integrations import recommendation,notify


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path));monkeypatch.setenv('DEMO_MODE','false')
    s=Store();yield s;s.db.close()


class NoNetwork:
    def page(self,*args): raise ValueError('No HTML in fixture')
    def document(self,*args): raise ValueError('No XML in fixture')


def transport(handler):
    return APITransport(client=httpx.Client(transport=httpx.MockTransport(handler)),sleep=lambda _:None)


def archive(*profiles):
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w') as z:
        for i,profile in enumerate(profiles):z.writestr(f'repo/src/companies/org-{i}.md',profile)
    return result.getvalue()


def profile(name,region,body):
    return f'---\ntitle: {name}\nwebsite: https://{name.lower()}.example/\ncareers_url: https://jobs.lever.co/{name.lower()}\nregion: {region}\n---\n{body}'


def test_default_workflow_needs_no_paid_key(config,monkeypatch):
    assert 'brave' not in config['providers']
    assert set(config['providers'])=={'public_sources','wikidata','wikimedia','overpass'}
    monkeypatch.setenv('BRAVE_SEARCH_API_KEY','old-key-must-not-be-used')
    monkeypatch.delenv('ENABLE_BRAVE_SEARCH',raising=False)
    assert not BraveSearch(transport(lambda _:pytest.fail('Brave was called'))).available
    monkeypatch.setenv('AI_API_KEY','old-key-must-not-be-used')
    monkeypatch.delenv('AI_PROVIDER',raising=False)
    monkeypatch.setattr('internship_assistant.integrations.httpx.post',lambda *a,**k:pytest.fail('Paid AI was called'))
    assert recommendation({'title':'تدريب علم البيانات','requirements':''})['category']=='Data Science'
    assert recommendation({'title':'تدريب الذكاء الاصطناعي'})['method']=='local'


def test_directory_discovers_companies_without_internships_and_respects_geography(config):
    body=archive(profile('Bank','other','Our technical office is in الرياض.'),
                 profile('Hospital','other','We have offices in Jeddah.'),
                 profile('Remote','worldwide','No local office evidence.'),
                 profile('Foreign','americas','US offices only.'))
    hits,stats=parse_directory_archive(body,config)
    assert {h['company_name'] for h in hits}=={'Bank','Hospital'}
    assert all(h['kind']=='company_lead' and h['authority']=='unverified' for h in hits)
    assert stats['profiles_read']==4
    config['include_remote_leads']=True
    hits,_=parse_directory_archive(body,config)
    assert {h['company_name'] for h in hits}=={'Bank','Hospital','Remote'}
    assert 'Saudi eligibility unverified' in next(h for h in hits if h['company_name']=='Remote')['location_hint']


def test_archive_paths_never_written_to_disk(config,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        z.writestr('../../outside.txt','unsafe path')
        z.writestr('repo/src/companies/company.md',profile('Org','other','Based in ثول.'))
    hits,_=parse_directory_archive(buffer.getvalue(),config)
    assert len(hits)==1 and list(tmp_path.iterdir())==[]


def test_public_source_pagination_cache_and_stats(config):
    calls=[]
    body=archive(*[profile(name,'other','Based in Riyadh.') for name in ['One','Two','Three']])
    source={'kind':'github_directory','name':'Fixture directory','url':'https://codeload.github.com/public/directory/zip/main'}
    p=PublicSources(transport(lambda r:(calls.append(r) or httpx.Response(200,content=body))),config,NoNetwork())
    first,more=p.search({'source':source},0,2)
    second,more2=p.search({'source':source},1,2)
    assert len(first)==2 and len(second)==1 and more and not more2
    assert len(calls)==1
    assert p.statistics['Fixture directory']['matching_company_leads']==3


def test_community_table_retains_only_target_locations_and_no_guessed_dates(config):
    text='''<table><tr><th>Company</th><th>Role</th><th>Location</th><th>Apply</th></tr>
    <tr><td>Example Bank</td><td>COOP Data Science</td><td>الرياض</td><td><a href="https://bank.example/jobs/1">Apply</a></td><td>1d</td></tr>
    <tr><td>↳</td><td>Software Internship</td><td>Jeddah</td><td><a href="https://bank.example/jobs/2">Apply</a></td></tr>
    <tr><td>Foreign</td><td>AI Intern</td><td>US Remote</td><td><a href="https://foreign.example/role">Apply</a></td></tr></table>'''
    hits,stats=parse_internship_table(text,config)
    assert len(hits)==2 and stats['rows_read']==3
    assert all(h['company_name']=='Example Bank' for h in hits)
    assert all('closes' not in h and 'eligibility' not in h for h in hits)


def test_rss_and_atom_bilingual_no_fabricated_employer_or_deadline(config):
    rss='''<rss><channel><item><title>تدريب تعاوني في الأمن السيبراني - جدة</title><link>https://org.example/jobs/1</link><guid>1</guid><description>التقديم للطلاب</description><pubDate>Monday</pubDate></item><item><title>AI Internship</title><link>https://foreign.example/jobs/1</link><description>New York only</description></item></channel></rss>'''
    hits,stats=parse_feed(rss,config)
    assert len(hits)==1 and hits[0]['company_name']=='' and hits[0]['posted_at']==''
    atom='''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Research Internship KAUST</title><link href="https://org.example/jobs/2"/><id>2</id><summary>Research training in Thuwal</summary></entry></feed>'''
    assert len(parse_feed(atom,config)[0])==1
    with pytest.raises(ValueError,match='entity'):
        parse_feed('<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><feed/>',config)


def test_wikimedia_real_api_contract_batches_entity_claims(config):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.host=='ar.wikipedia.org':
            assert request.url.params['gsrsearch']=='الرياض بنك'
            return httpx.Response(200,json={'query':{'pages':{'1':{'pageprops':{'wikibase_item':'Q123'}}}},'continue':{'gsroffset':10}})
        assert request.url.host=='www.wikidata.org' and request.url.params['ids']=='Q123'
        return httpx.Response(200,json={'entities':{'Q123':{'labels':{'ar':{'value':'بنك تجريبي'}},'claims':{'P856':[{'mainsnak':{'datavalue':{'value':'https://bank.example/'}}}]}}}})
    hits,more=WikimediaSearch(transport(handler)).search({'query':'الرياض بنك','language':'ar','location':'Riyadh'},0,10)
    assert len(calls)==2 and more
    assert hits[0]['title']=='بنك تجريبي' and hits[0]['authority']=='wikidata_website_claim'


def test_arabic_and_english_queries_have_separate_incremental_cursors(store,config):
    class Fake:
        available=True
        def __init__(self):self.calls=[]
        def search(self,task,*args):self.calls.append(task);return [],False
    config['providers']=['wikimedia'];config['search_requests_per_run']=2
    p=Fake();run_search(DiscoveryStore(store),config,{'wikimedia':p})
    assert {c['language'] for c in p.calls}=={'ar','en'}
    assert store.db.execute('SELECT count(*) FROM discovery_state').fetchone()[0]==2
    tasks=query_tasks(config,'wikimedia')
    assert any('الرياض' in t['query'] for t in tasks)


def test_greenhouse_and_lever_exact_public_endpoints_and_manual_only(config):
    company={'name':'Org','url':'https://org.example/','id':'org','authority':'reviewed'}
    def handler(request):
        if request.url.host=='boards-api.greenhouse.io':
            assert request.url.path=='/v1/boards/org/jobs'
            return httpx.Response(200,json={'jobs':[{'id':1,'title':'Data COOP Internship','content':'Training','location':{'name':'Riyadh'},'absolute_url':'https://boards.greenhouse.io/org/jobs/1'}, {'id':2,'title':'AI Intern','location':{'name':'US'},'absolute_url':'https://boards.greenhouse.io/org/jobs/2'}]})
        assert request.url.host=='api.lever.co' and request.url.params['mode']=='json'
        return httpx.Response(200,json=[{'id':'1','text':'تدريب الأمن السيبراني','descriptionPlain':'تدريب تعاوني','categories':{'location':'جدة'},'hostedUrl':'https://jobs.lever.co/org/1','applyUrl':'https://jobs.lever.co/org/1/apply','createdAt':0}])
    api=transport(handler)
    gh=resource_hits({'kind':'greenhouse','board':'org'},company,api,NoNetwork(),config)
    lever=resource_hits({'kind':'lever','board':'org'},company,api,NoNetwork(),config)
    assert len(gh)==1 and len(lever)==1
    assert gh[0]['provider']=='greenhouse' and lever[0]['apply_url'].endswith('/apply')
    assert not gh[0].get('closes') and not lever[0].get('email')
    assert ats_resource('https://job-boards.greenhouse.io/org/jobs/1')=={'kind':'greenhouse','board':'org'}
    assert ats_resource('https://jobs.lever.co/org/1')['board']=='org'
    assert ats_resource('https://jobs.lever.co/org/1')['region']=='global'
    assert ats_resource('https://example.org/org') is None


def test_feed_leads_go_to_existing_tracking_with_uncertainty_and_dedup(store,config,monkeypatch):
    state=DiscoveryStore(store)
    hit={'url':'https://org.example/jobs/1','title':'AI COOP','kind':'opportunity_lead','company_name':'Org',
        'source_url':'https://community.example/feed','provider':'public_sources','entry_id':'1','location_hint':'Riyadh'}
    ingest_public_hit(state,hit,config);ingest_public_hit(state,hit,config)
    assert len(store.all())==1
    item=store.all()[0]
    assert 'Unverified' in item['verification_status'] and item['eligibility']=='Unknown'
    assert item['closes']=='' and item['apply_url']=='https://org.example/jobs/1'
    store.status(item['id'],'Applied')
    ingest_public_hit(state,hit,config)
    assert store.get(item['id'])['status']=='Applied'
    monkeypatch.setenv('DEMO_MODE','true')
    messages=notify(store)
    assert len(messages)==1 and 'Unverified' in messages[0]['text']
    assert notify(store)==[]


def test_directory_provenance_does_not_invent_local_office_or_vacancy(store,config):
    state=DiscoveryStore(store)
    hit={'url':'https://org.example/','title':'Org','company_name':'Org','kind':'company_lead',
         'source_url':'https://public.example/directory','provider':'public_sources','career_url':'https://jobs.lever.co/org'}
    ingest_public_hit(state,hit,config)
    c=store.all('companies')[0]
    assert c['authority']=='directory_claim' and c['city']=='Unknown'
    assert not c.get('verified_at') and store.all()==[]
    candidate=next(c for c in state.candidates() if c.get('resource'))
    assert candidate['resource']['kind']=='lever'
    assert candidate['authority']!='official_link'


def test_official_page_discovers_free_ats_and_rss_without_board_guessing(store,config,monkeypatch):
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    company=store.company({'name':'Org','url':'https://org.example/','authority':'reviewed'})
    state=DiscoveryStore(store);state.enqueue({'url':company['url'],'title':'Org'},config,company)
    class Pages:
        def page(self,url):return BeautifulSoup('<a href="https://jobs.lever.co/actual-board">Careers</a><link rel="alternate" type="application/rss+xml" href="/jobs.rss">','html.parser')
    refresh_discovered(store,config,Pages())
    resources=[c['resource'] for c in state.candidates() if c.get('resource')]
    assert {'kind':'lever','board':'actual-board','region':'global','official_referral':True} in resources
    assert {'kind':'feed','url':'https://org.example/jobs.rss','official_referral':True} in resources


def test_default_free_sources_errors_are_explicit_not_synthetic(store,config,monkeypatch):
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    class Broken:
        available=True
        def search(self,*args):raise ValueError('Network unavailable')
    config['providers']=['public_sources'];config['search_requests_per_run']=1
    report=run_discovery(store,config,{'public_sources':Broken()},NoNetwork())
    assert report['status']=='partial' and report['providers']['public_sources']['status']=='error'
    assert store.all()==[] and report['pages_verified']==0


def test_demo_free_discovery_never_requests_public_sources(store,config,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','true')
    monkeypatch.setattr('internship_assistant.search.httpx.Client',lambda *a,**k:pytest.fail('Network client created'))
    assert run_discovery(store,config)['status']=='disabled'


def test_public_directory_and_feed_do_not_downgrade_stronger_evidence(store,config):
    employer=store.company({'name':'Org','url':'https://org.example/','city':'Riyadh','authority':'reviewed',
        'verification_status':'Official-source content fetched'})
    state=DiscoveryStore(store)
    ingest_public_hit(state,{'url':employer['url'],'title':'Org','company_name':'Org','kind':'company_lead',
        'source_url':'https://directory.example/list','career_url':'https://jobs.lever.co/org'},config)
    assert store.all('companies')[0]['authority']=='reviewed'
    resource=next(c['resource'] for c in state.candidates() if c.get('resource'))
    assert not resource.get('official_referral')  # Directory association is not an official endorsement.
    original=store.upsert({'company':'Org','title':'AI COOP','city':'Unknown','source_url':'https://org.example/careers',
        'apply_url':'https://org.example/apply','eligibility':'Confirmed','evidence':'Explicit university summer dates allowed',
        'closes':'2027-03-01','verification_status':'Official-source content fetched'})
    ingest_public_hit(state,{'url':'https://org.example/apply','title':'AI COOP','company_name':'Org',
        'kind':'opportunity_lead','source_url':'https://community.example/feed'},config)
    assert len(store.all())==1
    current=store.get(original['id'])
    assert current['closes']=='2027-03-01' and current['eligibility']=='Confirmed'
    assert current['verification_status']=='Official-source content fetched'


def test_free_resource_ingestion_and_api_errors_preserve_safe_tracking(store,config,monkeypatch):
    monkeypatch.setattr('internship_assistant.discovery.sources',lambda:[])
    employer=store.company({'name':'Org','url':'https://org.example/','authority':'reviewed'})
    state=DiscoveryStore(store)
    state.enqueue({'url':'https://jobs.lever.co/org','resource':{'kind':'lever','board':'org','official_referral':True}},config,employer)
    monkeypatch.setattr('internship_assistant.discovery.resource_hits',lambda *a,**k:[{
        'url':'https://jobs.lever.co/org/1','title':'AI COOP','company_name':'Org','kind':'opportunity_lead',
        'source_url':'https://api.lever.co/v0/postings/org','provider':'lever','entry_id':'1','city':'Riyadh'}])
    result=refresh_discovered(store,config,NoNetwork())
    assert result['opportunities_upserted']==1 and result['pages_verified']==1
    assert store.all()[0]['source_trusted'] is True
    assert store.all()[0]['eligibility']=='Unknown' and store.all()[0]['closes']==''


def test_feed_provider_uses_robots_aware_document_fetcher(config):
    class Feed:
        def document(self,url):
            assert url=='https://org.example/jobs.rss'
            return '<rss><channel><item><title>AI COOP Riyadh</title><link>https://org.example/job</link></item></channel></rss>'
    p=PublicSources(transport(lambda _:pytest.fail('Wrong fetch route')),config,Feed())
    hits,_=p.search({'source':{'name':'Org published feed','kind':'feed','url':'https://org.example/jobs.rss'}},0,10)
    assert len(hits)==1 and hits[0]['source_url']=='https://org.example/jobs.rss'


def test_repeatable_check_reports_real_empty_matches_without_synthetic_results(config,monkeypatch):
    from internship_assistant.free_sources import check_free_sources
    monkeypatch.setenv('DEMO_MODE','false')
    class Checked:
        statistics={'Fixture':{'rows_read':50,'matching_opportunity_leads':0}}
        def search(self,*args):return [],False
    config['free_sources']=[{'name':'Fixture','kind':'internship_table','url':'https://raw.githubusercontent.com/owner/repo/main/README.md'}]
    result=check_free_sources(config,Checked())
    assert result['checks'][0]['status']=='ok' and result['checks'][0]['returned_leads']==0
    assert result['checks'][0]['statistics']['rows_read']==50


def test_compressed_public_responses_are_decoded_once_and_stream_bounded(monkeypatch):
    import gzip
    from internship_assistant.sources import Fetcher
    raw=json.dumps({'ok':True}).encode()
    api=transport(lambda _:httpx.Response(200,content=gzip.compress(raw),headers={'Content-Encoding':'gzip'}))
    assert api.get('test','https://public.example/data')=={'ok':True}
    f=Fetcher();monkeypatch.setattr(f,'safe',lambda _:None)
    f.client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=gzip.compress(b'<h1>Org</h1>'),headers={'Content-Encoding':'gzip','Content-Type':'text/html'})))
    assert f.request('https://org.example/').text=='<h1>Org</h1>'
    huge=transport(lambda _:httpx.Response(200,content=b'x'*12_000_001))
    with pytest.raises(ValueError,match='12 MB'):
        huge.get('test','https://public.example/data')


def test_free_configuration_rejects_ambiguous_remote_boolean(tmp_path,monkeypatch,config):
    config['include_remote_leads']='false'
    p=tmp_path/'bad.json';p.write_text(json.dumps(config))
    monkeypatch.setenv('DISCOVERY_CONFIG',str(p))
    with pytest.raises(ValueError,match='JSON boolean'):
        load_config()


def test_overpass_free_local_all_sector_inventory_and_odbl_attribution(config):
    from internship_assistant.free_sources import OverpassDirectory
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.host=='overpass-api.de'
        assert '21.2,39.0,21.9,39.5' in request.url.params['data']
        assert 'hospital' in request.url.params['data'] and '"office"' in request.url.params['data']
        return httpx.Response(200,json={'elements':[
            {'type':'node','id':1,'tags':{'name':'بنك محلي','amenity':'bank','website':'https://bank.example/'}},
            {'type':'way','id':2,'tags':{'name:en':'Hospital','amenity':'hospital','contact:website':'https://hospital.example/'}},
            {'type':'node','id':3,'tags':{'name':'No website','office':'company'}}]})
    p=OverpassDirectory(transport(handler),config)
    task={'location':'Jeddah','query':'Jeddah public organizations'}
    first,more=p.search(task,0,1);second,more2=p.search(task,1,1)
    assert len(calls)==1 and more and not more2
    assert first[0]['company_name']=='بنك محلي' and second[0]['sector']=='hospital'
    assert first[0]['source_url']=='https://www.openstreetmap.org/node/1'
    assert first[0]['attribution_url']=='https://www.openstreetmap.org/copyright'
    assert first[0]['authority']=='unverified' and 'unverified' in first[0]['location_hint']


def test_overpass_rejects_unbounded_queries_and_partial_results(config):
    from internship_assistant.free_sources import OverpassDirectory
    config['city_bounds']['Jeddah']=[-90,-180,90,180]
    p=OverpassDirectory(transport(lambda _:pytest.fail('Unbounded query made')),config)
    with pytest.raises(ValueError,match='bounds'):
        p.search({'location':'Jeddah','query':'x'},0,10)
    config['city_bounds']['Jeddah']=[21.2,39.0,21.9,39.5]
    p=OverpassDirectory(transport(lambda _:httpx.Response(200,json={'remark':'timed out','elements':[]})),config)
    with pytest.raises(ValueError,match='incomplete'):
        p.search({'location':'Jeddah','query':'x'},0,10)


def test_free_inventory_cursors_expand_past_web_search_page_cap(store,config):
    class Inventory:
        available=True
        def search(self,*args):return [],True
    config['providers']=['overpass'];config['search_requests_per_run']=1;config['locations']=['Jeddah'];config['max_pages_per_query']=1
    state=DiscoveryStore(store)
    run_search(state,config,{'overpass':Inventory()})
    run_search(state,config,{'overpass':Inventory()})
    progress=json.loads(store.db.execute('SELECT payload FROM discovery_state').fetchone()[0])
    assert progress['page']==2  # No permanent first-page-only coverage; full inventory rotates incrementally.


def test_read_only_cli_check_never_opens_tracking_database(monkeypatch,capsys):
    from internship_assistant.cli import main
    monkeypatch.setenv('DEMO_MODE','true')
    monkeypatch.setattr('sys.argv',['internships','free-source-check'])
    monkeypatch.setattr('internship_assistant.cli.Store',lambda:pytest.fail('Read-only check opened DB'))
    main()
    assert json.loads(capsys.readouterr().out)['status']=='disabled'
