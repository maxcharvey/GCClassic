/* Strict numerical zero guards for a single-origin control, not mixed accuracy. */
#include <netcdf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define OK(x) do{int e=(x);if(e){fprintf(stderr,"%s: %s\n",#x,nc_strerror(e));exit(2);}}while(0)
static int check(int f,const char *name,const char *expected){
 int v,nd,ids[NC_MAX_VAR_DIMS];nc_type type;OK(nc_inq_varid(f,name,&v));OK(nc_inq_var(f,v,NULL,&type,&nd,ids,NULL));if(type!=NC_FLOAT&&type!=NC_DOUBLE)return 1;
 size_t n=1;for(int d=0;d<nd;d++){size_t k;OK(nc_inq_dimlen(f,ids[d],&k));if(!k)return 1;n*=k;}
 size_t len;char units[128];OK(nc_inq_attlen(f,v,"units",&len));if(len>=sizeof(units))return 1;OK(nc_get_att_text(f,v,"units",units));units[len]=0;if(strcmp(units,expected))return 1;
 double *a=malloc(n*sizeof(double));if(!a)exit(2);OK(nc_get_var_double(f,v,a));size_t nonzero=0,invalid=0;for(size_t i=0;i<n;i++){invalid+=!isfinite(a[i]);nonzero+=a[i]!=0;}free(a);
 printf("%s cells=%zu nonzero=%zu nonfinite=%zu %s\n",name,n,nonzero,invalid,nonzero||invalid?"FAIL":"PASS");return nonzero||invalid;
}
int main(int argc,char **argv){
 if(argc!=3)return 2;
 int r,h;OK(nc_open(argv[1],NC_NOWRITE,&r));OK(nc_open(argv[2],NC_NOWRITE,&h));int failed=0;
 const char *parents[]={"FSOAP","FSOAS","BRCSOA","NPBRCPOA","WTC","PBRCPOA","DBRCPOA"},*origins[]={"USA","CAN","ROW"};
 for(int s=0;s<7;s++)for(int o=0;o<3;o++){char name[96];snprintf(name,sizeof(name),"SpeciesRst_%s_%s",parents[s],origins[o]);failed+=check(r,name,"mol mol-1 dry");}
 for(int s=0;s<7;s++)if(s==0||s==3||s==5||s==6)for(int o=0;o<3;o++){char name[96];snprintf(name,sizeof(name),"Emis%s_%s_FireColumn",parents[s],origins[o]);failed+=check(h,name,"kg/m2/s");}
 OK(nc_close(r));OK(nc_close(h));printf("SUMMARY restart_zero_fields=21 emission_zero_fields=12 failed=%d\n",failed);return failed?1:0;
}
