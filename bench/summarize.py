#!/usr/bin/env python3
"""Print one Markdown table comparing every results/*.json (phase seconds per machine)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

folder = Path(sys.argv[1] if len(sys.argv) > 1 else 'results')
runs = [json.loads(p.read_text()) for p in sorted(folder.rglob('*.json'))]
if not runs:
    sys.exit('no results')
phases = []
for run in runs:
    for p in run['phases']:
        if p['phase'] not in phases:
            phases.append(p['phase'])

print('| Phase | ' + ' | '.join(r['label'] for r in runs) + ' |')
print('|---|' + '---|' * len(runs))
for name in phases:
    cells = []
    for run in runs:
        p = next((x for x in run['phases'] if x['phase'] == name), None)
        if not p or p['seconds'] is None:
            cells.append('–')
            continue
        flag = '' if p['exit'] == 0 else f' (exit {p["exit"]})'
        swap = f', swap +{p["swap_growth_mb"]} MB' if p.get('swap_growth_mb') else ''
        cells.append(f'{p["seconds"]:.0f}s{flag}{swap}')
    print(f'| {name} | ' + ' | '.join(cells) + ' |')
print()
for run in runs:
    m = run['machine']
    print(f'- **{run["label"]}**: {m.get("cpu") or m.get("platform")}, {m.get("cores")} cores, '
          f'{m.get("memory_gb")} GB; {m.get("xcode") or m.get("swift")}; '
          f'disk free {run["disk_free_gb_start"]} → {run["disk_free_gb_end"]} GB')
