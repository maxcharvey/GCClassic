"""Strict paired flight comparison after both per-case month integrity gates."""
from pathlib import Path
import sys, json, csv, datetime, hashlib
from workflow_common import ROOT, load, require, verify_hashes, sha
sys.path.insert(0, str(ROOT / 'analysis_tools'))
from compare_planeflight_profiles import compare, read_log, summarize
FIELDS = tuple('OCPI OCPO BCPI BCPO FSOAP FSOAS NPBRCPOA PBRCPOA DBRCPOA BRCSOA WTC FFOCPI FFOCPO CO'.split())
DATES = tuple('20180801,20180802,20180803,20180804,20180806,20180807,20180808,20180809,20180810,20180813,20180814,20180815,20180816,20180820,20180821,20180823,20180824,20180826,20180827,20180828'.split(','))

def main():
    left = ROOT / 'BRC_147_GFAS_FIXED30_L15_20260921'
    right = ROOT / 'BRC_148_GFAS_NATIVE3D_20260921'
    out = ROOT / 'august_analysis_20260922'
    if not not out.exists():
        raise ValueError('Do not overwrite existing analysis')
    for c in [left, right]:
        report = load(c / 'month_audit.json')
        require(report['status'] == 'PASS', 'Month audit failed')
        require(report['audit_script_sha256'] == sha(ROOT / 'audit_month_case.py'), 'Stale month audit script')
        verify_hashes(c, report['configuration_sha256'])
        verify_hashes(c, report['output_sha256'])
    reports = {}
    overall = {}
    for group, dates in [('all_flights', DATES), ('first_day', DATES[:1]), ('later_flights', DATES[1:])]:
        reports[group] = compare(left / 'OutputDir', right / 'OutputDir', left, right, FIELDS, tuple(range(200, 1101, 100)), dates)
        values = {f: {'left': [], 'right': [], 'paired_delta': []} for f in FIELDS}
        for date in dates:
            lhs = read_log(left / 'OutputDir' / ('plane.log.' + date), FIELDS, date)
            rhs = read_log(right / 'OutputDir' / ('plane.log.' + date), FIELDS, date)
            for key in lhs:
                for f in FIELDS:
                    values[f]['left'].append(lhs[key][f])
                    values[f]['right'].append(rhs[key][f])
                    values[f]['paired_delta'].append(rhs[key][f] - lhs[key][f])
        overall[group] = {f: {n: summarize(v) for n, v in groups.items()} for f, groups in values.items()}
    out.mkdir()
    for n, r in reports.items():
        (out / (n + '.json')).write_text(json.dumps(r, indent=2, allow_nan=False) + '\n')
    with (out / 'pressure_profiles.csv').open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['group', 'lower_hpa', 'upper_hpa', 'species', 'count', 'left_median', 'right_median', 'paired_delta_median', 'paired_delta_q25', 'paired_delta_q75', 'units'])
        for name, report in reports.items():
            for b in report['pressure_bins']:
                for species, v in b['fields'].items():
                    d = v['delta_14_8_minus_14_7']
                    writer.writerow([name, b['lower_hpa'], b['upper_hpa'], species, d['count'], v['left']['median'], v['right']['median'], d['median'], d['q25'], d['q75'], 'molec/cm3'])
    count = sum((v['matched_rows'] for v in reports['all_flights']['dates'].values()))
    summary = f'# August 2018 GFAS configuration comparison\n \n Mechanical paired flight-track coverage: PASS, {count} matched points across 20 dates. Full outputs passed the separate monthly integrity gates before this analysis. This is a 14.7 fixed 30%/15-level versus 14.8 native-variable-height comparison, so version and injection changes are confounded.\n \n `pressure_profiles.csv` contains pressure-binned species medians and paired 14.8-minus 14.7 difference quartiles in molecules/cm3. JSON files contain per-date counts, input/output hashes and excluded-pressure counts. `first_day.json` and `later_flights.json` separate startup from subsequent flights; this does not prove the initial-condition transient has vanished. August 26 21:40–21:53 UTC gap is preserved without interpolation.\n \n These are flight-track pressure profiles, not grid-column profiles. Both cases use 550 nm AOD diagnostics and 20-minute radiation calls. Original version-specific restart precision settings are retained. Organic-equivalent optics remain unqualified; no AAOD conversion, forcing interpretation, parameter promotion, or isolated model-version attribution is made. Review numerical tables and restart sensitivity before scientific conclusions.\n '
    summary += '\n## Paired concentration summaries\n\nAll units are molecules/cm3. Differences are paired 14.8 minus 14.7; the median paired difference need not equal the difference of medians. Overall summaries include all matched points; pressure-bin exclusions remain separately reported in the profile JSON.\n'
    for group in ['all_flights', 'first_day', 'later_flights']:
        summary += '\n### ' + group.replace('_', ' ') + '\n\n|Species|Points|14.7 median|14.8 median|Paired delta median|Delta Q25|Delta Q75|\n|---|---:|---:|---:|---:|---:|---:|\n'
        for f, v in overall[group].items():
            d = v['paired_delta']
            summary += f"|{f}|{d['count']}|{v['left']['median']:.5g}|{v['right']['median']:.5g}|{d['median']:.5g}|{d['q25']:.5g}|{d['q75']:.5g}|\n"
    (out / 'overall_species_summaries.json').write_text(json.dumps(overall, indent=2, allow_nan=False) + '\n')
    (out / 'SUMMARY.md').write_text(summary)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out / 'MANIFEST.json').write_text(json.dumps({'status': 'PASS', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sha256': manifest}, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'matched_points': count, 'output': str(out)}, indent=2))
if __name__ == '__main__':
    main()
