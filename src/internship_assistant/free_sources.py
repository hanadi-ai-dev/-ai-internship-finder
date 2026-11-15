"""Anonymous, free discovery sources. Public data is evidence of a lead, not certification."""
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlsplit, urljoin
from xml.etree import ElementTree as ET
import yaml
from bs4 import BeautifulSoup
from .discovery_store import clean_url, host_key
from .extraction import INTERNSHIP, plain, kind_for, date_value
from .search import ProviderError
from .evidence import internship_role


def location_match(text, config):
    aliases = config.get('location_aliases',{})
    terms = [term for city in config['locations'] for term in [city] + aliases.get(city,[])] + config.get('nearby_locations',[])
    return any(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)',text,re.I) for term in terms)


def in_scope(text, config):
    if location_match(text,config):
        return True
    return bool(config.get('include_remote_leads',False) and re.search(r'worldwide|anywhere|global remote|عن بعد',text,re.I))


def _https(url):
    if not isinstance(url,str) or urlsplit(url).scheme != 'https':
        return ''
    try:
        return clean_url(url)
    except ValueError:
        return ''


def parse_directory_archive(body, config):
    """Parse a licensed public source snapshot in memory; never extract paths to disk."""
    hits=[]
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        files=[f for f in archive.infolist() if '/src/companies/' in f.filename and f.filename.endswith('.md')]
        if len(files)>5000 or sum(f.file_size for f in archive.infolist())>50_000_000:
            raise ProviderError('public_sources: directory archive expands beyond budget')
        for file in sorted(files,key=lambda f:f.filename):
            if file.file_size>100_000:
                continue
            text=archive.read(file).decode('utf-8')
            parts=text.split('---',2)
            if len(parts)!=3 or parts[0].strip():
                continue
            meta=yaml.safe_load(parts[1])
            if not isinstance(meta,dict):
                continue
            # Geographic body evidence only; a name like "Saudi" in a company title is not an address.
            scope=str(meta.get('region',''))+' '+parts[2]
            if not in_scope(scope,config):
                continue
            url=_https(meta.get('website'))
            if url and isinstance(meta.get('title'),str):
                hits.append({'url':url,'title':meta['title'],'company_name':meta['title'],
                    'career_url':_https(meta.get('careers_url')),'kind':'company_lead','authority':'unverified',
                    'location_hint':'Target location mentioned' if location_match(scope,config) else 'Worldwide remote; Saudi eligibility unverified',
                    'scope_evidence':scope[:2000],'sector':'Technical directory; department unverified'})
    return hits,{'profiles_read':len(files),'matching_company_leads':len(hits)}


def parse_internship_table(text, config):
    """Community-published tables; never use relative age as a deadline or eligibility evidence."""
    page=BeautifulSoup(text,'html.parser')
    hits=[]; rows_read=0
    for table in page.select('table'):
        last_company=''
        for row in table.select('tr'):
            cells=row.find_all('td',recursive=False)
            if len(cells)<4:
                continue
            rows_read+=1
            company=cells[0].get_text(' ',strip=True)
            if company in ('↳','↪',''):
                company=last_company
            else:
                last_company=company
            title=cells[1].get_text(' ',strip=True)
            location=cells[2].get_text(' ',strip=True)
            if not company or not title or not internship_role(title) or not in_scope(location,config):
                continue
            links=[_https(a.get('href')) for a in cells[3].select('a[href]')]
            url=next((u for u in links if u and host_key(u) not in ('simplify.jobs',)), '')
            if not url:
                continue
            hits.append({'url':url,'title':title,'company_name':company,'kind':'opportunity_lead',
                         'location_hint':location,'entry_id':url,'authority':'unverified',
                         'scope_evidence':location,'internship_context':True})
    return hits,{'rows_read':rows_read,'matching_opportunity_leads':len(hits)}


def parse_feed(text, config):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('XML entity declarations are not accepted')
    root=ET.fromstring(text)
    # Namespace-independent RSS 2.0 and Atom support; no XML external resources are resolved.
    def local(tag): return tag.rsplit('}',1)[-1]
    entries=[node for node in root.iter() if local(node.tag) in ('item','entry')]
    hits=[]
    for entry in entries[:5000]:
        values={}
        links=[]
        for node in entry:
            name=local(node.tag)
            values[name]=''.join(node.itertext())
            if name=='link' and node.attrib.get('rel','alternate')=='alternate':
                links.append(node.attrib.get('href') or node.text or '')
        title=plain(values.get('title',''))
        raw_description=values.get('description') or values.get('summary') or values.get('content','')
        description=plain(raw_description)
        if not internship_role(title,description) or not in_scope(title+' '+description,config):
            continue
        url=next((u for value in links if (u:=_https(value))), '')
        if not url:
            continue
        # RSS authors are not assumed to be employers. Employer remains unknown unless source-configured.
        hits.append({'url':url,'title':title,'requirements':description[:12000], 'kind':'opportunity_lead',
                     'application_urls':[_https(a.get('href')) for a in BeautifulSoup(raw_description,'html.parser').select('a[href]') if _https(a.get('href'))][:10],
                     'company_name':'','location_hint':'Target location mentioned; exact workplace unverified',
                     'entry_id':values.get('guid') or values.get('id') or url,
                     'posted_at':'','authority':'unverified','scope_evidence':(title+' '+description)[:2000]})
    return hits,{'entries_read':len(entries),'matching_opportunity_leads':len(hits)}


class WikimediaSearch:
    """Anonymous Wikipedia search + Wikidata website claims; no billing or paid key."""
    name='wikimedia'
    available=True
    def __init__(self, transport): self.transport=transport
    def search(self,task,page,count):
        language=task.get('language','en')
        if language not in ('en','ar'):
            raise ProviderError('wikimedia: supported languages are en/ar')
        data=self.transport.get(self.name,f'https://{language}.wikipedia.org/w/api.php',params={
            'action':'query','generator':'search','gsrsearch':task['query'],'gsrlimit':count,
            'gsroffset':page*count,'prop':'pageprops','format':'json'})
        if 'error' in data:
            raise ProviderError('wikimedia: search API rejected query')
        pages=data.get('query',{}).get('pages',{})
        if not isinstance(pages,dict): raise ProviderError('wikimedia: invalid page schema')
        ids=[p.get('pageprops',{}).get('wikibase_item') for p in pages.values()]
        ids=[id for id in ids if isinstance(id,str) and re.fullmatch(r'Q\d+',id)]
        if not ids: return [],False
        entities=self.transport.get(self.name,'https://www.wikidata.org/w/api.php',params={
            'action':'wbgetentities','ids':'|'.join(ids),'props':'claims|labels','languages':language+'|en|ar','format':'json'})
        if 'error' in entities or not isinstance(entities.get('entities'),dict):
            raise ProviderError('wikimedia: invalid entity schema')
        hits=[]
        for id,entity in entities['entities'].items():
            labels=entity.get('labels',{})
            label=next((labels[l]['value'] for l in (language,'en','ar') if l in labels),'')
            for claim in entity.get('claims',{}).get('P856',[]):
                url=claim.get('mainsnak',{}).get('datavalue',{}).get('value')
                if _https(url) and label:
                    hits.append({'url':url,'title':label,'authority':'wikidata_website_claim',
                        'provider':self.name,'query':task['query'],'location_hint':task['location'],
                        'entity_id':'https://www.wikidata.org/wiki/'+id})
        return hits, bool(data.get('continue'))


class PublicSources:
    """Configurable, licensed/public feeds and directories; no accounts or API keys."""
    name='public_sources'
    available=True
    def __init__(self,transport,config,fetcher):
        self.transport,self.config,self.fetcher=transport,config,fetcher
        self.cache={}; self.statistics={}
    def search(self,task,page,count):
        source=task['source']; url=source['url']; kind=source['kind']
        if url not in self.cache:
            if kind=='github_directory':
                if urlsplit(url).hostname!='codeload.github.com':
                    raise ValueError('Directory archives must use published GitHub codeload URLs')
                body=self.transport.get(self.name,url,response_format='bytes')
                hits,stats=parse_directory_archive(body,self.config)
            elif kind=='internship_table':
                if urlsplit(url).hostname!='raw.githubusercontent.com':
                    raise ValueError('Community tables must use published GitHub raw URLs')
                text=self.transport.get(self.name,url,response_format='text')
                hits,stats=parse_internship_table(text,self.config)
            elif kind=='feed':
                text=self.fetcher.document(url)
                hits,stats=parse_feed(text,self.config)
            else:
                raise ValueError('Unknown public source kind')
            for hit in hits:
                hit.update(provider=self.name,source_url=url,query=source.get('name',url),
                           attribution_url=source.get('attribution_url',url))
                if source.get('company_name'):
                    hit['company_name']=source['company_name']
            self.cache[url]=hits
            self.statistics[source.get('name',url)]=dict(stats,source_url=url)
        hits=self.cache[url]
        start=page*count
        return hits[start:start+count],start+count<len(hits)


def ats_resource(url):
    """Resolve only documented public board URLs, never invent company board slugs."""
    p=urlsplit(url); parts=[part for part in p.path.split('/') if part]
    if not parts or not re.fullmatch(r'[A-Za-z0-9_-]+',parts[0]): return None
    if p.hostname in ('boards.greenhouse.io','job-boards.greenhouse.io'):
        return {'kind':'greenhouse','board':parts[0]}
    if p.hostname in ('jobs.lever.co','jobs.eu.lever.co'):
        return {'kind':'lever','board':parts[0],'region':'eu' if p.hostname=='jobs.eu.lever.co' else 'global'}
    if p.hostname in ('jobs.smartrecruiters.com','careers.smartrecruiters.com'):
        return {'kind':'smartrecruiters','board':parts[0]}
    return None


def resource_hits(resource,company,transport,fetcher,config):
    """Free, documented ATS read APIs or explicitly published employer feeds."""
    kind=resource['kind']
    board=resource.get('board','')
    if kind in ('greenhouse','lever','smartrecruiters') and not re.fullmatch(r'[A-Za-z0-9_-]+',board):
        raise ValueError('Invalid board slug')
    hits=[]
    if kind=='greenhouse':
        endpoint=f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs'
        data=transport.get('greenhouse',endpoint,params={'content':'true'})
        if not isinstance(data.get('jobs'),list): raise ValueError('Invalid Greenhouse schema')
        for row in data['jobs']:
            title=plain(row.get('title')); description=plain(row.get('content'))
            if not title or not internship_role(title,description): continue
            city=row.get('location',{}).get('name','')
            if not in_scope(city+' '+description,config): continue
            url=_https(row.get('absolute_url'))
            if url:
                hits.append({'url':url,'title':title,'company_name':company['name'],'requirements':description[:12000],
                    'location_hint':city,'city':city or 'Unknown','entry_id':str(row.get('id','')),
                    'source_url':endpoint,'provider':'greenhouse','kind':'opportunity_lead'})
    elif kind=='lever':
        host='api.eu.lever.co' if resource.get('region')=='eu' else 'api.lever.co'
        endpoint=f'https://{host}/v0/postings/{board}'
        # Read API pagination, capped per run; stable IDs and periodic refresh deduplicate repeated pages.
        for page in range(config['max_pages_per_query']):
            data=transport.get('lever',endpoint,params={'mode':'json','skip':page*100,'limit':100})
            if not isinstance(data,list): raise ValueError('Invalid Lever schema')
            for row in data:
                title=plain(row.get('text')); description=plain(row.get('descriptionPlain') or row.get('description'))
                city=row.get('categories',{}).get('location','')
                if not title or not internship_role(title,description,str(row.get('categories',{}).get('commitment',''))) or not in_scope(city+' '+description,config): continue
                url=_https(row.get('hostedUrl'))
                if url:
                    hits.append({'url':url,'title':title,'company_name':company['name'],'requirements':description[:12000],
                        'location_hint':city,'city':city or 'Unknown','entry_id':row.get('id',''),
                        'posted_at':datetime.fromtimestamp(row['createdAt']/1000,timezone.utc).date().isoformat() if isinstance(row.get('createdAt'),(int,float)) else '',
                        'apply_url':_https(row.get('applyUrl')),'source_url':endpoint,'provider':'lever','kind':'opportunity_lead'})
            if len(data)<100: break
    elif kind=='smartrecruiters':
        endpoint=f'https://api.smartrecruiters.com/v1/companies/{board}/postings'
        details_read=0
        for page in range(config['max_pages_per_query']):
            data=transport.get('smartrecruiters',endpoint,params={'offset':page*100,'limit':100})
            if not isinstance(data.get('content'),list):raise ValueError('Invalid SmartRecruiters public postings schema')
            for row in data['content']:
                title=plain(row.get('name'));city=row.get('location',{}).get('city','')
                employment=row.get('typeOfEmployment',{}).get('label','')
                if not title or not internship_role(title,employment=employment) or not in_scope(city,config):continue
                url=_https(row.get('ref'))
                if not url:continue
                # Public posting detail can supply the actual employer-provided apply URL.
                if urlsplit(url).hostname!='api.smartrecruiters.com' or not urlsplit(url).path.casefold().startswith(f'/v1/companies/{board}/postings/'.casefold()):continue
                if details_read>=config['links_per_page']:break
                detail=transport.get('smartrecruiters',url);details_read+=1
                employer=detail.get('company',{})
                # Do not trust a conflicting employer identity from a shared ATS response.
                if employer.get('name') and employer['name'].casefold() not in {company['name'].casefold(),*(n.casefold() for n in company.get('name_aliases',[]))}:continue
                sections=detail.get('jobAd',{}).get('sections',{})
                description=' '.join(plain(section.get('text')) for section in sections.values() if isinstance(section,dict))
                apply=_https(detail.get('applyUrl'))
                hits.append({'url':apply or url,'title':title,'company_name':company['name'],'requirements':description[:12000],
                    'city':city or 'Unknown','location_hint':city,'entry_id':str(row.get('id','')),
                    'posted_at':date_value(row.get('releasedDate')),'apply_url':apply,'source_url':url,
                    'provider':'smartrecruiters','kind':'opportunity_lead'})
            if len(data['content'])<100:break
    elif kind=='feed':
        endpoint=resource['url']; hits,_=parse_feed(fetcher.document(endpoint),config)
        for hit in hits: hit.update(company_name=company['name'],source_url=endpoint,provider='official-feed')
    else:
        raise ValueError('Unsupported free resource')
    return hits


def check_free_sources(config=None,provider=None):
    """Reproducible read-only live check: no DB writes, messaging, paid APIs or applications."""
    from .core import demo
    if demo(): return {'demo':True,'status':'disabled','checks':[]}
    from .discovery import load_config
    from .search import APITransport,query_tasks
    from .sources import Fetcher
    config=config or load_config()
    provider=provider or PublicSources(APITransport(config['provider_interval_seconds']),config,Fetcher())
    checks=[]
    for task in query_tasks(config,'public_sources'):
        source=task['source']
        try:
            hits,more=provider.search(task,0,config['results_per_page'])
            checks.append({'source':source['name'],'url':source['url'],'status':'ok','returned_leads':len(hits),
                'more':more,'statistics':provider.statistics.get(source['name'],{}),
                'verification':'Collection/parsing only. Leads are not verified vacancies or Saudi eligibility.'})
        except Exception:
            checks.append({'source':source.get('name',source['url']),'status':'error',
                'error':'Public source collection/parsing unavailable; inspect configuration and network policy'})
    return {'demo':False,'status':'partial' if any(c['status']=='error' for c in checks) else 'ok','checks':checks}


class OverpassDirectory:
    """Public OSM organization inventory; ODbL attribution retained, no office/ownership guarantees."""
    name='overpass'
    available=True
    def __init__(self,transport,config):
        self.transport,self.config,self.cache=transport,config,{}
    def search(self,task,page,count):
        city=task['location']; bounds=self.config['city_bounds'][city]
        if (not isinstance(bounds,list) or len(bounds)!=4 or
            not all(type(v) in (int,float) for v in bounds)):
            raise ValueError('City bounds must be numeric south,west,north,east')
        south,west,north,east=bounds
        if not (-90<=south<north<=90 and -180<=west<east<=180) or (north-south)*(east-west)>2:
            raise ValueError('City bounds invalid or exceed bounded query area')
        bbox=','.join(str(v) for v in bounds)
        # Explicit websites only; organization/local business categories, not guessed domains.
        query=f'''[out:json][timeout:20];(
          nwr["office"]["website"]({bbox});nwr["office"]["contact:website"]({bbox});
          nwr["amenity"~"bank|hospital|clinic|university|research_institute|townhall"]["website"]({bbox});
          nwr["amenity"~"bank|hospital|clinic|university|research_institute|townhall"]["contact:website"]({bbox});
          nwr["industrial"]["website"]({bbox});nwr["shop"]["website"]({bbox});
        );out tags;'''
        if city not in self.cache:
            data=self.transport.get(self.name,'https://overpass-api.de/api/interpreter',params={'data':query})
            if data.get('remark') or not isinstance(data.get('elements'),list):
                raise ProviderError('overpass: incomplete or invalid inventory response')
            hits=[]
            for element in data['elements']:
                tags=element.get('tags',{}); url=_https(tags.get('website') or tags.get('contact:website'))
                # HTTP website tags may seed an HTTPS candidate but are not themselves verified.
                if not url and isinstance(tags.get('website'),str) and tags['website'].startswith('http://'):
                    url=clean_url(tags['website'])
                name=tags.get('name:en') or tags.get('name') or tags.get('name:ar')
                element_type=element.get('type');id=element.get('id')
                if not url or not isinstance(name,str) or element_type not in ('node','way','relation') or not isinstance(id,int):continue
                source=f'https://www.openstreetmap.org/{element_type}/{id}'
                hits.append({'url':url,'title':name,'company_name':name,'kind':'company_lead','authority':'unverified',
                    'provider':self.name,'query':task['query'],'source_url':source,'entity_id':source,
                    'attribution_url':'https://www.openstreetmap.org/copyright',
                    'location_hint':f'Within configured {city} map bounds; address and department unverified',
                    'sector':tags.get('office') or tags.get('amenity') or tags.get('industrial') or tags.get('shop','Unknown')})
            self.cache[city]=hits
        hits=self.cache[city];start=page*count
        return hits[start:start+count], start+count<len(hits)
