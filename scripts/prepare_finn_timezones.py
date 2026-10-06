"""Create an immutable, versioned hour-valued TIMEZONES input for this clock.

HEMCO count bypasses unit conversion. The installed UTC_OFFSET file contains
minutes whereas HcoClock_GetLocal expects hours. Preserve categorical remap,
coordinates, dates and fill masks; only valid offset values are divided by60.
"""
from pathlib import Path
import argparse, hashlib, json, shutil
import netCDF4 as nc
import numpy as np


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()


def validate_timezone_file(path):
    with nc.Dataset(path) as d:
        v = d['UTC_OFFSET']
        if v.units != 'hours':
            raise ValueError(f'TIMEZONES UTC_OFFSET must be hours for this HEMCO clock; found {v.units}. Prepare a versioned derived file with prepare_finn_timezones.py; preserve the raw input.')
        assert v.dimensions == ('time', 'lat', 'lon')
        dates = nc.num2date(d['time'][:], d['time'].units)
        assert [(t.year, t.month, t.day, t.hour) for t in dates] == [(2017, m, 1, 0) for m in range(1, 13)]
    return path


def prepare(source, output):
    assert source.resolve() != output.resolve() and not output.exists()
    receipt = output.with_suffix(output.suffix+'.json'); assert not receipt.exists()
    original_sha = sha(source)
    with nc.Dataset(source) as d:
        assert d['UTC_OFFSET'].units == 'minutes'
        assert np.issubdtype(d['UTC_OFFSET'].dtype, np.floating)
        assert not {'scale_factor', 'add_offset'} & set(d['UTC_OFFSET'].ncattrs())
        assert d['UTC_OFFSET'].dimensions == ('time', 'lat', 'lon')
        assert len(d.dimensions['time']) == 12
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    worst, cells = 0., 0
    with nc.Dataset(source) as x, nc.Dataset(output, 'r+') as y:
        for k in range(12):
            original = x['UTC_OFFSET'][k]
            assert np.all(np.isfinite(original.compressed()))
            transformed = original/60.
            y['UTC_OFFSET'][k] = transformed
            written = y['UTC_OFFSET'][k]
            assert np.array_equal(np.ma.getmaskarray(original), np.ma.getmaskarray(written))
            expected = np.asarray(original.compressed(), dtype=np.float64)/60.
            error = float(np.max(np.abs(written.compressed()-expected)))
            assert error == 0., "Offset conversion must be exact for this installed input"
            worst = max(worst, error); cells += len(expected)
        for n in x.variables:
            if n != 'UTC_OFFSET':
                assert x[n][:].tobytes() == y[n][:].tobytes(), n
        y['UTC_OFFSET'].units = 'hours'
        y['UTC_OFFSET'].long_name = 'Offset from UTC in hours'
        y.setncattr('repair_source_file', str(source.resolve()))
        y.setncattr('repair_source_sha256', original_sha)
        y.setncattr('repair_transform', 'Valid UTC_OFFSET /60 from minutes to hours; original masks, dates, coordinates retained. Experimental WE-CAN clock-unit correction.')
    assert sha(source) == original_sha
    validate_timezone_file(output)
    report = {'status': 'PASS', 'source': str(source.resolve()), 'source_sha256': original_sha,
              'derived': str(output.resolve()), 'derived_sha256': sha(output),
              'valid_cells_converted': cells, 'max_absolute_conversion_error_hours': worst,
              'mask_and_other_variables_unchanged': True,
              'clock_policy': 'Existing categorical/modal count remap, floor hours, [-12,+13] valid range and longitude fallback preserved.'}
    receipt.write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    print(json.dumps(prepare(args.input, args.output), indent=2))
