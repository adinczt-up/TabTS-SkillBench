#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

def read(p): return pd.read_parquet(p) if p.suffix.lower() in {'.parquet','.pq'} else pd.read_excel(p) if p.suffix.lower() in {'.xlsx','.xls'} else pd.read_csv(p,low_memory=False)
def main():
 p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--group',required=True); p.add_argument('--time',required=True); p.add_argument('--value',required=True); p.add_argument('--frequency',choices=['month','quarter','year'],required=True); p.add_argument('--target',required=True); p.add_argument('--top-k',type=int,default=3); p.add_argument('--output',type=Path); a=p.parse_args()
 d=read(a.file)[[a.group,a.time,a.value]].copy(); d[a.time]=pd.to_datetime(d[a.time],errors='coerce'); d[a.value]=pd.to_numeric(d[a.value],errors='coerce'); d=d.dropna(); freq={'month':'M','quarter':'Q','year':'Y'}[a.frequency]; d['period']=d[a.time].dt.to_period(freq)
 if d.duplicated([a.group,'period']).any(): out={'status':'failed','failure_state':'duplicate_group_period'}; code=1
 else:
  target=pd.Period(a.target,freq=freq); rows=[]; failures=[]
  for group,g in d.groupby(a.group,dropna=False,sort=True):
   values=dict(zip(g.period,g[a.value])); missing=[]
   for label,period in [('actual',target),('previous',target-1),('next',target+1)]:
    if period not in values: missing.append(label)
   if missing: failures.append({'segment':str(group),'reason':'target_not_observed' if 'actual' in missing else 'missing_adjacent_period','missing':missing}); continue
   actual=float(values[target]); prev=float(values[target-1]); nxt=float(values[target+1]); imp=(prev+nxt)/2
   rows.append({'segment':str(group),'target_period':str(target),'previous_period':str(target-1),'next_period':str(target+1),'previous_value':prev,'next_value':nxt,'imputed':imp,'actual':actual,'absolute_error':abs(imp-actual)})
  rows.sort(key=lambda r:(-r['absolute_error'],r['segment'])); out={'status':'ok' if rows else 'failed','failure_state':None if rows else 'no_valid_groups','selected_rows':rows[:a.top_k],'all_rows':rows,'failures':failures}; code=0 if rows else 1
 text=json.dumps(out,ensure_ascii=False,indent=2); a.output.parent.mkdir(parents=True,exist_ok=True) if a.output else None; a.output.write_text(text+'\n',encoding='utf-8') if a.output else print(text); return code
if __name__=='__main__': raise SystemExit(main())
