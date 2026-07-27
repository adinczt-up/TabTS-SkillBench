#!/usr/bin/env python3
"""Validate target-specific stationarity evidence without benchmark gold."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path


def check_block(block: dict, errors: list[str], name: str) -> None:
    rows=block.get('window_summaries',[])
    if len(rows)<2: errors.append(f'{name}: fewer than two windows'); return
    values=[float(r['variance']) for r in rows]
    ratio=(max(values)+1e-12)/(min(values)+1e-12)
    if not math.isclose(ratio,float(block.get('variance_ratio',math.nan)),rel_tol=1e-8,abs_tol=1e-8): errors.append(f'{name}: variance ratio mismatch')
    expected=ratio<=1.5 or block.get('brown_forsythe_p') is None or float(block['brown_forsythe_p'])>=0.01
    if bool(block.get('variance_stable')) != expected: errors.append(f'{name}: variance decision violates finite-sample guardrail')


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--input',required=True,type=Path); a=p.parse_args()
    d=json.loads(a.input.read_text(encoding='utf-8-sig')); errors=[]
    if d.get('failure_state') and d.get('decision') not in {None,'undetermined'}: errors.append('failure state must not carry a decisive answer')
    if d.get('level'): check_block(d['level'],errors,'level')
    if d.get('difference'): check_block(d['difference'],errors,'difference')
    allowed={'stable','unstable','stationary','nonstationary','stationary_after_differencing','not_stationary_after_differencing','seasonally_stationary','not_seasonally_stationary','stationary_anomaly','nonstationary_anomaly','undetermined'}
    if d.get('decision') not in allowed: errors.append('invalid decision')
    print(json.dumps({'valid':not errors,'errors':errors},indent=2)); return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(main())