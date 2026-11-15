import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

STATUSES = {'Not Applied', 'Applied', 'Waiting', 'Interview', 'Accepted', 'Rejected'}
ELIGIBILITY = {'Confirmed', 'Possible', 'Unknown', 'Ineligible'}

def normalized(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))

def opportunity_aliases(item):
    from .discovery_store import url_key, host_key
    company = host_key(item['company_url']) if item.get('company_url') else normalized(item['company'])
    scope = '|'.join([company, normalized(item['title']), normalized(item.get('city', ''))])
    aliases = [scope + '|url:' + url_key(item['source_url'])]
    if item.get('apply_url'):
        aliases.append(scope + '|url:' + url_key(item['apply_url']))
    if item.get('canonical_job_url'):
        aliases.append(scope + '|url:' + url_key(item['canonical_job_url']))
    identifier = item.get('external_id')
    if identifier:
        aliases.append(company + '|external:' + str(identifier))
    if item.get('posted_at'):
        aliases = [a + '|cohort:' + item['posted_at'][:4] for a in aliases] + aliases
    return aliases

def now():
    return datetime.now(timezone.utc).isoformat()

def demo():
    return os.getenv('DEMO_MODE', 'true').lower() == 'true'

def canonical(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), p.query, ''))

def identity(item):
    key = '|'.join([item['company'].strip().casefold(), item['title'].strip().casefold(), canonical(item['source_url'])])
    return hashlib.sha256(key.encode()).hexdigest()[:24]

def validate(item):
    item = dict(item)
    for key in ('company', 'title', 'source_url'):
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError(f'{key} is required')
    if urlsplit(item['source_url']).scheme != 'https':
        raise ValueError('HTTPS source required')
    if item.get('eligibility', 'Unknown') not in ELIGIBILITY:
        raise ValueError('Invalid eligibility')
    if item.get('eligibility', 'Unknown') != 'Unknown' and not item.get('evidence'):
        raise ValueError('Eligibility classification requires quoted evidence')
    if item.get('email') and item.get('email_kind') not in ('recruitment', 'general'):
        raise ValueError('Email must be classified')
    if item.get('email') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', item['email']):
        raise ValueError('Invalid email')
    for key in ('opens', 'closes', 'follow_up'):
        if item.get(key):
            datetime.strptime(item[key], '%Y-%m-%d')
    item.setdefault('eligibility', 'Unknown')
    item.setdefault('status', 'Not Applied')
    if item['status'] not in STATUSES:
        raise ValueError('Invalid status')
    item['id'] = identity(item)
    return item

class Store:
    def __init__(self, path=None):
        path = Path(path or Path(os.getenv('DATA_DIR', 'data')) / ('demo.sqlite' if demo() else 'live.sqlite'))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS companies(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications(key TEXT PRIMARY KEY, sent_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS opportunity_aliases(alias TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY);
        ''')
        # Additive index backfill: existing IDs, statuses, applications and receipts stay intact.
        if not self.db.execute('SELECT 1 FROM schema_migrations WHERE name=?', ('discovery_aliases_v2',)).fetchone():
            with self.db:
                for item in self.all():
                    for alias in opportunity_aliases(item):
                        self.db.execute('INSERT OR IGNORE INTO opportunity_aliases VALUES(?,?)', (alias, item['id']))
                self.db.execute('INSERT INTO schema_migrations VALUES(?)', ('discovery_aliases_v2',))
    def upsert(self, raw):
        item = validate(raw)
        checked_url = item['source_url']
        previous = self.get(item['id'])
        if previous and ((previous.get('external_id') and item.get('external_id') and
                          previous['external_id'] != item['external_id']) or
                         normalized(previous.get('city','')) != normalized(item.get('city',''))):
            item['id'] = hashlib.sha256((item['id'] + '|' + item.get('external_id','') + '|' + item.get('city','')).encode()).hexdigest()[:24]
            previous = self.get(item['id'])
        if (previous and item.get('posted_at') and previous.get('posted_at') and
            item['posted_at'][:4] != previous['posted_at'][:4]):
            item['id'] = hashlib.sha256((item['id'] + '|' + item['posted_at'][:4]).encode()).hexdigest()[:24]
            previous = self.get(item['id'])
        aliases = opportunity_aliases(item)
        if not previous:
            for alias in aliases:
                row = self.db.execute('SELECT opportunity_id FROM opportunity_aliases WHERE alias=?', (alias,)).fetchone()
                if row:
                    candidate = self.get(row[0])
                    if candidate and normalized(candidate['title']) != normalized(item['title']):
                        continue
                    if (candidate and candidate.get('external_id') and item.get('external_id') and
                        candidate['external_id'] != item['external_id']):
                        continue
                    # Distinct explicitly dated cohorts must not collapse into an old application.
                    if candidate and not (item.get('posted_at') and candidate.get('posted_at') and
                                          item['posted_at'][:4] != candidate['posted_at'][:4]):
                        previous = candidate
                        item['id'] = candidate['id']
                        break
        source_urls = set(item.get('source_urls', [])) | {item['source_url']}
        if previous:
            source_urls.update(previous.get('source_urls', [previous['source_url']]))
            for key in ('status', 'follow_up'):
                if key in previous:
                    item[key] = previous[key]
            item['source_url'] = previous['source_url']
            # Preserve reviewed evidence when an automatic scan has no verified replacement.
            for field in ('email', 'email_kind', 'closes', 'opens', 'evidence', 'eligibility', 'apply_url'):
                if (previous.get('discovery_method') != 'automatic' and item.get('discovery_method') == 'automatic' and
                    (not item.get(field) or (field == 'eligibility' and item[field] == 'Unknown')) and previous.get(field)):
                    item[field] = previous[field]
        item['source_urls'] = sorted(source_urls)
        checks = {c['url']:c for c in (previous or {}).get('source_verifications', [])}
        if previous and previous.get('verified_at'):
            checks.setdefault(previous['source_url'], {'url':previous['source_url'], 'verified_at':previous['verified_at']})
        checks[checked_url] = {'url':checked_url, 'verified_at':now()}
        item['source_verifications'] = sorted(checks.values(), key=lambda c:c['url'])
        item['last_verified_source_url'] = checked_url
        item['demo'] = demo()
        content = {k:v for k,v in item.items() if k not in ('verified_at', 'fingerprint', 'source_urls', 'source_verifications', 'last_verified_source_url', 'discovered_at', 'recommendation', 'status', 'follow_up')}
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        item['fingerprint'] = fingerprint
        item['verified_at'] = now()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO opportunities VALUES(?,?,?)', (item['id'], json.dumps(item), fingerprint))
            for alias in aliases:
                self.db.execute('INSERT OR REPLACE INTO opportunity_aliases VALUES(?,?)', (alias, item['id']))
        return item
    def get(self, id):
        row = self.db.execute('SELECT payload FROM opportunities WHERE id=?', (id,)).fetchone()
        return json.loads(row[0]) if row else None
    def all(self, table='opportunities'):
        if table not in ('opportunities', 'companies', 'applications'):
            raise ValueError('Unknown table')
        return [json.loads(r[0]) for r in self.db.execute(f'SELECT payload FROM {table} ORDER BY id')]
    def seen(self, key):
        return self.db.execute('SELECT 1 FROM notifications WHERE key=?', (key,)).fetchone() is not None
    def mark(self, key):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO notifications VALUES(?,?)', (key, now()))
    def company(self, item):
        from .discovery_store import url_key
        identity_url = url_key(item['url'])
        previous = next((c for c in self.all('companies') if url_key(c['url']) == identity_url), None)
        id = previous['id'] if previous else hashlib.sha256(identity_url.encode()).hexdigest()[:24]
        if previous:
            merged = dict(previous, **item)
            for field in ('career_links', 'contact_emails', 'provenance', 'contacts', 'name_aliases'):
                values = previous.get(field, []) + item.get(field, [])
                merged[field] = list({json.dumps(v, sort_keys=True):v for v in values}.values())[-100:]
            merged['contacts'] = list({(c['email'].lower(),c['source_url'],c['kind']):c for c in merged.get('contacts',[])}.values())
            item = merged
        item = dict(item, id=id)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO companies VALUES(?,?)', (id, json.dumps(item)))
        return item
    def status(self, id, status, follow_up=''):
        if status not in STATUSES:
            raise ValueError('Invalid status')
        if follow_up:
            datetime.strptime(follow_up, '%Y-%m-%d')
        item = self.get(id)
        if not item:
            raise KeyError(id)
        item.update(status=status, follow_up=follow_up)
        with self.db:
            self.db.execute('UPDATE opportunities SET payload=? WHERE id=?', (json.dumps(item), id))
        return item
