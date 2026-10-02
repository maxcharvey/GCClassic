/* Exact numeric common-field comparison. Variant-only fields are allowed ONLY
   for the 12 explicitly named FINNv25 country diagnostics. */
#include <netcdf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define OK(x) do{int e=(x);if(e){fprintf(stderr,"%s: %s\n",#x,nc_strerror(e));exit(2);}}while(0)
static int allowed(const char *name){const char *p[]={"FSOAP","NPBRCPOA","PBRCPOA","DBRCPOA"},*o[]={"USA","CAN","ROW"};for(int i=0;i<4;i++)for(int j=0;j<3;j++){char expected[96];snprintf(expected,sizeof(expected),"Emis%s_%s_FireColumn",p[i],o[j]);if(!strcmp(name,expected))return 1;}return 0;}
int main(int argc,char **argv){
 if(argc!=3 && argc!=4)return 2;int expected=-1;if(argc==4){char *end;long value=strtol(argv[3],&end,10);if(*end || (value!=0 && value!=12))return 2;expected=value;}int a,b,na,nb;OK(nc_open(argv[1],NC_NOWRITE,&a));OK(nc_open(argv[2],NC_NOWRITE,&b));OK(nc_inq_nvars(a,&na));OK(nc_inq_nvars(b,&nb));int failed=0,count=0,extras=0;
 for(int v=0;v<na;v++){char name[NC_MAX_NAME+1];nc_type type,tb;int nd,ndb,ids[NC_MAX_VAR_DIMS],ib[NC_MAX_VAR_DIMS],w;OK(nc_inq_var(a,v,name,&type,&nd,ids,NULL));OK(nc_inq_varid(b,name,&w));OK(nc_inq_var(b,w,NULL,&tb,&ndb,ib,NULL));if(type!=tb||nd!=ndb){fprintf(stderr,"metadata mismatch %s\n",name);return 1;}if(type==NC_CHAR||type==NC_STRING)continue;if(type==NC_INT64||type==NC_UINT64){fprintf(stderr,"64-bit integer exact comparison unsupported %s\n",name);return 2;}size_t ua=0,ub=0;int ra=nc_inq_attlen(a,v,"units",&ua),rb=nc_inq_attlen(b,w,"units",&ub);if(ra!=rb||ua!=ub)return 1;if(ra==NC_NOERR){char ca[256]={0},cb[256]={0};if(ua>=sizeof(ca))return 2;OK(nc_get_att_text(a,v,"units",ca));OK(nc_get_att_text(b,w,"units",cb));if(memcmp(ca,cb,ua))return 1;}else if(ra!=NC_ENOTATT){OK(ra);}size_t n=1;for(int d=0;d<nd;d++){size_t x,y;char da[NC_MAX_NAME+1],db[NC_MAX_NAME+1];OK(nc_inq_dim(a,ids[d],da,&x));OK(nc_inq_dim(b,ib[d],db,&y));if(x!=y||strcmp(da,db))return 1;n*=x;}
  double *x=malloc(n*sizeof(double)),*y=malloc(n*sizeof(double));if(!x||!y)return 2;OK(nc_get_var_double(a,v,x));OK(nc_get_var_double(b,w,y));double max=0,scale=0;size_t differences=0,nonfinite=0;for(size_t i=0;i<n;i++){nonfinite+=!isfinite(x[i])||!isfinite(y[i]);differences+=x[i]!=y[i];max=fmax(max,fabs(x[i]-y[i]));scale=fmax(scale,fabs(x[i]));}printf("COMMON %s n=%zu differing=%zu nonfinite=%zu maxabs=%.17g relative_max=%.9g %s\n",name,n,differences,nonfinite,max,max/fmax(scale,1e-300),(differences||nonfinite)?"FAIL":"PASS");failed+=differences||nonfinite;count++;free(x);free(y);
 }
 for(int v=0;v<nb;v++){char name[NC_MAX_NAME+1];int w;OK(nc_inq_varname(b,v,name));int rc=nc_inq_varid(a,name,&w);if(rc==NC_ENOTVAR){if(!allowed(name)){fprintf(stderr,"unexpected variant field %s\n",name);return 1;}extras++;}else OK(rc);}
 if(expected>=0 && extras!=expected){fprintf(stderr,"country extras expected=%d actual=%d\n",expected,extras);failed++;}
 printf("SUMMARY common_numeric=%d allowed_country_extras=%d failed=%d strict=%s\n",count,extras,failed,failed?"FAIL":"PASS");OK(nc_close(a));OK(nc_close(b));return failed?1:0;
}
