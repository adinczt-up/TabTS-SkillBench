#!/usr/bin/env python3
"""Compare exact distributions or location-scale distribution families."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd


def read_table(path, sheet): return pd.read_excel(path,sheet_name=sheet or 0) if path.suffix.lower() in {'.xlsx','.xls'} else pd.read_csv(path)
def acf1(x): return 0.0 if len(x)<3 or not np.std(x[:-1]) or not np.std(x[1:]) else float(np.corrcoef(x[:-1],x[1:])[0,1])
def moments(x):
    z=(x-x.mean())/max(x.std(ddof=1),1e-12)
    return {'skew':float(np.mean(z**3)),'excess_kurtosis':float(np.mean(z**4)-3)}
def describe(x): return {'n':len(x),'mean':float(x.mean()),'std':float(x.std(ddof=1)),'median':float(np.median(x)),'iqr':float(np.quantile(x,.75)-np.quantile(x,.25)),'quantiles':[float(v) for v in np.quantile(x,[.05,.25,.5,.75,.95])],**moments(x)}
def robust_z(x):
    iqr=max(float(np.quantile(x,.75)-np.quantile(x,.25)),1e-12)
    return (x-np.median(x))/iqr


def main():
    p=argparse.ArgumentParser(); p.add_argument('--file',required=True,type=Path); p.add_argument('--sheet'); p.add_argument('--series-a',required=True); p.add_argument('--series-b',required=True)
    p.add_argument('--target',choices=['generic','gaussian_white_noise'],default='generic'); p.add_argument('--comparison',choices=['auto','exact','family'],default='auto'); p.add_argument('--shape-tolerance',type=float,default=.10)
    a=p.parse_args(); d=read_table(a.file,a.sheet); x=pd.to_numeric(d[a.series_a],errors='coerce').dropna().to_numpy(float); y=pd.to_numeric(d[a.series_b],errors='coerce').dropna().to_numpy(float)
    if min(len(x),len(y))<20: print(json.dumps({'failure_state':'insufficient_samples'})); return 1
    sx,sy=describe(x),describe(y); mode='family' if a.comparison=='auto' else a.comparison
    try:
        from scipy.stats import ks_2samp
        raw_ks=float(ks_2samp(x,y).statistic); shape_ks=float(ks_2samp(robust_z(x),robust_z(y)).statistic)
    except Exception: raw_ks=shape_ks=float('nan')
    pooled=max((sx['std']+sy['std'])/2,1e-12); center=abs(sx['mean']-sy['mean'])/pooled; scale=abs(sx['std']-sy['std'])/pooled
    shape_same=shape_ks<=a.shape_tolerance and abs(sx['skew']-sy['skew'])<=.75 and abs(sx['excess_kurtosis']-sy['excess_kurtosis'])<=1.0
    if a.target=='gaussian_white_noise':
        white=abs(acf1(x))<=3/np.sqrt(len(x)) and abs(acf1(y))<=3/np.sqrt(len(y)); gaussian=max(abs(sx['skew']),abs(sy['skew']))<=.5 and max(abs(sx['excess_kurtosis']),abs(sy['excess_kurtosis']))<=1.0
        same=white and gaussian and shape_same
    elif mode=='family': same=shape_same
    else: same=raw_ks<=a.shape_tolerance and center<=.25 and scale<=.25
    out={'target':a.target,'comparison':mode,'series_a':sx,'series_b':sy,'raw_ks':raw_ks,'standardized_shape_ks':shape_ks,'center_effect':center,'scale_effect':scale,'acf1':{'a':acf1(x),'b':acf1(y)},'shape_same':shape_same,'decision':'same' if same else 'different','failure_state':None}
    print(json.dumps(out,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())