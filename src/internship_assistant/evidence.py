"""Conservative bilingual role/announcement evidence, independent of website layout."""
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo


def text_key(text):
    text=unicodedata.normalize('NFKC',str(text)).casefold()
    return re.sub(r'[\u064b-\u065f\u0670\u0640]','',text).translate(str.maketrans('أإآى','اااي'))

ROLE = re.compile(r'\b(?:intern(?:ship)?s?|co[ -]?op|summer (?:training|research)|research (?:placement|internship)|student trainee)\b|(?:تدريب|التدريب)\s*(?:التعاوني|تعاوني|الصيفي|صيفي|الطلابي|طلاب)|(?:فرص|فرصة|برنامج|برامج)\s+(?:للتدريب|تدريب|التدريب)|متدرب(?:ة|ين|ون)?',re.I)
ANNOUNCE = re.compile(r'(?:applications?|registration).{0,35}(?:now open|are open|open for)|(?:hiring|recruiting|seeking).{0,35}\binterns?\b|(?:فتح|بدء|بدا|متاح|متاحة).{0,35}(?:التقديم|التسجيل)|تعلن.{0,70}(?:تدريب|متدرب)',re.I)
CLOSED = re.compile(r'\b(?:applications?|registration|position|opportunity).{0,25}(?:closed|expired|filled)\b|\bno longer accepting\b|\bexpired\b|التقديم\s*(?:مغلق|منتهي)|(?:انتهي|انتهت|اغلاق|اغلق).{0,30}(?:التقديم|التسجيل)|انتهت\s+(?:الفرصة|فترة)',re.I)
OPEN = re.compile(r'(?:applications?|registration).{0,25}(?:now open|are open)|apply now|(?:التقديم|التسجيل)\s*(?:مفتوح|متاح)|فتح باب (?:التقديم|التسجيل)',re.I)
PROGRAM = re.compile(r'\b(?:program(?:me)?s?|overview|about our|career pathways)\b|برنامج|برامج|عن البرنامج',re.I)
ORDINARY = re.compile(r'\b(?:senior|lead|principal|manager|director|permanent)\b|(?:مدير|خبير|اخصائي اول|مهندس اول)',re.I)


def internship_role(title,description='',employment=''):
    """Mentoring interns / previous internship experience does not turn a job into training."""
    title,description,employment=map(text_key,(title,description,employment))
    if re.search(r'\b(?:manager|director|coordinator|recruiter|trainer|head)\b|مدير|منسق|مدرب|مسوول',title) and not re.search(r'\binterns?\b|متدرب',title):
        return False  # An internship-program manager/recruiter is an ordinary staff role.
    if ROLE.search(title) or ROLE.search(employment):
        return True  # Full-time internships and COOP are legitimate; label alone never excludes.
    if re.match(r'^تدريب\s+',title) and ROLE.search(description):
        return True  # E.g. "تدريب الأمن السيبراني" with explicit COOP/student evidence.
    if ORDINARY.search(title):
        return False
    # A generic announcement heading may rely on an explicit announcement sentence,
    # but an ordinary engineer job cannot borrow an internship mention from its prose.
    generic=bool(re.search(r'announcement|opportunit|training|اعلان|فرص|تدريب|طلاب',title))
    return generic and bool(ANNOUNCE.search(description) and ROLE.search(description))


def classify_record(item,trusted,*,program=False,html=False,today=None):
    item=dict(item)
    text=text_key(item.get('title','')+' '+item.get('requirements',''))
    today=today or datetime.now(ZoneInfo('Asia/Riyadh')).date()
    closes=item.get('closes','')
    expired=bool(closes and datetime.strptime(closes,'%Y-%m-%d').date()<today)
    explicit_closed=bool(CLOSED.search(text))
    explicit_open=bool(OPEN.search(text))
    item['availability']='Closed' if expired or explicit_closed else ('Open (source statement)' if explicit_open else 'Unknown')
    if expired or explicit_closed:
        category='closed'
        status='Expired or closed opportunity; do not assume applications are accepted'
    elif program:
        category='general_program'
        status='General career/internship program page; no current vacancy verified'
    elif trusted and (not html or item.get('apply_url') or item.get('email_kind')=='recruitment' or ANNOUNCE.search(text)):
        category='verified_announcement'
        status='Verified internship announcement; current availability unconfirmed' if not explicit_open else 'Verified announcement; source states applications open'
    else:
        category='potential_lead'
        status='Potential internship lead; official confirmation and availability review required'
    item.update(record_class=category,advertised_status=status)
    if category=='general_program':
        item['verification_status']='General program page; current opening unconfirmed'
    elif category=='potential_lead':
        item['verification_status']='Unverified or incomplete internship lead; ownership/availability unconfirmed'
    elif category=='closed':
        item['verification_status']='Closed/expired source record; review evidence'
    return item


def page_outcome(page,records):
    if records:
        classes={r['record_class'] for r in records}
        return next(iter(classes)) if len(classes)==1 else 'multiple_opportunities'
    heading=page.select_one('h1')
    text=text_key(heading.get_text(' ',strip=True)) if heading else ''
    if (ROLE.search(text) and PROGRAM.search(text)) or re.fullmatch(r'careers?|jobs|فرص العمل|الوظائف|التوظيف',text):
        return 'general_program'
    return 'no_internship_announcements'
