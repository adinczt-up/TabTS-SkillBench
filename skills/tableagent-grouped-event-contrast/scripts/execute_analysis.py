#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

def read(p): return pd.read_parquet(p) if p.suffix.lower() in {'.parquet','.pq'} else pd.read_excel(p) if p.suffix.lower() in {'.xlsx','.xls'} else pd.read_csv(p,low_memory=False)
def main():
 p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--group',required=True); p.add_argument('--event',required=True); p.add_argument('--value',required=True); p.add_argument('--min-event',type=int,required=True); p.add_argument('--min-nonevent',type=int,required=True); p.add_argument('--top-k',type=int,default=0); p.add_argument('--output',type=Path); a=p.parse_args()
 d=read(a.file)[[a.group,a.event,a.value]].copy(); d[a.event]=pd.to_numeric(d[a.event],errors='coerce'); d[a.value]=pd.to_numeric(d[a.value],errors='coerce'); d=d.dropna(); rows=[]; unresolved=[]
 for group,g in d.groupby(a.group,dropna=False,sort=True):
  event=g[g[a.event]!=0][a.value]; non=g[g[a.event]==0][a.value]
  if len(event)<a.min_event or len(non)<a.min_nonevent: unresolved.append({'segment':str(group),'reason':'insufficient_event_rows','event_n':len(event),'nonevent_n':len(non)}); continue
  em=float(event.mean()); nm=float(non.mean()); rows.append({'segment':str(group),'event_mean':em,'nonevent_mean':nm,'event_effect':em-nm,'event_n':len(event),'nonevent_n':len(non)})
 rows.sort(key=lambda r:(-abs(r['event_effect']),r['segment'])); selected=rows[:a.top_k] if a.top_k>0 else rows; out={'status':'ok' if rows else 'failed','failure_state':None if rows else 'no_valid_groups','selected_rows':selected,'all_rows':rows,'unresolved':unresolved}; text=json.dumps(out,ensure_ascii=False,indent=2); a.output.parent.mkdir(parents=True,exist_ok=True) if a.output else None; a.output.write_text(text+'\n',encoding='utf-8') if a.output else print(text); return 0 if rows else 1
if __name__=='__main__': raise SystemExit(main())
