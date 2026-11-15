import json
import socket
from pathlib import Path
import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from internship_assistant.core import Store
from internship_assistant.discovery import load_config,refresh_discovered
from internship_assistant.discovery_store import DiscoveryStore
from internship_assistant.extraction import extract_opportunities,matching_employer
from internship_assistant.evidence import internship_role,page_outcome
from internship_assistant.sources import Fetcher
from internship_assistant.network import SourceFailure,failure_detail,diagnose_targets
from internship_assistant.social import import_linkedin_leads,linkedin_identity
from internship_assistant.free_sources import parse_feed,resource_hits,ats_resource
from internship_assistant.quality import employer_priority
from internship_assistant.api import app

ORG={'name':'Research Org','url':'https://org.example/','id':'org','authority':'reviewed','city':'Riyadh'}


def parse(html,url='https://org.example/careers',trusted=True):
    return extract_opportunities(BeautifulSoup(html,'html.parser'),url,ORG,trusted,['Riyadh','Jeddah','Thuwal'])


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path));monkeypatch.setenv('DEMO_MODE','false');monkeypatch.delenv('AI_API_KEY',raising=False)
    s=Store();yield s;s.db.close()


def test_english_cards_scope_dates_contacts_and_applications():
    html='''<main><h1>Careers</h1>
    <article class="job-card" data-job-id="42"><h2>AI COOP Internship</h2><span class="location">Riyadh</span>
    <p>Deadline <time datetime="2030-04-01">1 April 2030</time></p><a href="https://jobs.example/42/apply">Apply now</a></article>
    <article class="job-card"><h2>Senior Software Engineer</h2><p>Mentor interns. Previous internship experience valued.</p><p>Deadline 2020-01-01</p><a href="https://jobs.example/full-time">Apply</a><p>Apply by email to <a href="mailto:other@org.example">other@org.example</a></p></article></main>'''
    rows=parse(html)
    assert len(rows)==1
    row=rows[0]
    assert row['closes']=='2030-04-01' and row['apply_url']=='https://jobs.example/42/apply'
    assert row['city']=='Riyadh' and row['email']==''
    assert row['eligibility']=='Unknown' and row['record_class']=='verified_announcement'
    assert row['external_id']=='42' and row['extraction_evidence']['layout']=='card'


def test_arabic_card_with_external_application_and_no_deadline_guess():
    rows=parse('''<div class="job-card"><h3>فرصة تدريب تعاوني في علم البيانات</h3><p>فتح باب التقديم لطلاب الجامعة</p>
    <span class="location">جدة</span><p>آخر موعد 15/03/2030</p><a href="https://jobs.smartrecruiters.com/Org/123">التقديم</a></div>''')
    assert len(rows)==1 and rows[0]['kind']=='COOP'
    assert rows[0]['record_class']=='verified_announcement'
    assert rows[0]['closes']=='' and rows[0]['city']=='جدة'
    assert rows[0]['apply_url'].startswith('https://jobs.smartrecruiters.com/')


def test_listing_tables_and_expired_rows_are_distinct_from_application_status(store):
    rows=parse('''<table><tr><th>Job title</th><th>Location</th><th>Deadline</th><th>Application</th></tr>
    <tr><td>Research Internship</td><td>Thuwal</td><td>2020-01-01</td><td><a href="https://org.example/research/apply">Apply</a></td></tr>
    <tr><td>Software Engineer</td><td>Riyadh</td><td>2030-01-01</td><td><a href="https://org.example/job">Apply</a></td></tr>
    <tr><td>Cybersecurity Summer Internship</td><td>Jeddah</td><td>2030-02-01</td><td><a href="https://org.example/security">Apply</a></td></tr></table>''')
    assert len(rows)==2
    assert rows[0]['record_class']=='closed' and rows[0]['availability']=='Closed'
    assert rows[1]['closes']=='2030-02-01' and rows[1]['record_class']=='verified_announcement'
    old=store.upsert(rows[0]);store.status(old['id'],'Applied');store.upsert(rows[0])
    assert store.get(old['id'])['status']=='Applied'


def test_arabic_listing_table_and_explicit_closure():
    row=parse('''<table><tr><th>المسمى الوظيفي</th><th>المدينة</th><th>آخر موعد</th><th>التقديم</th></tr>
    <tr><td>برنامج التدريب الصيفي في الذكاء الاصطناعي</td><td>الرياض</td><td>2030-06-01</td><td>انتهت فترة التقديم <a href="https://org.example/apply">التقديم</a></td></tr></table>''')[0]
    assert row['record_class']=='closed' and row['city']=='الرياض'
    assert row['closes']=='2030-06-01'  # Explicit closure overrides a future date.


def test_bilingual_detail_announcements_and_evergreen_programs():
    row=parse('''<main><h1>Summer Research Internship 2030</h1><p>Applications are now open for student interns.</p><a href="/apply/research">Apply</a></main>''')[0]
    assert row['record_class']=='verified_announcement' and row['availability']=='Open (source statement)'
    program=parse('<main><h1>AI Summer Internship Program</h1><p>About our student program.</p><a href="/interest">Apply</a></main>')[0]
    assert program['record_class']=='general_program' and program['closes']==''
    ar=parse('<main><h1>فرص تدريب صيفي للطلاب</h1><p>التقديم مفتوح</p><a href="/apply">قدم الآن</a></main>')[0]
    assert ar['record_class']=='verified_announcement'


@pytest.mark.parametrize('title,description',[
    ('Senior AI Engineer','Mentor interns and review internship applications.'),
    ('Internship Program Manager','Manage all student summer internships.'),
    ('COOP Coordinator','Coordinate university trainees.'),
    ('مدير برنامج التدريب الصيفي','الاشراف على المتدربين'),
    ('Software Engineer','Previous internship experience required.'),
    ('مدير تقنية المعلومات','خبرة في تدريب الموظفين ومتابعة المتدربين'),
    ('Cybersecurity Analyst','We offer internships elsewhere; this is a permanent analyst position.')])
def test_ordinary_jobs_do_not_borrow_internship_mentions(title,description):
    node={'@type':'JobPosting','title':title,'description':description,'employmentType':'FULL_TIME'}
    assert not internship_role(title,description,'FULL_TIME')
    assert parse('<script type="application/ld+json">'+json.dumps(node)+'</script>')==[]


def test_full_time_internship_and_coop_are_kept():
    assert internship_role('AI Internship','Full-time hours','FULL_TIME')
    assert internship_role('COOP Software Engineering','Six-month COOP','FULL_TIME')
    assert internship_role('تدريب تعاوني في البرمجيات')


def test_detail_only_card_is_review_lead_not_fabricated_apply_link():
    row=parse('<article><h2>AI Internship</h2><a href="/jobs/42">View details</a></article>')[0]
    assert row['record_class']=='potential_lead' and row['apply_url']==''
    assert row['canonical_job_url']=='https://org.example/jobs/42'


def test_unconfirmed_employer_site_is_not_verified_announcement():
    row=parse('<article><h2>AI Internship</h2><a href="/apply">Apply</a></article>',trusted=False)[0]
    assert row['record_class']=='potential_lead'


def test_employer_identity_conflicts_on_shared_ats_are_rejected():
    assert matching_employer({'hiringOrganization':{'name':'Research Org','url':'https://other.example/'}},ORG) is False
    assert matching_employer({'hiringOrganization':{'name':'Other','url':'https://org.example/'}},ORG) is False
    node={'@type':'JobPosting','title':'AI Internship','hiringOrganization':{'name':'Other','url':'https://other.example/'}}
    assert parse('<script type="application/ld+json">'+json.dumps(node)+'</script>','https://ats.example/jobs/1')==[]


def test_multiple_cards_do_not_share_global_apply_button():
    rows=parse('<main><h1>Careers</h1><a href="/global">Apply</a><article><h2>AI Internship</h2><a href="/jobs/1">Details</a></article><article><h2>Software COOP</h2><a href="/jobs/2">Details</a></article></main>')
    assert len(rows)==2 and all(row['apply_url']=='' for row in rows)


def test_cards_and_ats_duplicates_preserve_tracking(store):
    card=parse('<article data-job-id="42"><h2>AI Internship</h2><span class="location">Riyadh</span><a href="/jobs/42">Details</a></article>')[0]
    first=store.upsert(card);store.status(first['id'],'Interview')
    node={'@type':'JobPosting','title':'AI Internship','identifier':{'value':'42'},'jobLocation':{'address':{'addressLocality':'Riyadh'}}}
    detail=parse('<script type="application/ld+json">'+json.dumps(node)+'</script>','https://org.example/jobs/42')[0]
    second=store.upsert(detail)
    assert first['id']==second['id'] and second['status']=='Interview' and len(store.all())==1


def test_no_announcements_is_successful_content_outcome(store,monkeypatch):
    config=load_config();company=store.company(ORG);state=DiscoveryStore(store)
    state.enqueue({'url':company['url'],'title':company['name']},config,company)
    class Pages:
        def page(self,url):return BeautifulSoup('<main><h1>Careers</h1><p>No current internships announced.</p></main>','html.parser')
    report=refresh_discovered(store,config,Pages())
    assert not report['errors'] and not store.all()
    assert state.candidates()[0]['content_outcome']=='general_program'
    assert state.candidates()[0]['verified_at']


def test_linkedin_url_import_is_unverified_unfetched_and_deduplicated(store):
    leads=[{'url':'https://www.linkedin.com/jobs/view/ai-intern-123456','title':'AI Internship','company_name':'Claimed Org',
            'source_url':'https://publisher.example/feed','application_urls':['https://org.example/jobs/42']}]
    report=import_linkedin_leads(store,leads)
    assert len(report['accepted'])==1
    item=store.all()[0]
    assert item['record_class']=='potential_lead' and item['verified_at']=='' and item['apply_url']==''
    assert item['eligibility']=='Unknown' and item['employer_identity']=='Unverified claim'
    assert 'verified_at' not in item['source_verifications'][0]
    store.status(item['id'],'Waiting')
    other=dict(leads[0],url='https://sa.linkedin.com/jobs/view/123456')
    import_linkedin_leads(store,[other])
    assert len(store.all())==1 and store.all()[0]['status']=='Waiting'
    candidates=DiscoveryStore(store).candidates()
    social=next(c for c in candidates if 'linkedin.com' in c['url'])
    assert social['state']=='needs_review' and not social.get('fetched_at') and not social.get('verified_at')
    official=next(c for c in candidates if c['url']=='https://org.example/jobs/42')
    assert not official.get('company_id') and official['authority']=='unverified'


def test_linkedin_posts_and_feeds_use_permitted_metadata_only(store):
    a='https://www.linkedin.com/posts/example-coop-activity-1234567890-abcd'
    b='https://www.linkedin.com/feed/update/urn:li:activity:1234567890/'
    assert linkedin_identity(a)==linkedin_identity(b)
    feed=f'''<rss><channel><item><title>تدريب تعاوني في الذكاء الاصطناعي - الرياض</title><link>{a}</link><description><![CDATA[<a href="https://org.example/apply">Official application link</a>]]></description></item></channel></rss>'''
    hits,_=parse_feed(feed,load_config());assert len(hits)==1
    from internship_assistant.discovery import ingest_public_hit
    hit=dict(hits[0],source_url='https://publisher.example/jobs.rss')
    ingest_public_hit(DiscoveryStore(store),hit,load_config())
    assert store.all()[0]['verified_at']=='' and len(DiscoveryStore(store).candidates())==2


def test_linkedin_urls_never_reach_network_clients(store,monkeypatch):
    config=load_config();state=DiscoveryStore(store)
    state.enqueue({'url':'https://www.linkedin.com/jobs/view/123','title':'AI Internship'},config)
    class Forbidden:
        def page(self,*args):pytest.fail('LinkedIn was requested')
    report=refresh_discovered(store,config,Forbidden())
    assert report['needs_review']==1 and report['pages_fetched']==0 and store.all()[0]['verified_at']==''
    monkeypatch.setattr('internship_assistant.sources.socket.getaddrinfo',lambda *a,**k:pytest.fail('LinkedIn DNS requested'))
    with pytest.raises(SourceFailure,match='manual review'):Fetcher().safe('https://www.linkedin.com/posts/public-post')
    from internship_assistant.search import APITransport
    transport=APITransport(client=httpx.Client(transport=httpx.MockTransport(lambda _:pytest.fail('LinkedIn HTTP requested'))))
    with pytest.raises(ValueError,match='manual review'):transport.get('test','https://www.linkedin.com/jobs/view/123')


def test_linkedin_search_and_login_urls_rejected_without_db_mutation(store):
    for url in ['https://www.linkedin.com/jobs/search/?keywords=intern','https://www.linkedin.com/login','http://www.linkedin.com/jobs/view/123']:
        report=import_linkedin_leads(store,[{'url':url,'title':'AI Internship'}])
        assert report['errors'] and not report['accepted']
    assert not store.all()


def test_network_failure_categories_and_connection_retries(monkeypatch):
    f=Fetcher();monkeypatch.setattr(f,'safe',lambda _:None)
    monkeypatch.setattr('internship_assistant.sources.time.sleep',lambda _:None)
    calls=[]
    def handler(request):
        calls.append(request)
        if len(calls)<3:raise httpx.ConnectError('fixture transport error')
        return httpx.Response(200,text='ok')
    f.client=httpx.Client(transport=httpx.MockTransport(handler))
    assert f.request('https://org.example/').text=='ok' and len(calls)==3
    f.client=httpx.Client(transport=httpx.MockTransport(lambda _:(_ for _ in ()).throw(httpx.ConnectError('fixture'))))
    with pytest.raises(SourceFailure) as error:f.request('https://org.example/')
    assert error.value.code=='connection'
    monkeypatch.setattr('internship_assistant.sources.socket.getaddrinfo',lambda *a,**k:(_ for _ in ()).throw(socket.gaierror('fixture')))
    with pytest.raises(SourceFailure) as dns:Fetcher().safe('https://org.example/')
    assert dns.value.code=='dns_local'


def test_priority_diagnostics_distinguish_local_dns_from_proxy_denial():
    class DNSFailed:
        def safe(self,url):raise SourceFailure('dns_local','Local DNS unavailable','dns')
    client=httpx.Client(transport=httpx.MockTransport(lambda _:(_ for _ in ()).throw(httpx.ProxyError('403 Forbidden'))))
    report=diagnose_targets([{'name':'Org','url':'https://org.example/'}],DNSFailed(),client)
    row=report['targets'][0]
    assert row['local_dns']['code']=='dns_local'
    assert row['homepage_head']['code']=='proxy_access' and row['homepage_head']['http_status']==403
    assert row['content_verified'] is False


@pytest.mark.parametrize('mode,expected',[('robots','robots_disallowed'),('access','robots_http_access'),('format','unsupported_content')])
def test_robots_access_and_unsupported_content_have_distinct_codes(monkeypatch,mode,expected):
    f=Fetcher();monkeypatch.setattr(f,'safe',lambda _:None);monkeypatch.setattr('internship_assistant.sources.time.sleep',lambda _:None)
    def handler(request):
        if request.url.path=='/robots.txt':
            return httpx.Response(403 if mode=='access' else 200,text='User-agent: *\nDisallow: /' if mode=='robots' else 'User-agent: *\nAllow: /')
        return httpx.Response(200,headers={'Content-Type':'application/pdf'},content=b'%PDF')
    f.client=httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SourceFailure) as error:f.page('https://org.example/')
    assert error.value.code==expected


def test_failed_priority_targets_remain_retryable_with_error_details(store):
    config=load_config();company=store.company(dict(ORG,priority=1));state=DiscoveryStore(store)
    state.enqueue({'url':company['url']},config,company)
    class Failure:
        def page(self,url):raise SourceFailure('dns_local','Local DNS resolution failed','dns')
    report=refresh_discovered(store,config,Failure())
    candidate=state.candidates()[0]
    assert report['errors'][0]['detail']['code']=='dns_local'
    assert candidate['state']=='error' and not candidate.get('verified_at')
    assert state.status()['due']==0 and state.status()['failure_counts']['dns_local']==1
    assert len(store.all('companies'))==1


def test_employer_priority_keeps_all_sectors_but_reduces_diplomatic_noise():
    bank=employer_priority({'name':'Local Bank','sector':'Bank','city':'Riyadh'})
    hospital=employer_priority({'name':'Hospital','sector':'Healthcare','city':'Jeddah'})
    mission=employer_priority({'name':'Diplomatic Embassy','sector':'Government','city':'Riyadh'})
    priority=employer_priority({'name':'KAUST','city':'Thuwal','priority':1})
    assert priority['priority_score']>bank['priority_score']>mission['priority_score']
    assert hospital['priority_score']>mission['priority_score'] and mission['priority_reasons']


def test_smartrecruiters_anonymous_contract_and_no_application_url_invention():
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/postings'):
            return httpx.Response(200,json={'content':[{'id':'1','name':'AI COOP Internship','location':{'city':'Riyadh'},'releasedDate':'2030-01-01','ref':'https://api.smartrecruiters.com/v1/companies/Org/postings/1'}, {'id':'2','name':'Senior Engineer','location':{'city':'Riyadh'},'ref':'https://api.smartrecruiters.com/v1/companies/Org/postings/2'}]})
        return httpx.Response(200,json={'company':{'name':'Research Org'},'jobAd':{'sections':{'jobDescription':{'text':'Student training'}}}})
    from internship_assistant.search import APITransport
    transport=APITransport(client=httpx.Client(transport=httpx.MockTransport(handler)),sleep=lambda _:None)
    resource=ats_resource('https://careers.smartrecruiters.com/Org')
    assert resource=={'kind':'smartrecruiters','board':'Org'}
    hits=resource_hits(resource,ORG,transport,None,load_config())
    assert len(hits)==1 and len(calls)==2 and hits[0]['apply_url']==''
    assert hits[0]['source_url'].endswith('/postings/1')


def test_social_import_api_requires_auth_and_bounds_input(store,monkeypatch):
    monkeypatch.setenv('API_TOKEN','fixture-token');client=TestClient(app)
    body={'leads':[{'url':'https://www.linkedin.com/jobs/view/123','title':'AI Internship'}]}
    assert client.post('/discovery/leads',json=body).status_code==401
    result=client.post('/discovery/leads',json=body,headers={'Authorization':'Bearer fixture-token'})
    assert result.status_code==200 and len(result.json()['accepted'])==1


def test_linkedin_copy_deduplicates_against_official_application_without_downgrading(store):
    official={'company':'Research Org','company_url':ORG['url'],'title':'AI Internship','city':'Unknown',
        'source_url':'https://org.example/careers/42','apply_url':'https://www.linkedin.com/jobs/view/123',
        'discovery_method':'automatic','record_class':'verified_announcement','verification_status':'Official-source content fetched'}
    item=store.upsert(official);store.status(item['id'],'Interview');stamp=item['verified_at']
    import_linkedin_leads(store,[{'url':official['apply_url'],'title':official['title'],'company_name':'Research Org'}])
    assert len(store.all())==1
    row=store.get(item['id'])
    assert row['record_class']=='verified_announcement' and row['verified_at']==stamp and row['status']=='Interview'
    observation=next(c for c in row['source_verifications'] if 'linkedin.com' in c['url'])
    assert 'verified_at' not in observation and observation['observed_at']


def test_external_directory_association_cannot_launder_employer_trust(store):
    company=store.company(ORG);config=load_config();state=DiscoveryStore(store)
    state.enqueue({'url':'https://third-party.example/jobs/42','provider':'directory'},config,company)
    class Pages:
        def page(self,url):
            node={'@type':'JobPosting','title':'AI Internship','hiringOrganization':{'name':ORG['name'],'url':ORG['url']}}
            return BeautifulSoup('<script type="application/ld+json">'+json.dumps(node)+'</script>','html.parser')
    report=refresh_discovered(store,config,Pages())
    assert report['opportunities_upserted']==1
    assert store.all()[0]['record_class']=='potential_lead' and report['pages_verified']==0


def test_structured_and_html_representations_of_same_job_do_not_double_count():
    node={'@type':'JobPosting','title':'AI Internship','identifier':{'value':'42'},'url':'https://org.example/jobs/42',
          'jobLocation':{'address':{'addressLocality':'Riyadh'}}}
    script='<script type="application/ld+json">'+json.dumps(node)+'</script>'
    assert len(parse(script+'<main><h1>AI Internship</h1><a href="/apply">Apply</a></main>'))==1
    rows=parse(script+'<article data-job-id="42"><h2>AI Internship</h2><a href="/jobs/42">Details</a></article><article><h2>Data Science Internship</h2><a href="/data">Apply</a></article>')
    assert len(rows)==2 and {r['title'] for r in rows}=={'AI Internship','Data Science Internship'}


def test_existing_v2_database_gets_additive_alias_upgrade_without_reset(tmp_path):
    path=tmp_path/'legacy.sqlite'
    store=Store(path)
    item=store.upsert({'company':'Research Org','company_url':ORG['url'],'title':'AI Internship','source_url':'https://org.example/jobs/42','apply_url':'https://org.example/apply/42'})
    store.status(item['id'],'Applied')
    with store.db:
        store.db.execute('DELETE FROM schema_migrations')
        store.db.execute('INSERT INTO schema_migrations VALUES(?)',('discovery_aliases_v2',))
        store.db.execute('DELETE FROM opportunity_aliases')
    store.db.close()
    upgraded=Store(path)
    assert upgraded.get(item['id'])['status']=='Applied'
    assert upgraded.db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0]==2
    assert upgraded.db.execute('SELECT count(*) FROM opportunity_aliases').fetchone()[0]>0
    upgraded.db.close()


def test_linkedin_redirect_is_retained_without_following_or_claiming_verification(store,monkeypatch):
    config=load_config();company=store.company(ORG);state=DiscoveryStore(store)
    state.enqueue({'url':company['url']},config,company)
    f=Fetcher();monkeypatch.setattr(f,'safe',lambda _:None);monkeypatch.setattr('internship_assistant.sources.time.sleep',lambda _:None)
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        assert request.url.host=='org.example'
        if request.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
        return httpx.Response(302,headers={'Location':'https://www.linkedin.com/jobs/view/123'})
    f.client=httpx.Client(transport=httpx.MockTransport(handler))
    report=refresh_discovered(store,config,f)
    assert not report['errors'] and report['needs_review']==1
    lead=next(c for c in state.candidates() if 'linkedin.com' in c['url'])
    assert lead['state']=='needs_review' and not lead.get('verified_at') and not lead.get('fetched_at')
    assert len(calls)==2
