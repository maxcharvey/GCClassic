/* Offline raw-parent replay and deliberately limited donor-fraction probes.
   Does NOT implement live origin transport or infer export efficiency. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#define FAIL(s) do{fprintf(stderr,"%s\n",s);exit(1);}while(0)
typedef struct {FILE *f;int swap,width,nx,ny,nz,j1,j2,origins;size_t n;char name[9];double dt,pc,*area,*geo,*raw,*orig[4],*pole,*dp1,*dp2,*cx,*cy,*wz,*x,*y,*predict,*z,*clean,*final,*fx,*fy,*fz;} Data;
static uint32_t swap32(uint32_t v){return ((v&255)<<24)|((v&65280)<<8)|((v>>8)&65280)|(v>>24);}
static uint64_t swap64(uint64_t v){return ((uint64_t)swap32((uint32_t)v)<<32)|swap32((uint32_t)(v>>32));}
static void exact(FILE *f,void *p,size_t bytes){if(fread(p,1,bytes,f)!=bytes)FAIL("truncated capture");}
static double *take(Data *d,size_t n){double *a=malloc(n*sizeof(double));if(!a)exit(2);for(size_t i=0;i<n;i++){if(d->width==8){uint64_t b;exact(d->f,&b,8);if(d->swap)b=swap64(b);memcpy(a+i,&b,8);}else{uint32_t b;float f;exact(d->f,&b,4);if(d->swap)b=swap32(b);memcpy(&f,&b,4);a[i]=f;}if(!isfinite(a[i]))FAIL("nonfinite capture payload");}return a;}
static size_t at(Data *d,int i,int j,int k){return ((size_t)k*d->ny+j)*d->nx+i;}
static size_t yf(Data *d,int i,int j,int k){return ((size_t)k*(d->ny+1)+j)*d->nx+i;}
static Data load(const char *path){
 Data d={0};d.f=fopen(path,"rb");if(!d.f)FAIL("cannot open capture");char magic[8];exact(d.f,magic,8);if(memcmp(magic,"BRCFX001",8))FAIL("capture magic mismatch");exact(d.f,d.name,8);d.name[8]=0;for(int i=7;i>=0&&d.name[i]==' ';i--)d.name[i]=0;
 uint32_t h[16];exact(d.f,h,sizeof(h));if(h[11]==0x04030201)d.swap=1;else if(h[11]!=0x01020304)FAIL("invalid endian marker");if(d.swap)for(int i=0;i<16;i++)h[i]=swap32(h[i]);
 if(h[0]!=1||h[1]<2||h[1]>3600||h[2]<6||h[2]>1800||h[3]<3||h[3]>200||(h[6]!=4&&h[6]!=8)||(h[10]!=0&&h[10]!=4))FAIL("unsupported capture header");
 d.nx=h[1];d.ny=h[2];d.nz=h[3];d.width=h[6];d.j1=h[7]-1;d.j2=h[8]-1;d.origins=h[10];d.n=(size_t)d.nx*d.ny*d.nz;if(d.j1!=2||d.j2!=d.ny-3)FAIL("requires native two-band polar cap");
 double *v=take(&d,1);d.dt=v[0];free(v);d.area=take(&d,d.ny);d.geo=take(&d,d.ny);v=take(&d,1);d.pc=v[0];free(v);
 d.raw=take(&d,d.n);for(int o=0;o<d.origins;o++)d.orig[o]=take(&d,d.n);
 d.pole=take(&d,d.n);d.dp1=take(&d,d.n);d.dp2=take(&d,d.n);d.cx=take(&d,d.n);d.cy=take(&d,d.n);d.wz=take(&d,d.n);
 d.x=malloc(d.n*8);d.y=malloc(d.n*8);if(!d.x||!d.y)exit(2);size_t plane=(size_t)d.nx*d.ny;
 for(int k=0;k<d.nz;k++){v=take(&d,plane);memcpy(d.x+k*plane,v,plane*8);free(v);v=take(&d,plane);memcpy(d.y+k*plane,v,plane*8);free(v);}
 d.predict=take(&d,d.n);d.z=take(&d,d.n);d.clean=take(&d,d.n);d.final=take(&d,d.n);d.fx=take(&d,d.n);d.fy=take(&d,(size_t)d.nx*(d.ny+1)*d.nz);d.fz=take(&d,d.n);
 if(fgetc(d.f)!=EOF)FAIL("unexpected extra capture payload");fclose(d.f);
 printf("CAPTURE %s step=%u dims=%dx%dx%d units=%u fpbytes=%d endian=%s origins=%d dt=%.9g IORD=%u JORD=%u KORD=%u CROSS=%u FILL=%u\n",d.name,h[4],d.nx,d.ny,d.nz,h[5],d.width,d.swap?"opposite_host":"host",d.origins,d.dt,h[12],h[13],h[14],h[15],h[9]);return d;
}
static void residual(Data *d,const char *label,const double *actual,const double *expected,double tolerance,int required){
 double max=0,scale=0,l1=0,signedsum=0;for(size_t n=0;n<d->n;n++){int j=(n/d->nx)%d->ny;double delta=actual[n]-expected[n];max=fmax(max,fabs(delta));scale=fmax(scale,fabs(actual[n]));l1+=fabs(delta)*d->area[j];signedsum+=delta*d->area[j];}
 int bad=max>tolerance*fmax(scale,1e-300);printf("RESIDUAL %s maxabs=%.17g relative_max=%.9g area_L1=%.17g area_signed=%.17g %s\n",label,max,max/fmax(scale,1e-300),l1,signedsum,required?(bad?"FAIL":"PASS"):"DESCRIPTIVE");if(required&&bad)FAIL("raw parent stage replay failed");
}
static void replay(Data *d){
 double *r=malloc(d->n*8),*initial=malloc(d->n*8);if(!r||!initial)exit(2);double tol=d->width==8?1e-12:1e-5;
 for(size_t n=0;n<d->n;n++){if(d->dp1[n]<=0||d->dp2[n]<=0)FAIL("nonpositive pressure thickness");initial[n]=d->pole[n]*d->dp1[n];}
 memcpy(r,initial,d->n*8);
 for(int k=0;k<d->nz;k++)for(int j=d->j1;j<=d->j2;j++)for(int i=0;i<d->nx;i++){size_t n=at(d,i,j,k);r[n]+=d->fx[n]-d->fx[at(d,(i+1)%d->nx,j,k)];}
 residual(d,"X_divergence",d->x,r,tol,1);
 memcpy(r,d->x,d->n*8);
 for(int k=0;k<d->nz;k++){
  for(int j=d->j1;j<=d->j2;j++)for(int i=0;i<d->nx;i++){size_t n=at(d,i,j,k);r[n]+=d->fy[yf(d,i,j,k)]-d->fy[yf(d,i,j+1,k)]*d->geo[j]/d->geo[j+1];}
  for(int i=0;i<d->nx;i++){
   double s=d->x[at(d,0,0,k)]+d->fy[yf(d,i,0,k)],n=d->x[at(d,0,d->ny-1,k)]+d->fy[yf(d,i,d->ny,k)];
   r[at(d,i,0,k)]=r[at(d,i,1,k)]=s;r[at(d,i,d->ny-1,k)]=r[at(d,i,d->ny-2,k)]=n;
  }
 }
 residual(d,"Y_divergence_and_caps",d->y,r,tol,1);
 for(int k=0;k<d->nz;k++)for(int j=0;j<d->ny;j++)for(int i=0;i<d->nx;i++){size_t n=at(d,i,j,k);r[n]=d->y[n]+d->fz[n]-(k+1<d->nz?d->fz[at(d,i,j,k+1)]:0);}
 residual(d,"Z_divergence",d->z,r,tol,1);
 residual(d,"Qckxyz_cleanup",d->clean,d->z,tol,0);
 for(size_t n=0;n<d->n;n++)r[n]=d->clean[n]/d->dp2[n];
 for(int k=0;k<d->nz;k++)for(int i=0;i<d->nx;i++){r[at(d,i,1,k)]=r[at(d,i,0,k)];r[at(d,i,d->ny-2,k)]=r[at(d,i,d->ny-1,k)];}
 size_t floored=0;for(size_t n=0;n<d->n;n++)if(r[n]<0){r[n]=1e-26;floored++;}
 residual(d,"pressure_division_capdup_floor",d->final,r,tol,1);
 double before=0,after=0,originL1=0,poleL1=0,crossL1=0;size_t longx=0,longy=0;
 for(size_t n=0;n<d->n;n++){int j=(n/d->nx)%d->ny;before+=d->raw[n]*d->dp1[n]*d->area[j];after+=d->final[n]*d->dp2[n]*d->area[j];poleL1+=fabs(d->pole[n]-d->raw[n])*d->dp1[n]*d->area[j];crossL1+=fabs(d->predict[n]-d->pole[n])*d->dp1[n]*d->area[j];longx+=fabs(d->cx[n])>1;longy+=fabs(d->cy[n])>1;if(d->origins){double sum=0;for(int o=0;o<4;o++)sum+=d->orig[o][n];originL1+=fabs(sum-d->raw[n])*d->dp1[n]*d->area[j];}}
 printf("ACCOUNTING pressure_area_before=%.17g after=%.17g relative_change=%.9g pre_origin_area_L1=%.17g pole_area_L1=%.17g predictor_area_L1=%.17g floored_cells=%zu long_Courant_X=%zu long_Courant_Y=%zu\n",before,after,(after-before)/fmax(fabs(before),1e-300),originL1,poleL1,crossL1,floored,longx,longy);free(r);free(initial);
}
/* Independent checkerboard probes at each actual parent stage. They are NOT
   sequential origin trajectories. Donor fractions may fail incoming-credit
   and long-Courant cases; no clipping, balancing or renormalization is applied. */
static void probe(Data *d,int stage,int uniform){
 double *start=malloc(d->n*8),*part=calloc(4*d->n,8),*result=calloc(4*d->n,8),*faces=calloc(4*(size_t)d->nx*(d->ny+1)*d->nz,8);if(!start||!part||!result||!faces)exit(2);size_t faceN=(size_t)d->nx*(d->ny+1)*d->nz;size_t zero_support=0;
 for(int k=0;k<d->nz;k++)for(int j=0;j<d->ny;j++)for(int i=0;i<d->nx;i++){size_t n=at(d,i,j,k);start[n]=stage==0?d->pole[n]*d->dp1[n]:stage==1?d->x[n]:d->y[n];for(int o=0;o<4;o++){double f=uniform?(o+1)*0.1:((j<2||j>d->ny-3)?0.25:((o==((i+j+k)&1))?1:0));part[o*d->n+n]=start[n]*f;result[o*d->n+n]=part[o*d->n+n];}}
 for(int k=0;k<d->nz;k++)for(int j=0;j<d->ny;j++)for(int i=0;i<d->nx;i++){
  if(stage==0&&(j<d->j1||j>d->j2))continue;if(stage==1&&(j<d->j1||j>d->j2+1))continue;if(stage==2&&k==0)continue;
  size_t n=at(d,i,j,k),fi=stage==1?yf(d,i,j,k):n;double flux=stage==0?d->fx[n]:stage==1?d->fy[fi]:d->fz[n];int di=i,dj=j,dk=k;
  if(stage==0&&flux>=0)di=(i+d->nx-1)%d->nx;
  if(stage==1){if(flux>=0)dj=j-1;if(dj==1)dj=0;if(dj==d->ny-2)dj=d->ny-1;}
  if(stage==2&&flux>=0)dk=k-1;size_t donor=at(d,di,dj,dk);
  if(!uniform&&start[donor]<=0&&flux!=0){zero_support++;continue;}
  for(int o=0;o<4;o++){double frac=uniform?(o+1)*0.1:(start[donor]>0?part[o*d->n+donor]/start[donor]:0);faces[o*faceN+fi]=flux*frac;}
 }
 for(int o=0;o<4;o++){
  for(int k=0;k<d->nz;k++)for(int j=0;j<d->ny;j++)for(int i=0;i<d->nx;i++){
   size_t n=at(d,i,j,k);double *f=faces+o*faceN;
   if(stage==0&&j>=d->j1&&j<=d->j2)result[o*d->n+n]+=f[n]-f[at(d,(i+1)%d->nx,j,k)];
   if(stage==1&&j>=d->j1&&j<=d->j2)result[o*d->n+n]+=f[yf(d,i,j,k)]-f[yf(d,i,j+1,k)]*d->geo[j]/d->geo[j+1];
   if(stage==2)result[o*d->n+n]+=f[n]-(k+1<d->nz?f[at(d,i,j,k+1)]:0);
  }
  if(stage==1)for(int k=0;k<d->nz;k++){
   double s=0,n=0;for(int i=0;i<d->nx;i++){s+=faces[o*faceN+yf(d,i,d->j1,k)]/d->geo[d->j1];n+=faces[o*faceN+yf(d,i,d->j2+1,k)]/d->geo[d->j2+1];}
   s=part[o*d->n+at(d,0,0,k)]-s/d->nx*d->pc;n=part[o*d->n+at(d,0,d->ny-1,k)]+n/d->nx*d->pc;
   for(int i=0;i<d->nx;i++){result[o*d->n+at(d,i,0,k)]=result[o*d->n+at(d,i,1,k)]=s;result[o*d->n+at(d,i,d->ny-1,k)]=result[o*d->n+at(d,i,d->ny-2,k)]=n;}
  }
 }
 for(int o=0;o<4;o++){double before=0,after=0;for(size_t n=0;n<d->n;n++){int j=(n/d->nx)%d->ny;before+=part[o*d->n+n]*d->area[j];after+=result[o*d->n+n]*d->area[j];}printf("DONOR_CONSERVATION stage=%c fractions=%s origin=%d before_pressure_area=%.17g after_pressure_area=%.17g relative_change=%.9g\n","XYZ"[stage],uniform?"uniform":"checkerboard",o,before,after,(after-before)/fmax(fabs(before),1e-300));}
 const double *parent=stage==0?d->x:stage==1?d->y:d->z;double scale=0,maxerr=0,min=0,negative_area=0;size_t negative=0,parentnegative=0;
 for(size_t n=0;n<d->n;n++){double sum=0;scale=fmax(scale,fabs(parent[n]));parentnegative+=parent[n]<0;for(int o=0;o<4;o++){double value=result[o*d->n+n];sum+=value;min=fmin(min,value);if(value<0){negative++;negative_area-=value*d->area[(n/d->nx)%d->ny];}}maxerr=fmax(maxerr,fabs(sum-parent[n]));}
 printf("DONOR_PROBE stage=%c fractions=%s zero_support=%zu negative_origin_cells=%zu parent_negative_cells=%zu min_origin=%.17g negative_pressure_area=%.17g relative_parent_closure=%.9g feasibility=%s placement_accuracy=UNQUALIFIED\n","XYZ"[stage],uniform?"uniform":"checkerboard",zero_support,negative,parentnegative,min,negative_area,maxerr/fmax(scale,1e-300),(zero_support||negative||maxerr>(d->width==8?1e-12:1e-5)*fmax(scale,1e-300))?"FAIL":"PASS");free(start);free(part);free(result);free(faces);
}
static void release(Data *d){double *p[]={d->area,d->geo,d->raw,d->pole,d->dp1,d->dp2,d->cx,d->cy,d->wz,d->x,d->y,d->predict,d->z,d->clean,d->final,d->fx,d->fy,d->fz};for(size_t i=0;i<sizeof(p)/sizeof(p[0]);i++)free(p[i]);for(int o=0;o<d->origins;o++)free(d->orig[o]);}
int main(int argc,char **argv){if(argc<2)return 2;for(int a=1;a<argc;a++){Data d=load(argv[a]);replay(&d);for(int s=0;s<3;s++){probe(&d,s,1);probe(&d,s,0);}release(&d);}puts("PASS capture schema and raw parent-stage replay; donor feasibility reported separately");return 0;}
