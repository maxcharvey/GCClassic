/* Append explicit zero fire-origin and parent-valued untagged variables to a
   NEW copy of a parent restart. Source must never be opened for writing. */
#include <netcdf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define OK(x) do{int e=(x);if(e){fprintf(stderr,"%s: %s\n",#x,nc_strerror(e));exit(2);}}while(0)
int main(int argc,char **argv){
 if(argc!=2){fprintf(stderr,"Usage: %s NEW_RESTART_COPY.nc4\n",argv[0]);return 2;}
 const char *parents[]={"FSOAP","FSOAS","BRCSOA","NPBRCPOA","WTC","PBRCPOA","DBRCPOA"};
 const char *origins[]={"USA","CAN","ROW","UNT"};int f;OK(nc_open(argv[1],NC_WRITE,&f));
 int parent[7],tag[7][4];size_t sizes[7];
 /* Validate all parent fields and absence of all overlay names before editing. */
 for(int s=0;s<7;s++){char name[96];sprintf(name,"SpeciesRst_%s",parents[s]);OK(nc_inq_varid(f,name,&parent[s]));
  for(int o=0;o<4;o++){int v;sprintf(name,"SpeciesRst_%s_%s",parents[s],origins[o]);if(nc_inq_varid(f,name,&v)==NC_NOERR){fprintf(stderr,"Existing origin field: %s\n",name);return 1;}}
 }
 OK(nc_redef(f));
 for(int s=0;s<7;s++){
  nc_type type;int nd,ids[NC_MAX_VAR_DIMS],na;OK(nc_inq_var(f,parent[s],NULL,&type,&nd,ids,&na));
  sizes[s]=1;for(int d=0;d<nd;d++){size_t n;OK(nc_inq_dimlen(f,ids[d],&n));sizes[s]*=n;}
  for(int o=0;o<4;o++){char name[96],desc[160];sprintf(name,"SpeciesRst_%s_%s",parents[s],origins[o]);OK(nc_def_var(f,name,type,nd,ids,&tag[s][o]));OK(nc_def_var_deflate(f,tag[s][o],1,1,1));
   for(int a=0;a<na;a++){char att[NC_MAX_NAME+1];OK(nc_inq_attname(f,parent[s],a,att));OK(nc_copy_att(f,parent[s],att,f,tag[s][o]));}
   sprintf(desc,"Diagnostic %s origin partition of %s",origins[o],parents[s]);OK(nc_put_att_text(f,tag[s][o],"long_name",strlen(desc),desc));
  }
 }
 const char *label="USA,CAN,ROW zero at cohort start; UNT equals parent restart; diagnostic overlays excluded from physical aerosol bins";
 OK(nc_put_att_text(f,NC_GLOBAL,"brc_origin_initialization",strlen(label),label));OK(nc_enddef(f));
 for(int s=0;s<7;s++){double *values=malloc(sizes[s]*sizeof(double)),*zeros=calloc(sizes[s],sizeof(double));if(!values||!zeros)return 2;OK(nc_get_var_double(f,parent[s],values));
  for(int o=0;o<4;o++)OK(nc_put_var_double(f,tag[s][o],o==3?values:zeros));
  printf("INITIALIZED %s origins=4 cells=%zu UNT=parent USA/CAN/ROW=0\n",parents[s],sizes[s]);free(values);free(zeros);
 }
 OK(nc_close(f));return 0;
}
