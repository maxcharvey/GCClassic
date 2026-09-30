import importlib.util
from pathlib import Path
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('prep',Path(__file__).with_name('prepare_finn_gfas_heights.py'))
prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)
class HeightsTests(unittest.TestCase):
    def test_common_support_and_weighting(self):
        c=np.ma.array([1.,3.,2.,0.])
        m=np.ma.array([100.,300.,np.nan,np.nan],mask=[0,0,1,1])
        t=np.ma.array([200.,500.,400.,0.])
        a=prep.moments(c,m,t)
        self.assertEqual(a['total_co_support'].sum(),6.)
        self.assertEqual(a['valid_co_support'].sum(),4.)
        self.assertEqual(a['mami_co_moment'].sum()/4,250.)
        self.assertEqual(a['apt_co_moment'].sum()/4,425.)
        self.assertTrue(all(np.all(np.isfinite(v)) for v in a.values()))
    def test_negative_msl_is_preserved(self):
        a=prep.moments(np.array([2.]),np.array([-30.]),np.array([10.]))
        self.assertEqual(a['mami_co_moment'][0],-60.)
    def test_masked_source_has_no_support(self):
        a=prep.moments(np.ma.array([np.nan],mask=[1]),np.array([0.]),np.array([0.]))
        self.assertEqual(a['total_co_support'][0],0.)
    def test_malformed_heights_fail(self):
        for m,t in [(np.nan,200.),(300.,200.),(100.,np.inf)]:
            with self.assertRaises(ValueError):prep.moments(np.array([1.]),np.array([m]),np.array([t]))
    def test_explicit_exclusion_preserves_total(self):
        a=prep.moments(np.array([2.,3.]),np.array([300.,100.]),np.array([200.,200.]),'exclude')
        self.assertEqual(a['total_co_support'].sum(),5.)
        self.assertEqual(a['valid_co_support'].sum(),3.)
        self.assertEqual(a['rejected_co_support'].sum(),2.)
        self.assertEqual(a['mami_co_moment'].sum(),300.)
        with self.assertRaises(ValueError):
            prep.moments(np.array([1.]),np.array([np.nan]),np.array([2.]),'exclude')
    def test_invalid_source_fails(self):
        for c in (-1.,np.nan,np.inf):
            with self.assertRaises(ValueError):prep.moments(np.array([c]),np.array([1.]),np.array([2.]))
if __name__=='__main__':unittest.main()
