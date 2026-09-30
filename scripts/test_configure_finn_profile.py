import importlib.util
from pathlib import Path
import re
import unittest
s=importlib.util.spec_from_file_location('cfg',Path(__file__).with_name('configure_finn_profile.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class ConfigTests(unittest.TestCase):
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
