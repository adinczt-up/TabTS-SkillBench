#!/usr/bin/env python3
"""Compute auditable service durations with explicit year-boundary semantics."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

def read(path,sheet): return pd.read_excel(path,sheet_name=sheet or 0) if path.suffix.lower() in {'.xlsx','.xls'} else pd.read_csv(path)
def endpoint(v):
 if pd.isna(v): return pd.NaT,'missing'
 s=str(v).strip(); s=s[:-2] if s.endswith('.0') else s
 if s.isdigit() and len(s)==4: return pd.Timestamp(int(s),1,1),'year'
 return pd.to_datetime(v,errors='coerce'),'date'
def main():
 p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--sheet'); p.add_argument('--start-column',required=True); p.add_argument('--end-column',required=True); p.add_argument('--entity-column'); p.add_argument('--operation',choices=['sum','mean','per_row'],default='sum'); p.add_argument('--method',choices=['auto','elapsed_years','completed_years','year_difference','inclusive_years'],default='auto'); p.add_argument('--ongoing-policy',choices=['error','exclude','as_of'],default='error'); p.add_argument('--as-of')
 a=p.parse_args(); d=read(a.file,a.sheet); parsed=[]; unresolved=[]
 for i,r in d.iterrows():
  start,sg=endpoint(r[a.start_column]); end,eg=endpoint(r[a.end_column]); raw_end=str(r[a.end_column]).strip().lower()
  if pd.isna(end) and raw_end in {'current','present','incumbent','ongoing'}:
   if a.ongoing_policy=='as_of' and a.as_of: end=pd.Timestamp(a.as_of); eg='date'
   elif a.ongoing_policy=='exclude': unresolved.append({'source_row':int(i),'reason':'ongoing_excluded'}); continue
   else: print(json.dumps({'failure_state':'ongoing_end_unresolved','source_row':int(i)})); return 1
  if pd.isna(start) or pd.isna(end) or end<start: print(json.dumps({'failure_state':'invalid_interval','source_row':int(i)})); return 1
  parsed.append((i,r,start,end,sg,eg))
 method=a.method
 if method=='auto':
  year_only=all(sg==eg=='year' for _,_,_,_,sg,eg in parsed)
  has_same_year=any(start.year==end.year for _,_,start,end,_,_ in parsed)
  adjacent=sum(parsed[i][3].year==parsed[i+1][2].year for i in range(len(parsed)-1))
  adjacency_rate=adjacent/max(len(parsed)-1,1)
  method='year_difference' if year_only and adjacency_rate>=0.95 else 'inclusive_years' if year_only and has_same_year else 'year_difference' if year_only else 'elapsed_years'
 rows=[]
 for i,r,start,end,sg,eg in parsed:
  if method=='elapsed_years': duration=(end-start).total_seconds()/86400/365.2425
  elif method=='completed_years': duration=end.year-start.year-((end.month,end.day)<(start.month,start.day))
  elif method=='inclusive_years': duration=end.year-start.year+1
  else: duration=end.year-start.year
  rows.append({'source_row':int(i),'entity':str(r[a.entity_column]) if a.entity_column else None,'start':start.isoformat(),'end':end.isoformat(),'granularity':'year' if sg==eg=='year' else 'date','duration':float(duration)})
 vals=[r['duration'] for r in rows]; result=vals if a.operation=='per_row' else sum(vals) if a.operation=='sum' else sum(vals)/len(vals)
 out={'status':'ok','parameters':{'operation':a.operation,'requested_method':a.method,'resolved_method':method,'boundary':'inclusive' if method=='inclusive_years' else 'end_minus_start','ongoing_policy':a.ongoing_policy,'output_unit':'years'},'rows':rows,'excluded_rows':unresolved,'row_count':len(rows),'result':result,'failure_state':None}
 print(json.dumps(out,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())