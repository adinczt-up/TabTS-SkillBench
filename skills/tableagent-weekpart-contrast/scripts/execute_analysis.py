#!/usr/bin/env python3
"""Compare grouped Monday-Friday and Saturday-Sunday means."""
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
 w=df[[g,t,v]].copy();w[t]=pd.to_datetime(w[t],errors='coerce');w[v]=pd.to_numeric(w[v],errors='coerce');w=w.dropna(subset=[g,t,v]);start=pd.Timestamp(p['window_start']);end=pd.Timestamp(p['window_end_exclusive']);w=w[(w[t]>=start)&(w[t]<end)];w['is_weekday']=w[t].dt.dayofweek<5
 wd=w[w.is_weekday].groupby(g,dropna=False)[v].agg(['mean','count']).rename(columns={'mean':'weekday_mean','count':'weekday_n'});we=w[~w.is_weekday].groupby(g,dropna=False)[v].agg(['mean','count']).rename(columns={'mean':'weekend_mean','count':'weekend_n'});a=wd.join(we,how='inner');a=a[(a.weekday_n>=int(p['minimum_n']))&(a.weekend_n>=int(p['minimum_n']))]
 if a.empty:raise ValueError('insufficient_weekpart_coverage')
 a['contrast']=a.weekday_mean-a.weekend_mean;rows=[]
 for group,row in a.sort_index().iterrows():rows.append({'segment':group,'weekday_mean':float(row.weekday_mean),'weekend_mean':float(row.weekend_mean),'contrast':float(row.contrast),'weekday_n':int(row.weekday_n),'weekend_n':int(row.weekend_n)})
 extreme=max(abs(r['contrast']) for r in rows);selected=[r for r in rows if abs(r['contrast'])==extreme]
 return {'operation':'weekpart_contrast','status':'ok','input':str(path),'parameters':p,'result_rows':rows,'selected_rows':selected,'checks':{'half_open_window':start<end,'weekday_is_monday_through_friday':True,'minimum_counts_applied':all(r['weekday_n']>=int(p['minimum_n']) and r['weekend_n']>=int(p['minimum_n']) for r in rows),'contrast_direction_weekday_minus_weekend':all(abs(r['contrast']-(r['weekday_mean']-r['weekend_mean']))<1e-12 for r in rows),'ties_complete':all((r in selected)==(abs(r['contrast'])==extreme) for r in rows)}}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--group-column',required=True);ap.add_argument('--time-column',required=True);ap.add_argument('--value-column',required=True);ap.add_argument('--window-start',required=True);ap.add_argument('--window-end-exclusive',required=True);ap.add_argument('--minimum-n',type=int,required=True);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();p={k:getattr(a,k) for k in ('group_column','time_column','value_column','window_start','window_end_exclusive','minimum_n')};r=compute(a.input,p);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())