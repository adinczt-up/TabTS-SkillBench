#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

def read(p): return pd.read_parquet(p) if p.suffix.lower() in {'.parquet','.pq'} else pd.read_excel(p) if p.suffix.lower() in {'.xlsx','.xls'} else pd.read_csv(p,low_memory=False)
def main():
 p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--group',required=True); p.add_argument('--time',required=True); p.add_argument('--value',required=True); p.add_argument('--frequency',choices=['day','week','month','quarter','year'],required=True); p.add_argument('--window',type=int,required=True); p.add_argument('--threshold-cutoff',required=True); p.add_argument('--quantile',type=float,required=True); p.add_argument('--top-k',type=int,default=3); p.add_argument('--output',type=Path); a=p.parse_args()
 d=read(a.file)[[a.group,a.time,a.value]].copy(); d[a.time]=pd.to_datetime(d[a.time],errors='coerce'); d[a.value]=pd.to_numeric(d[a.value],errors='coerce'); d=d.dropna(); freq={'day':'D','week':'W','month':'M','quarter':'Q','year':'Y'}[a.frequency]; d['period']=d[a.time].dt.to_period(freq)
 if d.duplicated([a.group,'period']).any(): out={'status':'failed','failure_state':'duplicate_group_period'}; code=1
 else:
  cutoff=pd.Period(a.threshold_cutoff,freq=freq); rows=[]; unresolved=[]
  for group,g in d.groupby(a.group,dropna=False,sort=True):
   g=g.sort_values('period'); ref=g[g.period<cutoff][a.value]
   if ref.empty: unresolved.append({'segment':str(group),'reason':'insufficient_reference'}); continue
   threshold=float(ref.quantile(a.quantile)); by_period=dict(zip(g.period,g[a.value]))
   for end in sorted(by_period):
    periods=[end-i for i in range(a.window-1,-1,-1)]
    if not all(period in by_period for period in periods): continue
    rolling=float(sum(float(by_period[x]) for x in periods)/a.window); excess=rolling-threshold
    if excess>0: rows.append({'segment':str(group),'window_end':str(end),'rolling_mean':rolling,'threshold':threshold,'excess':excess})
  rows.sort(key=lambda r:(-r['excess'],r['segment'],r['window_end'])); out={'status':'ok' if rows else 'failed','failure_state':None if rows else 'no_positive_exceedance','selected_rows':rows[:a.top_k],'all_exceedances':rows,'unresolved':unresolved}; code=0 if rows else 1
 text=json.dumps(out,ensure_ascii=False,indent=2); a.output.parent.mkdir(parents=True,exist_ok=True) if a.output else None; a.output.write_text(text+'\n',encoding='utf-8') if a.output else print(text); return code
if __name__=='__main__': raise SystemExit(main())
