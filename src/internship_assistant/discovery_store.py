"""Additive discovery state; existing opportunity/application IDs are preserved."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .core import now


def clean_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):
        raise ValueError('Not a public website URL')
    search_hosts = {'google.com', 'google.com.sa', 'bing.com', 'duckduckgo.com', 'search.brave.com'}
    if p.hostname.lower().removeprefix('www.') in search_hosts:
        raise ValueError('Search result HTML must not be scraped; use a supported API')
    query = [(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('gclid','fbclid')]
    # HTTP URLs are staged as HTTPS candidates; no HTTP content is trusted or fetched.
    host = p.hostname.lower()
    return urlunsplit(('https',host,p.path or '/',urlencode(sorted(query)),''))


def host_key(url):
    host = urlsplit(clean_url(url)).hostname
    return host.removeprefix('www.')


def url_key(url):
    p = urlsplit(clean_url(url))
    return urlunsplit(('https',p.hostname.removeprefix('www.'),p.path.rstrip('/'),p.query,''))


def key(text):
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def later(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class DiscoveryStore:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS discovery_candidates(id TEXT PRIMARY KEY, url TEXT NOT NULL, payload TEXT NOT NULL, next_check TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS discovery_state(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS discovery_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
        ''')

    def state(self, id, default=None):
        row = self.db.execute('SELECT payload FROM discovery_state WHERE id=?',(id,)).fetchone()
        return json.loads(row[0]) if row else (default or {})

    def set_state(self, id, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO discovery_state VALUES(?,?)',(id,json.dumps(value)))

    def enqueue(self, hit, config, company=None, depth=0, due=True):
        url = clean_url(hit['url'])
        id = key(url_key(url))
        row = self.db.execute('SELECT payload,next_check FROM discovery_candidates WHERE id=?',(id,)).fetchone()
        if not row and self.db.execute('SELECT count(*) FROM discovery_candidates').fetchone()[0] >= config['max_candidates']:
            return None
        item = json.loads(row[0]) if row else {'id':id,'url':url,'first_seen':now(),'depth':depth,'state':'pending','provenance':[]}
        old_authority = item.get('authority','unverified')
        old_company_id = item.get('company_id')
        provenance = {k:hit[k] for k in ('provider','query','entity_id','source_url','authority') if hit.get(k)}
        if provenance and provenance not in item['provenance']:
            item['provenance'].append(provenance)
        item['provenance'] = item['provenance'][-30:]
        item['last_seen'] = now()
        if hit.get('authority') in ('reviewed','wikidata_website_claim','configured'):
            item['authority'] = hit['authority']
            item['organization_name'] = hit.get('title','')
        item.setdefault('authority','unverified')
        for field in ('title','location_hint','sector','entity_id'):
            if hit.get(field) and not item.get(field):
                item[field] = hit[field]
        if company:
            # Do not let a later anonymous search hit erase the official referral chain.
            had_company = bool(item.get('company_id'))
            item['company_id'] = company['id']
            item['depth'] = min(depth,item.get('depth',depth)) if row and had_company else depth
            item['authority'] = 'official_link' if item['authority'] == 'unverified' else item['authority']
        next_check = row[1] if row else (now() if due else later(config['page_refresh_hours']))
        # A new trusted referral can rescue a previously unverified result immediately.
        promoted = (item['authority'] in ('reviewed','wikidata_website_claim') and item['authority'] != old_authority)
        new_trusted_referral = (company and company.get('authority') in ('reviewed','wikidata_website_claim') and not old_company_id)
        if row and item['state'] == 'needs_review' and (promoted or new_trusted_referral):
            next_check = now()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO discovery_candidates VALUES(?,?,?,?)',(id,item['url'],json.dumps(item),next_check))
        return item

    def candidates(self, limit=100, due=False):
        if due:
            rows = self.db.execute('SELECT payload FROM discovery_candidates WHERE next_check<=? ORDER BY next_check,id LIMIT ?',(now(),limit))
        else:
            rows = self.db.execute('SELECT payload FROM discovery_candidates ORDER BY id LIMIT ?',(limit,))
        return [json.loads(r[0]) for r in rows]

    def finish(self, item, config, state='verified', error=''):
        item = dict(item, state=state, last_attempt=now())
        if error:
            item['error'] = error
            item['failures'] = item.get('failures',0) + 1
            hours = min(168, config['error_retry_hours'] * 2 ** min(item['failures']-1,5))
        else:
            item.pop('error',None)
            item['failures'] = 0
            item['fetched_at'] = now()
            item['verified_at'] = now() if state == 'verified' else item.get('verified_at','')
            hours = config['page_refresh_hours']
        with self.db:
            self.db.execute('UPDATE discovery_candidates SET payload=?,next_check=? WHERE id=?',(json.dumps(item),later(hours),item['id']))
        return item

    def report(self, result):
        with self.db:
            self.db.execute('INSERT INTO discovery_runs(payload) VALUES(?)',(json.dumps(dict(result,completed_at=now())),))
        return result

    def status(self):
        row = self.db.execute('SELECT payload FROM discovery_runs ORDER BY id DESC LIMIT 1').fetchone()
        counts = {}
        for item in self.db.execute('SELECT payload FROM discovery_candidates'):
            state = json.loads(item[0])['state']
            counts[state] = counts.get(state,0) + 1
        return {'last_run':json.loads(row[0]) if row else None, 'candidate_counts':counts,
                'due':self.db.execute('SELECT count(*) FROM discovery_candidates WHERE next_check<=?',(now(),)).fetchone()[0]}
