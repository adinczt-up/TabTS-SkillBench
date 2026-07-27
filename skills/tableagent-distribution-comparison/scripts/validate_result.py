#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from pathlib import Path

def main():
 p=argparse.ArgumentParser(); p.add_argument('--input',required=True,type=Path); a=p.parse_args(); d=json.loads(a.input.read_text(encoding='utf-8-sig')); e=[]
 if d.get('comparison') not in {'exact','family'}: e.append('invalid comparison mode')
 if d.get('decision') not in {'same','different','undetermined'}: e.append('invalid decision')
 if d.get('failure_state') and d.get('decision')!='undetermined': e.append('decisive output under failure state')
 if d.get('comparison')=='family' and 'standardized_shape_ks' not in d: e.append('family comparison requires standardized evidence')
 print(json.dumps({'valid':not e,'errors':e},indent=2)); return 0 if not e else 1
if __name__=='__main__': raise SystemExit(main())