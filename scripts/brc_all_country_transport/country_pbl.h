#ifndef COUNTRY_PBL_H
#define COUNTRY_PBL_H
#include <stddef.h>
enum acp_status {ACP_OK, ACP_INVALID, ACP_OVERDRAFT, ACP_NEGATIVE_RHS,
 ACP_ZERO_SUPPORT, ACP_UNDERFLOW, ACP_CAPACITY, ACP_TARGET, ACP_SOLVER,
 ACP_OUTPUT, ACP_RESOURCE};
struct acp_solver_receipt {int rows,columns;};
struct acp_donors {const int *origin,*layer,*is_source;};
typedef int (*acp_solver)(int,int,const long double *,const long double *,
 const long double *,long double *,const struct acp_donors *,struct acp_solver_receipt *);
struct acp_receipt {
 int status,levels,origins,donors,solver_status;
 size_t workspace_bytes;
 long double row_error,column_error,origin_error,total_error;
};
/* Inputs top-to-bottom layer-major, origin-fast. Caller binds units/provenance.
   Solver sees receiver rows/donor columns. No dynamic optimizer is supplied. */
int country_pbl(int,int,const long double *,const long double *,const long double *,
 const long double *,const long double *,const long double *,long double,
 const long double *,const long double *,acp_solver,size_t,long double *,struct acp_receipt *);
int country_pbl_bundle(int,int,const long double *,const long double *,const long double *,
 const long double *,const long double *,const long double *,const long double *,
 const long double *,const long double *,acp_solver,size_t,long double *,struct acp_receipt *);
#endif
