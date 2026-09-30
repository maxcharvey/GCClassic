from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
class DiagnosticNames(unittest.TestCase):
 def test_manual_metrics_fit_hemco_names_for_every_configured_species(self):
  source=(ROOT/'src/HEMCO/src/Extensions/hcox_finn_profile_mod.F90').read_text()
  declared=source[source.index('PARAMETER :: Metrics'):source.index('CALL GetExtOpt')]
  prefixes=re.findall(r"'(FINNProfile[^']+_)'",declared)
  self.assertEqual(len(prefixes),5)
  for kind in ('fullchem','aerosol'):
   cfg=(ROOT/f'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.{kind}').read_text()
   species=re.search(r'^165\s+FINNv25_Inject\s*:\s*\S+\s+(\S+)',cfg,re.M)[1].split('/')
   names=[p+s for p in prefixes for s in species]
   self.assertEqual(len(names),len(set(names)))
   for name in names:self.assertLessEqual(len(name),31,name)
if __name__=='__main__':unittest.main()
