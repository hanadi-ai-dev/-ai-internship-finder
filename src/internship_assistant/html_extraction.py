"""Scoped HTML cards/tables/detail pages: evidence must belong to the same listing."""
import re
from .core import normalized
from .evidence import internship_role, PROGRAM, ANNOUNCE, text_key
from .extraction import https_link, kind_for, date_value, public_contacts

APPLY=re.compile(r'\b(?:apply|application form|submit application|register now)\b|التقديم|قدم الان|تقدم|سجل الان',re.I)
DETAIL=re.compile(r'details|view (?:job|opportunity)|learn more|التفاصيل|عرض الفرصة|عرض الوظيفة',re.I)
DATE=re.compile(r'\d{4}-\d{2}-\d{2}(?:T[0-9:+.Z-]+)?')
CLOSE=re.compile(r'deadline|clos(?:ing|es)|apply by|اخر موعد|نهاية التقديم|ينتهي التقديم',re.I)
START=re.compile(r'applications? open(?:s| from)|opening date|بداية التقديم|يبدا التقديم',re.I)
LOCATION=re.compile(r'location|city|الموقع|المدينة|مدينة',re.I)
TITLE=re.compile(r'job title|position|role|opportunity|المسمي|الوظيفة|الفرصة|البرنامج',re.I)


def dates_from_block(block,columns):
    dates={};evidence={}
    for field,pattern in [('closes',CLOSE),('opens',START)]:
        for node in block.select('time[datetime]'):
            context=node.parent.get_text(' ',strip=True)
            if pattern.search(text_key(context)) and date_value(node['datetime']):
                dates[field]=date_value(node['datetime']);evidence[field]=context[:500]+' [datetime='+node['datetime']+']'
        contexts=[value for label,value in columns if pattern.search(text_key(label))]
        contexts += [node.get_text(' ',strip=True) for node in block.select('p,li,time,[class*="deadline"],[class*="closing"]')
                     if pattern.search(text_key(node.get_text(' ',strip=True)))]
        # Plain detail pages can publish one labelled ISO date in a text node.
        for node in block.find_all(string=pattern):
            parent=node.parent
            if len(parent.get_text(' ',strip=True))<=600:contexts.append(parent.get_text(' ',strip=True))
        for context in contexts:
            if field in dates:break
            match=DATE.search(context)
            if match and date_value(match[0]):
                dates[field]=date_value(match[0]);evidence[field]=context[:600];break
    return dates,evidence


def scoped_method(block,url,title):
    apply=[];detail=[]
    for a in block.select('a[href]'):
        target=https_link(url,a['href'])
        if not target:continue
        text=a.get_text(' ',strip=True)
        if APPLY.search(text_key(text)):apply.append(target)
        if DETAIL.search(text_key(text)) or normalized(text)==normalized(title):detail.append(target)
    return next(iter(apply),''),next(iter(detail),'')


def html_opportunities(page,url,company,trusted,include_detail=True):
    blocks=[]
    for table in page.select('table'):
        header=table.select_one('tr')
        labels=[cell.get_text(' ',strip=True) for cell in header.find_all(['th','td'],recursive=False)] if header else []
        for row in table.select('tr'):
            cells=row.find_all('td',recursive=False)
            if not cells:continue
            columns=list(zip(labels,[c.get_text(' ',strip=True) for c in cells]))
            title=next((value for label,value in columns if TITLE.search(text_key(label))),'')
            if not title:
                title=next((cell.get_text(' ',strip=True) for cell in cells if internship_role(cell.get_text(' ',strip=True))), '')
            if title and internship_role(title):blocks.append((row,title,columns,'table'))
    for block in page.select('article,.job-card,.vacancy,.job-listing,[data-job-id],li.job,li.vacancy'):
        heading=block.select_one('h2,h3,h4,.job-title,.vacancy-title,[data-job-title]')
        if not heading:continue
        title=heading.get_text(' ',strip=True)
        if internship_role(title,block.get_text(' ',strip=True)):blocks.append((block,title,[],'card'))
    # A detail/announcement page is separate from a multi-card listing. Never borrow a
    # page-wide Apply button for a card that lacks its own method.
    h1=page.select_one('h1')
    if not blocks and h1 and include_detail:
        main=h1.find_parent('article') or page.select_one('main,article') or page.body or page
        title=h1.get_text(' ',strip=True)
        if internship_role(title,main.get_text(' ',strip=True)):blocks.append((main,title,[],'announcement'))
    results=[]
    for block,title,columns,layout in blocks:
        text=block.get_text(' ',strip=True)
        apply,detail=scoped_method(block,url,title)
        dates,date_evidence=dates_from_block(block,columns)
        contacts=public_contacts(block,url,trusted)
        contact=next((c for c in contacts if c['kind']=='recruitment'),{})
        city=next((value for label,value in columns if LOCATION.search(text_key(label))), '')
        if not city:
            location=block.select_one('[data-location],.location,.job-location,.city')
            city=(location.get('data-location') or location.get_text(' ',strip=True)) if location else ''
        if not city:
            city='Unknown'
            for field in block.select('p,span,li'):
                match=re.fullmatch(r'(?:Location|City|الموقع|المدينة)\s*[:：]\s*(.{1,100})',field.get_text(' ',strip=True),re.I)
                if match and not APPLY.search(text_key(match[1])) and not CLOSE.search(text_key(match[1])):
                    city=match[1].strip();break
        program=bool(layout=='announcement' and PROGRAM.search(text_key(title)) and not dates and
                     not ANNOUNCE.search(text_key(text)) and not re.search(r'\b20\d{2}\b',title))
        item={'company':company['name'],'company_url':company['url'],'company_id':company['id'],
            'title':title,'source_url':url,'city':city,'kind':kind_for(title),
            'eligibility':'Unknown','evidence':'','requirements':text[:12000],'apply_url':apply,
            'canonical_job_url':detail or url,'external_id':block.get('data-job-id',''),
            'closes':dates.get('closes',''),'opens':dates.get('opens',''),
            'email':contact.get('email',''),'email_kind':contact.get('kind',''),
            'contact_evidence':contact.get('evidence',''),'discovery_method':'automatic',
            'verification_status':'Official-source content fetched' if trusted else 'Website ownership unconfirmed; review required',
            'extraction_evidence':{'layout':layout,'title':title,'excerpt':text[:1600],
                'application_url':apply,'detail_url':detail,'dates':date_evidence},
            '_program':program,'_html':True}
        results.append(item)
    return results
