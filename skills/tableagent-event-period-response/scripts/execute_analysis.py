#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

def read(path,sheet):
    if path.suffix.lower()=='.parquet': return pd.read_parquet(path)
    if path.suffix.lower() in {'.xlsx','.xls'}: return pd.read_excel(path,sheet_name=sheet or 0)
    return pd.read_csv(path)
def main():
    p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--sheet'); p.add_argument('--group',required=True); p.add_argument('--time',required=True); p.add_argument('--value',required=True); p.add_argument('--event',required=True); p.add_argument('--event-op',choices=['gt','ge','eq'],required=True); p.add_argument('--event-threshold',type=float,required=True); p.add_argument('--reference-offset',type=int,default=-1); p.add_argument('--frequency',choices=['day','week','month','quarter','year'],default='month'); p.add_argument('--top-k',type=int,default=3)
    a=p.parse_args(); d=read(a.file,a.sheet)[[a.group,a.time,a.value,a.event]].copy(); d[a.time]=pd.to_datetime(d[a.time],errors='coerce'); d[a.value]=pd.to_numeric(d[a.value],errors='coerce'); d[a.event]=pd.to_numeric(d[a.event],errors='coerce'); d=d.dropna()
    if d.duplicated([a.group,a.time]).any(): print(json.dumps({'status':'failed','failure_state':'duplicate_group_period'})); return 1
    freq={'day':'D','week':'W','month':'M','quarter':'Q','year':'Y'}[a.frequency]; d['period']=d[a.time].dt.to_period(freq)
    pred={'gt':lambda x:x>a.event_threshold,'ge':lambda x:x>=a.event_threshold,'eq':lambda x:x==a.event_threshold}[a.event_op]
    lookup={(str(r[0]),r[1]):float(r[2]) for r in d[[a.group,'period',a.value]].itertuples(index=False,name=None)}; rows=[]
    for group,period,value,event in d[[a.group,'period',a.value,a.event]].itertuples(index=False,name=None):
        if not pred(float(event)): continue
        reference_period=period+a.reference_offset; reference=lookup.get((str(group),reference_period))
        if reference is None: continue
        rows.append({'group':str(group),'event_period':str(period),'event_rate':float(event),'reference_period':str(reference_period),'reference_value':float(reference),'event_value':float(value),'response':float(value)-float(reference)})
    rows.sort(key=lambda r:(-abs(r['response']),r['group'],r['event_period'])); selected=rows[:max(a.top_k,0)]
    valid=all(r['response']==r['event_value']-r['reference_value'] for r in rows)
    print(json.dumps({'status':'ok' if valid else 'failed','failure_state':None if valid else 'validation_failed','parameters':vars(a)|{'file':str(a.file)},'eligible_pairs':rows,'selected_rows':selected,'validation':{'valid':valid}},ensure_ascii=False,indent=2)); return 0 if valid else 1
if __name__=='__main__': raise SystemExit(main())
