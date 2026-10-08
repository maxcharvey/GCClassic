#!/usr/bin/env python3
"""Exact rational audit of saved manufactured dynamic donor construction."""
from fractions import Fraction
from pathlib import Path
import json
import sys


def number(value):
    sign = -1 if value.startswith('-') else 1
    value = value.lstrip('+-')
    mantissa, exponent = value.split('p')
    mantissa = mantissa.removeprefix('0x')
    whole, _, fraction = mantissa.partition('.')
    numerator = int(whole + fraction, 16)
    exponent = int(exponent) - 4*len(fraction)
    return sign * Fraction(numerator) * Fraction(2) ** exponent


def relative(x, y):
    return abs(x-y)/abs(y) if y else abs(x)


def audit(path):
    lines = Path(path).read_text().splitlines()
    rows, donors, prior, stocks = {}, {}, {}, {}
    refusals = []
    for line in lines:
        fields = line.split()
        if fields[0] == 'MATRIX':
            assert fields[1:] == ['2', '731']
        elif fields[0] == 'ROW':
            rows[int(fields[1])] = number(fields[2])
        elif fields[0] == 'DONOR':
            d,o,l,s = map(int,fields[1:5])
            donors[d] = (o,l,s,number(fields[5]))
        elif fields[0] == 'PRIOR':
            prior[tuple(map(int,fields[1:3]))] = number(fields[3])
        elif fields[0] == 'STOCK':
            stocks[int(fields[1])] = list(map(number,fields[2:]))
        elif fields[0] == 'REFUSAL':
            assert fields[-1] == 'atomic=PASS'
            refusals.append(fields[1])
    assert len(rows)==2 and len(donors)==731 and len(prior)==1462 and len(stocks)==244
    for o, values in stocks.items():
        x = Fraction(o+1,1024) if o<243 else Fraction(2)**-1000
        initial_top,initial_bottom,emission,loss,out_top,out_bottom = values
        assert initial_top==x and initial_bottom==2*x and loss==x/4
        assert emission==(x/2 if o<243 else 0)
        assert out_top==x and out_bottom==2*x-loss+emission
    for d,(o,l,s,mass) in donors.items():
        if d<488:
            assert (l,o,s)==(d//244,d%244,0)
            expected = stocks[o][l] - (stocks[o][3] if l==1 else 0)
        else:
            assert (l,o,s)==(1,d-488,1)
            expected = stocks[o][2]
        assert mass==expected and mass>0
        for i in range(2):
            assert prior[i,d]==(mass if i==l else 0)
        assert sum(prior[i,d] for i in range(2))==mass
    for i in range(2):
        total = sum(prior[i,d] for d in donors)
        assert relative(total,rows[i]) <= Fraction(5,10**14)
        for o in stocks:
            assert sum(prior[i,d] for d in donors if donors[d][0]==o)==stocks[o][4+i]
    required={'callback_failure','callback_dimensions','callback_nan','callback_negative',
              'callback_zero_support','callback_lost_positive','callback_bad_margin',
              'workspace_limit','allocation','own_overdraft','negative_native_rhs',
              'positive_underflow','own_target','late_nan','UNT_new_source','seventh_family',
              'receipt_alias','input_output_alias','seventh_family_bad_output'}
    assert set(refusals)==required and len(refusals)==19
    for item in ('PASS legacy_four_origin_donors_prior_losses_output_exact',
                 'PASS seven_family_bundle',
                 'PASS all_dynamic_constructor_controls; optimizer_and_live_NOT_QUALIFIED'):
        assert item in lines
    return {'verdict':'PASS','donors':731,'origins':244,'independent_exact_prior_edges':1462,
            'own_stock_loss_source_output_checks':244,'atomic_refusals':19,
            'legacy_four_origin_plumbing':'PASS','optimizer_qualified':False,'live_qualified':False}


if __name__ == '__main__':
    print(json.dumps([audit(path) for path in sys.argv[1:]],indent=2))
