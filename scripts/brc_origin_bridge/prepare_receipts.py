"""Reporting inputs from exact saved native hexadecimal plans, no solver calls."""
import sys
from pathlib import Path
case = 0
for block in Path(sys.argv[1]).read_text().split('COLUMN ')[1:]:
    records = [line.split() for line in block.splitlines()]
    for family in range(7):
        solver = next(v for v in records if v[0] == 'SOLVER' and int(v[1]) == family)
        nr, nc, status = map(int, solver[2:5])
        assert status == 0
        plans = {(int(v[2]), int(v[3])): v[4:6] for v in records if v[0] == 'PLAN' and int(v[1]) == family}
        assert len(plans) == nr * nc
        print(case, nr * nc)
        for i in range(nr):
            for j in range(nc):
                print(*plans[i, j])
        case += 1
assert case == 14
