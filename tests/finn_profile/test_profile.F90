PROGRAM TestProfile
  USE HCO_PRECISION_MOD, ONLY: hp => f8
  USE HCOX_FINN_PROFILE_KERNEL_MOD
  USE, INTRINSIC :: IEEE_ARITHMETIC
  IMPLICIT NONE
  REAL(hp), ALLOCATABLE :: X(:), W(:), E(:)
  REAL(hp) :: Bad, F
  INTEGER :: N, S, J, Assertions, Why
  REAL(hp) :: D(4), HW(4)
  Assertions=0
  DO J=1,2
     N=47
     IF (J==2) N=72
     ALLOCATE(X(N),W(N),E(N))
     X=0
     CALL FINN_Normalize(X,W,S)
     CALL Check(S==1 .AND. ALL(W==0.0_hp),'empty reference')
     X=1
     CALL FINN_Normalize(X,W,S)
     CALL Check(S==0 .AND. MAXVAL(ABS(W-1.0_hp/N))<1.0e-14_hp,'flat weights')
     F=3.75e-8_hp
     CALL FINN_Allocate(F,W,E,S)
     CALL Check(S==0 .AND. ALL(E>=0) .AND. ABS(SUM(E)/F-1.0_hp)<1.0e-14_hp,'flat allocation')
     X=0
     X(17)=7
     CALL FINN_Normalize(X,W,S)
     CALL FINN_Allocate(F,W,E,S)
     CALL Check(S==0 .AND. E(17)==F .AND. COUNT(E/=0)==1,'single layer')
     X=0
     X(1)=HUGE(1.0_hp)/4
     X(N)=HUGE(1.0_hp)/4
     CALL FINN_Normalize(X,W,S)
     CALL Check(S==0 .AND. W(1)==0.5_hp .AND. W(N)==0.5_hp,'large normalization')
     X=0
     X(1)=TINY(1.0_hp)
     CALL FINN_Normalize(X,W,S)
     CALL Check(S==0 .AND. W(1)==1,'tiny normalization')
     CALL FINN_Allocate(0.0_hp,W,E,S)
     CALL Check(S==0 .AND. ALL(E==0),'zero flux')
     CALL FINN_Allocate(-1.0_hp,W,E,S)
     CALL Check(S==2,'negative source')
     X=1
     X(3)=-1
     CALL FINN_Normalize(X,W,S)
     CALL Check(S==2,'negative reference')
     Bad=IEEE_VALUE(1.0_hp,IEEE_QUIET_NAN)
     X(3)=Bad
     CALL FINN_Normalize(X,W,S)
     CALL Check(S==2,'NaN reference')
     X(3)=IEEE_VALUE(1.0_hp,IEEE_POSITIVE_INF)
     CALL FINN_Normalize(X,W,S)
     CALL Check(S==2,'infinite reference')
     W=0
     W(1)=0.5_hp
     CALL FINN_Allocate(F,W,E,S)
     CALL Check(S==2,'nonclosing weights')
     X=0
     X(1:3)=[1.0_hp,1.0_hp,0.25_hp]
     CALL FINN_Normalize(X,W,S)
     CALL Check(S==0 .AND. ABS(W(3)-1.0_hp/9)<1.0e-15_hp,'partial PBL fallback')
     DEALLOCATE(X,W,E)
  ENDDO
  D=100.0_hp
  CALL FINN_HeightProfile(150.0_hp,250.0_hp,0.0_hp,D,.FALSE.,HW,Why,S)
  CALL Check(S==0 .AND. MAXVAL(ABS(HW-[2.0_hp/3,1.0_hp/3,0.0_hp,0.0_hp]))<1e-14_hp,'uniform partial layer')
  CALL FINN_HeightProfile(100.0_hp,200.0_hp,0.0_hp,D,.TRUE.,HW,Why,S)
  CALL Check(S==0 .AND. MAXVAL(ABS(HW-[0.5_hp,0.5_hp,0.0_hp,0.0_hp]))<1e-14_hp,'Gaussian symmetry')
  CALL FINN_HeightProfile(100.0_hp,100.0_hp,0.0_hp,D,.TRUE.,HW,Why,S)
  CALL Check(S==0 .AND. HW(2)==1.0_hp .AND. SUM(HW)==1.0_hp,'point on interior edge')
  CALL FINN_HeightProfile(400.0_hp,400.0_hp,0.0_hp,D,.TRUE.,HW,Why,S)
  CALL Check(S==0 .AND. HW(4)==1.0_hp,'point on model top')
  CALL FINN_HeightProfile(-30.0_hp,30.0_hp,-50.0_hp,D,.FALSE.,HW,Why,S)
  CALL Check(S==0 .AND. HW(1)==1.0_hp,'below-sea-level datum')
  CALL FINN_HeightProfile(50.0_hp,100.0_hp,100.0_hp,D,.FALSE.,HW,Why,S)
  CALL Check(S==1 .AND. Why==2 .AND. ALL(HW==0.0_hp),'terrain fallback')
  CALL FINN_HeightProfile(150.0_hp,100.0_hp,0.0_hp,D,.TRUE.,HW,Why,S)
  CALL Check(S==2,'reversed heights rejected')
  CALL FINN_HeightProfile(500.0_hp,600.0_hp,0.0_hp,D,.FALSE.,HW,Why,S)
  CALL Check(S==3,'uniform above model')
  CALL FINN_HeightProfile(350.0_hp,450.0_hp,0.0_hp,D,.TRUE.,HW,Why,S)
  CALL Check(S==3,'Gaussian above model')
  CALL FINN_HeightProfile(100.0_hp,500.0_hp,0.0_hp,D,.TRUE.,HW,Why,S)
  CALL Check(S==0 .AND. HW(3)==0.0_hp .AND. HW(4)==0.0_hp,'explicit capped symmetric support')
  D(2)=0.0_hp
  CALL FINN_HeightProfile(100.0_hp,200.0_hp,0.0_hp,D,.TRUE.,HW,Why,S)
  CALL Check(S==2,'invalid model geometry')
  D=100.0_hp
  CALL FINN_HeightProfile(Bad,200.0_hp,0.0_hp,D,.TRUE.,HW,Why,S)
  CALL Check(S==2,'nonfinite height')
  PRINT *, 'PASS profile kernel assertions:',Assertions
CONTAINS
  SUBROUTINE Check(OK,Label)
    LOGICAL, INTENT(IN) :: OK
    CHARACTER(LEN=*), INTENT(IN) :: Label
    IF (.NOT.OK) THEN
       PRINT *, 'FAIL: ',Label
       STOP 1
    ENDIF
    Assertions=Assertions+1
  END SUBROUTINE Check
END PROGRAM TestProfile
