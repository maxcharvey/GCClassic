#ifndef BRC_COUNTRY_BRIDGE_H
#define BRC_COUNTRY_BRIDGE_H
#define BRC_BRIDGE_LEVELS 128
#define BRC_BRIDGE_FAMILIES 7
#define BRC_BRIDGE_ORIGINS 4
enum brc_bridge_status { BRC_BRIDGE_OK, BRC_BRIDGE_INVALID,
 BRC_BRIDGE_PROVENANCE, BRC_BRIDGE_PARENT, BRC_BRIDGE_MAP,
 BRC_BRIDGE_KERNEL, BRC_BRIDGE_CALLER, BRC_BRIDGE_RESOURCE };
/* ABI1 is deliberately restricted to qualified first-event units2 fixtures.
   Level1 is bottom, arrays have Fortran contiguous level stride. */
struct brc_bridge_family {
 int species_id[5], map_advect[5], hco_id[5], safe;
 double mw, q[5][128], origin[4][128], emission[5], loss[5], bottom;
};
struct brc_bridge_column {
 int abi, n, units, provenance, step, date, clock, level_order;
 double area, dt, airmw;
 /* Exact archived ratio only; future runtime tmp1 has a separate contract. */
 long double coefficient;
 double air[128], cc[128], ze[128], term[128];
 struct brc_bridge_family family[7];
};
struct brc_bridge_receipt {
 /* accepted_families counts private staged families, never partial commits. */
 int status, family, detail, accepted_families;
 double max_additivity, max_budget;
};
/* destination layout (128,4,7), unused levels retained. Receipt may change on
   refusal; destination never does. Parent/input arrays are read-only. */
int brc_country_bridge(const struct brc_bridge_column *, double *,
 struct brc_bridge_receipt *);
#endif
