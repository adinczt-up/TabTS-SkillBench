#!/usr/bin/env python3
"""Fit deterministic grouped OLS slopes on unique period values."""
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
def month_offset(series,origin): return (series.dt.year-origin.year)*12+(series.dt.month-origin.month)
def compute(path,p):
 df=read_table(path);g=p['group_column'];t=p['period_column'];v=p['value_column'];missing=[c for c in (g,t,v) if c not in df]
 if missing:raise ValueError('missing_columns:'+','.join(missing))
 w=df[[g,t,v]].copy();w[t]=pd.to_datetime(w[t],errors='coerce');w[v]=pd.to_numeric(w[v],errors='coerce');w=w.dropna(subset=[g,t,v]);
 if w.duplicated([g,t]).any():raise ValueError('duplicate_group_period')
 origin=pd.Timestamp(p['origin_period']);rows=[]
 for group,part in w.groupby(g,dropna=False,sort=True):
  if len(part)<int(p['minimum_periods']):continue
  x=month_offset(part[t],origin).to_numpy(dtype=float);y=part[v].to_numpy(dtype=float)
  if len(np.unique(x))<2:continue
  slope=float(np.sum((x-x.mean())*(y-y.mean()))/np.sum((x-x.mean())**2));intercept=float(y.mean()-slope*x.mean());rss=float(np.sum((y-(intercept+slope*x))**2));rows.append({'segment':group,'slope':slope,'intercept':intercept,'month_n':int(len(part)),'residual_ss':rss})
 if not rows:raise ValueError('insufficient_periods')
 key=(lambda r:abs(r['slope'])) if p['selection']=='max_abs' else (lambda r:r['slope']);ext=max(key(r) for r in rows);selected=[r for r in rows if key(r)==ext]
 return {'operation':'grouped_linear_trend','status':'ok','input':str(path),'parameters':p,'result_rows':rows,'selected_rows':selected,'checks':{'unique_group_period':True,'positive_time_variance':True,'finite_coefficients':all(np.isfinite(r['slope']) for r in rows),'ties_complete':all((r in selected)==(key(r)==ext) for r in rows)}}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--group-column',required=True);ap.add_argument('--period-column',required=True);ap.add_argument('--value-column',required=True);ap.add_argument('--origin-period',required=True);ap.add_argument('--minimum-periods',type=int,default=4);ap.add_argument('--selection',choices=['max_abs','max_signed'],default='max_abs');ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();p={k:getattr(a,k) for k in ('group_column','period_column','value_column','origin_period','minimum_periods','selection')};r=compute(a.input,p);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())