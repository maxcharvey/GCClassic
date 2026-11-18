PROGRAM TestHeightScale
  USE HCO_PRECISION_MOD, ONLY: hp => f8
  USE HCOX_FINN_PROFILE_KERNEL_MOD
  USE, INTRINSIC :: IEEE_ARITHMETIC
  IMPLICIT NONE
  REAL(hp) :: H(4), X(4), W(4), E(4), Overflow, Bad, Factor
  REAL(hp), ALLOCATABLE :: Heights(:), Input(:), Weight(:), Edges(:), Expected(:)
  REAL(hp) :: Below, Above, MeanBefore, MeanAfter
  INTEGER :: S, J, K, L, N, Assertions
  Assertions=0
  H=[100.0_hp,200.0_hp,300.0_hp,1000.0_hp]
  X=[0.0_hp,1.0_hp,0.0_hp,0.0_hp]
  CALL FINN_Scale_Height(X,H,0.8_hp,W,Overflow,S)
  CALL Check(S==0 .AND. Overflow==0.0_hp,'lower succeeds')
  CALL Check(MAXVAL(ABS(W-[0.125_hp,0.875_hp,0.0_hp,0.0_hp]))<1.0e-14_hp, &
       'analytic lower overlap across unequal layers')
  CALL FINN_Scale_Height(X,H,1.2_hp,W,Overflow,S)
  CALL Check(S==0 .AND. Overflow==0.0_hp,'higher succeeds')
  CALL Check(MAXVAL(ABS(W-[0.0_hp,0.75_hp,0.25_hp,0.0_hp]))<1.0e-14_hp, &
       'analytic higher overlap across unequal layers')
  CALL FINN_Allocate(3.75e-8_hp,W,E,S)
  CALL Check(S==0 .AND. ABS(SUM(E)/3.75e-8_hp-1.0_hp)<1.0e-14_hp,'unchanged column mass')
  X=[0.2_hp,0.3_hp,0.5_hp,0.0_hp]
  CALL FINN_Scale_Height(X,H,1.0_hp,W,Overflow,S)
  CALL Check(S==0 .AND. ALL(W==X),'identity bitwise values')
  H=IEEE_VALUE(1.0_hp,IEEE_QUIET_NAN)
  CALL FINN_Scale_Height(X,H,1.0_hp,W,Overflow,S)
  CALL Check(S==0 .AND. ALL(W==X),'identity does not require geometry')
  CALL FINN_Scale_Height(X,H,0.8_hp,W,Overflow,S)
  CALL Check(S==2 .AND. ALL(W==0),'NaN geometry rejected')
  H=[100.0_hp,200.0_hp,300.0_hp,1000.0_hp]
  X=[1.0_hp,0.0_hp,0.0_hp,0.0_hp]
  CALL FINN_Scale_Height(X,H,0.8_hp,W,Overflow,S)
  CALL Check(S==0 .AND. ALL(W==X),'surface compression retains surface mass')
  CALL FINN_Scale_Height(X,H,1.2_hp,W,Overflow,S)
  CALL Check(S==0 .AND. ABS(W(1)-5.0_hp/6.0_hp)<1.0e-14_hp .AND. &
       ABS(W(2)-1.0_hp/6.0_hp)<1.0e-14_hp,'surface expansion has no loss')
  X=[0.0_hp,0.0_hp,0.0_hp,1.0_hp]
  CALL FINN_Scale_Height(X,H,1.2_hp,W,Overflow,S)
  CALL Check(S==3 .AND. ALL(W==0) .AND. ABS(Overflow-4.0_hp/15.0_hp)<1.0e-14_hp, &
       'top overflow is reported and rejected rather than clipped')
  CALL FINN_Scale_Height(X,H,0.8_hp,W,Overflow,S)
  CALL Check(S==0 .AND. Overflow==0 .AND. ABS(SUM(W)-1.0_hp)<1.0e-14_hp,'top compression closes')
  X=[0.0_hp,1.0_hp,0.0_hp,0.0_hp]
  DO J=1,5
     SELECT CASE(J)
     CASE(1)
        Bad=0.0_hp
     CASE(2)
        Bad=-0.8_hp
     CASE(3)
        Bad=IEEE_VALUE(1.0_hp,IEEE_QUIET_NAN)
     CASE(4)
        Bad=IEEE_VALUE(1.0_hp,IEEE_POSITIVE_INF)
     CASE(5)
        Bad=HUGE(1.0_hp)
     END SELECT
     CALL FINN_Scale_Height(X,H,Bad,W,Overflow,S)
     CALL Check(S==2 .AND. ALL(W==0),'invalid/overflowing factor rejected')
  ENDDO
  H(1)=0
  CALL FINN_Scale_Height(X,H,0.8_hp,W,Overflow,S)
  CALL Check(S==2,'zero layer depth rejected')
  H(1)=-1
  CALL FINN_Scale_Height(X,H,0.8_hp,W,Overflow,S)
  CALL Check(S==2,'negative layer depth rejected')
  H(1)=100
  X(1)=-1
  CALL FINN_Scale_Height(X,H,0.8_hp,W,Overflow,S)
  CALL Check(S==2,'negative weight rejected')
  X=[0.0_hp,0.5_hp,0.0_hp,0.0_hp]
  CALL FINN_Scale_Height(X,H,0.8_hp,W,Overflow,S)
  CALL Check(S==2,'nonclosing input rejected')
  CALL FINN_Scale_Height(X,H(:3),0.8_hp,W,Overflow,S)
  CALL Check(S==2,'inconsistent dimensions rejected')

  ! An independent CDF oracle: evaluate original cumulative mass at z/s.
  ! Verify dense and multimodal/sparse profiles on 47 and 72 unequal layers.
  DO J=1,4
     N=47
     IF (J>2) N=72
     ALLOCATE(Heights(N),Input(N),Weight(N),Edges(0:N),Expected(N))
     DO K=1,N
        Heights(K)=100.0_hp+11.0_hp*K*K
     ENDDO
     Input=0
     IF (MOD(J,2)==1) THEN
        Input(1:30)=[(REAL(MOD(K*7,19)+1,hp),K=1,30)]
     ELSE
        Input(2)=0.1_hp
        Input(17)=0.6_hp
        Input(30)=0.3_hp
     ENDIF
     CALL FINN_Normalize(Input,Weight,S)
     Input=Weight
     Edges(0)=0
     DO K=1,N
        Edges(K)=Edges(K-1)+Heights(K)
     ENDDO
     MeanBefore=SUM(Input*(Edges(1:)+Edges(:N-1))*0.5_hp)
     DO L=1,2
        Factor=0.8_hp
        IF (L==2) Factor=1.2_hp
        CALL FINN_Scale_Height(Input,Heights,Factor,Weight,Overflow,S)
        CALL Check(S==0 .AND. Overflow==0 .AND. ALL(Weight>=0),'nonuniform multilevel remap succeeds')
        Below=0
        DO K=1,N
           Above=SUM(Input*MAX(0.0_hp,MIN(1.0_hp,(Edges(K)/Factor-Edges(:N-1))/Heights)))
           Expected(K)=Above-Below
           Below=Above
        ENDDO
        CALL Check(MAXVAL(ABS(Weight-Expected))<2.0e-14_hp,'independent CDF oracle')
        CALL Check(ABS(SUM(Weight)-1.0_hp)<1.0e-14_hp,'profile fraction closure')
        MeanAfter=SUM(Weight*(Edges(1:)+Edges(:N-1))*0.5_hp)
        IF (Factor<1) THEN
           CALL Check(MeanAfter<MeanBefore,'lower mean altitude')
        ELSE
           CALL Check(MeanAfter>MeanBefore,'higher mean altitude')
        ENDIF
        ! Bound the binned-mean error by half the largest receiving layer.
        CALL Check(ABS(MeanAfter-Factor*MeanBefore)<=0.5_hp*MAXVAL(Heights,Weight>0), &
             'continuous height moment within discretization bound')
     ENDDO
     DEALLOCATE(Heights,Input,Weight,Edges,Expected)
  ENDDO
  PRINT *, 'PASS height-scale kernel assertions:',Assertions
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
END PROGRAM TestHeightScale
