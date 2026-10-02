/* Single-origin integration check. NEW_FILE [PARENT_FIELD_FILE].
   UNT equals parent, USA/CAN/ROW mass fields stay zero; all velocities equal.
   Compare relative to each parent field's maximum:1e-12 restart,5e-7 HISTORY. */
#include <netcdf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define OK(x) do{int e=(x);if(e){fprintf(stderr,"%s: %s\n",#x,nc_strerror(e));exit(2);}}while(0)
static double *array(int f,int v,size_t *n){int nd,ids[NC_MAX_VAR_DIMS];OK(nc_inq_var(f,v,NULL,NULL,&nd,ids,NULL));*n=1;for(int d=0;d<nd;d++){size_t k;OK(nc_inq_dimlen(f,ids[d],&k));*n*=k;}double *a=malloc(*n*sizeof(double));if(!a)exit(2);OK(nc_get_var_double(f,v,a));return a;}
int main(int argc,char **argv){
 if(argc!=2&&argc!=3)return 2;
 int f,g,nv;OK(nc_open(argv[1],NC_NOWRITE,&f));OK(nc_open(argc==3?argv[2]:argv[1],NC_NOWRITE,&g));OK(nc_inq_nvars(f,&nv));int checked=0,failed=0;
 for(int v=0;v<nv;v++){
  char name[NC_MAX_NAME+1],parent[NC_MAX_NAME+1];OK(nc_inq_varname(f,v,name));size_t len=strlen(name);
  if(len<5)continue;const char *origin=name+len-3;
  if(name[len-4]!='_'||(strcmp(origin,"USA")&&strcmp(origin,"CAN")&&strcmp(origin,"ROW")&&strcmp(origin,"UNT")))continue;
  if(strncmp(name,"SpeciesRst_",11)&&strncmp(name,"DryDep_",7)&&strncmp(name,"DryDepVel_",10)&&strncmp(name,"WetLossConv_",12)&&strncmp(name,"WetLossLS_",10))continue;
  memcpy(parent,name,len-4);parent[len-4]=0;int w;OK(nc_inq_varid(g,parent,&w));size_t n,m;double *x=array(f,v,&n),*y=array(g,w,&m);if(n!=m)return 1;
  int equal=!strcmp(origin,"UNT")||!strncmp(name,"DryDepVel_",10);double scale=0,err=0;
  for(size_t i=0;i<n;i++){if(!isfinite(x[i])||!isfinite(y[i]))return 1;scale=fmax(scale,fabs(y[i]));err=fmax(err,fabs(x[i]-(equal?y[i]:0)));}
  double tol=!strncmp(name,"SpeciesRst_",11)?1e-12:5e-7;int bad=err>tol*fmax(scale,1e-300);failed+=bad;checked++;
  printf("%s expected=%s scale=%.17g maxerr=%.17g relative=%.9g %s\n",name,equal?parent:"zero",scale,err,err/fmax(scale,1e-300),bad?"FAIL":"PASS");free(x);free(y);
 }
 OK(nc_close(f));OK(nc_close(g));if(!checked)return 1;printf("SUMMARY checked=%d failed=%d\n",checked,failed);return failed?1:0;
}
