#!/usr/bin/env python3
"""Compute grouped means or binary rates in two half-open windows."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

def read_table(path):
 s=path.suffix.lower()
 if s in {'.parquet','.pq'}:return pd.read_parquet(path)
 if s=='.csv':return pd.read_csv(path,low_memory=False)
 if s=='.tsv':return pd.read_csv(path,sep='\t',low_memory=False)
 if s in {'.xlsx','.xls'}:return pd.read_excel(path)
 raise ValueError('unsupported_input_format')
def compute(path,p):
 df=read_table(path);g=p['group_column'];t=p['time_column'];v=p['value_column'];missing=[c for c in (g,t,v) if c not in df]
 if missing:raise ValueError('missing_columns:'+','.join(missing))
 w=df[[g,t,v]].copy();w[t]=pd.to_datetime(w[t],errors='coerce');w[v]=pd.to_numeric(w[v],errors='coerce');w=w.dropna(subset=[g,t,v]);start=pd.Timestamp(p['window_start']);split=pd.Timestamp(p['split']);end=pd.Timestamp(p['window_end_exclusive']);w=w[(w[t]>=start)&(w[t]<end)]
 if p['mode']=='rate' and not w[v].isin([0,1]).all():raise ValueError('rate_value_not_binary')
 early=w[w[t]<split];late=w[w[t]>=split];eg=early.groupby(g,dropna=False)[v].agg(['mean','count']).rename(columns={'mean':'early_value','count':'early_n'});lg=late.groupby(g,dropna=False)[v].agg(['mean','count']).rename(columns={'mean':'late_value','count':'late_n'});joined=eg.join(lg,how='inner');joined=joined[(joined.early_n>=int(p['minimum_n']))&(joined.late_n>=int(p['minimum_n']))]
 if joined.empty:raise ValueError('insufficient_period_coverage')
 joined['change']=joined.late_value-joined.early_value;joined['absolute_change']=joined['change'].abs();rows=[]
 for group,row in joined.sort_index().iterrows():rows.append({'segment':group,'early_value':float(row.early_value),'late_value':float(row.late_value),'change':float(row.change),'absolute_change':float(row.absolute_change),'early_n':int(row.early_n),'late_n':int(row.late_n)})
 key={'max_signed':lambda r:r['change'],'max_abs':lambda r:r['absolute_change'],'min_abs':lambda r:-r['absolute_change']}[p['selection']];ext=max(key(r) for r in rows);selected=[r for r in rows if key(r)==ext]
 return {'operation':'grouped_two_period_aggregate','status':'ok','input':str(path),'parameters':p,'result_rows':rows,'selected_rows':selected,'checks':{'half_open_windows':start<split<end,'minimum_counts_applied':all(r['early_n']>=int(p['minimum_n']) and r['late_n']>=int(p['minimum_n']) for r in rows),'change_direction_late_minus_early':all(abs(r['change']-(r['late_value']-r['early_value']))<1e-12 for r in rows),'ties_complete':all((r in selected)==(key(r)==ext) for r in rows)}}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--group-column',required=True);ap.add_argument('--time-column',required=True);ap.add_argument('--value-column',required=True);ap.add_argument('--mode',choices=['mean','rate'],required=True);ap.add_argument('--window-start',required=True);ap.add_argument('--split',required=True);ap.add_argument('--window-end-exclusive',required=True);ap.add_argument('--minimum-n',type=int,required=True);ap.add_argument('--selection',choices=['max_signed','max_abs','min_abs'],required=True);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();p={k:getattr(a,k) for k in ('group_column','time_column','value_column','mode','window_start','split','window_end_exclusive','minimum_n','selection')};r=compute(a.input,p);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())