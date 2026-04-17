#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

scripts/gen_flows.sh >/dev/null

python3 - <<'PY'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {'m': 'http://soap.sforce.com/2006/04/metadata'}
repo = Path('.').resolve()
flows_dir = repo / 'force-app/main/default/flows'

rtf_files = sorted(flows_dir.glob('RTF_*_AfterSave_TV.flow-meta.xml'))
subflow_files = sorted(flows_dir.glob('SUB_*_Main_Automation_TV.flow-meta.xml'))

if len(rtf_files) != 6:
    raise SystemExit(f'Expected 6 RTF files, found {len(rtf_files)}')
if len(subflow_files) != 6:
    raise SystemExit(f'Expected 6 main subflow files, found {len(subflow_files)}')

for path in rtf_files + subflow_files:
    ET.parse(path)

for path in rtf_files:
    tree = ET.parse(path)
    root = tree.getroot()
    for action in root.findall('m:actionCalls', NS):
        action_type = action.find('m:actionType', NS)
        if action_type is not None and (action_type.text or '').strip() == 'flow':
            raise SystemExit(f'Invalid actionCalls actionType=flow in {path.name}')

    start = root.find('m:start', NS)
    if start is None:
        raise SystemExit(f'Missing <start> in {path.name}')
    child_order = [child.tag.split('}', 1)[1] for child in list(start)]
    expected = ['locationX', 'locationY', 'connector', 'filterLogic', 'filters', 'object', 'recordTriggerType', 'triggerType']
    if child_order != expected:
        raise SystemExit(f'Unexpected start order in {path.name}: {child_order}')

    formula_names = []
    for f in root.findall('m:formulas', NS):
        n = f.find('m:name', NS)
        if n is not None:
            formula_names.append(n.text)
    if 'frmIsNewRecord' not in formula_names:
        raise SystemExit(f'Missing frmIsNewRecord formula in {path.name}')

for path in subflow_files:
    root = ET.parse(path).getroot()
    var_names = []
    for v in root.findall('m:variables', NS):
        n = v.find('m:name', NS)
        if n is not None:
            var_names.append(n.text)
    if 'inIsNewRecord' not in var_names:
        raise SystemExit(f'Missing inIsNewRecord variable in {path.name}')

print('Validation OK: generated flow metadata is well-formed and schema-aware.')
PY

if command -v xmllint >/dev/null 2>&1; then
  while IFS= read -r file; do
    xmllint --noout "$file"
  done < <(find force-app/main/default/flows -maxdepth 1 \( -name 'RTF_*_AfterSave_TV.flow-meta.xml' -o -name 'SUB_*_Main_Automation_TV.flow-meta.xml' \) | sort)
  echo "xmllint OK for generated flow files."
else
  echo "xmllint not found; XML parse checks were completed with Python."
fi
