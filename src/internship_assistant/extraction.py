"""Deterministic evidence extraction; ambiguous source content stays a lead."""
import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit, unquote
from bs4 import BeautifulSoup
from .core import normalized, now
from .discovery_store import clean_url, host_key

INTERNSHIP = re.compile(r'\b(intern(?:ship)?s?|co[ -]?op|summer\s+(?:training|research)|research\s+(?:placement|training))\b|تدريب|تعاوني', re.I)
CAREER = re.compile(r'career|intern|co-?op|vacanc|jobs?|recruit|training|توظيف|وظائف|تدريب', re.I)
CONTACT = re.compile(r'contact|about|اتصل|تواصل|عن الشركة', re.I)
EMAIL = re.compile(r'^[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}$', re.I)
RECRUITMENT = re.compile(r'(?:apply|applications?|CV|resume).{0,70}(?:email|e-mail|send|to)|(?:recruitment|careers?)\s+(?:email|enquiries|contact)|(?:إرسال|ارسل|أرسل).{0,60}(?:السيرة|طلب)', re.I)
ORGANIZATION_TYPES = {'Organization','Corporation','LocalBusiness','GovernmentOrganization','EducationalOrganization','CollegeOrUniversity','Hospital','MedicalOrganization','ResearchOrganization','BankOrCreditUnion'}


def types(node):
    value = node.get('@type', [])
    return {v for v in (value if isinstance(value,list) else [value]) if isinstance(v,str)}


def structured(page):
    nodes = []
    def visit(value):
        if isinstance(value,list):
            for child in value:
                visit(child)
        elif isinstance(value,dict):
            nodes.append(value)
            for child in value.values():
                if isinstance(child,(dict,list)):
                    visit(child)
    for script in page.select('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError, RecursionError):
            continue
    return nodes


def plain(value):
    return BeautifulSoup(value, 'html.parser').get_text(' ',strip=True) if isinstance(value,str) else ''


def date_value(value):
    if not isinstance(value,str):
        return ''
    try:
        # Validate complete ISO format, then retain its stated calendar date; never guess locale.
        datetime.fromisoformat(value.replace('Z','+00:00'))
        return value[:10] if re.match(r'^\d{4}-\d{2}-\d{2}(?:T|$)',value) else ''
    except ValueError:
        return ''


def https_link(base, value):
    if not isinstance(value,str) or not value.strip():
        return ''
    try:
        url = urljoin(base,value.strip())
        # Do not silently upgrade a published application method; retain HTTPS evidence only.
        return clean_url(url) if urlsplit(url).scheme == 'https' else ''
    except ValueError:
        return ''


def organizations(page, url):
    results = []
    for node in structured(page):
        if not (types(node) & ORGANIZATION_TYPES) or not isinstance(node.get('name'),str):
            continue
        website = https_link(url,node.get('url',''))
        if website:
            results.append({'name':plain(node['name']), 'url':website})
    return results


def public_contacts(page, url, trusted):
    contacts = []
    for a in page.select('a[href^="mailto:"]'):
        email = unquote(a['href'][7:].split('?')[0]).strip()
        if not EMAIL.fullmatch(email):
            continue
        block = a.find_parent(['p','li','address','td']) or a.parent
        context = block.get_text(' ',strip=True)[:500]
        kind = 'recruitment' if trusted and RECRUITMENT.search(context) else 'general'
        contacts.append({'email':email, 'kind':kind, 'source_url':url, 'evidence':context,
                         'verified_at':now(), 'verification_status':'published on official-linked page' if trusted else 'published; website ownership unconfirmed'})
    # JSON-LD publishes explicit emails too; never synthesize mailbox names.
    for node in structured(page):
        email = node.get('email','')
        if isinstance(email,str) and EMAIL.fullmatch(email.removeprefix('mailto:')):
            contacts.append({'email':email.removeprefix('mailto:'), 'kind':'general', 'source_url':url,
                             'evidence':'Explicit JSON-LD email', 'verified_at':now(),
                             'verification_status':'published on official-linked page' if trusted else 'published; website ownership unconfirmed'})
    return list({(c['email'].lower(),c['kind']):c for c in contacts}.values())


def page_links(page, url, max_links):
    from .social import is_linkedin,linkedin_identity
    links = []
    for a in page.select('a[href]'):
        target = https_link(url,a['href'])
        if not target:
            continue
        if is_linkedin(target):
            try:linkedin_identity(target)
            except ValueError:continue
        text = a.get_text(' ',strip=True)
        relevant = CAREER.search(text + ' ' + urlsplit(target).path)
        if relevant or (CONTACT.search(text) and host_key(target) == host_key(url)):
            links.append({'url':target,'title':text[:300], 'career':bool(relevant),
                'kind':'linkedin_lead' if is_linkedin(target) else 'page'})
    # Internship details before contact pages; preserve deterministic order and bound fanout.
    links.sort(key=lambda x: (not bool(INTERNSHIP.search(x['title'] + x['url'])),not x['career'],x['url']))
    return list({l['url']:l for l in links}.values())[:max_links]


def matching_employer(node, company):
    org = node.get('hiringOrganization')
    if not isinstance(org,dict):
        return None
    url = https_link(company['url'],org.get('url',''))
    if url and host_key(url) != host_key(company['url']):
        return False
    name = org.get('name')
    if isinstance(name,str):
        names = [company['name']] + company.get('name_aliases',[])
        return normalized(name) in {normalized(n) for n in names}
    return True if url else None


def job_locations(node):
    places = node.get('jobLocation',[])
    if isinstance(places,dict):
        places = [places]
    result = []
    for place in places if isinstance(places,list) else []:
        address = place.get('address',{}) if isinstance(place,dict) else {}
        if isinstance(address,dict) and isinstance(address.get('addressLocality'),str):
            result.append(address['addressLocality'])
    return sorted(set(result))


def kind_for(text):
    if re.search(r'\bco[ -]?op\b|تعاوني',text,re.I):
        return 'COOP'
    if re.search(r'\bsummer\b|صيفي',text,re.I):
        return 'Summer'
    if re.search(r'\bresearch\b|بحث',text,re.I):
        return 'Research'
    return 'Unspecified'


def _structured_opportunities(page, url, company, trusted, locations):
    from .evidence import internship_role
    results = []
    contacts = public_contacts(page,url,trusted)
    links = [(https_link(url,a['href']),a.get_text(' ',strip=True)) for a in page.select('a[href]')]
    apply = next((u for u,t in links if u and re.search(r'\bapply\b|application form|تقدم|التقديم',t,re.I)), '')
    official_same_host = host_key(url) == host_key(company['url'])
    job_nodes=[node for node in structured(page) if 'JobPosting' in types(node)]
    for node in job_nodes:
        if 'JobPosting' not in types(node):
            continue
        title, description = plain(node.get('title')), plain(node.get('description'))
        role_text = title + ' ' + str(node.get('employmentType','')) + ' ' + description
        if not title or not internship_role(title,description,str(node.get('employmentType',''))):
            continue
        match = matching_employer(node,company)
        # Shared ATS pages need explicit employer matching; even same-site mismatches stay out.
        if match is False or (not official_same_host and match is not True):
            continue
        cities = job_locations(node)
        scope = ' '.join(cities).casefold()
        target_match = any(city.casefold() in scope for city in locations) if cities else None
        # Keep other/unknown locations as visible uncertain leads; never infer from the query.
        identifier = node.get('identifier','')
        if isinstance(identifier,dict):
            identifier = str(identifier.get('value',''))
        if not isinstance(identifier,str):
            identifier = ''
        canonical = https_link(url,node.get('url',''))
        # Only use a structured canonical URL on the same host; cross-domain strings are leads.
        canonical = canonical if canonical and host_key(canonical) == host_key(url) else url
        recruitment = next((c for c in contacts if c['kind'] == 'recruitment'),None) if len(job_nodes)==1 else None
        general = next(iter(contacts),None) if len(job_nodes)==1 else None
        contact = recruitment or general or {}
        results.append({'company':company['name'],'company_url':company['url'],'company_id':company['id'],
            'title':title,'source_url':url,'canonical_job_url':canonical,'city':', '.join(cities) or 'Unknown',
            'location_match':target_match,'location_hint':company.get('city','Unknown'),
            'kind':kind_for(role_text),'eligibility':'Unknown','evidence':'', 'requirements':description[:12000],
            'external_id':identifier,'posted_at':date_value(node.get('datePosted')),
            'closes':date_value(node.get('validThrough')),'opens':'', 'apply_url':apply if len(job_nodes)==1 else '',
            'email':contact.get('email',''),'email_kind':contact.get('kind',''),
            'contact_evidence':contact.get('evidence',''), 'discovery_method':'automatic',
            'verification_status':'Official-source content fetched (website association: ' + company.get('authority','reviewed') + ')' if trusted else 'Website ownership unconfirmed; review required',
            'advertised_status':'Structured JobPosting; current availability must be reviewed',
            'extraction_evidence':{'type':'JobPosting','title':title,'datePosted':node.get('datePosted',''),'validThrough':node.get('validThrough','')}})
    return results


def extract_opportunities(page, url, company, trusted, locations):
    from .html_extraction import html_opportunities
    from .evidence import classify_record
    rows=_structured_opportunities(page,url,company,trusted,locations)
    # A shared external HTML board without an employer match cannot establish ownership.
    if host_key(url)==host_key(company['url']) or getattr(page,'official_referral',False):
        structured_rows=list(rows)
        for row in html_opportunities(page,url,company,trusted,include_detail=not bool(rows)):
            duplicate=any(normalized(known['title'])==normalized(row['title']) and (
                (row.get('external_id') and row['external_id']==known.get('external_id')) or
                (row.get('canonical_job_url')!=url and row.get('canonical_job_url')==known.get('canonical_job_url')))
                for known in structured_rows)
            if not duplicate:rows.append(row)
    output={}
    for row in rows:
        item=classify_record(row,trusted,program=row.pop('_program',False),html=row.pop('_html',False))
        key=(normalized(item['title']),item.get('canonical_job_url') or item['source_url'],item.get('city',''))
        output.setdefault(key,item)
    return list(output.values())
