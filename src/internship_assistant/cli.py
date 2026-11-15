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
    parser.add_argument('command', choices=['demo','discover','monitor','notify','sync','discovery-status','discovery-candidates'])
    args = parser.parse_args()
    store = Store()
    try:
        if args.command in ('discover','monitor') and demo():
            raise ValueError('Live source commands require DEMO_MODE=false; use demo instead')
        from .discovery_store import DiscoveryStore
        actions = {'demo':load_demo, 'discover':discover, 'monitor':monitor, 'notify':notify, 'sync':sheet_sync,
                   'discovery-status':lambda s: DiscoveryStore(s).status(),
                   'discovery-candidates':lambda s: DiscoveryStore(s).candidates()}
        print(json.dumps(actions[args.command](store), indent=2, ensure_ascii=False))
    finally:
        store.db.close()

if __name__ == '__main__':
    main()
