/* Global native full-column process-rate QA against logged actual mass changes.
   Does not qualify country transport or infer separate emissions/dry deposition. */
#define _GNU_SOURCE
#include <netcdf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#define OK(x) do{int e=(x);if(e){fprintf(stderr,"%s: %s\n",#x,nc_strerror(e));exit(2);}}while(0)
#define FAIL(x) do{fprintf(stderr,"%s\n",x);exit(1);}while(0)
static const char *species[]={"FSOAP","FSOAS","BRCSOA","NPBRCPOA","WTC","PBRCPOA","DBRCPOA"};
static const char *origins[]={"PARENT","USA","CAN","ROW","UNT"};
static const char *operators[]={"transport","mixing","convection","chemistry","wetdep","uninstrumented_interstep"};
static const char *prefix[]={"BudgetTransportFull","BudgetMixingFull","BudgetConvectionFull","BudgetChemistryFull","BudgetWetDepFull"};
typedef struct {int seen,events;double delta,scale,initial,final;} Audit;
static int indexof(const char *name,const char **names,int n){for(int i=0;i<n;i++)if(!strcmp(name,names[i]))return i;FAIL("unexpected audit identifier");}
static void text_attribute(int f,int v,const char *name,char *value,size_t size){size_t n;OK(nc_inq_attlen(f,v,name,&n));if(n>=size)FAIL("attribute too long");OK(nc_get_att_text(f,v,name,value));value[n]=0;}
static time_t utc(const char *value){
 int y,m,d,h,minute,second,n=0;struct tm t={0},check;
 if(sscanf(value,"%d-%d-%d %d:%d:%dz%n",&y,&m,&d,&h,&minute,&second,&n)!=6||!n||value[n])FAIL("invalid UTC date metadata");
 if(y<1900||m<1||m>12||d<1||d>31||h<0||h>23||minute<0||minute>59||second<0||second>59)FAIL("invalid UTC date range");
 t.tm_year=y-1900;t.tm_mon=m-1;t.tm_mday=d;t.tm_hour=h;t.tm_min=minute;t.tm_sec=second;time_t epoch=timegm(&t);if(!gmtime_r(&epoch,&check))FAIL("UTC date conversion");
 if(check.tm_year!=y-1900||check.tm_mon!=m-1||check.tm_mday!=d||check.tm_hour!=h||check.tm_min!=minute||check.tm_sec!=second)FAIL("invalid calendar date");
 return epoch;
}
static void check_run_span(int f,const char *start,double seconds){
 char begin[128],finish[128],units[128],calendar[128],expected[128];
 text_attribute(f,NC_GLOBAL,"simulation_start_date_and_time",begin,sizeof(begin));text_attribute(f,NC_GLOBAL,"simulation_end_date_and_time",finish,sizeof(finish));
 if(strcmp(begin,start)||difftime(utc(finish),utc(begin))!=seconds)FAIL("budget run span mismatch");
 int v,nd,id;size_t n;OK(nc_inq_varid(f,"time",&v));OK(nc_inq_varndims(f,v,&nd));if(nd!=1)FAIL("time coordinate rank");OK(nc_inq_vardimid(f,v,&id));OK(nc_inq_dimlen(f,id,&n));if(n!=1)FAIL("requires one full-interval average record");
 text_attribute(f,v,"units",units,sizeof(units));text_attribute(f,v,"calendar",calendar,sizeof(calendar));snprintf(expected,sizeof(expected),"minutes since %.19s",begin);
 double time_value;OK(nc_get_var_double(f,v,&time_value));if(strcmp(units,expected)||strcmp(calendar,"gregorian")||time_value!=0)FAIL("budget averaging record start mismatch");
 /* Global metadata describe the run span. Matching daily/hourly HISTORY
    frequency/duration still require the frozen config/log contract. */
}
static double *coordinate(int f,const char *name,size_t *n){int v,nd,id;OK(nc_inq_varid(f,name,&v));OK(nc_inq_varndims(f,v,&nd));if(nd!=1)FAIL("coordinate rank");OK(nc_inq_vardimid(f,v,&id));OK(nc_inq_dimlen(f,id,n));double *a=malloc(*n*sizeof(double));if(!a)exit(2);OK(nc_get_var_double(f,v,a));for(size_t i=0;i<*n;i++)if(!isfinite(a[i])||(i&&a[i]<=a[i-1]))FAIL("invalid coordinate");return a;}
static void integrate(int f,const char *name,size_t nx,size_t ny,double seconds,long double *net,long double *l1){
 int v,nd,ids[NC_MAX_VAR_DIMS];nc_type type;OK(nc_inq_varid(f,name,&v));OK(nc_inq_var(f,v,NULL,&type,&nd,ids,NULL));
 if((nd!=3&&nd!=4)||(type!=NC_FLOAT&&type!=NC_DOUBLE))FAIL("budget must be time,[lev],lat,lon floating rate");
 for(int d=0;d<nd;d++){char dim[NC_MAX_NAME+1];size_t n;OK(nc_inq_dim(f,ids[d],dim,&n));
  const char *expected=d==0?"time":d==nd-1?"lon":d==nd-2?"lat":"lev";size_t size=d==nd-1?nx:d==nd-2?ny:1;
  if(strcmp(dim,expected)||n!=size)FAIL("budget dimension mismatch");
 }
 size_t len;char units[128];OK(nc_inq_attlen(f,v,"units",&len));if(len>=sizeof(units))FAIL("units too long");OK(nc_get_att_text(f,v,"units",units));units[len]=0;if(strcmp(units,"kg s-1"))FAIL("budget units must be kg s-1");
 char method[128];text_attribute(f,v,"averaging_method",method,sizeof(method));if(strcmp(method,"time-averaged"))FAIL("requires time-averaged budget rates");
 size_t n=nx*ny;double *a=malloc(n*sizeof(double));if(!a)exit(2);OK(nc_get_var_double(f,v,a));*net=*l1=0;
 for(size_t i=0;i<n;i++){if(!isfinite(a[i]))FAIL("nonfinite budget rate");*net+=(long double)a[i]*seconds;*l1+=fabsl((long double)a[i]*seconds);}free(a);
}
int main(int argc,char **argv){
 if(argc!=5)return 2;
 char *end;double seconds=strtod(argv[4],&end);if(end==argv[4]||*end||!isfinite(seconds)||seconds<=0)FAIL("invalid interval");
 Audit audit[6][7][5]={0};FILE *csv=fopen(argv[1],"r");if(!csv)FAIL("cannot read audit CSV");char line[1024],start[21],extra;double interval;unsigned dyn,chem;
 if(!fgets(line,sizeof(line),csv)||sscanf(line,"# start_utc=%20c interval_seconds=%lf dynamics_seconds=%u chemistry_seconds=%u %c",start,&interval,&dyn,&chem,&extra)!=4)FAIL("missing audit interval metadata");
 start[20]=0;
 if(interval!=seconds||!dyn||!chem||chem%dyn||fmod(seconds,dyn)||fmod(seconds,chem))FAIL("audit cadence/interval mismatch");
 if(!fgets(line,sizeof(line),csv)||strcmp(line,"operator,species,origin,events,audit_delta_kg,logged_mass_pair_scale_kg,initial_mass_kg,final_mass_kg\n"))FAIL("unexpected audit CSV header");
 while(fgets(line,sizeof(line),csv)){
  char op[64],sp[32],origin[16],extra;Audit a={0};
  if(sscanf(line,"%63[^,],%31[^,],%15[^,],%d,%lf,%lf,%lf,%lf %c",op,sp,origin,&a.events,&a.delta,&a.scale,&a.initial,&a.final,&extra)!=8)FAIL("invalid audit CSV row");
  if(a.events<0||!isfinite(a.delta)||!isfinite(a.scale)||a.scale<0||!isfinite(a.initial)||a.initial<0||!isfinite(a.final)||a.final<0)FAIL("invalid audit CSV inventory");
  int p=indexof(op,operators,6),s=indexof(sp,species,7),o=indexof(origin,origins,5);if(audit[p][s][o].seen)FAIL("duplicate audit row");a.seen=1;audit[p][s][o]=a;
 }
 fclose(csv);for(int p=0;p<6;p++)for(int s=0;s<7;s++)for(int o=0;o<5;o++)if(!audit[p][s][o].seen)FAIL("missing audit row");
 int f[2];OK(nc_open(argv[2],NC_NOWRITE,&f[0]));OK(nc_open(argv[3],NC_NOWRITE,&f[1]));check_run_span(f[0],start,seconds);check_run_span(f[1],start,seconds);size_t nx,ny,mx,my;double *x=coordinate(f[0],"lon",&nx),*y=coordinate(f[0],"lat",&ny),*xx=coordinate(f[1],"lon",&mx),*yy=coordinate(f[1],"lat",&my);
 if(nx!=mx||ny!=my)FAIL("budget grid shape mismatch");
 for(size_t i=0;i<nx;i++)if(x[i]!=xx[i])FAIL("budget longitude mismatch");
 for(size_t j=0;j<ny;j++)if(y[j]!=yy[j])FAIL("budget latitude mismatch");
 free(x);free(y);free(xx);free(yy);
 int failed=0,checked=0,fields=0;
 puts("operator,species,origin,audit_events,audit_delta_kg,HISTORY_delta_kg,difference_kg,HISTORY_cell_L1_kg,logged_mass_pair_scale_kg,rounding_bound_kg,gate");
 for(int p=0;p<5;p++)for(int s=0;s<7;s++)for(int o=0;o<5;o++){
  char suffix[20]="",name[128];if(o)snprintf(suffix,sizeof(suffix),"_%s",origins[o]);long double net=0,l1=0;
  if(!(p==4&&s==0)){
   snprintf(name,sizeof(name),"%s_%s%s",prefix[p],species[s],suffix);integrate(f[o?1:0],name,nx,ny,seconds,&net,&l1);fields++;
   if(p==1){long double second,second_l1;snprintf(name,sizeof(name),"BudgetEmisDryDepFull_%s%s",species[s],suffix);integrate(f[o?1:0],name,nx,ny,seconds,&second,&second_l1);net+=second;l1+=second_l1;fields++;}
  }
  Audit a=audit[p][s][o];long double diff=net-a.delta;
  /* Frozen QA precision envelope: native averaged float rounding plus printed
     global masses, sum order and unit conversion. Not an attribution tolerance. */
  long double bound=5e-7L*l1+5e-13L*a.scale+1e-10L;
  int bad=fabsl(diff)>bound;failed+=bad;checked++;
  printf("%s,%s,%s,%d,%.17g,%.17Lg,%.17Lg,%.17Lg,%.17g,%.17Lg,%s\n",operators[p],species[s],origins[o],a.events,a.delta,net,diff,l1,a.scale,bound,bad?"FAIL":"PASS");
 }
 for(int s=0;s<7;s++)for(int o=0;o<5;o++){
  Audit a=audit[5][s][o];long double total=a.delta;for(int p=0;p<5;p++)total+=audit[p][s][o].delta;
  fprintf(stderr,"UNINSTRUMENTED_INTERSTEP %s %s events=%d signed_kg=%.17g initial_kg=%.17g final_kg=%.17g audit_telescoping_residual_kg=%.17Lg; unassigned_not_process_attribution\n",species[s],origins[o],a.events,a.delta,a.initial,a.final,total-((long double)a.final-a.initial));
 }
 OK(nc_close(f[0]));OK(nc_close(f[1]));fprintf(stderr,"%s process_budget_QA comparisons=%d native_fields=%d failed=%d interval_seconds=%.17g precision_envelope_only; no origin_accuracy/export/deposition_efficiency_acceptance\n",failed?"FAIL":"PASS",checked,fields,failed,seconds);return failed?1:0;
}
