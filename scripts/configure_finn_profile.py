#!/usr/bin/env python3
"""Opt an existing fullchem/aerosol run into this branch's FINN profile method.

Does not change dates, restarts, meteorology or chemistry. Writes a backup,
refuses unknown layouts, and installs FINN source rows from this checkout.
"""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
METHOD = 'gfas_prepared'


def configure(text, template, auxiliary, legacy=False):
    def set_option(key, value):
        nonlocal text
        pattern = rf'^(\s*-->\s*{re.escape(key)}\s*:\s*)\S+'
        text, count = re.subn(pattern, lambda m: m[1]+value, text, flags=re.M)
        if count != 1:
            raise ValueError(f'Expected one option {key}, found {count}')
    for name in ('GFED', 'GFAS', 'FINNv25_Inject'):
        pattern = rf'^(\s*\d+\s+{name}\s*:\s*)\S+([^\n]*)'
        match = re.search(pattern, template, re.M)
        if not match:
            raise ValueError(f'No template extension {name}')
        value = 'on' if name == 'FINNv25_Inject' else 'off'
        text, count = re.subn(pattern, lambda m: m[1]+value+match[2], text, flags=re.M)
        if count != 1:
            raise ValueError(f'Expected one extension {name}, found {count}')
    set_option('FINNv25', 'true')
    set_option('FINNV25_BRC_HARMONIZED_SENSITIVITY', 'true')
    # Import the full species inventory, preserving canonical units/proxy scales.
    start, end = '(((FINNv25\n', ')))FINNv25\n'
    a,b = text.index(start), text.index(end)+len(end)
    ta,tb = template.index(start), template.index(end)+len(end)
    text = text[:a]+template[ta:tb]+text[b:]
    for key in ('FINNV25_GFAS_PROFILE','FINNv25_profile_fallback','FINNv25_profile_datum'):
        text = re.sub(rf'^\s*-->\s*{key}\s*:[^\n]*\n', '', text, flags=re.M)
    # Replace the one known auxiliary block from a fresh branch-generated run.
    aux_pattern = r'# Auxiliary shape only:[^\n]*\n\(\(\(FINNv25_Inject\n\(\(\(FINNV25_GFAS_PROFILE\n.*?\)\)\)FINNV25_GFAS_PROFILE\n\)\)\)FINNv25_Inject\n'
    text, count = re.subn(aux_pattern, '', text, flags=re.S)
    if count > 1 or '165 FINNV25_GFAS_REFERENCE ' in text or '165 FINNV25_GFAS_SUPPORT ' in text:
        raise ValueError('Unrecognized or duplicate existing auxiliary rows')
    set_option('FINNv25_vertical_injection_fraction', '0.0')
    set_option('FINNv25_vertical_injection_levels', '0')
    anchor = re.search(r'^.*-->\s*FINNv25_vertical_injection_levels\s*:[^\n]*\n',text,re.M)
    options = ('    --> FINNV25_GFAS_PROFILE : '+('false' if legacy else 'true')+'\n'
               '    --> FINNv25_profile_fallback : pbl\n')
    text=text[:anchor.end()]+options+text[anchor.end():]
    marker='# Auxiliary shape only:'
    tail=template[template.index(marker):]
    aux=tail[:tail.index(')))FINNv25_Inject\n')+len(')))FINNv25_Inject\n')]
    if auxiliary:
        aux=re.sub(r'\$ROOT/GFAS/v2026-06/\$YYYY/\$MM/GFAS-smoke-\$YYYY\$MM\$DD.nc',lambda m:auxiliary,aux)
    pos=text.index(end)+len(end)
    return text[:pos]+'\n'+aux+text[pos:]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run_dir',type=Path)
    ap.add_argument('--kind',choices=('fullchem','aerosol'),default='fullchem')
    ap.add_argument('--auxiliary',help='Auxiliary filename with optional HEMCO $YYYY/$MM/$DD tokens')
    ap.add_argument('--legacy',action='store_true',help='Same FINN inventory with legacy surface allocation')
    args=ap.parse_args()
    path=args.run_dir/'HEMCO_Config.rc'
    backup=path.with_suffix('.rc.before_finn_profile')
    if backup.exists():
        raise SystemExit(f'Refusing to overwrite {backup}')
    template=(ROOT/f'src/GEOS-Chem/run/GCClassic/HEMCO_Config.rc.templates/HEMCO_Config.rc.{args.kind}').read_text()
    old=path.read_text()
    new=configure(old,template,args.auxiliary,args.legacy)
    backup.write_text(old)
    path.write_text(new)
    print(f'Configured {METHOD if not args.legacy else "legacy_surface"}: {path}')

if __name__=='__main__':
    main()
