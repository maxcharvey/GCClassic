import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
import netCDF4 as nc
import numpy as np
s=importlib.util.spec_from_file_location('prep',Path(__file__).resolve().parents[2]/'scripts/prepare_finn_gfas_heights.py')
p=importlib.util.module_from_spec(s);s.loader.exec_module(p)
class IOTests(unittest.TestCase):
    def fixture(self,root):
        path=root/'source.nc'
        with nc.Dataset(path,'w') as d:
            for k,n in [('time',1),('lat',2),('lon',2)]:d.createDimension(k,n)
            for k,x in [('lat',[-.05,.05]),('lon',[-.05,.05])]:d.createVariable(k,'f8',(k,))[:]=x
            t=d.createVariable('time','f8',('time',));t.units='hours since 2018-08-01 00:00:00';t[:]=0
            for k,x,u in [('cofire',[1,3,2,0],'kg/m2/s'),('mami',[100,300,np.nan,np.nan],'m'),('apt',[200,500,0,0],'m')]:
                v=d.createVariable(k,'f8',('time','lat','lon'),fill_value=np.nan);v[:]=np.array(x).reshape(1,2,2);v.units=u
        return path
    def test_roundtrip_and_adjacent_day(self):
        with TemporaryDirectory() as td:
            r=Path(td);src=self.fixture(r);out=r/'aux.nc'
            meta=p.prepare(src,out,'2018-08-02')
            self.assertEqual(meta['gfas_source_minus_model_days'],-1)
            with nc.Dataset(out) as d:
                self.assertEqual(d.height_datum,'MSL')
                self.assertEqual(d['valid_co_support'][:].sum(),4.)
                self.assertEqual(d['mami_co_moment'][:].sum(),1000.)
                self.assertEqual(d['mami_co_moment'].units,'m')
                self.assertEqual(nc.num2date(d['time'][:],d['time'].units)[0].day,2)
            self.assertEqual(json.loads(out.with_suffix('.json').read_text())['output_sha256'],p.digest(out))
    def test_refuse_unsupported_offset_and_existing_provenance(self):
        with TemporaryDirectory() as td:
            r=Path(td);src=self.fixture(r);out=r/'aux.nc'
            with self.assertRaises(ValueError):p.prepare(src,out,'2018-08-04')
            out.with_suffix('.json').write_text('preserved')
            with self.assertRaises(ValueError):p.prepare(src,out)
            self.assertEqual(out.with_suffix('.json').read_text(),'preserved')
if __name__=='__main__':unittest.main()
