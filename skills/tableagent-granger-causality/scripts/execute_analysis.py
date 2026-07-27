#!/usr/bin/env python3
"""Run bidirectional Granger tests with mixed-integration safeguards."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
import numpy as np
import pandas as pd

def read_table(path,sheet): return pd.read_excel(path,sheet_name=sheet or 0) if path.suffix.lower() in {'.xlsx','.xls'} else pd.read_csv(path)
def detrend(x):
 i=np.arange(len(x),dtype=float); return x-np.polyval(np.polyfit(i,x,1),i)
def classify(xy,yx,alpha,minimum):
 sx=sum(v<alpha for v in xy.values()); sy=sum(v<alpha for v in yx.values())
 if sx>=minimum and sy<minimum: return 'cause_to_effect',sx,sy
 if sy>=minimum and sx<minimum: return 'effect_to_cause',sx,sy
 if sx<minimum and sy<minimum: return 'none',sx,sy
 return 'conflicting_or_weak',sx,sy
def main():
 p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--sheet'); p.add_argument('--cause',required=True); p.add_argument('--effect',required=True); p.add_argument('--max-lag',type=int,default=10); p.add_argument('--preprocess',choices=['auto','none','difference','detrend'],default='auto'); p.add_argument('--alpha',type=float,default=.05)
 a=p.parse_args()
 try:
  import statsmodels.api as sm
  from statsmodels.tsa.stattools import adfuller,grangercausalitytests
 except Exception as e: print(json.dumps({'failure_state':'dependency_missing','error':str(e)})); return 1
 d=read_table(a.file,a.sheet); x=pd.to_numeric(d[a.cause],errors='coerce').to_numpy(float); y=pd.to_numeric(d[a.effect],errors='coerce').to_numpy(float); m=np.isfinite(x)&np.isfinite(y); x=x[m]; y=y[m]
 if len(x)<max(80,a.max_lag*12): print(json.dumps({'failure_state':'too_few_points','n':len(x)})); return 1
 adf_x=float(adfuller(x,autolag='AIC')[1]); adf_y=float(adfuller(y,autolag='AIC')[1]); stx=adf_x<a.alpha; sty=adf_y<a.alpha; mixed=stx!=sty
 mode=a.preprocess
 if mode=='auto': mode='toda_yamamoto_levels' if mixed else 'none' if stx and sty else 'difference'
 def standard_pvals(effect,cause):
  r=grangercausalitytests(np.column_stack([effect,cause]),maxlag=a.max_lag,verbose=False); return {str(k):float(r[k][0]['ssr_ftest'][1]) for k in range(1,a.max_lag+1)}
 if mode=='toda_yamamoto_levels':
  z=np.column_stack([x,y]); xy={}; yx={}; dmax=1
  for order in range(1,a.max_lag+1):
   total=order+dmax; target=z[total:]; design=sm.add_constant(np.column_stack([z[total-lag:-lag,j] for lag in range(1,total+1) for j in (0,1)]))
   for effect,cause,out in [(1,0,xy),(0,1,yx)]:
    fit=sm.OLS(target[:,effect],design).fit(); restriction=np.zeros((order,design.shape[1]))
    for lag in range(1,order+1): restriction[lag-1,1+(lag-1)*2+cause]=1
    out[str(order)]=float(fit.f_test(restriction).pvalue)
  minimum=max(3,math.ceil(a.max_lag/2)); decision,sx,sy=classify(xy,yx,a.alpha,minimum)
  warning='mixed integration orders: Toda-Yamamoto sensitivity across base lag orders; augmented lag excluded from restrictions'
 else:
  if mode=='difference': x,y=np.diff(x),np.diff(y)
  elif mode=='detrend': x,y=detrend(x),detrend(y)
  xy=standard_pvals(y,x); yx=standard_pvals(x,y); minimum=2; decision,sx,sy=classify(xy,yx,a.alpha,minimum); warning=None
 out={'n':len(x),'requested_preprocess':a.preprocess,'resolved_preprocess':mode,'stationarity':{'cause_adf_p':adf_x,'effect_adf_p':adf_y,'cause_stationary':stx,'effect_stationary':sty},'warning':warning,'max_lag':a.max_lag,'alpha':a.alpha,'minimum_consistent_orders':minimum,'cause_to_effect_pvalues':xy,'effect_to_cause_pvalues':yx,'cause_to_effect_significant_count':sx,'effect_to_cause_significant_count':sy,'decision':decision,'failure_state':None}
 print(json.dumps(out,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())