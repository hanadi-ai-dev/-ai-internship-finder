import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

STATUSES = {'Not Applied', 'Applied', 'Waiting', 'Interview', 'Accepted', 'Rejected'}
ELIGIBILITY = {'Confirmed', 'Possible', 'Unknown', 'Ineligible'}

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
        ''')
    def upsert(self, raw):
        item = validate(raw)
        previous = self.get(item['id'])
        if previous:
            for key in ('status', 'follow_up'):
                if key in previous:
                    item[key] = previous[key]
        item['demo'] = demo()
        content = {k:v for k,v in item.items() if k not in ('verified_at', 'fingerprint')}
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        item['fingerprint'] = fingerprint
        item['verified_at'] = now()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO opportunities VALUES(?,?,?)', (item['id'], json.dumps(item), fingerprint))
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
        id = hashlib.sha256(canonical(item['url']).encode()).hexdigest()[:24]
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
