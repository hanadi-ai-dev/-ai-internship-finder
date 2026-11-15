import json
import pytest
from fastapi.testclient import TestClient
from internship_assistant.core import Store, validate
from internship_assistant.cli import load_demo
from internship_assistant.integrations import notify, message, recommendation
from internship_assistant import applications
from internship_assistant.sources import monitor, Fetcher
from internship_assistant.api import app
from bs4 import BeautifulSoup

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMO_MODE','true')
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    s = Store()
    yield s
    s.db.close()

def sample(**changes):
    return dict(company='Example',title='COOP AI Internship',source_url='https://example.org/jobs/123',kind='COOP', **changes)

def test_demo_dedup_notifications_and_tracking(store):
    first = load_demo(store)
    assert len(first) == 2
    store.status(first[0]['id'], 'Applied', '2027-01-01')
    load_demo(store)
    assert len(store.all()) == 2
    assert store.get(first[0]['id'])['status'] == 'Applied'
    assert len(notify(store)) == 2
    assert notify(store) == []
    assert all('DEMO' in message(i) and 'Manual' in message(i) for i in store.all())

def test_no_invented_eligibility_or_excluded_coop(store):
    item = store.upsert(sample())
    assert item['eligibility'] == 'Unknown'
    assert recommendation(item)['score'] >= 0
    with pytest.raises(ValueError, match='evidence'):
        validate(sample(eligibility='Confirmed'))
    with pytest.raises(ValueError):
        validate(sample(closes='tomorrow'))

def test_notifications_only_mark_success(store, monkeypatch):
    store.upsert(sample())
    monkeypatch.setattr('internship_assistant.integrations.telegram', lambda _: (_ for _ in ()).throw(ValueError('failed')))
    with pytest.raises(ValueError):
        notify(store)
    assert store.db.execute('SELECT count(*) FROM notifications').fetchone()[0] == 0

def test_monitor_verifies_evidence(store, monkeypatch):
    vacancy = dict(sample(eligibility='Possible', evidence='Summer students may apply'), selector='#job')
    monkeypatch.setattr('internship_assistant.sources.sources', lambda:[{'name':'Example','city':'Riyadh','opportunities':[vacancy]}])
    class Fake:
        def page(self, url):
            return BeautifulSoup('<div id="job">COOP AI Internship Summer students may apply</div>', 'html.parser')
    result = monitor(store, Fake())
    assert len(result['opportunities']) == 1 and not result['errors']
    vacancy['closes'] = '2027-04-01'
    result = monitor(store, Fake())
    assert not result['opportunities'] and 'closes' in result['errors'][0]['error']

def test_email_is_disabled_even_with_approval(store):
    item = store.upsert(sample(email='careers@example.org', email_kind='recruitment'))
    drafted = applications.draft(store,item['id'],'AI student seeking summer training.')
    assert applications.draft(store,item['id'],'different')['body'] == drafted['body']
    applications.approve(store,item['id'])
    with pytest.raises(ValueError, match='disabled'):
        applications.send(store,item['id'])

def test_general_contacts_require_manual_outreach(store):
    item = store.upsert(sample(email='info@example.org',email_kind='general'))
    assert applications.draft(store,item['id'],'Student')['manual_required']

def test_ssrf_rejected():
    f = Fetcher()
    for url in ['http://example.org','https://127.0.0.1','https://user:pass@example.org','https://example.org:5678']:
        with pytest.raises(ValueError):
            f.safe(url)

def test_api_auth_and_smoke(store, monkeypatch):
    monkeypatch.setenv('API_TOKEN','test-only-token')
    c = TestClient(app)
    assert c.get('/health').json()['demo']
    assert c.post('/monitor').status_code == 401
    headers = {'Authorization':'Bearer test-only-token'}
    assert len(c.post('/monitor',headers=headers).json()) == 2
    items = c.get('/opportunities',headers=headers).json()
    assert len(items) == 2
    assert c.patch('/opportunities/'+items[0]['id'],headers=headers,json={'status':'Interview'}).status_code == 200
    assert c.post('/sync', headers=headers).json()['written'] is False

def test_workflow_safety():
    from pathlib import Path
    workflows = list(Path('workflows').glob('*.json'))
    assert len(workflows) == 4
    for path in workflows:
        workflow = json.loads(path.read_text())
        assert workflow['active'] is False
        assert not any('/send' in json.dumps(n) for n in workflow['nodes'])

def test_live_and_demo_databases_are_separate(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('DEMO_MODE','true')
    a = Store()
    a.upsert(sample())
    a.db.close()
    monkeypatch.setenv('DEMO_MODE','false')
    b = Store()
    assert b.all() == []
    b.db.close()

def test_changed_content_alert_and_failed_status(store):
    item = store.upsert(sample())
    assert len(notify(store)) == 1
    store.upsert(sample(requirements='New requirement'))
    assert len(notify(store)) == 1
    with pytest.raises(ValueError):
        store.status(item['id'],'Invented status')

def test_smtp_success_is_mocked_and_duplicate_blocked(store, monkeypatch, tmp_path):
    monkeypatch.setenv('DEMO_MODE','false')
    monkeypatch.setenv('EMAIL_SENDING_ENABLED','true')
    for key,value in {'SMTP_HOST':'smtp.example.org','SMTP_FROM':'student@example.org','SMTP_USER':'test','SMTP_PASSWORD':'test'}.items():
        monkeypatch.setenv(key,value)
    pdf = tmp_path/'test.pdf'
    pdf.write_bytes(b'%PDF-1.4 synthetic fixture')
    monkeypatch.setenv('CV_PATH',str(pdf))
    monkeypatch.setenv('TRAINING_LETTER_PATH',str(pdf))
    sent = []
    class FakeSMTP:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def login(self,*args): pass
        def send_message(self,msg): sent.append(msg)
    monkeypatch.setattr('internship_assistant.applications.smtplib.SMTP_SSL',FakeSMTP)
    item = store.upsert(sample(email='careers@example.org',email_kind='recruitment'))
    applications.draft(store,item['id'],'Synthetic student summary')
    with pytest.raises(ValueError, match='Approval'):
        applications.send(store,item['id'])
    applications.approve(store,item['id'])
    assert applications.send(store,item['id'])['state'] == 'sent'
    assert len(sent) == 1 and len(list(sent[0].iter_attachments())) == 2
    with pytest.raises(ValueError):
        applications.send(store,item['id'])
    assert len(sent) == 1
    assert store.get(item['id'])['status'] == 'Applied'

def test_smtp_uncertain_delivery_blocks_retries(store, monkeypatch, tmp_path):
    monkeypatch.setenv('DEMO_MODE','false')
    monkeypatch.setenv('EMAIL_SENDING_ENABLED','true')
    for key,value in {'SMTP_HOST':'smtp.example.org','SMTP_FROM':'student@example.org','SMTP_USER':'test','SMTP_PASSWORD':'test'}.items():
        monkeypatch.setenv(key,value)
    pdf = tmp_path/'test.pdf'
    pdf.write_bytes(b'%PDF-1.4 synthetic fixture')
    monkeypatch.setenv('CV_PATH',str(pdf))
    monkeypatch.setenv('TRAINING_LETTER_PATH',str(pdf))
    def fail(*args,**kwargs):
        raise OSError('Synthetic transport failure')
    monkeypatch.setattr('internship_assistant.applications.smtplib.SMTP_SSL',fail)
    item = store.upsert(sample(email='careers@example.org',email_kind='recruitment'))
    applications.draft(store,item['id'],'Synthetic')
    applications.approve(store,item['id'])
    with pytest.raises(ValueError,match='uncertain'):
        applications.send(store,item['id'])
    assert store.all('applications')[0]['state'] == 'delivery_unknown'
    with pytest.raises(ValueError,match='already attempted'):
        applications.send(store,item['id'])

def test_robots_disallows_without_fetching_page(monkeypatch):
    calls = []
    class Reply:
        text = 'User-agent: *\nDisallow: /private'
    f = Fetcher()
    monkeypatch.setattr(f,'request',lambda url: (calls.append(url) or Reply()))
    with pytest.raises(ValueError,match='robots'):
        f.page('https://example.org/private/job')
    assert calls == ['https://example.org/robots.txt']
