"""Bounded official-page discovery; no speculative vacancy generation."""
import ipaddress
import json
import os
import socket
import time
from datetime import datetime
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib import robotparser
from urllib.parse import urljoin, urlsplit
import httpx
from bs4 import BeautifulSoup
from .core import now, demo
from .network import SourceFailure
from .social import is_linkedin

AGENT = 'InternshipResearchBot/0.4'

class Fetcher:
    def __init__(self):
        self.client = httpx.Client(timeout=25, follow_redirects=False, headers={'User-Agent': AGENT})
        self.last = {}
        self.robots = {}
    def safe(self, url):
        if is_linkedin(url):
            raise SourceFailure('manual_social_review','LinkedIn URLs require manual review; no LinkedIn requests are permitted','policy')
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
            raise SourceFailure('invalid_source','Only public HTTPS sources allowed','policy')
        try:
            addresses=socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise SourceFailure('dns_local','Local public DNS resolution failed; remote DNS health is unknown','dns') from None
        for addr in addresses:
            if not ipaddress.ip_address(addr[4][0]).is_global:
                raise SourceFailure('private_destination','Private network destination refused','policy')
    def request(self, url):
        self.safe(url)
        host = urlsplit(url).netloc
        for attempt in range(3):
            time.sleep(max(0, 2 - (time.monotonic() - self.last.get(host, 0))))
            self.last[host] = time.monotonic()
            # Bound actual bytes read, not merely the response after downloading it.
            try:
                with self.client.stream('GET', url) as streamed:
                    body = bytearray()
                    for chunk in streamed.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 2_000_000:
                            raise SourceFailure('response_limit','Source exceeds 2 MB limit')
                    headers={k:v for k,v in streamed.headers.items() if k.lower() not in ('content-encoding','content-length')}
                    response = httpx.Response(streamed.status_code, headers=headers,
                                              content=bytes(body), request=streamed.request)
            except (httpx.ConnectError,httpx.TimeoutException,httpx.ProxyError) as error:
                from .network import failure_detail
                detail=failure_detail(error)
                if attempt==2 or detail['code']=='proxy_access':
                    raise SourceFailure(detail['code'],detail['message'],detail['phase'],detail.get('http_status')) from None
                time.sleep(2**(attempt+1))
                continue
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            if attempt < 2:
                try:
                    delay = max(2, int(response.headers.get('Retry-After', 2 ** (attempt + 1))))
                except ValueError:
                    try:
                        delay = max(2, (parsedate_to_datetime(response.headers['Retry-After']) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, KeyError):
                        delay = 10
                if delay > 60:
                    raise SourceFailure('rate_limited','Source requested cooldown; retry later','http',response.status_code)
                time.sleep(delay)
        if response.status_code not in (301, 302, 303, 307, 308, 404):
            response.raise_for_status()
        return response
    def page(self, url):
        for _ in range(6):
            result = self._page_once(url)
            if isinstance(result, BeautifulSoup):
                return result
            url = result
        raise ValueError('Too many source redirects')

    def _page_once(self, url, document=False):
        self.safe(url)
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            try:r = self.request(origin + '/robots.txt')
            except httpx.HTTPStatusError as error:
                raise SourceFailure('robots_http_access','robots.txt endpoint unavailable/restricted; content not fetched','robots',error.response.status_code) from None
            robot = robotparser.RobotFileParser()
            if r.status_code == 404:
                robot.allow_all = True
            elif 300 <= r.status_code < 400:
                raise SourceFailure('robots_redirect','robots.txt redirect requires canonical source URL','robots',r.status_code)
            else:
                robot.parse(r.text.splitlines())
            self.robots[origin] = robot
        robot = self.robots[origin]
        if not robot.can_fetch(AGENT, url):
            raise SourceFailure('robots_disallowed','robots.txt disallows source','robots')
        delay = robot.crawl_delay(AGENT) or 2
        if delay > 60:
            raise ValueError('Source crawl delay exceeds bounded worker budget')
        time.sleep(max(0, delay - (time.monotonic() - self.last.get(p.netloc, 0))))
        r = self.request(url)
        if 300 <= r.status_code < 400:
            target = urljoin(url, r.headers.get('location', ''))
            if is_linkedin(target):
                from .social import linkedin_identity
                linkedin_identity(target)
                error=SourceFailure('manual_social_review','LinkedIn redirect retained for manual review; not requested','policy')
                error.lead_url=target
                raise error
            self.safe(target)
            return target  # Each redirect destination receives its own robots/SSRF checks.
        r.raise_for_status()
        if document:
            return r
        if not any(kind in r.headers.get('content-type', '') for kind in ('text/html','application/xhtml+xml')):
            raise SourceFailure('unsupported_content','Expected HTML; unsupported source content format','content',r.status_code)
        page = BeautifulSoup(r.text, 'html.parser')
        page.source_url = url
        return page

    def document(self, url):
        """Read a published RSS/Atom/XML document using the same robots and redirect policy."""
        for _ in range(6):
            result = self._page_once(url,document=True)
            if isinstance(result,httpx.Response):
                return result.text
            url = result
        raise ValueError('Too many source redirects')

def sources():
    with open(os.getenv('SOURCE_CONFIG', 'config/sources.json')) as f:
        return json.load(f)

def discover(store, fetcher=None):
    from .discovery import run_discovery
    return run_discovery(store, fetcher=fetcher)

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
                from .evidence import classify_record
                item=classify_record(item,True)
                item['recommendation'] = recommendation(item)
                results.append(store.upsert(item))
            except Exception as e:
                errors.append({'source':vacancy.get('source_url'), 'error':str(e)[:250]})
    output = {'opportunities':results, 'errors':errors}
    if not demo():
        from .discovery import refresh_discovered
        output['discovery'] = refresh_discovered(store, fetcher=fetcher)
    return output
