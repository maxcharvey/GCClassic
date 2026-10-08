/* Reporting only. No optimizer, plan updates, or bridge calls. */
#include <stdio.h>
#include <stdlib.h>
#include "stable_kl_receipt.h"
int main(void){
 long double prior[128*128],plan[128*128];int id,n,expected=0;
 for(;;){
  int scan=scanf("%d %d",&id,&n);
  if(scan==EOF)break;
  if(scan!=2||id!=expected||n<1||n>128*128)return 2;
  for(int i=0;i<n;i++)if(scanf("%La %La",&prior[i],&plan[i])!=2)return 2;
  long double value;
  if(!stable_kl_sum(n,plan,prior,&value))return 3;
  printf("STABLE_KL %d %La\n",id,value);expected++;
 }
 return expected==14&&!ferror(stdin)&&!ferror(stdout)?0:2;
}
