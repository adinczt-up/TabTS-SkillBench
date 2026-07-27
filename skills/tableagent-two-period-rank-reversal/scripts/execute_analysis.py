#!/usr/bin/env python3
"""Compute tie-aware dense ranks and rank movement across two windows."""
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
 def summary(part,prefix):return part.groupby(g,dropna=False)[v].agg(['mean','count']).rename(columns={'mean':prefix+'_mean','count':prefix+'_n'})
 a=summary(w[w[t]<split],'early').join(summary(w[w[t]>=split],'late'),how='inner');a=a[(a.early_n>=int(p['minimum_n']))&(a.late_n>=int(p['minimum_n']))]
 if a.empty:raise ValueError('insufficient_period_coverage')
 ascending=p['rank_direction']=='ascending';a['early_rank']=a.early_mean.rank(method='dense',ascending=ascending).astype(int);a['late_rank']=a.late_mean.rank(method='dense',ascending=ascending).astype(int);a['rank_gain']=a.early_rank-a.late_rank;best=int(a.rank_gain.max());rows=[]
 for group,row in a.sort_index().iterrows():rows.append({'segment':group,'early_rank':int(row.early_rank),'late_rank':int(row.late_rank),'rank_gain':int(row.rank_gain),'early_mean':float(row.early_mean),'late_mean':float(row.late_mean),'early_n':int(row.early_n),'late_n':int(row.late_n)})
 selected=[r for r in rows if r['rank_gain']==best]
 return {'operation':'two_period_rank_reversal','status':'ok','input':str(path),'parameters':p,'result_rows':rows,'selected_rows':selected,'checks':{'half_open_windows':start<split<end,'dense_ranks_positive':all(r['early_rank']>=1 and r['late_rank']>=1 for r in rows),'rank_gain_direction_early_minus_late':all(r['rank_gain']==r['early_rank']-r['late_rank'] for r in rows),'ties_complete':all((r in selected)==(r['rank_gain']==best) for r in rows)}}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--group-column',required=True);ap.add_argument('--time-column',required=True);ap.add_argument('--value-column',required=True);ap.add_argument('--window-start',required=True);ap.add_argument('--split',required=True);ap.add_argument('--window-end-exclusive',required=True);ap.add_argument('--minimum-n',type=int,required=True);ap.add_argument('--rank-direction',choices=['descending','ascending'],default='descending');ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();p={k:getattr(a,k) for k in ('group_column','time_column','value_column','window_start','split','window_end_exclusive','minimum_n','rank_direction')};r=compute(a.input,p);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())