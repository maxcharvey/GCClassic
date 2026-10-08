#include "country_pbl.h"
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
static long double relative(long double x,long double y){return y==0?(x==0?0:INFINITY):fabsl(x-y)/fabsl(y);}
static int fail(struct acp_receipt *r,int s){r->status=s;return s;}
static int overlap(const void *a,size_t na,const void *b,size_t nb){
 uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
 return x<=y?y-x<na:x-y<nb;
}
static int aliased(int n,int no,int families,const long double *air,const long double *green,
 const long double *transfer,const long double *initial,const long double *emissions,
 const long double *losses,const long double *alpha,const long double *rows,
 const long double *targets,long double *output,struct acp_receipt *r){
 const void *inputs[]={air,green,transfer,initial,emissions,losses,alpha,rows,targets};
 size_t lengths[]={(size_t)n,(size_t)families*n*n,(size_t)families*n*n,(size_t)families*n*no,(size_t)families*no,(size_t)families*no,(size_t)families,(size_t)families*n,(size_t)families*no};
 size_t outbytes=(size_t)families*n*no*sizeof(long double);
 if(overlap(r,sizeof *r,output,outbytes))return 1;
 for(int i=0;i<9;i++)if(overlap(r,sizeof *r,inputs[i],lengths[i]*sizeof(long double))||overlap(output,outbytes,inputs[i],lengths[i]*sizeof(long double)))return 1;
 return 0;
}
/* Bounds n<=128,no<=244 make every product below SIZE_MAX on supported ABI. */
int country_pbl(int n,int no,const long double *air,const long double *green,
 const long double *transfer,const long double *initial,const long double *emissions,
 const long double *losses,long double alpha,const long double *rows,
 const long double *targets,acp_solver solver,size_t limit,long double *output,
 struct acp_receipt *r){
 if(!r)return ACP_INVALID;
 if(n<2||n>128||no<1||no>244||!air||!green||!transfer||!initial||!emissions||!losses||!rows||!targets||!solver||!output||!isfinite(alpha)||alpha<0)return ACP_INVALID;
 if(aliased(n,no,1,air,green,transfer,initial,emissions,losses,&alpha,rows,targets,output,r))return ACP_INVALID;
 memset(r,0,sizeof *r);r->status=ACP_INVALID;r->levels=n;r->origins=no;
 if(no==244&&emissions[243]!=0)return fail(r,ACP_INVALID);
 size_t maxdonors=(size_t)(n+1)*no,edges=(size_t)n*maxdonors,stocks=(size_t)n*no;
 if(edges>SIZE_MAX/(3*sizeof(long double))||stocks>SIZE_MAX/sizeof(long double)||maxdonors>SIZE_MAX/(sizeof(long double)+3*sizeof(int)))return fail(r,ACP_CAPACITY);
 size_t bytes=3*edges*sizeof(long double)+stocks*sizeof(long double)+maxdonors*(sizeof(long double)+3*sizeof(int));
 r->workspace_bytes=bytes;
 if(bytes>limit)return fail(r,ACP_CAPACITY);
 long double *rhs=calloc(edges,sizeof *rhs),*prior=calloc(edges,sizeof *prior),*plan=calloc(edges,sizeof *plan),*trial=calloc(stocks,sizeof *trial),*columns=calloc(maxdonors,sizeof *columns);
 int *origin=calloc(maxdonors,sizeof *origin),*layer=calloc(maxdonors,sizeof *layer),*source=calloc(maxdonors,sizeof *source);
 int status=ACP_RESOURCE;
 if(!rhs||!prior||!plan||!trial||!columns||!origin||!layer||!source)goto cleanup;
 status=ACP_INVALID;int forcing=0;
 long double expected[244]={0},returned[244]={0};
 for(int o=0;o<no;o++){
  if(!isfinite(emissions[o])||emissions[o]<0||!isfinite(losses[o])||losses[o]<0||!isfinite(targets[o])||targets[o]<0)goto cleanup;
  if(emissions[o]>0||losses[o]>0)forcing=1;
 }
 if(forcing&&alpha==0){status=ACP_ZERO_SUPPORT;goto cleanup;}
 for(int j=0;j<n;j++){
  if(!isfinite(air[j])||air[j]<=0||!isfinite(rows[j])||rows[j]<0)goto cleanup;
  for(int d=0;d<n;d++)if(!isfinite(green[j*n+d])||green[j*n+d]<0||!isfinite(transfer[j*n+d])||transfer[j*n+d]<0)goto cleanup;
  for(int o=0;o<no;o++)if(!isfinite(initial[j*no+o])||initial[j*no+o]<0)goto cleanup;
 }
 for(int l=0;l<n;l++)for(int o=0;o<no;o++){
  long double stock=initial[l*no+o],mass=stock,q=stock/air[l],native[128],native_total=0;
  if(!isfinite(q))goto cleanup;
  if(stock>0&&q==0){status=ACP_UNDERFLOW;goto cleanup;}
  long double removal=0;
  if(l==n-1){
   if(losses[o]>stock){status=ACP_OVERDRAFT;goto cleanup;}
   mass-=losses[o];removal=alpha*losses[o];
   if(!isfinite(removal))goto cleanup;
   if(losses[o]>0&&removal==0){status=ACP_UNDERFLOW;goto cleanup;}
  }
  for(int k=0;k<n;k++){
   native[k]=q*transfer[k*n+l];
   if(!isfinite(native[k]))goto cleanup;
   if(q>0&&transfer[k*n+l]>0&&native[k]==0){status=ACP_UNDERFLOW;goto cleanup;}
   if(k==n-1)native[k]-=removal;
   if(!isfinite(native[k]))goto cleanup;
   if(native[k]<0){status=ACP_NEGATIVE_RHS;goto cleanup;}
   native_total+=native[k];
  }
  if(!isfinite(native_total))goto cleanup;
  if((mass==0)!=(native_total==0)){status=ACP_ZERO_SUPPORT;goto cleanup;}
  expected[o]+=mass;if(!isfinite(expected[o]))goto cleanup;
  if(mass==0)continue;
  int d=r->donors++;columns[d]=mass;origin[d]=o;layer[d]=l;
  for(int k=0;k<n;k++)rhs[k*maxdonors+d]=native[k];
 }
 for(int o=0;o<no;o++){
  expected[o]+=emissions[o];if(!isfinite(expected[o]))goto cleanup;
  if(relative(expected[o],targets[o])>5e-12L){status=ACP_TARGET;goto cleanup;}
  if(emissions[o]==0)continue;
  int d=r->donors++;columns[d]=emissions[o];origin[d]=o;layer[d]=n-1;source[d]=1;
  long double q=alpha*emissions[o];if(!isfinite(q))goto cleanup;
  if(q==0){status=ACP_UNDERFLOW;goto cleanup;}
  rhs[(n-1)*maxdonors+d]=q;
 }
 if(r->donors==0){
  for(int j=0;j<n;j++)if(rows[j]!=0){status=ACP_TARGET;goto cleanup;}
  memcpy(output,trial,stocks*sizeof *trial);status=ACP_OK;goto cleanup;
 }
 for(int j=0;j<n;j++)for(int d=0;d<r->donors;d++){
  long double response=0;
  for(int k=0;k<n;k++){
   long double q=rhs[k*maxdonors+d],product=green[j*n+k]*q;
   if(!isfinite(product))goto cleanup;
   if(green[j*n+k]>0&&q>0&&product==0){status=ACP_UNDERFLOW;goto cleanup;}
   response+=product;
  }
  long double p=response*air[j];if(!isfinite(response)||!isfinite(p))goto cleanup;
  if(response>0&&p==0){status=ACP_UNDERFLOW;goto cleanup;}
  prior[j*r->donors+d]=p;
 }
 struct acp_solver_receipt sr={0,0};
 struct acp_donors metadata={origin,layer,source};
 r->solver_status=solver(n,r->donors,prior,rows,columns,plan,&metadata,&sr);
 if(r->solver_status!=0){status=ACP_SOLVER;goto cleanup;}
 if(sr.rows!=n||sr.columns!=r->donors){status=ACP_OUTPUT;goto cleanup;}
 for(int d=0;d<r->donors;d++){
  long double sum=0;
  for(int i=0;i<n;i++)sum+=plan[i*r->donors+d];
  if(!isfinite(sum)){status=ACP_OUTPUT;goto cleanup;}
  long double error=relative(sum,columns[d]);
  if(error>r->column_error)r->column_error=error;
 }
 long double total=0,target_total=0;
 for(int i=0;i<n;i++){
  long double row=0;
  for(int d=0;d<r->donors;d++){
   int v=i*r->donors+d,o=origin[d];long double p=plan[v];
   if(!isfinite(p)||p<0||(prior[v]==0&&p!=0)){status=ACP_OUTPUT;goto cleanup;}
   if(prior[v]>0&&rows[i]>0&&p==0){status=ACP_UNDERFLOW;goto cleanup;}
   trial[i*no+o]+=p;returned[o]+=p;row+=p;
  }
  long double error=relative(row,rows[i]);if(error>r->row_error)r->row_error=error;
  for(int o=0;o<no;o++)if(!isfinite(trial[i*no+o])){status=ACP_OUTPUT;goto cleanup;}
  total+=row;target_total+=rows[i];
 }
 for(int o=0;o<no;o++){long double error=relative(returned[o],targets[o]);if(error>r->origin_error)r->origin_error=error;}
 r->total_error=relative(total,target_total);
 if(!isfinite(total)||!isfinite(target_total)||r->row_error>5e-14L||r->column_error>5e-14L||r->origin_error>5e-12L||r->total_error>2e-14L){status=ACP_OUTPUT;goto cleanup;}
 memcpy(output,trial,stocks*sizeof *trial);status=ACP_OK;
cleanup:
 free(rhs);free(prior);free(plan);free(trial);free(columns);free(origin);free(layer);free(source);
 return fail(r,status);
}
int country_pbl_bundle(int n,int no,const long double *air,const long double *green,
 const long double *transfer,const long double *initial,const long double *emissions,
 const long double *losses,const long double *alpha,const long double *rows,
 const long double *targets,acp_solver solver,size_t limit,long double *output,
 struct acp_receipt *r){
 if(!r)return ACP_INVALID;
 if(n<2||n>128||no<1||no>244||!air||!green||!transfer||!initial||!emissions||!losses||!alpha||!rows||!targets||!solver||!output)return ACP_INVALID;
 if(aliased(n,no,7,air,green,transfer,initial,emissions,losses,alpha,rows,targets,output,r))return ACP_INVALID;
 memset(r,0,sizeof *r);r->status=ACP_INVALID;
 size_t stocks=(size_t)n*no,bytes=7*stocks*sizeof(long double);
 if(bytes>limit)return fail(r,ACP_CAPACITY);
 long double *trial=malloc(bytes);if(!trial)return fail(r,ACP_RESOURCE);
 int status=ACP_OK;
 for(int f=0;f<7;f++){
  status=country_pbl(n,no,air,green+f*n*n,transfer+f*n*n,initial+f*stocks,emissions+f*no,losses+f*no,alpha[f],rows+f*n,targets+f*no,solver,limit-bytes,trial+f*stocks,r);
  if(status)break;
 }
 if(!status)memcpy(output,trial,bytes);
 free(trial);return fail(r,status);
}
