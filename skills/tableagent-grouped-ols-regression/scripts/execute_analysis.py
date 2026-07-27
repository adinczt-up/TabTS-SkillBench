#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd

def read(path,sheet):
    if path.suffix.lower()=='.parquet': return pd.read_parquet(path)
    if path.suffix.lower() in {'.xlsx','.xls'}: return pd.read_excel(path,sheet_name=sheet or 0)
    return pd.read_csv(path)
def main():
    p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--sheet'); p.add_argument('--group',required=True); p.add_argument('--time',required=True); p.add_argument('--predictor',required=True); p.add_argument('--response',required=True); p.add_argument('--calendar-lag',type=int,default=0); p.add_argument('--frequency',choices=['day','week','month','quarter','year'],default='month'); p.add_argument('--top-k',type=int,default=3); p.add_argument('--min-pairs',type=int,default=3)
    a=p.parse_args(); cols=[a.group,a.time,a.predictor,a.response]; d=read(a.file,a.sheet)[cols].copy(); d[a.time]=pd.to_datetime(d[a.time],errors='coerce'); d[a.predictor]=pd.to_numeric(d[a.predictor],errors='coerce'); d[a.response]=pd.to_numeric(d[a.response],errors='coerce'); d=d.dropna()
    if d.duplicated([a.group,a.time]).any(): print(json.dumps({'status':'failed','failure_state':'duplicate_group_period'})); return 1
    freq={'day':'D','week':'W','month':'M','quarter':'Q','year':'Y'}[a.frequency]; d['period']=d[a.time].dt.to_period(freq)
    results=[]; unresolved=[]
    for group,g in d.groupby(a.group,dropna=False,sort=True):
        y=g[['period',a.response]].rename(columns={a.response:'response'}); x=g[['period',a.predictor]].rename(columns={a.predictor:'predictor'}).copy(); x['period']=x['period']+a.calendar_lag
        pairs=y.merge(x,on='period',how='inner').dropna().sort_values('period')
        if len(pairs)<a.min_pairs: unresolved.append({'group':str(group),'reason':'insufficient_pairs','pair_n':len(pairs)}); continue
        xv=pairs.predictor.to_numpy(float); yv=pairs.response.to_numpy(float)
        if np.var(xv)<=1e-15: unresolved.append({'group':str(group),'reason':'constant_predictor','pair_n':len(pairs)}); continue
        slope,intercept=np.polyfit(xv,yv,1); pred=slope*xv+intercept; sse=float(np.sum((yv-pred)**2)); sst=float(np.sum((yv-yv.mean())**2)); r2=1-sse/sst if sst>0 else 1.0
        results.append({'group':str(group),'slope':float(slope),'intercept':float(intercept),'r2':float(r2),'pair_n':len(pairs),'pairs':[{'period':str(r.period),'predictor':float(r.predictor),'response':float(r.response)} for r in pairs.itertuples()]})
    results.sort(key=lambda r:(-abs(r['slope']),r['group'])); selected=results[:max(a.top_k,0)]
    valid=all(r['pair_n']==len(r['pairs']) for r in results)
    print(json.dumps({'status':'ok' if valid else 'failed','failure_state':None if valid else 'validation_failed','parameters':vars(a)|{'file':str(a.file)},'group_results':results,'selected_rows':selected,'unresolved_groups':unresolved,'validation':{'valid':valid}},ensure_ascii=False,indent=2)); return 0 if valid else 1
if __name__=='__main__': raise SystemExit(main())
