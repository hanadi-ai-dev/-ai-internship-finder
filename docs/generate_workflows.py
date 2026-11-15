"""Regenerate importable n8n workflows without credentials or instance IDs."""
import json
import os
from zoneinfo import ZoneInfo
from pathlib import Path


with open(os.getenv('DISCOVERY_CONFIG', 'config/discovery.json')) as f:
    schedule = json.load(f)['schedules']
ZoneInfo(schedule['timezone'])
for field in ('discovery_cron','monitor_cron','notifications_cron'):
    if len(schedule[field].split()) not in (5,6):
        raise ValueError('Use a 5- or 6-field n8n cron expression')

def request(id, name, path, position):
    return {'id':id, 'name':name, 'type':'n8n-nodes-base.httpRequest', 'typeVersion':4.2, 'position':position,
        'parameters':{'method':'POST', 'url':'http://assistant:8000' + path,
                      'authentication':'genericCredentialType', 'genericAuthType':'httpHeaderAuth',
                      'options':{'timeout':900000}},
        'retryOnFail':True, 'maxTries':3, 'waitBetweenTries':5000}

for file, name, cron, paths in [
    ('01_company_discovery', 'Internships — company discovery', schedule['discovery_cron'], [('Discover companies','/discover'),('Sync discovery to Sheets','/sync')]),
    ('02_internship_monitoring', 'Internships — monitor and sync', schedule['monitor_cron'], [('Monitor official sources','/monitor'),('Sync Google Sheets','/sync')]),
    ('03_notifications', 'Internships — notifications', schedule['notifications_cron'], [('New opportunity alerts','/notify/new'),('Deadline and follow-up reminders','/notify/deadlines'),('Daily summary','/notify/daily')]),
]:
    trigger = {'id':'schedule', 'name':'Daily schedule', 'type':'n8n-nodes-base.scheduleTrigger','typeVersion':1.2,'position':[0,0], 'parameters':{'rule':{'interval':[{'field':'cronExpression','expression':cron}]}}}
    manual = {'id':'manual','name':'Manual test','type':'n8n-nodes-base.manualTrigger','typeVersion':1,'position':[0,200],'parameters':{}}
    nodes = [trigger, manual] + [request(str(i), title, path, [(i+1)*260,0]) for i,(title,path) in enumerate(paths)]
    connections = {'Daily schedule':{'main':[[{'node':paths[0][0], 'type':'main','index':0}]]},'Manual test':{'main':[[{'node':paths[0][0], 'type':'main','index':0}]]}}
    for (title,_),(next_title,_) in zip(paths,paths[1:]):
        connections[title] = {'main':[[{'node':next_title,'type':'main','index':0}]]}
    workflow = {'name':name,'nodes':nodes,'connections':connections,'active':False,'settings':{'executionOrder':'v1','timezone':schedule['timezone']},'tags':[]}
    Path('workflows/' + file + '.json').write_text(json.dumps(workflow, indent=2) + '\n')
# No send node: approval and sending remain deliberate authenticated API actions.
workflow = {'name':'Internships — future application review (manual only)', 'active':False,
    'nodes':[{'id':'manual','name':'Manual review','type':'n8n-nodes-base.manualTrigger','typeVersion':1,'position':[0,0],'parameters':{}},
    {'id':'list','name':'List application drafts','type':'n8n-nodes-base.httpRequest','typeVersion':4.2,'position':[260,0],
     'parameters':{'url':'http://assistant:8000/applications','authentication':'genericCredentialType','genericAuthType':'httpHeaderAuth','options':{'timeout':30000}}}],
    'connections':{'Manual review':{'main':[[{'node':'List application drafts','type':'main','index':0}]]}},
    'settings':{'executionOrder':'v1','timezone':schedule['timezone']},'tags':[]}
Path('workflows/04_application_review.json').write_text(json.dumps(workflow,indent=2) + '\n')
