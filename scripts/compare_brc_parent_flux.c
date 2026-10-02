/* Compare the immutable parent portion of two captures. Origin prestates are
   intentionally separate payloads; parent/geometry equality remains exact. */
#define main capture_reader_program
#include "audit_brc_parent_flux.c"
#undef main
static int compare(Data *a,Data *b,const char *name,double *x,double *y,size_t length){
 double scale=0,max=0,l1=0;size_t differing=0,first=0;
 for(size_t i=0;i<length;i++){double diff=fabs(x[i]-y[i]);if(diff){if(!differing)first=i;differing++;}scale=fmax(scale,fabs(x[i]));max=fmax(max,diff);l1+=diff;}
 printf("COMPARE %s %s differing=%zu first_index=%zu maxabs=%.17g relative_max=%.9g unweighted_L1=%.17g %s\n",a->name,name,differing,first,max,max/fmax(scale,1e-300),l1,differing?"FAIL":"PASS");(void)b;return differing>0;
}
static void metadata(const char *path,uint32_t *h){FILE *f=fopen(path,"rb");if(!f)FAIL("cannot open metadata");char prefix[16];exact(f,prefix,16);exact(f,h,16*sizeof(uint32_t));fclose(f);if(h[11]==0x04030201){for(int i=0;i<16;i++)h[i]=swap32(h[i]);}else if(h[11]!=0x01020304)FAIL("invalid endian metadata");}
int main(int argc,char **argv){
 if(argc!=3)return 2;uint32_t ha[16],hb[16];metadata(argv[1],ha);metadata(argv[2],hb);for(int i=0;i<16;i++)if(i!=10 && ha[i]!=hb[i])FAIL("incompatible capture header");Data a=load(argv[1]),b=load(argv[2]);
 if(strcmp(a.name,b.name)||a.nx!=b.nx||a.ny!=b.ny||a.nz!=b.nz||a.width!=b.width||a.dt!=b.dt||a.pc!=b.pc)FAIL("incompatible captures");
 int failed=0;
#define CHECK(field,length) failed+=compare(&a,&b,#field,a.field,b.field,length)
 CHECK(area,a.ny);CHECK(geo,a.ny);CHECK(dp1,a.n);CHECK(dp2,a.n);CHECK(cx,a.n);CHECK(cy,a.n);CHECK(wz,a.n);
 CHECK(raw,a.n);CHECK(pole,a.n);CHECK(x,a.n);CHECK(y,a.n);CHECK(predict,a.n);CHECK(z,a.n);CHECK(clean,a.n);CHECK(final,a.n);CHECK(fx,a.n);CHECK(fy,(size_t)a.nx*(a.ny+1)*a.nz);CHECK(fz,a.n);
 printf("SUMMARY parent_capture_stages_failed=%d strict=%s\n",failed,failed?"FAIL":"PASS");release(&a);release(&b);return failed?1:0;
}
