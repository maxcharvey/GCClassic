#!/usr/bin/env bash
# Configuration parser regression: no model or Python required.
set -euo pipefail
if (($#!=1));then echo 'usage: test_configure_brc_origins.sh BASELINE_RUN_DIR' >&2;exit 2;fi
baseline=$1
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT
for name in hour day invalid gfas;do
 mkdir "$staging/$name"
 for file in species_database.yml geoschem_config.yml HEMCO_Config.rc HEMCO_Diagn.rc HISTORY.rc;do cp "$baseline/$file" "$staging/$name/$file";done
done
perl -0pi -e 's/start_date: \[\d{8}, \d{6}\]/start_date: [20180902, 000000]/;s/end_date: \[\d{8}, \d{6}\]/end_date: [20180902, 010000]/' "$staging/hour/geoschem_config.yml"
perl "$script_dir/configure_brc_origins.pl" --run-dir "$staging/hour" --short-test-hourly
rg -q 'FINN_ORIGINS.20180902.nc4 .* 2018/9/2/0 ' "$staging/hour/HEMCO_Config.rc"
rg -q 'BrCOriginConc.frequency: 00000000 010000' "$staging/hour/HISTORY.rc"
perl -0777 -e 'my $text=<>;die "Native CO/SOAP inheritance chain split\n" unless $text=~/^165 FINNV25_INJECT_CO[^\n]*\n165 FINNV25_INJECT_SOAP - - - - - - /m;die "Tags missing safe terminal anchor\n" unless $text=~/^165 FINNV25_INJECT_MACR[^\n]*\n# BRC_ORIGIN_PROTOTYPE:[^\n]*\n165 FINNV25_TAG_/m;' "$staging/hour/HEMCO_Config.rc"
if perl "$script_dir/configure_brc_origins.pl" --run-dir "$staging/hour" > "$staging/repeated.log" 2>&1;then exit 1;fi
perl -0pi -e 's/start_date: \[\d{8}, \d{6}\]/start_date: [20181231, 000000]/;s/end_date: \[\d{8}, \d{6}\]/end_date: [20190101, 000000]/' "$staging/day/geoschem_config.yml"
perl "$script_dir/configure_brc_origins.pl" --run-dir "$staging/day"
rg -q 'FINN_ORIGINS.20181231.nc4 .* 2018/12/31/0 ' "$staging/day/HEMCO_Config.rc"
rg -q 'BrCOriginConc.frequency: 00000001 000000' "$staging/day/HISTORY.rc"
perl -0pi -e 's/end_date: \[\d{8}, \d{6}\]/end_date: [20180802, 010000]/' "$staging/invalid/geoschem_config.yml"
(cd "$staging/invalid" && sha256sum *.yml *.rc) > "$staging/before"
if perl "$script_dir/configure_brc_origins.pl" --run-dir "$staging/invalid" > "$staging/invalid.log" 2>&1;then exit 1;fi
(cd "$staging/invalid" && sha256sum *.yml *.rc) > "$staging/after"
cmp "$staging/before" "$staging/after"
[[ ! -e "$staging/invalid/HISTORY.rc.pre-origins" ]]
perl -0pi -e 's/(--> FINNV25_GFAS_PROFILE\s*:\s*)false/${1}true/' "$staging/gfas/HEMCO_Config.rc"
rg -q 'FINNV25_GFAS_PROFILE.*true' "$staging/gfas/HEMCO_Config.rc"
(cd "$staging/gfas" && sha256sum *.yml *.rc) > "$staging/gfas.before"
if perl "$script_dir/configure_brc_origins.pl" --run-dir "$staging/gfas" > "$staging/gfas.log" 2>&1;then exit 1;fi
rg -q 'GFAS profile backend is not implemented' "$staging/gfas.log"
(cd "$staging/gfas" && sha256sum *.yml *.rc) > "$staging/gfas.after"
cmp "$staging/gfas.before" "$staging/gfas.after"
[[ ! -e "$staging/gfas/HISTORY.rc.pre-origins" ]]
echo 'PASS native CO/SOAP inheritance, safe terminal insertion, date-derived native input, year rollover, hourly/daily intervals, repeated staging, atomic invalid-period and unsupported GFAS-profile refusal'
