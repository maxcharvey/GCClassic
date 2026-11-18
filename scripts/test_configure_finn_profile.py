import importlib.util
from pathlib import Path
import re
import unittest
s=importlib.util.spec_from_file_location('cfg',Path(__file__).with_name('configure_finn_profile.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class ConfigTests(unittest.TestCase):
 def test_height_only_preserves_custom_paths_and_fallback(self):
  t=(m.ROOT/'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem').read_text()
  old=m.configure(t,t,'./custom/GFAS/$YYYY$MM$DD.nc',fallback='legacy_65_35_l15')
  old=old.replace('$ROOT/FINN/v2025-06/','./custom/FINN/')
  old=re.sub(r'^.*--> FINNv25_GFAS_height_scale[^\n]*\n','',old,flags=re.M)
  for factor in (0.8,1.0,1.2):
   new=m.configure_height_scale(old,factor)
   stripped=re.sub(r'^.*--> FINNv25_GFAS_height_scale[^\n]*\n','',new,flags=re.M)
   self.assertEqual(stripped,old)
   changed=m.configure_height_scale(new,1.2)
   self.assertEqual(changed.count('--> FINNv25_GFAS_height_scale'),1)
   self.assertIn('FINNv25_GFAS_height_scale : 1.2',changed)
  with self.assertRaisesRegex(ValueError,'Duplicate'):
   m.configure_height_scale(new+'    --> FINNv25_GFAS_height_scale : 1.0\n',0.8)
  with self.assertRaisesRegex(ValueError,'requires'):
   m.configure_height_scale(t,0.8)
 def test_height_scaling_on_accepted_layout(self):
  for kind in ('fullchem','aerosol'):
   t=(m.ROOT/f'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.{kind}').read_text()
   # The already accepted runs predate the new option.
   old=re.sub(r'^.*--> FINNv25_GFAS_height_scale[^\n]*\n','',t,flags=re.M)
   baseline=m.configure(old,t,'./GFAS/file.nc',fallback='legacy_65_35_l15')
   for factor in (0.8,1.0,1.2):
    out=m.configure(old,t,'./GFAS/file.nc',fallback='legacy_65_35_l15',height_scale=factor)
    self.assertEqual(out.count('--> FINNv25_GFAS_height_scale'),1)
    self.assertIn(f'FINNv25_GFAS_height_scale : {factor}',out)
    # Only the height option differs: all source rows/fallback/dates retained.
    self.assertEqual(out.replace(f'height_scale : {factor}','height_scale : 1.0'),baseline)
    again=m.configure(out,t,'./GFAS/file.nc',fallback='legacy_65_35_l15',height_scale=factor)
    self.assertEqual(again.count('--> FINNv25_GFAS_height_scale'),1)
 def test_invalid_height_scales(self):
  t=(m.ROOT/'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem').read_text()
  for factor in (0,-0.8,float('nan'),float('inf')):
   with self.assertRaisesRegex(ValueError,'finite and positive'):
    m.configure(t,t,'./GFAS/file.nc',height_scale=factor)
  with self.assertRaisesRegex(ValueError,'prepared-profile'):
   m.configure(t,t,'./GFAS/file.nc',legacy=True,height_scale=0.8)
 def test_explicit_timezone_hours_path(self):
  t=(m.ROOT/'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem').read_text()
  out=m.configure(t,t,'./GFAS/file.nc',timezone_hours='./TIMEZONES/hours.nc')
  self.assertRegex(out,r'\* TIMEZONES ./TIMEZONES/hours.nc UTC_OFFSET 2017/1-12/1/0 C xy count')
  with self.assertRaisesRegex(ValueError,'255-character limit'):
   m.configure(t,t,'./GFAS/file.nc',timezone_hours='./'+('x'*260)+'.nc')
 def test_rejects_read_once_daily_inventory(self):
  t=(m.ROOT/'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem').read_text()
  start=t.index('(((FINNv25\n');end=t.index(')))FINNv25\n',start)
  stale=t[:start]+t[start:end].replace(' RF xy ', ' EF xy ')+t[end:]
  with self.assertRaisesRegex(ValueError, 'must use RF'):
   m.configure(t,stale,'./GFAS/file.nc')
 def test_opt_in_legacy_fallback(self):
  t=(m.ROOT/'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem').read_text()
  out=m.configure(t,t,'./GFAS/$YYYY/$MM/GFAS-smoke-$YYYY$MM$DD.nc',fallback='legacy_65_35_l15')
  self.assertRegex(out,r'FINNv25_profile_fallback\s*:\s*legacy_65_35_l15')
  self.assertRegex(out,r'FINNv25_vertical_injection_fraction\s*:\s*0.0')
  self.assertRegex(out,r'FINNv25_vertical_injection_levels\s*:\s*0')
  with self.assertRaisesRegex(ValueError,'Unknown'):
   m.configure(t,t,'./GFAS/file.nc',fallback='invalid')
 def test_inventory_and_auxiliary_switches(self):
  for kind in ('fullchem','aerosol'):
   t=(m.ROOT/f'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.{kind}').read_text()
   t=re.sub(r'(GFAS_BRC_HARMONIZED_SENSITIVITY\s*:\s*)false',r'\g<1>true',t)
   for legacy in (False,True):
    with self.subTest(kind=kind,legacy=legacy):
     out=m.configure(t,t,'/tmp/aux.nc',legacy)
     for key in ('GFAS_BRC_HARMONIZED_SENSITIVITY','QFED2_BRC_HARMONIZED_SENSITIVITY','QFED2'):
      self.assertRegex(out,rf'{key}\s*:\s*false')
     self.assertRegex(out,r'FINNV25_BRC_HARMONIZED_SENSITIVITY\s*:\s*true')
     self.assertRegex(out,r'112\s+GFAS\s*:\s*off')
     self.assertRegex(out,r'111\s+GFED\s*:\s*off')
     self.assertRegex(out,r'165\s+FINNv25_Inject\s*:\s*on')
     self.assertRegex(out,r'FINNV25_GFAS_PROFILE\s*:\s*'+('false' if legacy else 'true'))
     aux=[x for x in out.splitlines() if x.startswith('165 FINNV25_GFAS_')]
     self.assertEqual(len(aux),1 if m.METHOD=='gfas_prepared' else 4)
     self.assertTrue(all('/tmp/aux.nc' in x for x in aux))
     self.assertTrue(all(x.split()[5]=='RFY' for x in aux))
 def test_historical_config_without_qfed_proxy_option(self):
  t=(m.ROOT/'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem').read_text()
  old=re.sub(r'^.*--> QFED2_BRC_HARMONIZED_SENSITIVITY[^\n]*\n','',t,flags=re.M)
  out=m.configure(old,t,'/tmp/aux.nc')
  self.assertRegex(out,r'GFAS_BRC_HARMONIZED_SENSITIVITY\s*:\s*false')
 def test_long_auxiliary_path_rejected(self):
  t=(m.ROOT/'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.fullchem').read_text()
  with self.assertRaisesRegex(ValueError,'255-character limit'):
   m.configure(t,t,'/tmp/'+('x'*260)+'.nc')
if __name__=='__main__':unittest.main()
