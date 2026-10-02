/* Offline feasibility experiment only; NOT a production transport method.
   Independent constant-velocity Fourier reference exposes placement error. */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#define MAXN 32
#define REQUIRE(x) do{if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static int solve(int n,const double *matrix,const double *rhs,double *out){
 double a[MAXN][MAXN+1],scale=0;
 for(int i=0;i<n;i++){for(int j=0;j<n;j++){a[i][j]=matrix[i*n+j];scale=fmax(scale,fabs(a[i][j]));}a[i][n]=rhs[i];}
 for(int k=0;k<n;k++){int p=k;for(int i=k+1;i<n;i++)if(fabs(a[i][k])>fabs(a[p][k]))p=i;if(fabs(a[p][k])<=1e-13*fmax(scale,1e-300))return 1;
  for(int j=k;j<=n;j++){double t=a[p][j];a[p][j]=a[k][j];a[k][j]=t;}
  for(int i=k+1;i<n;i++){double f=a[i][k]/a[k][k];for(int j=k;j<=n;j++)a[i][j]-=f*a[k][j];}
 }
 for(int i=n-1;i>=0;i--){double t=a[i][n];for(int j=i+1;j<n;j++)t-=a[i][j]*out[j];out[i]=t/a[i][i];}return 0;
}
static int partition(int n,const double *before,const double *after,const double *flows,const double *initial,double *result,int verbose){
 double a[MAXN*MAXN]={0},f[MAXN]={0},rhs[MAXN],frac[4][MAXN];
 for(int i=0;i<n;i++){REQUIRE(before[i]>=0&&after[i]>=0);double incoming=0,outgoing=0;for(int j=0;j<n;j++){REQUIRE(flows[i*n+j]>=0);outgoing+=flows[i*n+j];incoming+=flows[j*n+i];a[i*n+j]-=flows[j*n+i];}a[i*n+i]+=after[i]+outgoing;REQUIRE(fabs(after[i]+outgoing-before[i]-incoming)<1e-12);double sum=0;for(int o=0;o<4;o++){REQUIRE(initial[o*n+i]>=0);sum+=initial[o*n+i];}REQUIRE(fabs(sum-before[i])<1e-12);}
 double linear=0,closure=0,min=1,conservation=0,face=0;
 for(int o=0;o<4;o++){for(int i=0;i<n;i++)rhs[i]=initial[o*n+i];if(solve(n,a,rhs,f))return 1;double old=0,new=0;for(int i=0;i<n;i++){frac[o][i]=f[i];min=fmin(min,f[i]);result[o*n+i]=after[i]*f[i];old+=initial[o*n+i];new+=result[o*n+i];double r=-rhs[i];for(int j=0;j<n;j++)r+=a[i*n+j]*f[j];linear=fmax(linear,fabs(r));}conservation=fmax(conservation,fabs(new-old));}
 for(int i=0;i<n;i++){double sum=0;for(int o=0;o<4;o++)sum+=frac[o][i];closure=fmax(closure,fabs(sum-1));for(int j=0;j<n;j++)face=fmax(face,fabs(flows[i*n+j]*(sum-1)));}
 REQUIRE(linear<1e-11&&closure<1e-11&&min>=-1e-13&&conservation<1e-11&&face<1e-11);
 if(verbose)printf("FEASIBILITY n=%d linear=%.3g fraction_closure=%.3g min_fraction=%.3g shared_face_closure=%.3g origin_conservation=%.3g PASS placement=UNQUALIFIED\n",n,linear,closure,min,face,conservation);return 0;
}
static void cases(void){
 double b[3]={1,1,1},p[3]={1,1,1},flow[9]={0},ini[12]={0},out[12];
 /* Periodic circulating flux: the explicit checkerboard donor split fails,
    while implicit mixing is positive but changes spatial origin placement. */
 flow[1]=flow[3]=2;ini[0]=1;ini[3]=0;ini[2]=0;ini[1]=0;ini[4]=1;ini[5]=1;
 REQUIRE(partition(3,b,p,flow,ini,out,1)==0);REQUIRE(fabs(out[0]-.6)<1e-12&&fabs(out[1]-.4)<1e-12);
 puts("PLACEMENT_COUNTEREXAMPLE two-cell Courant2 exact periodic advection returns front; implicit result [0.6,0.4] instead of [1,0]");
 /* Zero-stock intermediate throughflow, incoming credit, two-edge label path. */
 b[0]=1;b[1]=b[2]=0;p[0]=p[2]=.5;p[1]=0;memset(flow,0,sizeof(flow));flow[1]=flow[5]=.5;memset(ini,0,sizeof(ini));ini[0]=1;
 REQUIRE(partition(3,b,p,flow,ini,out,1)==0);REQUIRE(fabs(out[2]-.5)<1e-12);puts("SUPPORT_COUNTEREXAMPLE origin traverses two connected faces in one implicit step; propagation unqualified");
 /* Empty closed circulating component has undetermined flux provenance. */
 memset(b,0,sizeof(b));memset(p,0,sizeof(p));memset(ini,0,sizeof(ini));memset(flow,0,sizeof(flow));flow[1]=flow[5]=flow[6]=1;
 REQUIRE(partition(3,b,p,flow,ini,out,0)==1);puts("PASS singular zero-stock circulation explicitly refused");
 /* Disconnected anchored compartments and constant fractions. */
 for(int i=0;i<3;i++){b[i]=p[i]=1;for(int o=0;o<4;o++)ini[o*3+i]=.1*(o+1);}memset(flow,0,sizeof(flow));REQUIRE(partition(3,b,p,flow,ini,out,1)==0);
}
static void refinement(int direction){
 const int n=16;double theta=2*acos(-1.)/n,total=2,previous=1e9;
 for(int steps=1;steps<=64;steps*=2){double b[MAXN],p[MAXN],flow[MAXN*MAXN]={0},ini[4*MAXN]={0},out[4*MAXN];for(int i=0;i<n;i++){b[i]=p[i]=1;flow[i*n+(i+direction+n)%n]=total/steps;ini[i]=.5+.4*cos(theta*i);ini[n+i]=1-ini[i];}
  for(int k=0;k<steps;k++){REQUIRE(partition(n,b,p,flow,ini,out,0)==0);memcpy(ini,out,4*n*sizeof(double));}
  double discrete=0,continuum=0,amplitude=.4*exp(total*(cos(theta)-1)),phase=direction*total*sin(theta);
  for(int i=0;i<n;i++){double reference=.5+amplitude*cos(theta*i-phase),exact=.5+.4*cos(theta*(i-direction*total));discrete=fmax(discrete,fabs(ini[i]-reference));continuum=fmax(continuum,fabs(ini[i]-exact));}
  REQUIRE(discrete<previous);previous=discrete;printf("REFINEMENT direction=%d steps=%d discrete_Fourier_error=%.9g exact_advection_error=%.9g\n",direction,steps,discrete,continuum);
 }
}
int main(void){cases();refinement(1);refinement(-1);puts("PASS bounded implicit partition algebra; live integration and origin placement remain UNQUALIFIED");return 0;}
