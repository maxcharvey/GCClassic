#!/usr/bin/env python3
"""Prepare native CO-weighted height moments; never emits or modifies FINN mass.

Support is CO divided by 1 kg m-2 s-1 (dimensionless); height moments are m.
A common validity mask is applied before multiplication. HEMCO conservatively
remaps numerator and denominator separately, then forms the weighted heights.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import netCDF4 as nc
import numpy as np


def moments(co, mami, apt, invalid_height_policy="error"):
    if invalid_height_policy not in ("error","exclude"):
        raise ValueError("Invalid height policy")
    co,mami,apt=map(np.ma.asarray,(co,mami,apt))
    if co.shape!=mami.shape or co.shape!=apt.shape:
        raise ValueError('CO and height dimensions differ')
    c=np.asarray(co.filled(0),dtype=np.float64)
    if np.any(~np.isfinite(c)) or np.any(c<0):
        raise ValueError('CO support must be finite and nonnegative')
    hm=np.ma.getmaskarray(mami); ht=np.ma.getmaskarray(apt)
    m=np.asarray(mami.filled(0),dtype=np.float64)
    t=np.asarray(apt.filled(0),dtype=np.float64)
    if np.any((~hm)&(~np.isfinite(m))) or np.any((~ht)&(~np.isfinite(t))):
        raise ValueError('Unrecognized nonfinite height; declare missing values in source')
    valid=(c>0)&(~hm)&(~ht)
    rejected=valid&(t<m)
    if np.any(rejected) and invalid_height_policy=='error':
        raise ValueError('Positive supported GFAS cell has APT < MAMI')
    valid=valid&~rejected
    support=np.where(valid,c,0)
    mnum=np.zeros_like(c);tnum=np.zeros_like(c)
    mnum[valid]=c[valid]*m[valid]
    tnum[valid]=c[valid]*t[valid]
    if np.any(~np.isfinite(mnum)) or np.any(~np.isfinite(tnum)):
        raise ValueError('Height moment overflow')
    return dict(total_co_support=c,valid_co_support=support,
                mami_co_moment=mnum,apt_co_moment=tnum,
                rejected_co_support=np.where(rejected,c,0))


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def prepare(source, output, target_date=None, invalid_height_policy="error"):
    for reserved in (output,output.with_suffix('.json'),output.with_suffix(output.suffix+'.tmp')):
        if reserved.exists():raise ValueError(f'Refusing to overwrite {reserved}')
    with nc.Dataset(source) as ds:
        for name,units in [('cofire','kg m-2 s-1'),('mami','m'),('apt','m')]:
            if name not in ds.variables:raise ValueError(f'Missing required {name}')
        if ds['cofire'].units.replace(' ','') not in ('kgm-2s-1','kg/m2/s','kgm**-2s**-1'):
            raise ValueError(f'Unrecognized CO units: {ds["cofire"].units}')
        if ds['mami'].units not in ('m','meters','metres') or ds['apt'].units not in ('m','meters','metres'):
            raise ValueError('Heights must be metres; no implicit conversion')
        if ds['cofire'].dimensions!=('time','lat','lon'):
            raise ValueError(f'Unsupported dimensions: {ds["cofire"].dimensions}')
        for name in ('mami','apt'):
            if ds[name].dimensions!=ds['cofire'].dimensions:raise ValueError('Height coordinates do not align')
        if len(ds.dimensions['time'])!=1:raise ValueError('Require one UTC daily source record')
        times=nc.num2date(ds['time'][:],ds['time'].units,calendar=getattr(ds['time'],'calendar','standard'))
        source_time=times[0]
        if (source_time.hour,source_time.minute,source_time.second)!=(0,0,0):
            raise ValueError('Source time must explicitly represent day-start UTC')
        source_date=source_time.strftime('%Y-%m-%d')
        day=datetime.strptime(target_date or source_date,'%Y-%m-%d')
        offset=(datetime.strptime(source_date,'%Y-%m-%d')-day).days
        if offset not in (-1,0,1):raise ValueError('Only explicit adjacent-day sensitivity offsets -1/0/+1 supported')
        lat=np.asarray(ds['lat'][:]);lon=np.asarray(ds['lon'][:])
        for coords,label in [(lat,'lat'),(lon,'lon')]:
            if len(coords)<2 or np.any(~np.isfinite(coords)) or np.any(np.diff(coords)<=0):
                raise ValueError(f'Invalid {label} coordinate')
            if not np.allclose(np.diff(coords),np.diff(coords)[0],atol=2e-5,rtol=1e-3):
                raise ValueError(f'{label} must be regular')
        if not (-90<=lat.min()<lat.max()<=90 and -180<=lon.min()<lon.max()<=180):
            raise ValueError('Expected canonical GFAS latitude/longitude convention')
        data=moments(ds['cofire'][:],ds['mami'][:],ds['apt'][:],invalid_height_policy)
    output.parent.mkdir(parents=True,exist_ok=True)
    area=np.cos(np.deg2rad(lat))[None,:,None]
    total=float(np.sum(data['total_co_support']*area))
    excluded=float(np.sum(data['rejected_co_support']*area))
    bad_indices=np.argwhere(data['rejected_co_support'][0]>0)
    spatial_bins={}
    for i,j in bad_indices:
        key=f'lat20deg_bin_{int(np.floor(lat[i]/20))}_lon30deg_bin_{int(np.floor(lon[j]/30))}'
        entry=spatial_bins.setdefault(key,{'cells':0,'global_CO_area_fraction':0.0})
        entry['cells']+=1
        entry['global_CO_area_fraction']+=float(data['rejected_co_support'][0,i,j]*area[0,i,0]/total)
    meta={'source_path':str(source.resolve()),'source_sha256':digest(source),'source_utc_date':source_date,
          'model_date':day.strftime('%Y-%m-%d'),'gfas_source_minus_model_days':offset,
          'height_datum':'MSL','support_reference':'1 kg m-2 s-1',
          'invalid_height_policy':invalid_height_policy,
          'reversed_pair_cells':int(len(bad_indices)),
          'reversed_pair_CO_area_fraction':excluded/total if total>0 else 0.0,
          'reversed_pair_spatial_bins':spatial_bins,
          'missing_policy':'recognized masked heights remove joint height support; FINN mass never altered',
          'positive_native_cells':int(np.count_nonzero(data['total_co_support'])),
          'height_supported_cells':int(np.count_nonzero(data['valid_co_support'])),
          'created_utc':datetime.now(timezone.utc).isoformat()}
    tmp=output.with_suffix(output.suffix+'.tmp')
    try:
        with nc.Dataset(tmp,'w') as out:
            for name,n in [('time',1),('lat',len(lat)),('lon',len(lon))]:out.createDimension(name,n)
            for name,values,units in [('lat',lat,'degrees_north'),('lon',lon,'degrees_east')]:
                v=out.createVariable(name,'f8',(name,));v[:]=values;v.units=units
            tm=out.createVariable('time','f8',('time',));tm.units='hours since 2000-01-01 00:00:00';tm.calendar='standard'
            tm[:]=nc.date2num(day,tm.units,tm.calendar)
            for name,values in data.items():
                v=out.createVariable(name,'f8',('time','lat','lon'),zlib=True,complevel=4,fill_value=False)
                v[:]=values;v.units='m' if 'moment' in name else '1'
            out.height_datum='MSL'
            out.invalid_height_policy=invalid_height_policy
            out.source_utc_date=source_date
            out.model_date=meta['model_date']
            out.gfas_source_minus_model_days=offset
            out.history='Native joint-valid CO-weighted moments; no forest multiplier; '+json.dumps(meta,sort_keys=True)
        tmp.replace(output)
    finally:
        if tmp.exists():tmp.unlink()
    meta['output_sha256']=digest(output)
    output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    return meta


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--target-date',help='YYYY-MM-DD; explicit same/adjacent model date')
    ap.add_argument('--invalid-height-policy',choices=('error','exclude'),default='error',
                    help='Explicit sensitivity: exclude finite reversed height pairs from support; retain total CO')
    a=ap.parse_args();print(json.dumps(prepare(a.source,a.output,a.target_date,a.invalid_height_policy),indent=2))
if __name__=='__main__':main()
