import argparse
import json
from pathlib import Path
from .core import Store, demo
from .sources import discover, monitor
from .integrations import notify, sheet_sync

def load_demo(store):
    if not demo():
        raise ValueError('Demo import requires DEMO_MODE=true')
    with open('data/demo/opportunities.json') as f:
        return [store.upsert(i) for i in json.load(f)]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['demo','discover','monitor','notify','sync','discovery-status','discovery-candidates','free-source-check','import-leads','diagnose-targets'])
    parser.add_argument('--file',help='JSON array of public LinkedIn URL leads (import-leads only)')
    args = parser.parse_args()
    if args.command == 'diagnose-targets':
        from .network import diagnose_targets
        print(json.dumps({'demo':True,'status':'disabled','targets':[]} if demo() else diagnose_targets(),indent=2,ensure_ascii=False))
        return
    if args.command == 'import-leads' and not args.file:
        parser.error('import-leads requires --file with a public URL JSON array')
    if args.command == 'free-source-check':
        from .free_sources import check_free_sources
        print(json.dumps(check_free_sources(),indent=2,ensure_ascii=False))
        return
    store = Store()
    try:
        if args.command in ('discover','monitor') and demo():
            raise ValueError('Live source commands require DEMO_MODE=false; use demo instead')
        from .discovery_store import DiscoveryStore
        from .social import import_linkedin_leads
        def import_file(s):
            path=Path(args.file)
            if path.stat().st_size>1_000_000:raise ValueError('Lead import exceeds 1 MB')
            return import_linkedin_leads(s,json.loads(path.read_text(encoding='utf-8')))
        actions = {'import-leads':import_file,'demo':load_demo, 'discover':discover, 'monitor':monitor, 'notify':notify, 'sync':sheet_sync,
                   'discovery-status':lambda s: DiscoveryStore(s).status(),
                   'discovery-candidates':lambda s: DiscoveryStore(s).candidates()}
        print(json.dumps(actions[args.command](store), indent=2, ensure_ascii=False))
    finally:
        store.db.close()

if __name__ == '__main__':
    main()
