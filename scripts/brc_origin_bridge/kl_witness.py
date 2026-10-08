"""Independent first-witness precision convergence; no producer readers imported."""
import json
import sys
from pathlib import Path
from decimal import Decimal, localcontext
from fractions import Fraction
def number(s):
    m, e = s.lower().split('p')
    whole, _, tail = m[2:].partition('.')
    return Fraction(int(whole + tail, 16), 16 ** len(tail)) * Fraction(2) ** int(e)
def decimal(x):
    return Decimal(x.numerator) / Decimal(x.denominator)
phase = Path(sys.argv[1])
records = [v.split() for v in (phase / 'OPT/OUTPUT.log').read_text().split('COLUMN ')[1].splitlines()]
plans = [(number(v[4]), number(v[5])) for v in records if v[0] == 'PLAN' and v[1] == '0']
assert len(plans) == 47 * 48
raw = next(number(v[2]) for v in records if v[0] == 'OBJECTIVE' and v[1] == '0')
stable = number((phase / 'STABLE_OPT.log').read_text().splitlines()[0].split()[2])
values = []
for precision in [150, 200]:
    with localcontext() as ctx:
        ctx.prec = precision
        value = sum((decimal(q) * (decimal(q) / decimal(p)).ln() - decimal(q) + decimal(p) if q else decimal(p) for p, q in plans), Decimal(0))
        values.append(value)
with localcontext() as ctx:
    ctx.prec = 200
    convergence = abs(values[0] - values[1]) / abs(values[1])
    raw_error = abs(decimal(raw) - values[1]) / abs(values[1])
    stable_error = abs(decimal(stable) - values[1]) / abs(values[1])
    assert convergence < Decimal('1e-140')
    assert raw_error > Decimal('5e-12')
    assert stable_error <= Decimal('5e-12')
print(json.dumps(dict(status='PASS', column=[19, 46], family='FSOAP', precision=[150, 200],
                      true_kl=str(values[1]), reference_relative_difference=str(convergence),
                      preserved_original_relative_error=str(raw_error), stable_relative_error=str(stable_error)), indent=2))
