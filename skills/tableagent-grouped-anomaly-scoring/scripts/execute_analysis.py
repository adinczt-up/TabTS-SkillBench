#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

def read_table(path: Path, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet": return pd.read_parquet(path)
    if path.suffix.lower() in {".xlsx", ".xls"}: return pd.read_excel(path, sheet_name=sheet or 0)
    return pd.read_csv(path)

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--sheet')
    p.add_argument('--group',required=True); p.add_argument('--time',required=True); p.add_argument('--value',required=True)
    p.add_argument('--method',required=True,choices=['iqr','mad']); p.add_argument('--top-k',type=int,default=3)
    p.add_argument('--min-points',type=int,default=4); p.add_argument('--quantile-interpolation',default='linear',choices=['linear','lower','higher','midpoint','nearest'])
    a=p.parse_args(); d=read_table(a.file,a.sheet)[[a.group,a.time,a.value]].copy(); d[a.value]=pd.to_numeric(d[a.value],errors='coerce'); d=d.dropna()
    if d.duplicated([a.group,a.time]).any(): print(json.dumps({'status':'failed','failure_state':'duplicate_group_period'})); return 1
    scored=[]; stats=[]; unresolved=[]
    for group,g in d.groupby(a.group,dropna=False,sort=True):
        x=g[a.value].to_numpy(float)
        if len(x)<a.min_points: unresolved.append({'group':str(group),'reason':'insufficient_group_points','n':len(x)}); continue
        if a.method=='iqr':
            q1=float(np.quantile(x,.25,method=a.quantile_interpolation)); q3=float(np.quantile(x,.75,method=a.quantile_interpolation)); scale=q3-q1; center=None
            if scale<=0: unresolved.append({'group':str(group),'reason':'zero_scale','n':len(x)}); continue
            scores=np.where(x<q1,(q1-x)/scale,np.where(x>q3,(x-q3)/scale,0.0)); stat={'q1':q1,'q3':q3,'iqr':scale}
        else:
            center=float(np.median(x)); mad=float(np.median(np.abs(x-center))); scale=1.4826*mad
            if scale<=0: unresolved.append({'group':str(group),'reason':'zero_scale','n':len(x)}); continue
            scores=np.abs(x-center)/scale; stat={'center':center,'mad':mad,'scale':scale}
        stats.append({'group':str(group),'n':len(x),**stat})
        for (_,row),score in zip(g.iterrows(),scores):
            scored.append({'group':str(group),'period':str(row[a.time]),'value':float(row[a.value]),'anomaly_score':float(score),**stat})
    scored.sort(key=lambda r:(-r['anomaly_score'],r['group'],r['period']))
    selected=scored[:max(a.top_k,0)]
    valid=all(math.isfinite(r['anomaly_score']) for r in scored) and selected==sorted(selected,key=lambda r:(-r['anomaly_score'],r['group'],r['period']))
    out={'status':'ok' if valid else 'failed','failure_state':None if valid else 'validation_failed','parameters':{'method':a.method,'top_k':a.top_k,'min_points':a.min_points,'quantile_interpolation':a.quantile_interpolation},'group_statistics':stats,'scored_rows':scored,'selected_rows':selected,'unresolved_groups':unresolved,'validation':{'valid':valid,'selected_count':len(selected)}}
    print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if valid else 1
if __name__=='__main__': raise SystemExit(main())
