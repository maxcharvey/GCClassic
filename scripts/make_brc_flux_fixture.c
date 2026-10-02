/* Independent golden stream producer: periodic throughflow at Courant2,
   uniform parent remains positive while local checkerboard donor splits fail.
   OUTDIR must exist; writes4new endian/precision variants, no overwrite. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
static uint32_t rev32(uint32_t n){return ((n&255)<<24)|((n&65280)<<8)|((n>>8)&65280)|(n>>24);}
static uint64_t rev64(uint64_t n){return ((uint64_t)rev32((uint32_t)n)<<32)|rev32((uint32_t)(n>>32));}
static void bytes(FILE *f,const void *p,size_t n){if(fwrite(p,1,n,f)!=n)exit(2);}
static void real(FILE *f,double v,int width,int swap){if(width==8){uint64_t n;memcpy(&n,&v,8);if(swap)n=rev64(n);bytes(f,&n,8);}else{float v4=v;uint32_t n;memcpy(&n,&v4,4);if(swap)n=rev32(n);bytes(f,&n,4);}}
static void field(FILE *f,const double *v,size_t n,int w,int s){for(size_t i=0;i<n;i++)real(f,v[i],w,s);}
int main(int argc,char **argv){
 if(argc!=2)return 2;uint32_t host=1;int hostLittle=*(unsigned char*)&host;const int nx=2,ny=6,nz=3,n=36;
 double q[36],p[36],cx[36],zero[42]={0},fx[36],z[36],final[36],fz[36];
 for(int k=0;k<nz;k++)for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){int a=(k*ny+j)*nx+i;q[a]=1;p[a]=10;cx[a]=(j>=2&&j<=3)?2:0;fx[a]=(j>=2&&j<=3)?20:0;fz[a]=k==1?1:k==2?0.2:0;z[a]=k==0?9:k==1?10.8:10.2;final[a]=z[a]/10;}
 for(int big=0;big<2;big++)for(int w=4;w<=8;w+=4){
  int swap=big==hostLittle;char path[1024];snprintf(path,sizeof(path),"%s/fixture_%s_fp%d.bin",argv[1],big?"be":"le",w);FILE *f=fopen(path,"wbx");if(!f)return 1;
  bytes(f,"BRCFX001",8);bytes(f,"FSOAP   ",8);uint32_t h[]={1,nx,ny,nz,1,2,w,3,4,1,4,0x01020304,3,3,7,1};for(int i=0;i<16;i++){uint32_t v=swap?rev32(h[i]):h[i];bytes(f,&v,4);}
  real(f,600,w,swap);for(int i=0;i<ny;i++)real(f,1,w,swap);for(int i=0;i<ny;i++)real(f,1,w,swap);real(f,0.5,w,swap);field(f,q,n,w,swap);
  for(int o=0;o<4;o++){double origin[36];for(int i=0;i<n;i++)origin[i]=q[i]*(o+1)*0.1;field(f,origin,n,w,swap);}
  field(f,q,n,w,swap);field(f,p,n,w,swap);field(f,p,n,w,swap);field(f,cx,n,w,swap);field(f,zero,n,w,swap);field(f,zero,n,w,swap);
  for(int k=0;k<nz;k++){field(f,p+k*nx*ny,nx*ny,w,swap);field(f,p+k*nx*ny,nx*ny,w,swap);}
  field(f,q,n,w,swap);field(f,z,n,w,swap);field(f,z,n,w,swap);field(f,final,n,w,swap);field(f,fx,n,w,swap);field(f,zero,nx*(ny+1)*nz,w,swap);field(f,fz,n,w,swap);
  if(fclose(f))return 2;puts(path);
 }
 return 0;
}
