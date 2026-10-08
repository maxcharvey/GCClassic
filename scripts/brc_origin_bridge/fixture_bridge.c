/* Frozen decoders are compile-time prerequisites, never copied/rewritten. */
#define main qualified_mixing_reader_main
#include "baseline_mixing_reader.c"
#undef main
#include <ctype.h>
#include "signed_budget_decoder.h"
#include "country_bridge.h"
#include "guarded_entropy.h"
#define LIM 128
static Budget native_budget;
static int select_lat,select_column,select_species=-1,first=2;
static struct brc_bridge_column column;
static int emit,solver_family;
void brc_iso_probe(const struct brc_bridge_column *,double *,struct brc_bridge_receipt *,int *,size_t *);
int __real_guarded_entropy(int,int,const long double *,const long double *,const long double *,long double *,struct nn_receipt *);
int __wrap_guarded_entropy(int nr,int nc,const long double *p,const long double *rows,
 const long double *cols,long double *out,struct nn_receipt *r){
 int s=__real_guarded_entropy(nr,nc,p,rows,cols,out,r);
 if(emit){
  printf("SOLVER %d %d %d %d %La %La %La\n",solver_family,nr,nc,s,r->marginal.row_error,r->marginal.column_error,r->marginal.total_mismatch);
  printf("OBJECTIVE %d %La\n",solver_family,r->marginal.objective);
  for(int i=0;i<nr;i++)printf("ROW %d %d %La\n",solver_family,i,rows[i]);
  for(int j=0;j<nc;j++)printf("DONOR %d %d %La\n",solver_family,j,cols[j]);
  for(int i=0;i<nr;i++)for(int j=0;j<nc;j++)printf("PLAN %d %d %d %La %La %.21Lg %.21Lg\n",solver_family,i,j,p[i*nc+j],out[i*nc+j],p[i*nc+j],out[i*nc+j]);
  solver_family++;
 }
 return s;
}
static void negative(const char *name,struct brc_bridge_column *bad,int status,int detail){
 double output[7*4*128],saved[7*4*128];for(int k=0;k<7*4*128;k++)output[k]=-123.25;
 memcpy(saved,output,sizeof output);struct brc_bridge_receipt receipt;
 int s=brc_country_bridge(bad,output,&receipt);
 if(s!=status||(detail>=0&&receipt.detail!=detail)||memcmp(saved,output,sizeof output)){
  fprintf(stderr,"NEGATIVE_FAIL %s status=%d detail=%d family=%d\n",name,s,receipt.detail,receipt.family);fail("atomic negative");
 }
 printf("REFUSAL %s %d %d %d %d\n",name,s,receipt.detail,receipt.family,receipt.accepted_families);
}
static void analyze(const char *file,int step,int lat,int i,int nx,int nz,int top,size_t cell,
 double dt,const double *ad,const double *area,const double *flux,double *const q[6],
 const double *cc,const double *ze,const double *term,const double *bot,const double *num,const double *den,
 const uint32_t *safe,int species){
 (void)den;
 if(!((lat==19&&i+1==46)||(lat==28&&i+1==131)))return;
 if(top!=0||nz!=47||step!=1||bytes!=8)fail("fixture geometry");
 const int b=species*5;const size_t gv=(size_t)(lat-1)*nx+i;
 if(species==0){
  memset(&column,0,sizeof column);column.abi=1;column.n=nz;column.units=2;column.provenance=1;
  column.step=step;column.date=native_budget.h[7];column.clock=native_budget.h[8];column.level_order=1;
  column.area=area[i];column.dt=dt;column.airmw=native_budget.airmw;
  int chosen=-1;long double largest=0;
  for(int s=0;s<35;s++){
   long double e=native_budget.field[1][s*native_budget.cells+gv],d=native_budget.field[2][s*native_budget.cells+gv];
   long double net=flux[(size_t)s*nx+i],scale=fabsl(e)+fabsl(d);
   if(net!=0&&scale>0&&fabsl(e-d)>=.01L*scale&&fabsl(net)>largest){chosen=s;largest=fabsl(net);}
  }
  if(chosen<0)fail("unobservable fixture coefficient");
  /* Preserve original long-double ratio across the ISO ABI. */
  column.coefficient=(long double)bot[(size_t)chosen*nx+i]/flux[(size_t)chosen*nx+i];
  for(int j=0;j<nz;j++){
   size_t v=(size_t)j*nx+i;int k=nz-1-j;
   column.air[k]=ad[v];column.cc[k]=cc[v];column.ze[k]=ze[v];column.term[k]=term[v];
  }
 }
 struct brc_bridge_family *p=&column.family[species];p->safe=safe[(size_t)b*nx+i];p->mw=native_budget.mw[b];p->bottom=bot[(size_t)b*nx+i];
 for(int o=0;o<5;o++){
  const int sp=b+o;size_t bv=(size_t)sp*native_budget.cells+gv;
  p->species_id[o]=native_budget.map[sp][0];p->map_advect[o]=native_budget.map[sp][1];p->hco_id[o]=native_budget.map[sp][2];
  if(native_budget.mw[sp]!=p->mw)fail("origin molecular weight");
  p->emission[o]=native_budget.field[1][bv];p->loss[o]=native_budget.field[2][bv];
  double constant=fp(native_budget.airmw/native_budget.mw[sp]);
  double dry=fp(native_budget.field[0][bv]/constant),acting=q[0][(size_t)sp*cell+(size_t)(nz-1)*nx+i];
  double net=fp(p->emission[o]-p->loss[o]),actual=flux[(size_t)sp*nx+i];
  if(memcmp(&dry,&acting,8)||memcmp(&net,&actual,8))fail("original acting stock/net binding");
  if(o){
   double target=0;for(int j=0;j<nz;j++)target=fp(target+fp(q[0][(size_t)sp*cell+(size_t)j*nx+i]*ad[(size_t)j*nx+i]));
   target=fp(target+fp(fp(net*area[i])*dt));
   if(memcmp(&target,&num[(size_t)sp*nx+i],8))fail("original causal target comparison");
  }
 }
 for(int j=0;j<nz;j++){
  size_t v=(size_t)j*nx+i;int k=nz-1-j;
  const int phases[5]={0,2,3,4,5};
  for(int s=0;s<5;s++)p->q[s][k]=q[phases[s]][(size_t)b*cell+v];
  for(int o=0;o<4;o++)p->origin[o][k]=q[0][(size_t)(b+o+1)*cell+v];
 }
 if(species!=6)return;
 printf("COLUMN %s %d %d\n",file,lat,i+1);
 double output[7*4*128];for(int k=0;k<7*4*128;k++)output[k]=-123.25;
 struct brc_bridge_column saved=column;struct brc_bridge_receipt r;
 emit=1;solver_family=0;int s=brc_country_bridge(&column,output,&r);emit=0;
 if(s!=0||solver_family!=7||memcmp(&saved,&column,sizeof column)){
  fprintf(stderr,"BRIDGE_FAIL status=%d detail=%d family=%d\n",s,r.detail,r.family);fail("bridge/original parent identity");
 }
 double iso_output[7*4*128];for(int k=0;k<7*4*128;k++)iso_output[k]=-123.25;
 struct brc_bridge_receipt iso_receipt;int iso_status;size_t sizes[3];
 brc_iso_probe(&column,iso_output,&iso_receipt,&iso_status,sizes);
 if(sizes[0]!=sizeof column||sizes[1]!=sizeof column.family[0]||sizes[2]!=sizeof r||
    iso_status!=0||memcmp(output,iso_output,sizeof output)||memcmp(&saved,&column,sizeof column))fail("Fortran ABI equivalence");
 printf("ISO_PASS %zu %zu %zu\n",sizes[0],sizes[1],sizes[2]);
 for(int f=0;f<7;f++)for(int o=0;o<4;o++)for(int k=0;k<128;k++){
  if(k>=nz&&output[(f*4+o)*128+k]!=-123.25)fail("unused level mutation");
  if(k<nz)printf("OUTPUT %d %d %d %a\n",f,o,k,output[(f*4+o)*128+k]);
 }
 printf("ACCEPT %d %.17g %.17g\n",r.accepted_families,r.max_additivity,r.max_budget);
 struct brc_bridge_column bad=column;
 bad.units=6;negative("native_units_unbound",&bad,BRC_BRIDGE_PROVENANCE,-1);
 bad=column;bad.provenance=2;negative("runtime_coefficient_unbound",&bad,BRC_BRIDGE_PROVENANCE,-1);
 bad=column;bad.n=129;negative("dimension",&bad,BRC_BRIDGE_INVALID,-1);
 bad=column;bad.air[0]=NAN;negative("nan_air",&bad,BRC_BRIDGE_INVALID,-1);
 bad=column;bad.family[6].safe=0;negative("late_unsafe_parent",&bad,BRC_BRIDGE_PARENT,0);
 bad=column;bad.family[6].q[3][0]=bad.family[6].q[2][0]+1;negative("late_clipping",&bad,BRC_BRIDGE_PARENT,2);
 bad=column;bad.family[6].origin[0][0]=-1;negative("late_negative_origin",&bad,BRC_BRIDGE_INVALID,-1);
 bad=column;bad.family[6].map_advect[4]=bad.family[0].map_advect[0];negative("duplicate_map",&bad,BRC_BRIDGE_MAP,1);
 bad=column;
 for(int o=0;o<4;o++){
  bad.family[6].emission[o+1]=bad.family[6].emission[0]/4;
  bad.family[6].loss[o+1]=bad.family[6].loss[0]/4;
  for(int k=0;k<nz;k++)bad.family[6].origin[o][k]=bad.family[6].q[0][k]/4;
 }
 negative("late_donor_capacity",&bad,BRC_BRIDGE_KERNEL,6);
 printf("COLUMN_PASS\n");
}
int main(int argc,char **argv){
 if(argc!=4)fail("usage GROSS MIX19 MIX28");
 native_budget=load_budget(argv[1]);
#include "native_signed_parse.inc"
