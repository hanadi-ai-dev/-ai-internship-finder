"""Official public APIs only; search results are leads, never verified vacancies."""
import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx


class ProviderError(ValueError):
    """Sanitized provider failure safe to persist without request headers/keys."""


class APITransport:
    def __init__(self, interval=2, client=None, sleep=time.sleep, clock=time.monotonic):
        self.client = client or httpx.Client(timeout=30, follow_redirects=False,
            headers={'User-Agent':'SaudiInternshipAssistant/0.2 (+https://github.com/hanadi-ai-dev/-ai-internship-finder; public-source research)'})
        self.interval, self.sleep, self.clock = max(1, interval), sleep, clock
        self.last = {}

    def get(self, provider, url, **kwargs):
        for attempt in range(3):
            self.sleep(max(0, self.interval - (self.clock() - self.last.get(provider, -1e9))))
            self.last[provider] = self.clock()
            try:
                response = self.client.get(url, **kwargs)
            except httpx.HTTPError:
                if attempt == 2:
                    raise ProviderError(f'{provider}: transport failure') from None
                self.sleep(2 ** (attempt + 1))
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                delay = response.headers.get('Retry-After', '')
                try:
                    delay = float(delay)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(delay) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        delay = 2 ** (attempt + 1)
                # Do not retry sooner than a long provider-requested cooldown.
                if delay > 60:
                    raise ProviderError(f'{provider}: cooldown required; retry later')
                self.sleep(max(1, delay))
                continue
            if response.status_code != 200:
                raise ProviderError(f'{provider}: HTTP {response.status_code}')
            try:
                return response.json()
            except ValueError:
                raise ProviderError(f'{provider}: invalid JSON response') from None
        raise ProviderError(f'{provider}: retry budget exhausted')


class BraveSearch:
    name = 'brave'

    def __init__(self, transport):
        self.transport = transport

    @property
    def available(self):
        return bool(os.getenv('BRAVE_SEARCH_API_KEY'))

    def search(self, task, page, count):
        if not self.available:
            raise ProviderError('brave: missing BRAVE_SEARCH_API_KEY')
        data = self.transport.get(self.name, 'https://api.search.brave.com/res/v1/web/search',
            params={'q':task['query'], 'count':min(20,count), 'offset':page, 'country':'SA'},
            headers={'X-Subscription-Token':os.environ['BRAVE_SEARCH_API_KEY'], 'Accept':'application/json'})
        try:
            rows = data.get('web', {}).get('results', [])
            if not isinstance(rows, list):
                raise ValueError()
            hits = [{'url':r['url'], 'title':r.get('title',''), 'snippet':r.get('description',''),
                     'location_hint':task['location'], 'query':task['query'], 'provider':self.name,
                     'authority':'unverified'} for r in rows if isinstance(r,dict) and isinstance(r.get('url'),str)]
            more = bool(data.get('query', {}).get('more_results_available', len(rows) >= count))
            return hits, more
        except (TypeError, AttributeError, ValueError):
            raise ProviderError('brave: invalid result schema') from None


class WikidataSearch:
    """CC0 structured organization directory; sparse coverage is explicitly reported."""
    name = 'wikidata'
    available = True

    def __init__(self, transport):
        self.transport = transport

    def search(self, task, page, count):
        # JSON strings safely quote user-configured labels; no SPARQL interpolation of raw syntax.
        city = json.dumps(task['location'], ensure_ascii=False) + '@en'
        query = f'''SELECT DISTINCT ?org ?orgLabel ?website ?sectorLabel WHERE {{
          ?city rdfs:label {city} .
          ?org (wdt:P159|wdt:P131) ?city ; wdt:P856 ?website .
          ?org wdt:P31/wdt:P279* wd:Q43229 .
          OPTIONAL {{ ?org wdt:P452 ?sector . }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ar" . }}
        }} ORDER BY ?org ?website LIMIT {int(count)} OFFSET {int(page * count)}'''
        data = self.transport.get(self.name, 'https://query.wikidata.org/sparql',
            params={'query':query, 'format':'json'}, headers={'Accept':'application/sparql-results+json'})
        try:
            rows = data['results']['bindings']
            hits = [{'url':r['website']['value'], 'title':r['orgLabel']['value'],
                     'entity_id':r['org']['value'], 'sector':r.get('sectorLabel',{}).get('value','Unknown'),
                     'location_hint':task['location'], 'provider':self.name, 'query':task['query'],
                     'authority':'wikidata_website_claim'} for r in rows]
            return hits, len(rows) >= count
        except (KeyError, TypeError):
            raise ProviderError('wikidata: invalid result schema') from None


def query_tasks(config, provider):
    if provider == 'wikidata':
        return [{'query':'Organizations with listed websites in ' + city, 'location':city} for city in config['locations']]
    tasks = [{'query':f'"{target}" official careers internship', 'location':target} for target in config['priority_targets']]
    # Interleave company and vacancy queries, rather than spending all first runs on one group.
    company = [{'query':f'{city} {sector} official company technology careers', 'location':city}
               for sector in config['sectors'] for city in config['locations']]
    internships = [{'query':f'{city} {field} {kind} official application', 'location':city}
                   for kind in config['internship_terms'] for field in config['fields'] for city in config['locations']]
    for i in range(max(len(company),len(internships))):
        if i < len(company):
            tasks.append(company[i])
        if i < len(internships):
            tasks.append(internships[i])
    tasks.extend({'query':q, 'location':'Unknown'} for q in config['extra_queries'])
    return tasks
