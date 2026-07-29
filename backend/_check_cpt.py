import sys, json
from pathlib import Path
sys.path.insert(0, '.')
from resource_library.inspector import inspect_resource

data = json.loads(Path('../.resource-index/resources.json').read_text(encoding='utf-8'))
target = None
for r in data['resources']:
    if r['relative_path'].endswith('财务经营管报日报.cpt'):
        target = r
        break

print('target:', target['relative_path'] if target else None)
if target:
    summary = inspect_resource(Path('../资源库'), target)
    print('status:', summary.status)
    print('warnings:', summary.warnings)
    print('signals keys:', list(summary.signals.keys()) if hasattr(summary, 'signals') else None)
    if hasattr(summary, 'signals'):
        for k, v in summary.signals.items():
            if isinstance(v, (str, int)):
                print(f'  {k}: {v}')
            elif isinstance(v, list):
                preview = v[:5]
                print(f'  {k} ({len(v)}): {preview}')
            elif isinstance(v, dict):
                print(f'  {k}: dict with keys {list(v.keys())[:5]}')
