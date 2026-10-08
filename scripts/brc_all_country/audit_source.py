#!/usr/bin/env python3
"""Independent decimal summation and support/closure audit of saved probe outputs."""
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sys
import numpy as np


def audit(path):
    lines = Path(path).read_text().splitlines()
    bits = int(lines[0].split()[1])
    tolerance = Decimal('5e-5' if bits == 32 else '5e-12')
    dtype = np.float32 if bits == 32 else np.float64
    success = 0
    refused = 0
    worst = Decimal(0)
    for i, line in enumerate(lines):
        if not line.startswith('CASE '):
            continue
        _, name, status, parent, injected, error = line.split()
        if int(status):
            refused += 1
            continue  # Unchanged destination is separately asserted by compiled probe.
        raw = [Decimal(x) for x in lines[i+1].split()[1:]]
        parts = [Decimal(x) for x in lines[i+2].split()[1:]]
        assert len(raw) == len(parts) == 244, name
        assert all(x.is_finite() and x >= 0 for x in parts), name
        # Reconstruct separately rounded native divide/multiply and ordered sum.
        # Decimal strings in the probe roundtrip the binary source values.
        native_raw = np.array([dtype(float(x)) for x in raw], dtype=dtype)
        native_parts = np.array([dtype(float(x)) for x in parts], dtype=dtype)
        native_total = dtype(0)
        for value in native_raw:
            native_total = dtype(native_total + value)
        native_parent = dtype(float(parent))
        native_injected = dtype(float(injected))
        if native_parent:
            source_error = dtype(abs(dtype(native_total-native_parent)) / max(native_total,native_parent))
            assert source_error <= dtype(2e-6), (name, 'raw-parent closure')
            expected = np.multiply(native_injected, np.divide(native_raw, native_total, dtype=dtype), dtype=dtype)
        else:
            expected = np.zeros(244,dtype=dtype)
        assert expected.tobytes() == native_parts.tobytes(), (name, 'per-country native direct product')
        for source, part in zip(raw, parts):
            assert source or part == 0, (name, 'zero support')
            assert not (source > 0 and Decimal(injected) > 0 and part == 0), (name, 'lost support')
        total = sum(parts, Decimal(0))
        if Decimal(injected):
            relative = abs(total-Decimal(injected))/Decimal(injected)
            assert relative <= tolerance, (name, relative)
            worst = max(worst, relative)
        else:
            assert total == 0, name
        success += 1
    assert success == 7 and refused == 11, (success, refused)
    assert 'CHECK shape_capacity_empty PASS' in lines
    assert 'CHECK legacy_compatibility_400 PASS' in lines
    assert 'CHECK bundle_success_late_failure_UNT_mapping PASS' in lines
    assert 'PASS_CASES 18' in lines
    return {'precision_bits': bits, 'success_cases': success, 'refusal_cases': refused,
            'shape_capacity_empty': 'PASS', 'legacy_comparisons': 400,
            'per_country_native_share_oracle': 'PASS',
            'max_independent_closure_relative': str(worst)}


if __name__ == '__main__':
    with localcontext() as context:
        context.prec = 100
        result = [audit(path) for path in sys.argv[1:]]
    print(json.dumps({'verdict': 'PASS', 'variants': result}, indent=2))
