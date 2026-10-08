#include "country_bridge.h"
#include "signed_cg_pbl_kernel.h"
#include "pressure_cg_incoming.h"
#include "guarded_entropy.h"
#include <float.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
static long double relative(long double x,long double y){
 return y==0?(x==0?0:INFINITY):fabsl(x-y)/fabsl(y);
}
/* Preserve the actual binary64 operations, even on excess-precision hosts. */
static double native(double x){volatile double y=x;return y;}
static int refuse(struct brc_bridge_receipt *r,int s,int d){r->status=s;r->detail=d;return s;}
static int overlap(const void *a,size_t na,const void *b,size_t nb){
 uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
 return x<=y?y-x<na:x-y<nb;
}
int brc_country_bridge(const struct brc_bridge_column *v,double *destination,
 struct brc_bridge_receipt *r){
 const size_t outsize=7*4*128*sizeof(double);
 if(!r)return BRC_BRIDGE_INVALID;
 /* Aliasing the receipt must not mutate a caller's destination or parents. */
 if((v&&overlap(r,sizeof *r,v,sizeof *v))||
    (destination&&overlap(r,sizeof *r,destination,outsize)))return BRC_BRIDGE_INVALID;
 memset(r,0,sizeof *r);r->family=-1;
 if(!v||!destination||overlap(v,sizeof *v,destination,outsize)||
    v->abi!=1||v->n<2||v->n>128||sizeof(double)!=8||DBL_MANT_DIG!=53||
    LDBL_MANT_DIG!=64||LDBL_MAX_EXP!=16384)return refuse(r,BRC_BRIDGE_INVALID,0);
 if(v->units!=2||v->provenance!=1||v->step!=1||v->date!=20180801||
    v->clock!=0||v->level_order!=1)return refuse(r,BRC_BRIDGE_PROVENANCE,0);
 if(!isfinite(v->area)||v->area<=0||!isfinite(v->dt)||v->dt<=0||
    v->airmw!=28.9644||!isfinite(v->coefficient)||v->coefficient<0)
  return refuse(r,BRC_BRIDGE_INVALID,1);
 for(int k=0;k<v->n;k++)if(!isfinite(v->air[k])||v->air[k]<=0||
   !isfinite(v->cc[k])||!isfinite(v->ze[k])||!isfinite(v->term[k]))
  return refuse(r,BRC_BRIDGE_INVALID,2);
 /* Validate every namespace independently; coincident IDs are not a mapping. */
 for(int f=0;f<7;f++)for(int o=0;o<5;o++){
  const struct brc_bridge_family *p=&v->family[f];
  if(p->species_id[o]<=0||p->map_advect[o]<=0||p->hco_id[o]<0)
   return refuse(r,BRC_BRIDGE_MAP,0);
  for(int g=0;g<=f;g++)for(int t=0;t<5;t++)if(g<f||t<o){
   const struct brc_bridge_family *q=&v->family[g];
   if(p->species_id[o]==q->species_id[t]||p->map_advect[o]==q->map_advect[t]||
      (p->hco_id[o]>0&&p->hco_id[o]==q->hco_id[t]))return refuse(r,BRC_BRIDGE_MAP,1);
  }
 }
 double trial[7*4*128];memcpy(trial,destination,outsize);
 struct scp_receipt *full=malloc(sizeof *full);
 if(!full)return refuse(r,BRC_BRIDGE_RESOURCE,0);
 int status=BRC_BRIDGE_OK;
 const int n=v->n;
 const long double integration=(long double)v->area*v->dt;
 if(!isfinite(integration)||integration<=0){free(full);return refuse(r,BRC_BRIDGE_INVALID,3);}
 for(int f=0;f<7;f++){
  r->family=f;const struct brc_bridge_family *p=&v->family[f];
  long double air[128],cc[128],ze[128],term[128],before[128],approved[128];
  long double H[128],T[128*128],G[128*128],initial[128*4],rows[128],out[128*4];
  long double targets[4]={0},emission[4],loss[4],e=0,d=0,total=0,target_total=0;
  struct pc_receipt pc={0};struct pic_receipt pic={0};
  if(p->safe!=1||p->mw!=(f<2?150.0:12.01)||!isfinite(p->bottom)){
   status=refuse(r,BRC_BRIDGE_PARENT,0);break;
  }
  for(int o=0;o<5;o++)if(!isfinite(p->emission[o])||p->emission[o]<0||
     !isfinite(p->loss[o])||p->loss[o]<0){status=refuse(r,BRC_BRIDGE_INVALID,4);break;}
  if(status)break;
  for(int o=0;o<4;o++){
   emission[o]=(long double)p->emission[o+1]*integration;
   loss[o]=(long double)p->loss[o+1]*integration;e+=emission[o];d+=loss[o];
   double target=0;
   /* Literal archived constructor iterates native top to bottom. */
   for(int j=n-1;j>=0;j--)target=native(target+native(p->origin[o][j]*v->air[j]));
   double net=native(p->emission[o+1]-p->loss[o+1]);
   target=native(target+native(native(net*v->area)*v->dt));
   targets[o]=target;target_total+=targets[o];
   if(!isfinite(target)||target<0){status=refuse(r,BRC_BRIDGE_INVALID,5);break;}
  }
  if(status)break;
  if(relative(e,(long double)p->emission[0]*integration)>5e-12L||
     relative(d,(long double)p->loss[0]*integration)>5e-12L){status=refuse(r,BRC_BRIDGE_CALLER,0);break;}
  for(int j=0;j<n;j++){
   const int k=n-1-j;air[j]=v->air[k];cc[j]=v->cc[k];ze[j]=v->ze[k];term[j]=v->term[k];
   for(int s=0;s<5;s++)if(!isfinite(p->q[s][k])||p->q[s][k]<0){status=refuse(r,BRC_BRIDGE_PARENT,1);break;}
   if(status)break;
   if(p->q[2][k]!=p->q[3][k]){status=refuse(r,BRC_BRIDGE_PARENT,2);break;}
   before[j]=p->q[0][k];approved[j]=p->q[1][k];rows[j]=(long double)p->q[4][k]*air[j];total+=rows[j];
   long double sum=0;
   for(int o=0;o<4;o++){
    if(!isfinite(p->origin[o][k])||p->origin[o][k]<0){status=refuse(r,BRC_BRIDGE_INVALID,6);break;}
    initial[j*4+o]=(long double)p->origin[o][k]*air[j];sum+=initial[j*4+o];
   }
   if(status)break;
   if(relative(sum,before[j]*air[j])>1e-12L){status=refuse(r,BRC_BRIDGE_CALLER,1);break;}
  }
  if(status)break;
  if(relative(total,target_total)>1e-12L){status=refuse(r,BRC_BRIDGE_CALLER,2);break;}
  int cs=pressure_cg_incoming(n,cc,ze,term,before,approved,H,T,G,&pc,&pic);
  if(cs!=PC_OK){status=refuse(r,BRC_BRIDGE_KERNEL,100+cs);break;}
  for(int j=0;j<n;j++){
   long double raw=G[j*n+n-1]*p->bottom;
   for(int k=0;k<n;k++)raw+=G[j*n+k]*approved[k];
   if(!isfinite(raw)||relative(raw,p->q[2][n-1-j])>5e-12L){status=refuse(r,BRC_BRIDGE_PARENT,3);break;}
  }
  if(status)break;
  int ss=signed_cg_pbl_kernel(n,air,G,T,initial,emission,loss,
    (long double)v->coefficient/integration,rows,targets,guarded_entropy,out,full);
  if(ss!=SP_OK){status=refuse(r,BRC_BRIDGE_KERNEL,ss);break;}
  for(int j=0;j<n;j++){
   long double rhs=0;for(int t=0;t<full->coupling.donors;t++)rhs+=full->rhs[j*SP_LIMIT+t];
   if(relative(rhs,approved[j]+(j==n-1?p->bottom:0))>5e-12L||
      relative(full->coupling.prior_rows[j]/air[j],p->q[2][n-1-j])>5e-12L){status=refuse(r,BRC_BRIDGE_PARENT,4);break;}
   long double sum=0;
   for(int o=0;o<4;o++){
    double value=(double)(out[j*4+o]/air[j]);
    if(!isfinite(value)||value<0||(out[j*4+o]>0&&value==0)){
     status=refuse(r,BRC_BRIDGE_CALLER,3);break;
    }
    trial[(f*4+o)*128+n-1-j]=value;sum+=value;
   }
   if(status)break;
   long double err=relative(sum,p->q[4][n-1-j]);
   if(err>r->max_additivity)r->max_additivity=(double)err;
   if(err>5e-12L){status=refuse(r,BRC_BRIDGE_CALLER,4);break;}
  }
  if(status)break;
  for(int o=0;o<4;o++){
   long double sum=0;for(int k=0;k<n;k++)sum+=(long double)trial[(f*4+o)*128+k]*v->air[k];
   long double err=relative(sum,targets[o]);if(err>r->max_budget)r->max_budget=(double)err;
   if(err>5e-12L){status=refuse(r,BRC_BRIDGE_CALLER,5);break;}
  }
  if(status)break;
  r->accepted_families++;
 }
 free(full);
 if(status)return status;
 memcpy(destination,trial,outsize);r->family=-1;r->status=BRC_BRIDGE_OK;
 return BRC_BRIDGE_OK;
}
