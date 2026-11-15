"""Transparent relevance priorities, never an industry/eligibility exclusion filter."""
import re
from .evidence import text_key


def employer_priority(company):
    text=text_key(' '.join(str(company.get(k,'')) for k in ('name','sector','city','location_hint','url')))
    score=30;reasons=[]
    if company.get('priority')==1 or re.search(r'\bkaust\b|\bkacst\b|wadi jeddah|كاوست|وادي جدة|مدينة الملك عبدالعزيز',text):
        score+=50;reasons.append('Configured priority organization')
    groups=[(25,r'research|university|جامعة|ابحاث|بحوث','Research/university employer'),
            (20,r'\bai\b|software|technology|تقنية|ذكاء|برمجيات','Technical employer signal'),
            (15,r'government|bank|financ|hospital|health|حكوم|بنك|مالي|مستشفي|صحي','Relevant technical departments may exist across this sector'),
            (12,r'startup|sme|corporation|industrial|ناشئة|شركة|صناعي','Broad employer outreach potential')]
    for amount,pattern,reason in groups:
        if re.search(pattern,text):score+=amount;reasons.append(reason)
    if re.search(r'jeddah|riyadh|thuwal|جدة|الرياض|ثول',text):score+=10;reasons.append('Target city or query hint; actual location needs evidence')
    if re.search(r'embassy|consulate|diplomatic|سفارة|قنصلية|دبلوماس',text):
        score-=30;reasons.append('Diplomatic mission: lower discovery priority; retained for review')
    return {'priority_score':max(0,min(100,score)),'priority_reasons':reasons or ['Uncertain employer relevance; retained']}
