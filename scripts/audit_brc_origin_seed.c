/* Read-only independent verifier of cohort initialization and parent preservation.
   Run on a compute allocation: NEW_ORIGIN_RESTART ORIGINAL_PARENT_RESTART. */
#include <netcdf.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define OK(x) do{int e=(x);if(e){fprintf(stderr,"%s: %s\n",#x,nc_strerror(e));exit(2);}}while(0)
static double *read(int f,int v,size_t *n){
 int nd,ids[NC_MAX_VAR_DIMS];OK(nc_inq_var(f,v,NULL,NULL,&nd,ids,NULL));*n=1;
 for(int d=0;d<nd;d++){size_t len;OK(nc_inq_dimlen(f,ids[d],&len));*n*=len;}
 double *a=malloc(*n*sizeof(double));if(!a)exit(2);OK(nc_get_var_double(f,v,a));return a;
}
int main(int argc,char **argv){
 if(argc!=3)return 2;int a,b;OK(nc_open(argv[1],NC_NOWRITE,&a));OK(nc_open(argv[2],NC_NOWRITE,&b));
 const char *p[]={"FSOAP","FSOAS","BRCSOA","NPBRCPOA","WTC","PBRCPOA","DBRCPOA"};
 const char *o[]={"USA","CAN","ROW","UNT"};int na,nb;OK(nc_inq_nvars(a,&na));OK(nc_inq_nvars(b,&nb));
 if(na-nb!=28){fprintf(stderr,"Expected exactly28 added fields\n");return 1;}
 /* Compare every original numeric array exactly, including auxiliary fields. */
 int common=0;
 for(int v=0;v<nb;v++){
  char name[NC_MAX_NAME+1];nc_type type;OK(nc_inq_var(b,v,name,&type,NULL,NULL,NULL));
  if(type==NC_CHAR||type==NC_STRING)continue;
  int w;OK(nc_inq_varid(a,name,&w));size_t n,m;double *x=read(b,v,&n),*y=read(a,w,&m);
  if(n!=m)return 1;for(size_t i=0;i<n;i++)if(!isfinite(x[i])||x[i]!=y[i]){fprintf(stderr,"Parent change %s index%zu\n",name,i);return 1;}
  free(x);free(y);common++;
 }
 for(int s=0;s<7;s++){
  char name[96];int v;snprintf(name,sizeof(name),"SpeciesRst_%s",p[s]);OK(nc_inq_varid(a,name,&v));size_t n;double *parent=read(a,v,&n);
  for(int k=0;k<4;k++){
   snprintf(name,sizeof(name),"SpeciesRst_%s_%s",p[s],o[k]);OK(nc_inq_varid(a,name,&v));size_t m;double *tag=read(a,v,&m);
   if(n!=m)return 1;for(size_t i=0;i<n;i++)if(!isfinite(tag[i])||tag[i]!=(k==3?parent[i]:0)){fprintf(stderr,"Initialization mismatch %s index%zu\n",name,i);return 1;}
   printf("PASS %s cells=%zu expected=%s\n",name,n,k==3?"parent":"zero");free(tag);
  }free(parent);
 }
 OK(nc_close(a));OK(nc_close(b));printf("PASS origin cohort seed28fields; original_numeric_fields=%d exact\n",common);return 0;
}
