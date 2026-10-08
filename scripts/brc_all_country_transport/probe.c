#include "country_pbl.h"
#include "signed_cg_pbl_kernel.h"
#include <assert.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int mode,calls,fail_call,bad_output_call,allocation_failure;
static struct scp_receipt *legacy;
void *__real_calloc(size_t,size_t);
void *__wrap_calloc(size_t n,size_t s){if(allocation_failure){allocation_failure=0;return NULL;}return __real_calloc(n,s);}
static int old_solver(int nr,int nc,const long double *p,const long double *r,const long double *c,long double *out,struct nn_receipt *receipt){
 (void)r;(void)c;memset(receipt,0,sizeof *receipt);memcpy(out,p,(size_t)nr*nc*sizeof *out);return BC_OK;
}
static int solver(int nr,int nc,const long double *p,const long double *rows,const long double *cols,long double *out,const struct acp_donors *ids,struct acp_solver_receipt *receipt){
 calls++;receipt->rows=nr;receipt->columns=nc;
 if(fail_call==calls||mode==1)return 1;
 if(mode==10){
  assert(nr==legacy->coupling.n&&nc==legacy->coupling.donors);
  for(int d=0;d<nc;d++){
   assert(ids->origin[d]==legacy->coupling.origin[d]);
   assert(ids->layer[d]==legacy->coupling.layer[d]);
   assert(ids->is_source[d]==legacy->coupling.is_source[d]);
   assert(cols[d]==legacy->coupling.columns[d]);
  }
  for(int v=0;v<nr*nc;v++)assert(p[v]==legacy->coupling.prior[v]);
 }
 for(int d=0;d<nc;d++)assert(ids->origin[d]>=0&&ids->origin[d]<244&&ids->layer[d]>=0&&ids->layer[d]<nr&&(ids->is_source[d]==0||ids->is_source[d]==1));
 memcpy(out,p,(size_t)nr*nc*sizeof *out);
 if(bad_output_call==calls)out[nr*nc-1]=NAN;
 if(mode==2)receipt->columns++;
 if(mode==3)out[nr*nc-1]=NAN;
 if(mode==4)out[nr*nc-1]=-1;
 if(mode==5){for(int v=0;v<nr*nc;v++)if(p[v]==0){out[v]=1;break;}}
 if(mode==6){for(int v=nr*nc-1;v>=0;v--)if(p[v]>0){out[v]=0;break;}}
 if(mode==7){for(int v=0;v<nr*nc;v++)if(p[v]>0){out[v]*=2;break;}}
 /* Saved values support independent construction/output verification. */
 if(mode==20){
  printf("MATRIX %d %d\n",nr,nc);
  for(int i=0;i<nr;i++)printf("ROW %d %La\n",i,rows[i]);
  for(int d=0;d<nc;d++)printf("DONOR %d %d %d %d %La\n",d,ids->origin[d],ids->layer[d],ids->is_source[d],cols[d]);
  for(int i=0;i<nr;i++)for(int d=0;d<nc;d++)printf("PRIOR %d %d %La\n",i,d,p[i*nc+d]);
 }
 return 0;
}
static int no=244;
static long double air[2]={1,1},g[4]={1,0,0,1},t[4]={1,0,0,1};
static long double initial[488],emission[244],loss[244],rows[2],targets[244],output[488];
static struct acp_receipt receipt;
static const size_t limit=64*1024*1024;
static void fixture(int origins){
 no=origins;rows[0]=rows[1]=0;mode=0;calls=0;fail_call=0;bad_output_call=0;
 for(int o=0;o<no;o++){
  long double x=(long double)(o+1)/1024;
  if(o==no-1)x=scalbnl(1,-1000);
  initial[o]=x;initial[no+o]=2*x;emission[o]=o==no-1?0:x/2;loss[o]=x/4;
  targets[o]=(initial[o]+(initial[no+o]-loss[o]))+emission[o];
  rows[0]+=x;rows[1]+=2*x-loss[o]+emission[o];
 }
 for(int v=0;v<2*no;v++)output[v]=-77;
}
static int run(size_t memory){return country_pbl(2,no,air,g,t,initial,emission,loss,1,rows,targets,solver,memory,output,&receipt);}
static void check_refusal(const char *name,int expected){
 int s=run(limit);assert(s==expected);for(int v=0;v<2*no;v++)assert(output[v]==-77);
 printf("REFUSAL %s status=%d atomic=PASS\n",name,s);
}
int main(void){
 assert(LDBL_MANT_DIG==64&&LDBL_MAX_EXP==16384);
 legacy=calloc(1,sizeof *legacy);assert(legacy);
 fixture(4);assert(signed_cg_pbl_kernel(2,air,g,t,initial,emission,loss,1,rows,targets,old_solver,output,legacy)==SP_OK);
 long double saved[8];memcpy(saved,output,sizeof saved);for(int v=0;v<8;v++)output[v]=-77;
 mode=10;assert(run(limit)==ACP_OK);for(int v=0;v<8;v++)assert(output[v]==saved[v]);
 puts("PASS legacy_four_origin_donors_prior_losses_output_exact");free(legacy);legacy=NULL;
 fixture(244);mode=20;assert(run(limit)==ACP_OK);assert(receipt.donors==731);
 for(int o=0;o<no;o++){
  assert(output[o]==initial[o]);assert(output[no+o]==(initial[no+o]-loss[o])+emission[o]);
  printf("STOCK %d %La %La %La %La %La %La\n",o,initial[o],initial[no+o],emission[o],loss[o],output[o],output[no+o]);
 }
 printf("PASS all_country donors=%d workspace_bytes=%zu row=%La column=%La origin=%La total=%La\n",receipt.donors,receipt.workspace_bytes,receipt.row_error,receipt.column_error,receipt.origin_error,receipt.total_error);
 for(int bad=1;bad<=7;bad++){
  fixture(244);mode=bad;
  check_refusal((const char *[]) {"","callback_failure","callback_dimensions","callback_nan","callback_negative","callback_zero_support","callback_lost_positive","callback_bad_margin"}[bad],bad==1?ACP_SOLVER:bad==6?ACP_UNDERFLOW:ACP_OUTPUT);
 }
 fixture(244);assert(run(1)==ACP_CAPACITY);for(int v=0;v<488;v++)assert(output[v]==-77);puts("REFUSAL workspace_limit atomic=PASS");
 fixture(244);allocation_failure=1;check_refusal("allocation",ACP_RESOURCE);
 fixture(244);loss[243]=initial[244+243]*2;check_refusal("own_overdraft",ACP_OVERDRAFT);
 fixture(244);loss[243]=initial[244+243]/2;t[3]=0.25L;check_refusal("negative_native_rhs",ACP_NEGATIVE_RHS);t[3]=1;
 fixture(244);initial[243]=LDBL_MIN*LDBL_EPSILON;air[0]=LDBL_MAX;check_refusal("positive_underflow",ACP_UNDERFLOW);air[0]=1;
 fixture(244);targets[243]*=2;check_refusal("own_target",ACP_TARGET);
 fixture(244);initial[487]=NAN;check_refusal("late_nan",ACP_INVALID);
 fixture(244);emission[243]=1;check_refusal("UNT_new_source",ACP_INVALID);
 fixture(244);
 assert(country_pbl(2,no,air,g,t,initial,emission,loss,1,rows,targets,solver,limit,output,(struct acp_receipt *)output)==ACP_INVALID);
 for(int v=0;v<488;v++)assert(output[v]==-77);
 puts("REFUSAL receipt_alias atomic=PASS");
 long double saved_initial[488];memcpy(saved_initial,initial,sizeof initial);
 assert(country_pbl(2,no,air,g,t,initial,emission,loss,1,rows,targets,solver,limit,initial,&receipt)==ACP_INVALID);
 assert(memcmp(saved_initial,initial,sizeof initial)==0);
 puts("REFUSAL input_output_alias atomic=PASS");
 fixture(244);long double gi[28],ti[28],ii[3416],ee[1708],ll[1708],rr[14],tt[1708],aa[7],oo[3416];
 for(int f=0;f<7;f++){
  memcpy(gi+4*f,g,sizeof g);memcpy(ti+4*f,t,sizeof t);memcpy(ii+488*f,initial,sizeof initial);
  memcpy(ee+244*f,emission,sizeof emission);memcpy(ll+244*f,loss,sizeof loss);memcpy(rr+2*f,rows,sizeof rows);memcpy(tt+244*f,targets,sizeof targets);aa[f]=1;
 }
 for(int v=0;v<3416;v++)oo[v]=-77;
 assert(country_pbl_bundle(2,244,air,gi,ti,ii,ee,ll,aa,rr,tt,solver,limit,oo,&receipt)==ACP_OK);
 puts("PASS seven_family_bundle");
 for(int v=0;v<3416;v++)oo[v]=-77;
 calls=0;fail_call=7;
 assert(country_pbl_bundle(2,244,air,gi,ti,ii,ee,ll,aa,rr,tt,solver,limit,oo,&receipt)==ACP_SOLVER);
 for(int v=0;v<3416;v++)assert(oo[v]==-77);
 puts("REFUSAL seventh_family atomic=PASS");
 calls=0;fail_call=0;bad_output_call=7;
 assert(country_pbl_bundle(2,244,air,gi,ti,ii,ee,ll,aa,rr,tt,solver,limit,oo,&receipt)==ACP_OUTPUT);
 for(int v=0;v<3416;v++)assert(oo[v]==-77);
 puts("REFUSAL seventh_family_bad_output atomic=PASS");
 puts("PASS all_dynamic_constructor_controls; optimizer_and_live_NOT_QUALIFIED");return 0;
}
