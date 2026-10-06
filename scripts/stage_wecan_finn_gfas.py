"""Stage the approved frozen-input monthly FINN/GFAS WE-CAN experiment."""
from pathlib import Path
import argparse, importlib.util, json, re, shutil, subprocess
BASE=Path('/cluster/work/climate/mharvey/ModelDevlopment/BrC')
SRC=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-root',type=Path,required=True,
                    help='New versioned run root; never reuse a released package')
parser.add_argument('--timezone-hours',type=Path,required=True,
                    help='Verified versioned hour-valued UTC_OFFSET input')
parser.add_argument('--season-only',action='store_true',
                    help='Stage only the season after independent repair acceptance')
args=parser.parse_args()
OUT=args.output_root.resolve()
if OUT.exists():
 raise SystemExit(f'Refusing to overwrite existing run root: {OUT}')
from prepare_finn_timezones import validate_timezone_file
validate_timezone_file(args.timezone_hours)
(OUT/'inputs/timezones').mkdir(parents=True)
shutil.copy2(args.timezone_hours,OUT/'inputs/timezones/timezones_vohra_2017_hours.nc')
receipt=args.timezone_hours.with_suffix(args.timezone_hours.suffix+'.json')
if receipt.exists():
 shutil.copy2(receipt,OUT/'inputs/timezones/timezones_vohra_2017_hours.nc.json')
OLD=BASE/'runs/validation/BRC_1480_WECAN_MAYSEP2018_20260924'
FINN=BASE/'runs/validation/BRC_147_WECAN_GFAS_FINN_MAYSEP2018_20260928/inputs/FINNv25/v2025-06'
CONFIGS=('geoschem_config.yml','HEMCO_Config.rc','HEMCO_Config.rc.gmao_metfields','HEMCO_Diagn.rc','HISTORY.rc','species_database.yml')
spec=importlib.util.spec_from_file_location('cfg',SRC/'scripts/configure_finn_profile.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
template=(SRC/'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem').read_text()
cases=[('season','20180501','000000','20181001','000000',True,True,'legacy_65_35_l15'),
 ('may_smoke','20180501','000000','20180501','010000',True,True,'legacy_65_35_l15'),
 ('aug_smoke','20180801','000000','20180801','010000',True,True,'legacy_65_35_l15'),
 ('aug_nodiag','20180801','000000','20180801','010000',True,False,'legacy_65_35_l15'),
 ('aug_defaultoff','20180801','000000','20180801','010000',False,False,'pbl'),
 ('aug_forcedfallback','20180801','000000','20180801','010000',True,True,'legacy_65_35_l15'),
 ('aug_legacy6535','20180801','000000','20180801','010000',False,False,'pbl'),
 ('aug_supported_control','20180801','000000','20180801','010000',True,True,'pbl'),
 ('aug_day_transition','20180801','000000','20180802','010000',True,True,'legacy_65_35_l15')]
if args.season_only:
 cases=cases[:1]
else:
 # The forced-fallback fixture is a frozen input, not a missing directory.
 zero=BASE/'runs/validation/BRC_148_FINN_GFAS_WECAN_20261005/inputs/zero_profile'
 shutil.copytree(zero,OUT/'inputs/zero_profile')
for name,start,st,end,et,profile,diagnostics,fallback in cases:
 run=OUT/'cases'/name
 assert not run.exists(),run
 run.mkdir(parents=True)
 for f in CONFIGS:shutil.copy2(OLD/'global_wecan'/f,run/f)
 for d in ('Restarts','OutputDir'): (run/d).mkdir()
 (run/'FINN').symlink_to(FINN);(run/'GFAS').symlink_to(OLD/'inputs/GFAS/v2026-06')
 (run/'CodeDir').symlink_to(SRC)
 (run/'TIMEZONES').symlink_to(OUT/'inputs/timezones')
 (run/'gcclassic').symlink_to(SRC/'build_method/bin/gcclassic')
 seed=OLD/'global_wecan/Restarts'/f'GEOSChem.Restart.{start}_0000z.nc4'
 (run/'Restarts'/seed.name).symlink_to(seed.resolve())
 for f in (OLD/'global_wecan').glob('Planeflight.dat.2018*'):(run/f.name).symlink_to(f.resolve())
 p=run/'geoschem_config.yml';s=p.read_text()
 s=re.sub(r'start_date: \[[^\]]+\]',f'start_date: [{start}, {st}]',s)
 s=re.sub(r'end_date: \[[^\]]+\]',f'end_date: [{end}, {et}]',s);p.write_text(s)
 p=run/'HEMCO_Config.rc'
 aux='./GFAS/$YYYY/$MM/GFAS-smoke-$YYYY$MM$DD.nc'
 if name=='aug_forcedfallback':
  (run/'GFAS_ZERO').symlink_to(OUT/'inputs/zero_profile')
  aux='./GFAS_ZERO/GFAS-smoke-$YYYY$MM$DD.nc'
 s=m.configure(p.read_text(),template,aux,legacy=not profile,fallback=fallback,timezone_hours='./TIMEZONES/timezones_vohra_2017_hours.nc')
 s=s.replace('$ROOT/FINNv25/v2025-06/','./FINN/')
 s=re.sub(r'^DiagnFreq:.*$', 'DiagnFreq:                   Monthly' if name=='season' else 'DiagnFreq:                   00000000 010000',s,flags=re.M)
 if name=='aug_legacy6535':
  s=re.sub(r'(FINNv25_vertical_injection_fraction\s*:\s*)0.0',r'\g<1>0.35',s)
  s=re.sub(r'(FINNv25_vertical_injection_levels\s*:\s*)0',r'\g<1>15',s)
 p.write_text(s)
 species=re.search(r'^165\s+FINNv25_Inject\s*:\s*on\s+([^\n]+)',s,re.M)[1].split()[0].split('/')
 rows=['# FINN-only layer-integrated flux and column rates; kg/m2/s.']
 for sp in species:
  rows += [f'Emis{sp}_Fire {sp} 165 -1 -1 3 kg/m2/s FINN_layer_flux',f'Emis{sp}_FireColumn {sp} 165 -1 -1 2 kg/m2/s FINN_column_flux']
 (run/'HEMCO_Diagn.rc').write_text('\n'.join(rows)+'\n')
 p=run/'HISTORY.rc';s=p.read_text()
 if name!='season':
  # Focused one-hour output in separate validation directories only.
  s=re.sub(r"(?m)^(\s*\w+\.(?:frequency|duration):)\s+\d{8}\s+\d{6}.*$",r'\1 00000000 010000',s)
  if name=='aug_day_transition':
   s=re.sub(r"(?m)^(\s*\w+\.(?:frequency|duration):)\s+\d{8}\s+\d{6}.*$",r'\1 00000001 000000',s)
   # Daily averages, but final instantaneous restart for the 25-hour endpoint.
   s=re.sub(r'(?m)^(\s*Restart\.(?:frequency|duration):).*$',r"\1 'End'",s)
 else:
  s=re.sub(r"(?m)^(\s*\w+\.(?:frequency|duration):)\s+\d{8}\s+\d{6}.*$",r'\1 00000100 000000',s)
 # Add air mass for burden conversions, avoiding monthly-mean nonlinear reconstruction.
 if "'Met_AD " not in s:
  s=re.sub(r'(StateMet.fields:\s*)',r"\1'Met_AD',\n                              ",s,count=1)
 p.write_text(s)
 if diagnostics:
  flag='--monthly' if name=='season' else '--short-test-hourly' if name!='aug_day_transition' else None
  cmd=['perl',str(SRC/'scripts/configure_brc_deposition.pl'),'--history',str(p)]
  if flag:cmd.append(flag)
  subprocess.run(cmd,check=True)
 info={'case':name,'start':[start,st],'end':[end,et],'grid':'2x2.5/47L','threads':192,'fallback':fallback,'profile_enabled':profile,'species':species,'source':str(SRC),'seed':str(seed.resolve()),'gfas_date_offset':0,'diagnostic_cadence':'monthly' if name=='season' else 'short-test','origin_tags':False,'timezone_policy':'Versioned minute-to-hour offset conversion; categorical remap and clock policy unchanged','timezone_input':str(OUT/'inputs/timezones/timezones_vohra_2017_hours.nc'),'naming_contract':'Approved descriptive campaign name follows recent vault validation roots.'}
 (run/'STAGING.json').write_text(json.dumps(info,indent=2)+'\n')
 print('STAGED',name,flush=True)
