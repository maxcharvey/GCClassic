/* Engineering inventory/dry deposition/signed wet-process loss integrals.
   Never first-passage export or gross wet scavenging.
   HEMCO_FILE DRY_FILE WET_FILE INTERVAL_SECONDS OMOC_BBOA ARCTIC_LATITUDE.
   Files must each contain one verified full-interval average record. */
#include <netcdf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define OK(x) do{int e=(x);if(e){fprintf(stderr,"%s: %s\n",#x,nc_strerror(e));exit(2);}}while(0)
#define FAIL(x) do{fprintf(stderr,"%s\n",x);exit(1);}while(0)
static double *read(int f,const char *name,size_t *n,char *units){
 int v,nd,ids[NC_MAX_VAR_DIMS];OK(nc_inq_varid(f,name,&v));OK(nc_inq_var(f,v,NULL,NULL,&nd,ids,NULL));*n=1;
 for(int d=0;d<nd;d++){size_t k;OK(nc_inq_dimlen(f,ids[d],&k));*n*=k;}
 if(units){size_t len;OK(nc_inq_attlen(f,v,"units",&len));if(len>=128)FAIL("units too long");OK(nc_get_att_text(f,v,"units",units));units[len]=0;}
 double *a=malloc(*n*sizeof(double));if(!a)exit(2);OK(nc_get_var_double(f,v,a));for(size_t i=0;i<*n;i++)if(!isfinite(a[i]))FAIL("nonfinite input");return a;
}
static void integrate(int f,const char *name,const char *expected,size_t nx,size_t ny,double *area,double *lat,double threshold,double multiplier,int perarea,double *global,double *arctic){
 int v,nd,ids[NC_MAX_VAR_DIMS];OK(nc_inq_varid(f,name,&v));OK(nc_inq_var(f,v,NULL,NULL,&nd,ids,NULL));
 if(nd!=3&&nd!=4)FAIL("expected time,[lev],lat,lon");
 for(int d=0;d<nd;d++){char dim[NC_MAX_NAME+1];size_t n;OK(nc_inq_dim(f,ids[d],dim,&n));
  if(d==0&&(strcmp(dim,"time")||n!=1))FAIL("requires one averaging interval");
  if(d==nd-1&&(strcmp(dim,"lon")||n!=nx))FAIL("longitude layout mismatch");
  if(d==nd-2&&(strcmp(dim,"lat")||n!=ny))FAIL("latitude layout mismatch");
  if(nd==4&&d==1&&strcmp(dim,"lev"))FAIL("vertical layout mismatch");
 }
 char units[128];size_t n;double *a=read(f,name,&n,units);if(strcmp(units,expected))FAIL("unexpected flux units");*global=*arctic=0;
 int signed_loss=!strncmp(name,"WetLoss",7);size_t negatives=0;
 double lo=0,hi=0,positive=0,negative=0,arctic_positive=0,arctic_negative=0;
 for(size_t i=0;i<n;i++){
  lo=fmin(lo,a[i]);hi=fmax(hi,a[i]);negatives+=a[i]<0;
  if(a[i]<0&&!signed_loss){fprintf(stderr,"negative source/dry deposition field=%s index=%zu value=%.17g\n",name,i,a[i]);exit(1);}
  size_t cell=i%(nx*ny),j=cell/nx;
  double value=a[i]*multiplier*(perarea?area[cell]:1);
  *global+=value;if(lat[j]>=threshold)*arctic+=value;
  if(value>=0){positive+=value;if(lat[j]>=threshold)arctic_positive+=value;}
  else{negative+=value;if(lat[j]>=threshold)arctic_negative+=value;}
 }
 if(signed_loss)fprintf(stderr,"RESOLVED_NET_FIELD %s negative_cells=%zu min=%.17g max=%.17g positive_global_kg=%.17g negative_global_kg=%.17g positive_arctic_kg=%.17g negative_arctic_kg=%.17g signed_global_kg=%.17g signed_arctic_kg=%.17g\n",name,negatives,lo,hi,positive,negative,arctic_positive,arctic_negative,*global,*arctic);
 free(a);
}
int main(int argc,char **argv){
 if(argc!=7&&argc!=9)return 2;
 char *end;double seconds=strtod(argv[4],&end);if(end==argv[4]||*end)FAIL("invalid interval");
 double omoc=strtod(argv[5],&end);if(end==argv[5]||*end)FAIL("invalid carbon basis");
 double boundary=strtod(argv[6],&end);if(end==argv[6]||*end)FAIL("invalid latitude");
 if(!isfinite(seconds)||seconds<=0||!isfinite(omoc)||omoc<=0||!isfinite(boundary)||fabs(boundary)>90)FAIL("invalid interval/basis/region");
 int h,d,w;OK(nc_open(argv[1],NC_NOWRITE,&h));OK(nc_open(argv[2],NC_NOWRITE,&d));OK(nc_open(argv[3],NC_NOWRITE,&w));
 int pd=d,pw=w;if(argc==9){OK(nc_open(argv[7],NC_NOWRITE,&pd));OK(nc_open(argv[8],NC_NOWRITE,&pw));}
 size_t nx,ny,n;char units[128];double *lon=read(h,"lon",&nx,NULL),*lat=read(h,"lat",&ny,NULL),*area=read(h,"AREA",&n,units);
 if(n!=nx*ny||strcmp(units,"m2"))FAIL("invalid HEMCO area");
 for(size_t i=0;i<n;i++)if(area[i]<=0)FAIL("nonpositive area");
 int grids[4]={d,w,pd,pw};
 for(int k=0;k<4;k++){size_t mx,my;double *x=read(grids[k],"lon",&mx,NULL),*y=read(grids[k],"lat",&my,NULL);if(mx!=nx||my!=ny)FAIL("grid mismatch");for(size_t i=0;i<nx;i++)if(x[i]!=lon[i])FAIL("longitude mismatch");for(size_t j=0;j<ny;j++)if(y[j]!=lat[j])FAIL("latitude mismatch");free(x);free(y);}
 const char *parents[]={"FSOAP","FSOAS","BRCSOA","NPBRCPOA","WTC","PBRCPOA","DBRCPOA"};
 const char *origins[]={"PARENT","USA","CAN","ROW","UNT"};double emitted[5]={0},dry[5]={0},wet[5]={0};
 puts("kind,species,origin,global_species_kg,arctic_species_kg,global_carbon_basis_kg,arctic_carbon_basis_kg");
 for(int s=0;s<7;s++)for(int o=0;o<5;o++){
  char suffix[20]="",name[96];if(o)snprintf(suffix,sizeof(suffix),"_%s",origins[o]);double g,a,basis=s<2?1/omoc:1;
  if((s==0||s==3||s==5||s==6)&&o<4){
   snprintf(name,sizeof(name),"Emis%s%s_FireColumn",parents[s],suffix);integrate(h,name,"kg/m2/s",nx,ny,area,lat,boundary,seconds,1,&g,&a);
   printf("fire_emission,%s,%s,%.17g,%.17g,%.17g,%.17g\n",parents[s],origins[o],g,a,g*basis,a*basis);emitted[o]+=g*basis;
  }
  if(s==0)continue;
  double mw=s==1?150.0:12.01;
  snprintf(name,sizeof(name),"DryDep_%s%s",parents[s],suffix);
  integrate(o?d:pd,name,"molec cm-2 s-1",nx,ny,area,lat,boundary,seconds*1e4*mw/1000/6.02214076e23,1,&g,&a);
  printf("dry_deposition,%s,%s,%.17g,%.17g,%.17g,%.17g\n",parents[s],origins[o],g,a,g*basis,a*basis);dry[o]+=a*basis;
  const char *process[]={"WetLossConv","WetLossLS"};
  for(int k=0;k<2;k++){snprintf(name,sizeof(name),"%s_%s%s",process[k],parents[s],suffix);integrate(o?w:pw,name,"kg s-1",nx,ny,area,lat,boundary,seconds,0,&g,&a);
   printf("net_%s,%s,%s,%.17g,%.17g,%.17g,%.17g\n",process[k],parents[s],origins[o],g,a,g*basis,a*basis);wet[o]+=a*basis;
  }
 }
 fprintf(stderr,"Signed wet-process atmospheric loss includes resolved returns to air; positive/negative integrals of averaged fields do not recover gross event-level scavenging. Surface precipitation boundary accounting and attribution accuracy remain unqualified.\n");
 for(int o=1;o<4;o++)fprintf(stderr,"%s interval_fire_carbon_basis_kg=%.9g arctic_dry_kg=%.9g arctic_net_wet_loss_kg=%.9g raw_arctic_net_loss_to_emission=%.9g; ENGINEERING_ONLY geography/transport unqualified\n",origins[o],emitted[o],dry[o],wet[o],emitted[o]>0?(dry[o]+wet[o])/emitted[o]:0);
 free(lon);free(lat);free(area);OK(nc_close(h));OK(nc_close(d));OK(nc_close(w));if(argc==9){OK(nc_close(pd));OK(nc_close(pw));}return 0;
}
