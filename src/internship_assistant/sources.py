"""Bounded official-page discovery; no speculative vacancy generation."""
import ipaddress
import json
import os
import socket
import time
from datetime import datetime
from urllib import robotparser
from urllib.parse import urljoin, urlsplit
import httpx
from bs4 import BeautifulSoup
from .core import now

AGENT = 'InternshipResearchBot/0.1'

class Fetcher:
    def __init__(self):
        self.client = httpx.Client(timeout=25, follow_redirects=False, headers={'User-Agent': AGENT})
        self.last = {}
        self.robots = {}
    def safe(self, url):
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
            raise ValueError('Only public HTTPS sources allowed')
        for addr in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(addr[4][0]).is_global:
                raise ValueError('Private network destination refused')
    def request(self, url):
        self.safe(url)
        host = urlsplit(url).netloc
        time.sleep(max(0, 2 - (time.monotonic() - self.last.get(host, 0))))
        self.last[host] = time.monotonic()
        for attempt in range(3):
            response = self.client.get(url)
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            if attempt < 2:
                try:
                    delay = min(60, max(2, int(response.headers.get('Retry-After', 2 ** (attempt + 1)))))
                except ValueError:
                    delay = 10
                time.sleep(delay)
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError('Source exceeds 2 MB limit')
        return response
    def page(self, url):
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            r = self.request(origin + '/robots.txt')
            robot = robotparser.RobotFileParser()
            robot.parse(r.text.splitlines())
            self.robots[origin] = robot
        robot = self.robots[origin]
        if not robot.can_fetch(AGENT, url):
            raise ValueError('robots.txt disallows source')
        delay = robot.crawl_delay(AGENT) or 2
        time.sleep(max(0, delay - (time.monotonic() - self.last.get(p.netloc, 0))))
        r = self.request(url)
        if 'text/html' not in r.headers.get('content-type', ''):
            raise ValueError('Expected HTML')
        return BeautifulSoup(r.text, 'html.parser')

def sources():
    with open(os.getenv('SOURCE_CONFIG', 'config/sources.json')) as f:
        return json.load(f)

def discover(store, fetcher=None):
    fetcher = fetcher or Fetcher()
    results = []
    for source in sources():
        company = dict(source, verification_status='Unverified', verified_at='', contact_emails=[], career_links=[])
        try:
            page = fetcher.page(source['url'])
            company['career_links'] = sorted({urljoin(source['url'], a['href']) for a in page.select('a[href]') if any(w in a.get_text(' ', strip=True).lower() for w in ('career', 'intern', 'training', 'توظيف', 'تدريب')) and urlsplit(urljoin(source['url'], a['href'])).scheme == 'https'})[:30]
            company['contact_emails'] = sorted({a['href'][7:].split('?')[0] for a in page.select('a[href^="mailto:"]')})
            company.update(verification_status='Official page fetched; contacts are general unless reviewed', verified_at=now())
        except Exception as e:
            company['error'] = f'{type(e).__name__}: {str(e)[:250]}'
        results.append(store.company(company))
    return results

def monitor(store, fetcher=None):
    fetcher = fetcher or Fetcher()
    results, errors = [], []
    # Explicit selectors and evidence mappings are reviewed in config, not guessed by AI.
    for source in sources():
        for vacancy in source.get('opportunities', []):
            try:
                page = fetcher.page(vacancy['source_url'])
                node = page.select_one(vacancy['selector'])
                if node is None:
                    raise ValueError('Configured opportunity selector no longer matches')
                text = node.get_text(' ', strip=True)
                if vacancy['title'].casefold() not in text.casefold():
                    raise ValueError('Title not present in source')
                item = {k:v for k,v in vacancy.items() if k != 'selector'}
                item.update(company=source['name'], city=source['city'], requirements=text[:12000])
                for key in ('email', 'opens', 'closes', 'evidence'):
                    if item.get(key) and item[key] not in text:
                        raise ValueError(f'{key} not present verbatim in source')
                if item.get('apply_url') and item['apply_url'] not in [urljoin(vacancy['source_url'], a['href']) for a in node.select('a[href]')]:
                    raise ValueError('Application link not present in source block')
                from .integrations import recommendation
                item['recommendation'] = recommendation(item)
                results.append(store.upsert(item))
            except Exception as e:
                errors.append({'source':vacancy.get('source_url'), 'error':str(e)[:250]})
    return {'opportunities':results, 'errors':errors}
