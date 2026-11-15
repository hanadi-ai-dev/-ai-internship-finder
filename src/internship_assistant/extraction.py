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
    return set(value if isinstance(value,list) else [value])


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
    links = []
    for a in page.select('a[href]'):
        target = https_link(url,a['href'])
        if not target:
            continue
        text = a.get_text(' ',strip=True)
        relevant = CAREER.search(text + ' ' + urlsplit(target).path)
        if relevant or (CONTACT.search(text) and host_key(target) == host_key(url)):
            links.append({'url':target,'title':text[:300], 'career':bool(relevant)})
    # Internship details before contact pages; preserve deterministic order and bound fanout.
    links.sort(key=lambda x: (not bool(INTERNSHIP.search(x['title'] + x['url'])),not x['career'],x['url']))
    return list({l['url']:l for l in links}.values())[:max_links]


def matching_employer(node, company):
    org = node.get('hiringOrganization')
    if not isinstance(org,dict):
        return None
    url = https_link(company['url'],org.get('url',''))
    if url and host_key(url) == host_key(company['url']):
        return True
    name = org.get('name')
    if isinstance(name,str):
        names = [company['name']] + company.get('name_aliases',[])
        return normalized(name) in {normalized(n) for n in names}
    return None


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


def extract_opportunities(page, url, company, trusted, locations):
    results = []
    contacts = public_contacts(page,url,trusted)
    links = [(https_link(url,a['href']),a.get_text(' ',strip=True)) for a in page.select('a[href]')]
    apply = next((u for u,t in links if u and re.search(r'\bapply\b|application form|تقدم|التقديم',t,re.I)), '')
    official_same_host = host_key(url) == host_key(company['url'])
    for node in structured(page):
        if 'JobPosting' not in types(node):
            continue
        title, description = plain(node.get('title')), plain(node.get('description'))
        role_text = title + ' ' + str(node.get('employmentType','')) + ' ' + description
        if not title or not INTERNSHIP.search(role_text):
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
        recruitment = next((c for c in contacts if c['kind'] == 'recruitment'),None)
        general = next(iter(contacts),None)
        contact = recruitment or general or {}
        results.append({'company':company['name'],'company_url':company['url'],'company_id':company['id'],
            'title':title,'source_url':url,'canonical_job_url':canonical,'city':', '.join(cities) or 'Unknown',
            'location_match':target_match,'location_hint':company.get('city','Unknown'),
            'kind':kind_for(role_text),'eligibility':'Unknown','evidence':'', 'requirements':description[:12000],
            'external_id':identifier,'posted_at':date_value(node.get('datePosted')),
            'closes':date_value(node.get('validThrough')),'opens':'', 'apply_url':apply,
            'email':contact.get('email',''),'email_kind':contact.get('kind',''),
            'contact_evidence':contact.get('evidence',''), 'discovery_method':'automatic',
            'verification_status':'Official-source content fetched (website association: ' + company.get('authority','reviewed') + ')' if trusted else 'Website ownership unconfirmed; review required',
            'advertised_status':'Structured JobPosting; current availability must be reviewed',
            'extraction_evidence':{'type':'JobPosting','title':title,'datePosted':node.get('datePosted',''),'validThrough':node.get('validThrough','')}})
    # HTML announcement fallback requires a specific internship heading plus an explicit apply link.
    # Generic career/internship program pages remain candidates instead of invented vacancies.
    heading = page.select_one('h1')
    if not results and heading and INTERNSHIP.search(heading.get_text(' ',strip=True)) and apply and official_same_host:
        title = heading.get_text(' ',strip=True)
        if len(title.split()) >= 3:
            main = page.select_one('main,article') or page.body or page
            results.append({'company':company['name'],'company_url':company['url'],'company_id':company['id'],
                'title':title,'source_url':url,'city':'Unknown','location_hint':company.get('city','Unknown'),
                'kind':kind_for(title),'eligibility':'Unknown','evidence':'','closes':'','opens':'',
                'requirements':main.get_text(' ',strip=True)[:12000], 'apply_url':apply,
                'discovery_method':'automatic','verification_status':'Announcement found; availability unconfirmed',
                'advertised_status':'Announcement; human review required','extraction_evidence':{'heading':title,'apply_url':apply}})
    return results
