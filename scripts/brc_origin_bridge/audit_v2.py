"""Read-only arithmetic/reference verification; native diagnostic output only."""
import json
import sys
from pathlib import Path
from fractions import Fraction
from decimal import Decimal, localcontext

def exact(token):
    sign = -1 if token.startswith('-') else 1
    mantissa, exponent = token.lstrip('+-').lower().split('p')
    whole, _, tail = mantissa[2:].partition('.')
    return sign * Fraction(int(whole + tail, 16), 16 ** len(tail)) * Fraction(2) ** int(exponent)

def relative(x, y):
    if y == 0:
        assert x == 0
        return Fraction(0)
    return abs(x - y) / abs(y)

def dec(x):
    return Decimal(x.numerator) / Decimal(x.denominator)

phase, previous = map(Path, sys.argv[1:])
text = (phase / 'OPT/OUTPUT.log').read_text()
assert text == (phase / 'SAN/OUTPUT.log').read_text()
families = ['FSOAP', 'FSOAS', 'BRCSOA', 'NPBRCPOA', 'WTC', 'PBRCPOA', 'DBRCPOA']
stable_records = [line.split() for line in (phase / 'STABLE_OPT.log').read_text().splitlines()]
assert (phase / 'STABLE_OPT.log').read_bytes() == (phase / 'STABLE_SAN.log').read_bytes()
assert len(stable_records) == 14
assert [int(v[1]) for v in stable_records] == list(range(14))
assert all(v[0] == 'STABLE_KL' and len(v) == 3 for v in stable_records)
stable = {int(v[1]): exact(v[2]) for v in stable_records}
expected_input = []
for b in text.split('COLUMN ')[1:]:
    records = [line.split() for line in b.splitlines()]
    for f in range(7):
        solver = next(v for v in records if v[0] == 'SOLVER' and int(v[1]) == f)
        nr, nc = map(int, solver[2:4])
        p = {(int(v[2]),int(v[3])):v[4:6] for v in records if v[0] == 'PLAN' and int(v[1]) == f}
        expected_input.append((nr, nc, p))
expected_text = ''
for index, (nr, nc, p) in enumerate(expected_input):
    expected_text += f'{index} {nr * nc}\n'
    for i in range(nr):
        for j in range(nc):
            expected_text += ' '.join(p[i,j]) + '\n'
assert (phase / 'RECEIPT_INPUT.txt').read_text() == expected_text
reports = []
for block in text.split('COLUMN ')[1:]:
    lines = [line.split() for line in block.splitlines()]
    lat, col = map(int, lines[0][-2:])
    assert (lat, col) in [(19, 46), (28, 131)]
    assert sum(line[0] == 'REFUSAL' for line in lines) == 9
    assert sum(line[0] == 'ISO_PASS' for line in lines) == 1
    assert lines[-1] == ['COLUMN_PASS']
    for line in lines:
        if line[0] == 'REFUSAL' and line[1].startswith('late_'):
            assert line[-2:] == ['6', '6'], line
    for f, family in enumerate(families):
        folder = 'first_country_candidate/results' if f < 2 else 'all_family_surface_evolution/solver_results'
        ref = previous / folder / f'surface_lat{lat}_col{col}_{family}_candidate_OPT.log'
        original = [line.split() for line in ref.read_text().splitlines()]
        original_plans = {(int(v[2]), int(v[3])): v[4:] for v in original if v[0] == 'CG_NATIVE_PLAN'}
        plans = {(int(v[2]), int(v[3])): v[4:] for v in lines if v[0] == 'PLAN' and int(v[1]) == f}
        assert plans.keys() == original_plans.keys()
        # Canonical21 decimal roundtrip identifies the native64 plan and prior.
        for key, values in plans.items():
            assert values[2:4] == original_plans[key][:2], (lat, col, family, key)
        rows = {int(v[2]): exact(v[3]) for v in lines if v[0] == 'ROW' and int(v[1]) == f}
        cols = {int(v[2]): exact(v[3]) for v in lines if v[0] == 'DONOR' and int(v[1]) == f}
        row_error = max(relative(sum((exact(plans[i, j][1]) for j in cols), Fraction(0)), target) for i, target in rows.items())
        col_error = max(relative(sum((exact(plans[i, j][1]) for i in rows), Fraction(0)), target) for j, target in cols.items())
        total = sum((exact(v[1]) for v in plans.values()), Fraction(0))
        total_error = relative(total, sum(cols.values(), Fraction(0)))
        assert row_error <= Fraction('5e-14') and col_error <= Fraction('5e-14')
        assert total_error <= Fraction('2e-14')
        for (i, j), values in plans.items():
            prior, plan = map(exact, values[:2])
            assert prior >= 0 and plan >= 0
            assert (prior > 0 and rows[i] > 0 and cols[j] > 0) == (plan > 0)
        with localcontext() as ctx:
            ctx.prec = 100
            kl = Decimal(0)
            edges = {}
            for (i, j), values in plans.items():
                p, q = map(lambda v: dec(exact(v)), values[:2])
                kl += q * (q / p).ln() - q + p if q else p
                if q:
                    logratio = (q / p).ln()
                    edges.setdefault(('r', i), []).append((('c', j), logratio))
                    edges.setdefault(('c', j), []).append((('r', i), logratio))
            raw_objective = next(exact(v[2]) for v in lines if v[0] == 'OBJECTIVE' and int(v[1]) == f)
            objective = stable[len(reports)]
            assert abs(dec(objective) - kl) <= Decimal('5e-12') * abs(kl) if kl else objective == 0
            potentials = {}
            residual = Decimal(0)
            for node in edges:
                if node in potentials:
                    continue
                potentials[node] = Decimal(0)
                stack = [node]
                while stack:
                    n = stack.pop()
                    for neighbor, ratio in edges[n]:
                        expected = ratio - potentials[n]
                        if neighbor in potentials:
                            residual = max(residual, abs(expected - potentials[neighbor]))
                        else:
                            potentials[neighbor] = expected
                            stack.append(neighbor)
            assert residual <= Decimal('5e-12')
        # Frozen row receipts contain integrated country endpoints and air.
        original_rows = {int(v[2]): v[3:] for v in original if v[0] == 'CG_NATIVE_ROW'}
        for v in lines:
            if v[0] == 'OUTPUT' and int(v[1]) == f:
                o, k = map(int, v[2:4])
                vals = original_rows[46 - k]
                expected = float(Decimal(vals[8 + 4 * o]) / Decimal(vals[0]))
                assert float.fromhex(v[4]) == expected, (lat, col, family, o, k)
        reports.append(dict(lat=lat, column=col, family=family, row_error=str(float(row_error)),
                            column_error=str(float(col_error)), total_error=str(float(total_error)),
                            kl_error=str(abs(dec(objective) - kl)), stable_kl_relative_error=str(abs(dec(objective)-kl)/abs(kl) if kl else 0), raw_kl_relative_error=str(abs(dec(raw_objective)-kl)/abs(kl) if kl else 0), true_kl=str(kl), representation_error=str(residual)))
assert len(reports) == 14
print(json.dumps(dict(status='PASS', profiles=14, whole_column_refusals=18, reports=reports), indent=2))
