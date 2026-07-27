#!/usr/bin/env python3
"""Create reproducible event episodes from robust adjacent-change candidates."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd

def read(path,sheet): return pd.read_excel(path,sheet_name=sheet or 0) if path.suffix.lower() in {'.xlsx','.xls'} else pd.read_csv(path)
def main():
 p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--sheet'); p.add_argument('--time-column',required=True); p.add_argument('--value-column',required=True); p.add_argument('--window-start'); p.add_argument('--window-end'); p.add_argument('--direction',choices=['up','down','both'],default='both'); p.add_argument('--threshold-z',type=float,default=6.0); p.add_argument('--adjacency-steps',type=int,default=1); p.add_argument('--recovery-window',type=int,default=3); p.add_argument('--baseline-window',type=int,default=5); p.add_argument('--min-magnitude',type=float,default=0.0)
 a=p.parse_args(); d=read(a.file,a.sheet); t=pd.to_datetime(d[a.time_column],errors='coerce'); x=pd.to_numeric(d[a.value_column],errors='coerce'); m=t.notna()&x.notna(); d=pd.DataFrame({'time':t[m],'value':x[m]}).sort_values('time').reset_index(drop=True)
 if a.window_start: d=d[d.time>=pd.Timestamp(a.window_start)]
 if a.window_end: d=d[d.time<=pd.Timestamp(a.window_end)]
 d=d.reset_index(drop=True); values=d.value.to_numpy(float); delta=np.diff(values)
 if len(delta)<16: print(json.dumps({'failure_state':'too_few_points'})); return 1
 center=float(np.median(delta)); mad=float(np.median(np.abs(delta-center))); scale=1.4826*mad
 if scale<=1e-12:
  nz=np.abs(delta-center); scale=float(np.quantile(nz[nz>0],.5)) if np.any(nz>0) else 0.0
 if scale<=1e-12: print(json.dumps({'failure_state':'threshold_unstable'})); return 1
 score=(delta-center)/scale; mask=np.abs(score)>=a.threshold_z
 if a.direction=='down': mask &= delta<0
 elif a.direction=='up': mask &= delta>0
 mask &= np.abs(delta)>=a.min_magnitude
 candidates=np.where(mask)[0]+1
 groups=[]
 for idx in candidates:
  if not groups or idx-groups[-1][-1]>max(a.adjacency_steps,a.recovery_window): groups.append([int(idx)])
  else: groups[-1].append(int(idx))
 events=[]
 for g in groups:
  start,end=g[0],g[-1]; before=values[max(0,start-a.baseline_window):start]; baseline=float(np.median(before)) if len(before) else float(values[start-1]); post=values[end:min(len(values),end+1+a.recovery_window)]; magnitude=float(max(abs(values[i]-values[i-1]) for i in g)); tolerance=max(3*scale,.1*magnitude); recovered=bool(len(post) and np.any(np.abs(post-baseline)<=tolerance))
  event_type='transient_spike' if recovered else 'level_shift' if len(g)==1 else 'sustained_change'
  members=[{'index':i,'timestamp':d.time.iloc[i].isoformat(),'previous_value':float(values[i-1]),'current_value':float(values[i]),'delta':float(delta[i-1]),'robust_score':float(score[i-1])} for i in g]
  events.append({'start_time':d.time.iloc[start].isoformat(),'end_time':d.time.iloc[end].isoformat(),'peak_change_time':max(members,key=lambda r:abs(r['delta']))['timestamp'],'direction':'down' if sum(r['delta'] for r in members)<0 else 'up','type':event_type,'magnitude':magnitude,'member_candidates':members,'recovered':recovered,'baseline':baseline,'in_requested_window':True})
 out={'parameters':{'direction':a.direction,'threshold_z':a.threshold_z,'adjacency_steps':a.adjacency_steps,'recovery_window':a.recovery_window,'window_start':a.window_start,'window_end':a.window_end,'robust_center':center,'robust_scale':scale},'events':events,'reported_count':len(events),'failure_state':None}
 print(json.dumps(out,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())