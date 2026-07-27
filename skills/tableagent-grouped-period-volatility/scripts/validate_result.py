#!/usr/bin/env python3
"""Recompute a Skill result from its declared source and parameters."""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from execute_analysis import compute

def normalized(value):
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 12)
    if isinstance(value, list): return [normalized(x) for x in value]
    if isinstance(value, dict): return {k: normalized(v) for k, v in value.items()}
    return value

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True,type=Path); ap.add_argument('--output',type=Path)
    args=ap.parse_args(); observed=json.loads(args.input.read_text(encoding='utf-8-sig'))
    required={'operation','status','input','parameters','result_rows','selected_rows','checks'}
    missing=sorted(required-set(observed)); errors=[]
    if missing: errors.append('missing_fields:'+','.join(missing))
    if observed.get('status')!='ok': errors.append('non_ok_result')
    if not errors:
        expected=compute(Path(observed['input']), observed['parameters'])
        if normalized(expected)!=normalized(observed): errors.append('source_recomputation_mismatch')
        if not observed.get('selected_rows'): errors.append('empty_selection')
        if not all(bool(v) for v in observed.get('checks',{}).values()): errors.append('failed_invariant')
    report={'status':'ok' if not errors else 'failed','valid':not errors,'source_result':str(args.input),'errors':errors,'recomputed_from_source':not errors}
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output: args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(text+'\n',encoding='utf-8')
    else: print(text)
    return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(main())