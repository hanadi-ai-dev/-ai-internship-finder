"""Typed, sanitized source failures and bounded priority-target diagnostics."""
import ipaddress
import socket
import re
from urllib.parse import urlsplit
import httpx


class SourceFailure(ValueError):
    def __init__(self,code,message,phase='content',status=None):
        super().__init__(message)
        self.code,self.phase,self.status=code,phase,status
    def detail(self):
        return {'code':self.code,'phase':self.phase,'http_status':self.status,'message':str(self)}


def failure_detail(error):
    if isinstance(error,SourceFailure):return error.detail()
    if isinstance(error,socket.gaierror):return {'code':'dns_local','phase':'dns','message':'Local public DNS resolution failed; remote DNS health is unknown'}
    if isinstance(error,httpx.ProxyError):
        status=re.search(r'\b(403|407|451)\b',str(error))
        if status:return {'code':'proxy_access','phase':'proxy','http_status':int(status[1]),'message':'Proxy access denied; inspect outbound policy/authentication'}
        return {'code':'proxy_connection','phase':'proxy','message':'Proxy connection failed; inspect proxy readiness'}
    if isinstance(error,httpx.TimeoutException):return {'code':'timeout','phase':'connection','message':'Source request timed out'}
    if isinstance(error,httpx.ConnectError):return {'code':'connection','phase':'connection','message':'Source connection failed'}
    if isinstance(error,httpx.HTTPStatusError):
        status=error.response.status_code
        return {'code':'http_access' if status in (401,403,451) else ('rate_limited' if status==429 else 'http_error'),'phase':'http','http_status':status,'message':f'HTTP {status}: source unavailable/restricted'}
    return {'code':'extraction_error','phase':'content','message':'Source extraction failed; review layout/evidence'}


def diagnostic_url(url):
    from .social import is_linkedin
    if is_linkedin(url):raise ValueError('LinkedIn URLs are never probed automatically')
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError('Public HTTPS target required')
    host=p.hostname.lower()
    if '.' not in host or host.endswith(('.local','.internal','.localhost')):raise ValueError('Private diagnostic target refused')
    try:
        if not ipaddress.ip_address(host).is_global:raise ValueError('Private diagnostic target refused')
    except ValueError as e:
        if str(e)=='Private diagnostic target refused':raise
    return f'https://{p.netloc}'


def diagnose_targets(targets=None,fetcher=None,client=None):
    """Read-only DNS + HEAD probes, never treat them as content/robots verification."""
    from .sources import Fetcher,sources
    from .core import now
    targets=sources() if targets is None else targets
    fetcher=fetcher or Fetcher()
    owned=client is None
    client=client or httpx.Client(timeout=15,follow_redirects=False,headers={'User-Agent':'InternshipResearchBot/0.4 diagnostics'})
    results=[]
    try:
        for target in targets[:20]:
            origin=diagnostic_url(target['url'])
            row={'name':target['name'],'origin':origin,'checked_at':now(),
                 'content_verified':False,'note':'HEAD responses do not establish robots permission, vacancies or remote DNS health'}
            try:fetcher.safe(target['url']);row['local_dns']={'status':'resolved_public'}
            except Exception as e:
                detail=failure_detail(e);row['local_dns']={'status':'failed',**detail}
                if detail['code']!='dns_local':
                    row['probe_outcome']='Refused: destination validation failed'
                    results.append(row)
                    continue
            # HEAD through the inherited proxy distinguishes local resolver failure from
            # the observable HTTP path. It does not bypass the content crawler's DNS guard.
            for label,path in [('robots_head','/robots.txt'),('homepage_head','/')]:
                try:
                    response=client.head(origin+path)
                    row[label]={'http_status':response.status_code,
                        'outcome':'http_access' if response.status_code in (401,403,451) else ('redirect' if response.is_redirect else 'responded')}
                except Exception as e:row[label]=failure_detail(e)
            results.append(row)
    finally:
        if owned:client.close()
    return {'targets':results,'note':'No notifications, submissions or content verification performed. Failed targets remain queued for retry.'}
