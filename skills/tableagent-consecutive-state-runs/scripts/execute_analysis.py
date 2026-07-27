#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd
import numpy as np

def read(path,sheet):
    if path.suffix.lower()=='.parquet': return pd.read_parquet(path)
    if path.suffix.lower() in {'.xlsx','.xls'}: return pd.read_excel(path,sheet_name=sheet or 0)
    return pd.read_csv(path)
def main():
    p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--sheet'); p.add_argument('--group',required=True); p.add_argument('--time',required=True); p.add_argument('--value',required=True); p.add_argument('--frequency',choices=['day','week','month','quarter','year'],required=True); p.add_argument('--threshold',choices=['median','mean'],required=True); p.add_argument('--comparison',choices=['gt','ge','lt','le'],required=True); p.add_argument('--top-k',type=int,default=3)
    a=p.parse_args(); d=read(a.file,a.sheet)[[a.group,a.time,a.value]].copy(); d[a.time]=pd.to_datetime(d[a.time],errors='coerce'); d[a.value]=pd.to_numeric(d[a.value],errors='coerce'); d=d.dropna()
    if d.duplicated([a.group,a.time]).any(): print(json.dumps({'status':'failed','failure_state':'duplicate_group_period'})); return 1
    freq={'day':'D','week':'W','month':'M','quarter':'Q','year':'Y'}[a.frequency]; d['period']=d[a.time].dt.to_period(freq)
    cmp={'gt':lambda x,t:x>t,'ge':lambda x,t:x>=t,'lt':lambda x,t:x<t,'le':lambda x,t:x<=t}[a.comparison]
    all_runs=[]; best=[]
    for group,g in d.sort_values('period').groupby(a.group,dropna=False,sort=True):
        threshold=float(g[a.value].median() if a.threshold=='median' else g[a.value].mean()); g=g.copy(); g['state']=cmp(g[a.value],threshold)
        runs=[]; current=[]
        for period,value,state in g[['period',a.value,'state']].itertuples(index=False,name=None):
            value=float(value); state=bool(state)
            if not state: current=[]; continue
            if current and period.ordinal!=current[-1][0].ordinal+1: current=[]
            current.append((period,value))
            record={'group':str(group),'start_period':str(current[0][0]),'end_period':str(current[-1][0]),'duration_periods':len(current),'mean_value':float(np.mean([x[1] for x in current])),'threshold':threshold}
            if runs and runs[-1]['start_period']==record['start_period']: runs[-1]=record
            else: runs.append(record)
        all_runs.extend(runs)
        if runs: best.append(sorted(runs,key=lambda r:(-r['duration_periods'],r['start_period']))[0])
    best.sort(key=lambda r:(-r['duration_periods'],r['group'],r['start_period'])); selected=best[:max(a.top_k,0)]
    valid=all(r['duration_periods']>=1 and r['start_period']<=r['end_period'] for r in all_runs)
    print(json.dumps({'status':'ok' if valid else 'failed','failure_state':None if valid else 'validation_failed','parameters':vars(a)|{'file':str(a.file)},'all_runs':all_runs,'selected_rows':selected,'validation':{'valid':valid}},ensure_ascii=False,indent=2)); return 0 if valid else 1
if __name__=='__main__': raise SystemExit(main())
