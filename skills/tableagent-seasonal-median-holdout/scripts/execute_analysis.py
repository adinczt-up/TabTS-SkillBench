#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd
def read(p): return pd.read_parquet(p) if p.suffix.lower() in {'.parquet','.pq'} else pd.read_excel(p) if p.suffix.lower() in {'.xlsx','.xls'} else pd.read_csv(p,low_memory=False)
def main():
 p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--group',required=True); p.add_argument('--time',required=True); p.add_argument('--value',required=True); p.add_argument('--frequency',choices=['month','quarter'],required=True); p.add_argument('--target',required=True); p.add_argument('--min-donors',type=int,default=2); p.add_argument('--top-k',type=int,default=3); p.add_argument('--output',type=Path); a=p.parse_args(); d=read(a.file)[[a.group,a.time,a.value]].copy(); d[a.time]=pd.to_datetime(d[a.time],errors='coerce'); d[a.value]=pd.to_numeric(d[a.value],errors='coerce'); d=d.dropna(); freq={'month':'M','quarter':'Q'}[a.frequency]; d['period']=d[a.time].dt.to_period(freq)
 if d.duplicated([a.group,'period']).any(): out={'status':'failed','failure_state':'duplicate_group_period'}; code=1
 else:
  target=pd.Period(a.target,freq=freq); rows=[]; failures=[]
  for group,g in d.groupby(a.group,dropna=False,sort=True):
   target_rows=g[g.period==target]
   if target_rows.empty: failures.append({'segment':str(group),'reason':'target_not_observed'}); continue
   same_season=(g.period.map(lambda x:x.month if a.frequency=='month' else x.quarter)==(target.month if a.frequency=='month' else target.quarter)); donors=g[same_season & (g.period!=target) & (g.period.map(lambda x:x.year)!=target.year)][a.value]
   if len(donors)<a.min_donors: failures.append({'segment':str(group),'reason':'insufficient_donors','donor_n':len(donors)}); continue
   imputed=float(donors.median()); actual=float(target_rows.iloc[0][a.value]); rows.append({'segment':str(group),'target_period':str(target),'imputed':imputed,'actual':actual,'absolute_error':abs(imputed-actual),'donor_n':len(donors)})
  rows.sort(key=lambda r:(-r['absolute_error'],r['segment'])); out={'status':'ok' if rows else 'failed','failure_state':None if rows else 'no_valid_groups','selected_rows':rows[:a.top_k],'all_rows':rows,'failures':failures}; code=0 if rows else 1
 text=json.dumps(out,ensure_ascii=False,indent=2); a.output.parent.mkdir(parents=True,exist_ok=True) if a.output else None; a.output.write_text(text+'\n',encoding='utf-8') if a.output else print(text); return code
if __name__=='__main__': raise SystemExit(main())
