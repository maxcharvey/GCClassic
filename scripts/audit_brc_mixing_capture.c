/* Read-only BRCMX001 native PBL evidence. No attribution accuracy gate. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <errno.h>
static const char *names[7]={"FSOAP","FSOAS","BRCSOA","NPBRCPOA","WTC","PBRCPOA","DBRCPOA"};
static void fail(const char *s){fprintf(stderr,"FAIL %s\n",s);exit(2);}
static int swapbytes,bytes;
static void readraw(FILE *f,void *v,size_t n){if(fread(v,1,n,f)!=n)fail("truncated mixing capture");}
static uint32_t u32(FILE *f){uint32_t n;readraw(f,&n,4);if(swapbytes)n=(n>>24)|((n>>8)&0xff00)|((n<<8)&0xff0000)|(n<<24);return n;}
static double realv(FILE *f){unsigned char v[8],w[8];readraw(f,v,(size_t)bytes);for(int i=0;i<bytes;i++)w[i]=v[swapbytes?bytes-1-i:i];double d;if(bytes==4){float x;memcpy(&x,w,4);d=x;}else memcpy(&d,w,8);if(!isfinite(d))fail("nonfinite native evidence");return d;}
static double *reals(FILE *f,size_t n){double *v=calloc(n,sizeof *v);if(!v)fail("allocation");for(size_t i=0;i<n;i++)v[i]=realv(f);return v;}
static double fp(double x){double r=bytes==4?(double)(float)x:x;if(!isfinite(r))fail("nonfinite derived native arithmetic");return r;}
static double rel(double a,double b){if(!isfinite(a)||!isfinite(b)||!isfinite(a-b))fail("nonfinite derived comparison");return fabs(a-b)/fmax(fmax(fabs(a),fabs(b)),1e-200);}
static double *diffuse(int nx,int nz,int top,const double *q,const double *cc,const double *ze,const double *term,const double *bot){
 size_t cell=(size_t)nx*nz;double *out=calloc(cell*35,sizeof *out),*fq=calloc((size_t)nz,sizeof *fq);
 if(!out||!fq)fail("diffusion allocation");
 for(int b=0;b<35;b++)for(int i=0;i<nx;i++){
  size_t v=(size_t)top*nx+i;fq[top]=fp(q[(size_t)b*cell+v]*term[v]);
  for(int k=top+1;k<nz-1;k++){v=(size_t)k*nx+i;fq[k]=fp(fp(q[(size_t)b*cell+v]+fp(cc[v]*fq[k-1]))*term[v]);}
  v=(size_t)(nz-1)*nx+i;double d=fp(1.0+fp(cc[v]*fp(1.0-ze[v-nx])));if(d<=0)fail("nonpositive diffusion denominator");
  double inv=fp(1.0/d);fq[nz-1]=fp(fp(fp(q[(size_t)b*cell+v]+bot[(size_t)b*nx+i])+fp(cc[v]*fq[nz-2]))*inv);
  out[(size_t)b*cell+v]=fq[nz-1];
  for(int k=nz-2;k>=top;k--){v=(size_t)k*nx+i;out[(size_t)b*cell+v]=fp(fq[k]+fp(ze[v]*out[(size_t)b*cell+v+nx]));}
 }
 free(fq);return out;
}
int main(int argc,char **argv){
 if(argc<2)fail("usage: audit_brc_mixing_capture CAPTURE...");
 printf("file,step,lat,phase,parent,parent_kg,signed_residual_kg,L1_kg,max_cell_kg,negative_parent,negative_USA,negative_CAN,negative_ROW,negative_UNT,rollback_disagreements,scale_factor_disagreements,source_signed_kg,source_L1_kg\n");
 for(int a=1;a<argc;a++){
  FILE *f=fopen(argv[a],"rb");if(!f){fprintf(stderr,"%s: %s\n",argv[a],strerror(errno));return 2;}
  char magic[8];readraw(f,magic,8);if(memcmp(magic,"BRCMX001",8))fail("wrong magic");
  unsigned char raw[48];readraw(f,raw,48);uint32_t marker;memcpy(&marker,raw+40,4);
  swapbytes=marker!=0x01020304u;if(swapbytes&&marker!=0x04030201u)fail("bad endian marker");
  uint32_t h[12];for(int j=0;j<12;j++){unsigned char w[4];for(int i=0;i<4;i++)w[i]=raw[4*j+(swapbytes?3-i:i)];memcpy(h+j,w,4);}
  int nx=(int)h[1],nz=(int)h[2],step=(int)h[3],lat=(int)h[4],cg=(int)h[8]-1,top=(int)h[9]-1;
  bytes=(int)h[6];if(h[0]!=1||nx<1||nx>10000||nz<2||nz>300||step<1||step>6||lat<1||lat>10000||h[5]!=35||h[7]!=2||h[11]!=6||(bytes!=4&&bytes!=8)||cg<0||cg>=nz||top<0||top>=nz-1)fail("invalid mixing header");
  size_t cell=(size_t)nx*nz,cols=(size_t)nx*35,slab=cell*35;
  double dt=realv(f);if(dt<=0)fail("nonpositive interval");
  double *ad=reals(f,cell),*area=reals(f,(size_t)nx),*flx=reals(f,cols);
  for(size_t i=0;i<cell;i++)if(ad[i]<=0)fail("nonpositive dry air mass");
  for(int i=0;i<nx;i++)if(area[i]<=0)fail("nonpositive area");
  double *cc=NULL,*ze=NULL,*term=NULL,*bot=NULL;
  double *q[6];for(int p=0;p<6;p++){
   if(p==3){readraw(f,magic,8);if(memcmp(magic,"BRCMD001",8))fail("missing native diffusion coefficients");cc=reals(f,cell);ze=reals(f,cell);term=reals(f,cell);bot=reals(f,cols);}
   if(u32(f)!=(uint32_t)(p+1))fail("phase order");
   q[p]=reals(f,slab);
  }
  double *threshold=reals(f,35);uint32_t *mask=calloc(cols,4),*safe=calloc(cols,4);if(!mask||!safe)fail("allocation");
  for(size_t i=0;i<cols;i++){mask[i]=u32(f);if(mask[i]>1)fail("missing rollback mask");}
  double *num=reals(f,cols),*den=reals(f,cols);
  for(size_t i=0;i<cols;i++){safe[i]=u32(f);if(safe[i]>1)fail("missing scale branch");}
  if(fgetc(f)!=EOF)fail("unexpected trailing evidence");
  fclose(f);
  double maxnum=0,maxden=0,maxscale=0,maxdiff=0;
  double *actualdiff=diffuse(nx,nz,top,q[2],cc,ze,term,bot),*shared=calloc(slab,sizeof *shared);
  if(!shared)fail("shared-mask allocation");
  for(size_t v=0;v<slab;v++){double e=rel(actualdiff[v],q[3][v]);if(e>maxdiff)maxdiff=e;}
  for(int b=0;b<35;b++)for(int i=0;i<nx;i++){
   size_t col=(size_t)b*nx+i;int expected=0;
   int en=0,ed=0;frexp(num[col],&en);frexp(den[col],&ed);
   int can_divide=den[col]!=0 && en-ed<(bytes==4?128:1024) && en-ed>(bytes==4?-125:-1021);
   if(safe[col]!=(uint32_t)can_divide)fail("safe division predicate replay differs");
   for(int k=cg;k<nz;k++)if(q[1][(size_t)b*cell+(size_t)k*nx+i]<threshold[b])expected=1;
   if(mask[col]!=(uint32_t)expected)fail("rollback mask differs from native threshold predicate");
   double n=0,d=0;
   for(int k=0;k<nz;k++){
    size_t v=(size_t)b*cell+(size_t)k*nx+i;
    double rb=(k>=cg&&expected)?q[0][v]:q[1][v];if(q[2][v]!=rb)fail("rollback replay differs");
    if(q[4][v]!=fmax(q[3][v],0.0))fail("negative clipping replay differs");
    if(k>=top){n=fp(n+fp(q[0][v]*ad[(size_t)k*nx+i]));d=fp(d+fp(q[4][v]*ad[(size_t)k*nx+i]));}
    double scaled=q[4][v];if(k>=top&&safe[col]){if(den[col]==0)fail("zero scale denominator");scaled=fp(fp(scaled*num[col])/den[col]);}
    double e=rel(q[5][v],scaled);if(e>maxscale)maxscale=e;
   }
   n=fp(n+fp(fp(flx[col]*area[i])*dt));double e=rel(n,num[col]);if(e>maxnum)maxnum=e;e=rel(d,den[col]);if(e>maxden)maxden=e;
  }
  double tol=bytes==4?5e-5:5e-12;
  if(maxnum>tol||maxden>tol||maxscale>tol||maxdiff>tol)fail("native diffusion/restoration argument/replay tolerance exceeded");
  fprintf(stderr,"PASS %s native masks/rollback/diffusion/clip/scale replay; max_num_rel=%.9g max_den_rel=%.9g max_scale_rel=%.9g max_diffusion_rel=%.9g\n",argv[a],maxnum,maxden,maxscale,maxdiff);
  for(int b=0;b<35;b++)for(int k=0;k<nz;k++)for(int i=0;i<nx;i++){
   size_t v=(size_t)b*cell+(size_t)k*nx+i;size_t parentcol=(size_t)(b/5*5)*nx+i;
   shared[v]=(k>=cg&&mask[parentcol])?q[0][v]:q[1][v];
  }
  double *counter=diffuse(nx,nz,top,shared,cc,ze,term,bot);
  for(int s=0;s<7;s++){
   int b=s*5;long rbdis=0,scdis=0;double src=0,srcL1=0;
   for(int i=0;i<nx;i++){
    double r=0;for(int o=1;o<5;o++){r+=flx[(size_t)(b+o)*nx+i];if(mask[(size_t)(b+o)*nx+i]!=mask[(size_t)b*nx+i])rbdis++;
     size_t pc=(size_t)b*nx+i,oc=(size_t)(b+o)*nx+i;
     double pf=safe[pc]?num[pc]/den[pc]:1,of=safe[oc]?num[oc]/den[oc]:1;
     if(!isfinite(pf)||!isfinite(of))fail("nonfinite derived scale factor");
     if(safe[pc]!=safe[oc]||fabs(pf-of)>tol*fmax(1,fmax(fabs(pf),fabs(of))))scdis++;
    }
    r=(r-flx[(size_t)b*nx+i])*area[i]*dt;src+=r;srcL1+=fabs(r);
   }
   if(!isfinite(src)||!isfinite(srcL1))fail("nonfinite derived source inventory");
   double rawl1=0,finall1=0,noclipl1=0,clipmass=0,clipsigned=0,botl1=0;
   for(int i=0;i<nx;i++){
    double r=0;for(int o=1;o<5;o++)r+=bot[(size_t)(b+o)*nx+i];r-=bot[(size_t)b*nx+i];botl1+=fabs(r)*ad[(size_t)(nz-1)*nx+i];
    size_t pc=(size_t)b*nx+i;double factor=safe[pc]?num[pc]/den[pc]:1;
    for(int k=0;k<nz;k++){
     size_t v=(size_t)k*nx+i;double parts=0;for(int o=1;o<5;o++)parts+=counter[(size_t)(b+o)*cell+v];
     double rscale=k>=top?factor:1;double parentraw=q[3][(size_t)b*cell+v],parentfinal=q[5][(size_t)b*cell+v];
     rawl1+=fabs(parts-parentraw)*ad[v];finall1+=fabs(parts*rscale-parentfinal)*ad[v];noclipl1+=fabs((parts-parentraw)*rscale)*ad[v];
     double clip=(q[4][(size_t)b*cell+v]-parentraw)*rscale*ad[v];clipmass+=fabs(clip);clipsigned+=clip;
    }
   }
   if(!isfinite(rawl1)||!isfinite(finall1)||!isfinite(noclipl1)||!isfinite(clipmass)||!isfinite(botl1))fail("nonfinite signed counterfactual");
   fprintf(stderr,"PROBE file=%s step=%d lat=%d parent=%s shared_mask_raw_L1_kg=%.17g shared_factor_actual_parent_L1_kg=%.17g shared_factor_unclipped_parent_L1_kg=%.17g parent_clipping_L1_kg=%.17g parent_clipping_signed_kg=%.17g bottom_tendency_L1_kg=%.17g ENGINEERING_ONLY\n",argv[a],step,lat,names[s],rawl1,finall1,noclipl1,clipmass,clipsigned,botl1);
   for(int o=1;o<5;o++){
    long negatives=0,scaled_negatives=0;double min=0,scaled_min=0,negative_mass=0,scaled_negative_mass=0;
    double target_signed=0,target_l1=0,target_max=0;
    for(int k=0;k<nz;k++)for(int i=0;i<nx;i++){
     size_t v=(size_t)k*nx+i,pc=(size_t)b*nx+i;double value=counter[(size_t)(b+o)*cell+v],factor=(k>=top&&safe[pc])?num[pc]/den[pc]:1;
     if(value<0){negatives++;if(value<min)min=value;negative_mass+=value*ad[v];}
     double scaled=value*factor;if(!isfinite(scaled))fail("nonfinite scaled counterfactual");
     if(scaled<0){scaled_negatives++;if(scaled<scaled_min)scaled_min=scaled;scaled_negative_mass+=scaled*ad[v];}
    }
    for(int i=0;i<nx;i++){
     size_t pc=(size_t)b*nx+i,oc=(size_t)(b+o)*nx+i;double factor=safe[pc]?num[pc]/den[pc]:1,mass=0;
     for(int k=top;k<nz;k++){size_t v=(size_t)k*nx+i;mass+=counter[(size_t)(b+o)*cell+v]*factor*ad[v];}
     double residual=mass-num[oc];if(!isfinite(residual))fail("nonfinite counterfactual origin target residual");
     target_signed+=residual;target_l1+=fabs(residual);if(fabs(residual)>target_max)target_max=fabs(residual);
    }
    if(!isfinite(negative_mass)||!isfinite(scaled_negative_mass)||!isfinite(target_signed)||!isfinite(target_l1)||!isfinite(target_max))fail("nonfinite counterfactual negative inventory or target");
    fprintf(stderr,"PROBE_ORIGIN file=%s step=%d lat=%d parent=%s origin=%d negative_raw_cells=%ld minimum_raw_kgkg=%.17g negative_raw_kg=%.17g negative_shared_factor_cells=%ld minimum_shared_factor_kgkg=%.17g negative_shared_factor_kg=%.17g target_signed_error_kg=%.17g target_column_L1_error_kg=%.17g target_max_column_error_kg=%.17g ENGINEERING_ONLY_SIGNED\n",argv[a],step,lat,names[s],o,negatives,min,negative_mass,scaled_negatives,scaled_min,scaled_negative_mass,target_signed,target_l1,target_max);
   }
   for(int p=0;p<6;p++){
    double mass=0,signedr=0,l1=0,max=0;long negative[5]={0};
    for(size_t v=0;v<cell;v++){
     double parent=q[p][(size_t)b*cell+v],r=0;mass+=parent*ad[v];
     for(int o=0;o<5;o++)if(q[p][(size_t)(b+o)*cell+v]<0)negative[o]++;
     for(int o=1;o<5;o++)r+=q[p][(size_t)(b+o)*cell+v];
     r=(r-parent)*ad[v];signedr+=r;l1+=fabs(r);if(fabs(r)>max)max=fabs(r);
    }
    if(!isfinite(mass)||!isfinite(signedr)||!isfinite(l1)||!isfinite(max))fail("nonfinite derived phase inventory");
    printf("%s,%d,%d,%d,%s,%.17g,%.17g,%.17g,%.17g,%ld,%ld,%ld,%ld,%ld,%ld,%ld,%.17g,%.17g\n",argv[a],step,lat,p+1,names[s],mass,signedr,l1,max,negative[0],negative[1],negative[2],negative[3],negative[4],rbdis,scdis,src,srcL1);
   }
  }
  for(int p=0;p<6;p++)free(q[p]);
  free(ad);free(area);free(flx);free(threshold);free(mask);free(safe);free(num);free(den);
  free(cc);free(ze);free(term);free(bot);free(actualdiff);free(shared);free(counter);
 }
 return 0;
}
