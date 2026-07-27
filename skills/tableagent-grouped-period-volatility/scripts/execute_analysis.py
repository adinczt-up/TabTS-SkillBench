#!/usr/bin/env python3
"""Compute sample volatility across validated group-period values."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd

def read_table(path):
 s=path.suffix.lower()
 if s in {'.parquet','.pq'}:return pd.read_parquet(path)
 if s=='.csv':return pd.read_csv(path,low_memory=False)
 if s=='.tsv':return pd.read_csv(path,sep='\t',low_memory=False)
 if s in {'.xlsx','.xls'}:return pd.read_excel(path)
 raise ValueError('unsupported_input_format')
def compute(path,p):
 df=read_table(path);g=p['group_column'];period=p['period_column'];v=p['value_column'];missing=[c for c in (g,period,v) if c not in df]
 if missing:raise ValueError('missing_columns:'+','.join(missing))
 w=df[[g,period,v]].copy();w[v]=pd.to_numeric(w[v],errors='coerce');w=w.dropna(subset=[g,period,v]);
 if w.duplicated([g,period]).any():raise ValueError('duplicate_group_period')
 rows=[]
 for group,part in w.groupby(g,dropna=False,sort=True):
  if len(part)<int(p['minimum_periods']):continue
  rows.append({'segment':group,'volatility':float(part[v].std(ddof=1)),'month_n':int(len(part))})
 if not rows:raise ValueError('insufficient_periods')
 extreme=max(r['volatility'] for r in rows);selected=[r for r in rows if r['volatility']==extreme]
 return {'operation':'grouped_period_volatility','status':'ok','input':str(path),'parameters':p,'result_rows':rows,'selected_rows':selected,'checks':{'unique_group_period':True,'sample_ddof_is_one':int(p['ddof'])==1,'minimum_periods_applied':all(r['month_n']>=int(p['minimum_periods']) for r in rows),'ties_complete':all((r in selected)==(r['volatility']==extreme) for r in rows)}}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--group-column',required=True);ap.add_argument('--period-column',required=True);ap.add_argument('--value-column',required=True);ap.add_argument('--minimum-periods',type=int,default=4);ap.add_argument('--ddof',type=int,choices=[1],default=1);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();p={k:getattr(a,k) for k in ('group_column','period_column','value_column','minimum_periods','ddof')};r=compute(a.input,p);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())