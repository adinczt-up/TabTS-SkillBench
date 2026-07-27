#!/usr/bin/env python3
"""Compute exact grouped continuous quantile ranges and tie-complete extrema."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np, pandas as pd

def read_table(path):
 s=path.suffix.lower()
 if s in {'.parquet','.pq'}: return pd.read_parquet(path)
 if s=='.csv': return pd.read_csv(path,low_memory=False)
 if s=='.tsv': return pd.read_csv(path,sep='\t',low_memory=False)
 if s in {'.xlsx','.xls'}: return pd.read_excel(path)
 raise ValueError('unsupported_input_format')
def compute(path, p):
 df=read_table(path); groups=list(p['group_columns']); value=p['value_column']; needed=groups+[value]
 missing=[c for c in needed if c not in df]
 if missing: raise ValueError('missing_columns:'+','.join(missing))
 work=df[needed].copy(); work[value]=pd.to_numeric(work[value],errors='coerce'); invalid=int(work[value].isna().sum());work=work.dropna(subset=[value])
 rows=[]
 key=groups[0] if len(groups)==1 else groups
 for g,part in work.groupby(key,dropna=False,sort=True):
  if len(part)<int(p['minimum_group_n']): continue
  vals=part[value].to_numpy(dtype=float); lo=float(np.quantile(vals,float(p['lower_probability']),method='linear'));hi=float(np.quantile(vals,float(p['upper_probability']),method='linear'))
  keys=(g,) if len(groups)==1 else tuple(g); row={c:(None if pd.isna(v) else v) for c,v in zip(groups,keys)};row.update({'p_lower':lo,'p_upper':hi,'spread':hi-lo,'n':int(len(vals))});rows.append(row)
 if not rows: raise ValueError('insufficient_group_n')
 extreme=max(r['spread'] for r in rows) if p['selection']=='max' else min(r['spread'] for r in rows); selected=[r for r in rows if r['spread']==extreme]
 return {'operation':'quantile_range','status':'ok','input':str(path),'parameters':p,'result_rows':rows,'selected_rows':selected,'checks':{'finite_values_only':True,'quantile_order_valid':all(r['p_lower']<=r['p_upper'] for r in rows),'spread_nonnegative':all(r['spread']>=0 for r in rows),'ties_complete':all((r in selected)==(r['spread']==extreme) for r in rows)},'excluded_non_numeric_n':invalid}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--group-column',action='append',required=True);ap.add_argument('--value-column',required=True);ap.add_argument('--lower-probability',type=float,default=.1);ap.add_argument('--upper-probability',type=float,default=.9);ap.add_argument('--minimum-group-n',type=int,required=True);ap.add_argument('--selection',choices=['max','min'],default='max');ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
 p={'group_columns':a.group_column,'value_column':a.value_column,'lower_probability':a.lower_probability,'upper_probability':a.upper_probability,'minimum_group_n':a.minimum_group_n,'selection':a.selection}; result=compute(a.input,p);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())