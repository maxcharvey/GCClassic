/* Native FINNv2.5 proxy partition for a short engineering fixture.
   Geographic membership uses pinned Natural Earth 1:50 million polygons,
   BEFORE inventory-to-model emission regridding. No parent field is altered.
   Cell-centre assignment is an explicitly approximate boundary method, not a claim of
   political-border accuracy. Compile and execute on a compute allocation. */
#include <netcdf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define NCOK(x) do{int e=(x);if(e){fprintf(stderr,"%s: %s\n",#x,nc_strerror(e));exit(2);}}while(0)
#define FAIL(msg) do{fprintf(stderr,"%s\n",msg);exit(1);}while(0)
typedef struct {size_t n;double *x,*y,xmin,xmax,ymin,ymax;} Ring;
typedef struct {size_t n;Ring *r;} Country;
static double *read_coord(int f,const char *name,size_t *n){
 int v,nd,id[NC_MAX_VAR_DIMS];NCOK(nc_inq_varid(f,name,&v));NCOK(nc_inq_varndims(f,v,&nd));
 if(nd!=1)FAIL("coordinate rank");
 NCOK(nc_inq_vardimid(f,v,id));NCOK(nc_inq_dimlen(f,id[0],n));
 double *a=malloc(*n*sizeof(double));if(!a)exit(2);NCOK(nc_get_var_double(f,v,a));
 for(size_t i=0;i<*n;i++)if(!isfinite(a[i])||(i&&a[i]<=a[i-1]))FAIL("invalid native coordinate");
 return a;
}
static Country load_country(const char *path){
 Country c;FILE *f=fopen(path,"r");if(!f)FAIL("open polygon file");
 if(fscanf(f,"%zu",&c.n)!=1||c.n==0||c.n>10000)FAIL("invalid ring count");
 c.r=calloc(c.n,sizeof(Ring));if(!c.r)exit(2);size_t points=0;
 for(size_t k=0;k<c.n;k++){
  Ring *r=&c.r[k];if(fscanf(f,"%zu",&r->n)!=1||r->n<4||r->n>1000000)FAIL("invalid polygon ring");
  r->x=malloc(r->n*sizeof(double));r->y=malloc(r->n*sizeof(double));if(!r->x||!r->y)exit(2);
  r->xmin=r->ymin=1e9;r->xmax=r->ymax=-1e9;
  for(size_t i=0;i<r->n;i++){
   if(fscanf(f,"%lf %lf",&r->x[i],&r->y[i])!=2||!isfinite(r->x[i])||!isfinite(r->y[i])||fabs(r->x[i])>180||fabs(r->y[i])>90)FAIL("invalid polygon coordinate");
   r->xmin=fmin(r->xmin,r->x[i]);r->xmax=fmax(r->xmax,r->x[i]);r->ymin=fmin(r->ymin,r->y[i]);r->ymax=fmax(r->ymax,r->y[i]);
  }
  if(r->x[0]!=r->x[r->n-1]||r->y[0]!=r->y[r->n-1])FAIL("unclosed polygon ring");
  points+=r->n;
 }
 fclose(f);printf("COUNTRY %s rings=%zu points=%zu\n",path,c.n,points);return c;
}
static double sample(Country c,double x,double y){
 if(x>=180)x-=360;
 int inside=0;
 for(size_t k=0;k<c.n;k++){
  Ring *r=&c.r[k];if(x<r->xmin||x>r->xmax||y<r->ymin||y>r->ymax)continue;
  /* Even-odd crossings preserve holes and disjoint islands. No country priority. */
  for(size_t i=0,j=r->n-1;i<r->n;j=i++)
   if((r->y[i]>y)!=(r->y[j]>y))
    if(x<(r->x[j]-r->x[i])*(y-r->y[i])/(r->y[j]-r->y[i])+r->x[i])inside=!inside;
 }
 return inside;
}
static void attr(int f,int v,const char *name,const char *text){NCOK(nc_put_att_text(f,v,name,strlen(text),text));}
int main(int argc,char **argv){
 if(argc!=7){fprintf(stderr,"Usage: %s USA_POLYGONS CAN_POLYGONS FINN_DIR YYYYMMDD time_index output.nc\n",argv[0]);return 2;}
 int date=atoi(argv[4]);size_t t=(size_t)strtoul(argv[5],0,10);Country usa=load_country(argv[1]),can=load_country(argv[2]);
 const char *places[]={"Denver","Anchorage","Fairbanks","Honolulu","Ottawa","Toronto","Iqaluit","Whitehorse","Yellowknife","PuertoRico","Guam","Mexico","Greenland","AlaskaWestBorder","YukonEastBorder","USA49South","CAN49North","USANortheast","CANQuebec","AleutianWest","AleutianEast"};double px[]={-104.99,-149.9,-147.72,-157.85,-75.70,-79.38,-68.52,-135.06,-114.37,-66.1,144.79,-102.55,-42.6,-141.05,-140.95,-110,-110,-71,-71,172.9,-176.65},py[]={39.74,61.2,64.84,21.3,45.42,43.65,63.75,60.72,62.45,18.47,13.44,23.63,71.7,64,64,48.95,49.05,44,47.1,52.9,51.88};
 for(size_t i=0;i<sizeof(px)/sizeof(px[0]);i++)printf("COVERAGE %s USA=%.9g CAN=%.9g\n",places[i],sample(usa,px[i],py[i]),sample(can,px[i],py[i]));
 int out;NCOK(nc_create(argv[6],NC_NETCDF4|NC_NOCLOBBER,&out));
 attr(out,NC_GLOBAL,"boundary_method","Natural Earth 50m Admin0 ADM0_A3 USA and CAN polygon membership at native FINN cell centres; approximate coastlines; dependencies ROW");
 attr(out,NC_GLOBAL,"parent_source","unchanged FINNv2.5 CO/BC/OC proxy inputs");attr(out,NC_GLOBAL,"USA_polygons",argv[1]);attr(out,NC_GLOBAL,"Canada_polygons",argv[2]);
 const char *proxy[]={"CO","BC","OC"},*origin[]={"USA","CAN","ROW"};
 size_t nx=0,ny=0;double *x=NULL,*y=NULL,*uw=NULL,*cw=NULL;int dims[3],vars[3][3],vx,vy,vt,vd;double timestamp=0;
 for(int p=0;p<3;p++){
  char path[2048],var[96];int year=date/10000;
  snprintf(path,sizeof(path),"%s/emissions-finnv2.5modvrs_%s_bb_surface_daily_%d0101-%d1231_0.1x0.1.nc",argv[3],proxy[p],year,year);int f,v,dv,tv;NCOK(nc_open(path,NC_NOWRITE,&f));
  size_t nxc,nyc;double *xc=read_coord(f,"lon",&nxc),*yc=read_coord(f,"lat",&nyc);int actual;NCOK(nc_inq_varid(f,"date",&dv));NCOK(nc_get_var1_int(f,dv,&t,&actual));if(actual!=date)FAIL("source date/time index mismatch");
  double source_time;NCOK(nc_inq_varid(f,"time",&tv));NCOK(nc_get_var1_double(f,tv,&t,&source_time));
  if(p==0){nx=nxc;ny=nyc;x=xc;y=yc;timestamp=source_time;
   NCOK(nc_def_dim(out,"time",1,&dims[0]));NCOK(nc_def_dim(out,"lat",ny,&dims[1]));NCOK(nc_def_dim(out,"lon",nx,&dims[2]));
   NCOK(nc_def_var(out,"time",NC_DOUBLE,1,&dims[0],&vt));NCOK(nc_def_var(out,"date",NC_INT,1,&dims[0],&vd));NCOK(nc_def_var(out,"lat",NC_DOUBLE,1,&dims[1],&vy));NCOK(nc_def_var(out,"lon",NC_DOUBLE,1,&dims[2],&vx));
   NCOK(nc_copy_att(f,tv,"units",out,vt));NCOK(nc_copy_att(f,tv,"calendar",out,vt));attr(out,vd,"units","YYYYMMDD");attr(out,vx,"units","degrees_east");attr(out,vy,"units","degrees_north");
   for(int q=0;q<3;q++)for(int o=0;o<3;o++){snprintf(var,sizeof(var),"%s_%s",proxy[q],origin[o]);NCOK(nc_def_var(out,var,NC_DOUBLE,3,dims,&vars[q][o]));NCOK(nc_def_var_deflate(out,vars[q][o],1,1,1));attr(out,vars[q][o],"units","molecules/cm^2/s");}
   NCOK(nc_enddef(out));NCOK(nc_put_var_double(out,vx,x));NCOK(nc_put_var_double(out,vy,y));NCOK(nc_put_var_double(out,vt,&timestamp));NCOK(nc_put_var_int(out,vd,&date));
   uw=malloc(nx*ny*sizeof(double));cw=malloc(nx*ny*sizeof(double));if(!uw||!cw)exit(2);double maxoverlap=0;
   for(size_t j=0;j<ny;j++)for(size_t i=0;i<nx;i++){size_t k=j*nx+i;uw[k]=sample(usa,x[i],y[j]);cw[k]=sample(can,x[i],y[j]);maxoverlap=fmax(maxoverlap,uw[k]+cw[k]-1);if(uw[k]+cw[k]>1+1e-12)FAIL("country masks overlap; no arbitrary precedence allowed");}
   printf("NATIVE_GRID nx=%zu ny=%zu maximum_overlap=%.17g\n",nx,ny,maxoverlap);
  }else{if(nx!=nxc||ny!=nyc||source_time!=timestamp)FAIL("proxy coordinate/time mismatch");for(size_t i=0;i<nx;i++)if(x[i]!=xc[i])FAIL("longitude mismatch");for(size_t j=0;j<ny;j++)if(y[j]!=yc[j])FAIL("latitude mismatch");free(xc);free(yc);}
  size_t start[]={t,0,0},count[]={1,ny,nx},n=nx*ny;double *src=malloc(n*sizeof(double)),*tag=malloc(n*sizeof(double));if(!src||!tag)exit(2);snprintf(var,sizeof(var),"fire_modisviirs_%s",proxy[p]);NCOK(nc_inq_varid(f,var,&v));NCOK(nc_get_vara_double(f,v,start,count,src));
  double sums[3]={0},mass[3]={0},total=0,maxerr=0,earth=6371000.0;
  for(size_t j=0;j<ny;j++)for(size_t i=0;i<nx;i++){size_t k=j*nx+i;double z=src[k];if(!isfinite(z)||z<0)FAIL("invalid native fire proxy");double a=z*uw[k],b=z*cw[k],c=z-a-b;maxerr=fmax(maxerr,fabs(a+b+c-z));}
  for(int o=0;o<3;o++){
   for(size_t j=0;j<ny;j++)for(size_t i=0;i<nx;i++){size_t k=j*nx+i;double weight=o==0?uw[k]:o==1?cw[k]:1-uw[k]-cw[k];tag[k]=src[k]*weight;sums[o]+=tag[k];double dy=(j==0?y[1]-y[0]:j==ny-1?y[ny-1]-y[ny-2]:(y[j+1]-y[j-1])/2);double dx=(i==0?x[1]-x[0]:i==nx-1?x[nx-1]-x[nx-2]:(x[i+1]-x[i-1])/2);double area=earth*earth*dx*M_PI/180*(sin((y[j]+dy/2)*M_PI/180)-sin((y[j]-dy/2)*M_PI/180));mass[o]+=tag[k]*area*1e4;if(o==0)total+=src[k]*area*1e4;}
   NCOK(nc_put_var_double(out,vars[p][o],tag));
  }
  printf("SOURCE %s raw_cell_sums=%.17g,%.17g,%.17g area_weighted_molec_s=%.17g,%.17g,%.17g total=%.17g max_cell_closure=%.17g global_rel_closure=%.17g\n",proxy[p],sums[0],sums[1],sums[2],mass[0],mass[1],mass[2],total,maxerr,(mass[0]+mass[1]+mass[2]-total)/fmax(total,1.0));
  free(src);free(tag);NCOK(nc_close(f));
 }
 NCOK(nc_close(out));printf("PASS native proxy partitions date=%d; geography is approximate\n",date);return 0;
}
