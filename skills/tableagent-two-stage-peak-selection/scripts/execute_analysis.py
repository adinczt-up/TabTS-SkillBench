#!/usr/bin/env python3
"""Perform tie-complete within-group then global period selection."""
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
 df=read_table(path);g=p['group_column'];period=p['period_column'];metric=p['metric_column'];needed=[g,period,metric]+([p['count_column']] if p.get('count_column') else []);missing=[c for c in needed if c not in df]
 if missing:raise ValueError('missing_columns:'+','.join(missing))
 w=df[needed].copy();w[metric]=pd.to_numeric(w[metric],errors='coerce');w=w.dropna(subset=[g,period,metric]);
 if w.duplicated([g,period]).any():raise ValueError('duplicate_group_period')
 stage=[]
 for _,part in w.groupby(g,dropna=False,sort=True):
  extreme=(part[metric].max() if p['within_direction']=='max' else part[metric].min());stage.append(part[part[metric]==extreme])
 one=pd.concat(stage,ignore_index=True);global_extreme=(one[metric].max() if p['global_direction']=='max' else one[metric].min());sel=one[one[metric]==global_extreme]
 def records(frame):return json.loads(frame.to_json(orient='records',date_format='iso'))
 all_rows=records(w);stage_rows=records(one);selected=records(sel)
 return {'operation':'two_stage_peak_selection','status':'ok','input':str(path),'parameters':p,'result_rows':stage_rows,'selected_rows':selected,'checks':{'unique_group_period':True,'every_group_represented':one[g].nunique(dropna=False)==w[g].nunique(dropna=False),'within_ties_complete':True,'global_ties_complete':True},'eligible_rows':all_rows}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--group-column',required=True);ap.add_argument('--period-column',required=True);ap.add_argument('--metric-column',required=True);ap.add_argument('--count-column');ap.add_argument('--within-direction',choices=['max','min'],default='max');ap.add_argument('--global-direction',choices=['max','min'],default='max');ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();p={k:getattr(a,k) for k in ('group_column','period_column','metric_column','count_column','within_direction','global_direction')};r=compute(a.input,p);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())