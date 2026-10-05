PROGRAM TestLegacyFallback
 USE HCO_PRECISION_MOD, ONLY: hp => f8
 USE HCOX_FIRE_INJECTION_MOD, ONLY: HCOX_FireInject_Profile
 IMPLICIT NONE
 REAL(hp) :: PBL(47), Edge(48), P(47), Flux
 INTEGER :: K,S,N
 N=0; Flux=3.75e-8_hp
 DO K=1,48
  Edge(K)=1000.0_hp-20.0_hp*(K-1)
 ENDDO
 PBL=0;PBL(1:3)=[0.4_hp,0.4_hp,0.2_hp]
 CALL HCOX_FireInject_Profile(Flux,PBL,Edge,0.35_hp,15,P,S)
 CALL Check(S==0,'partial-PBL accepted')
 CALL Check(ABS(SUM(P)/Flux-1.0_hp)<1e-14_hp,'source closure')
 CALL Check(ABS(SUM(P(1:3))/Flux-0.65_hp)<1e-14_hp,'65 percent in PBL')
 CALL Check(ABS(SUM(P(4:18))/Flux-0.35_hp)<1e-14_hp,'35 percent in 15 levels')
 CALL Check(ALL(P>=0).AND.ALL(P(19:)==0),'nonnegative and exact support')
 CALL Check(MAXVAL(ABS(P(1:3)/Flux-[0.26_hp,0.26_hp,0.13_hp]))<1e-14_hp,'partial PBL normalized')
 CALL Check(MAXVAL(ABS(P(4:18)/Flux-0.35_hp/15))<1e-14_hp,'pressure weighting')
 DO K=1,48
  Edge(K)=1000.0_hp-0.2_hp*(K-1)**2
 ENDDO
 CALL HCOX_FireInject_Profile(Flux,PBL,Edge,0.35_hp,15,P,S)
 CALL Check(S==0.AND.ABS(SUM(P)/Flux-1.0_hp)<1e-14_hp,'nonuniform-pressure closure')
 CALL Check(MAXVAL(ABS(P(4:18)/Flux-0.35_hp*(Edge(4:18)-Edge(5:19))/ &
      (Edge(4)-Edge(19))))<1e-14_hp,'nonuniform pressure-weighted fractions')
 CALL HCOX_FireInject_Profile(0.0_hp,PBL,Edge,0.35_hp,15,P,S)
 CALL Check(S==0.AND.ALL(P==0),'source-free exact zero')
 PBL=0;PBL(1:35)=1.0_hp/35
 CALL HCOX_FireInject_Profile(Flux,PBL,Edge,0.35_hp,15,P,S)
 CALL Check(S==2,'insufficient levels refused')
 PBL=0
 CALL HCOX_FireInject_Profile(Flux,PBL,Edge,0.35_hp,15,P,S)
 CALL Check(S==1,'empty PBL refused')
 PBL(1)=-1
 CALL HCOX_FireInject_Profile(Flux,PBL,Edge,0.35_hp,15,P,S)
 CALL Check(S/=0,'negative PBL refused')
 PBL=0;PBL(1)=1
 CALL HCOX_FireInject_Profile(-Flux,PBL,Edge,0.35_hp,15,P,S)
 CALL Check(S/=0,'negative source refused')
 Edge(2)=Edge(1)
 CALL HCOX_FireInject_Profile(Flux,PBL,Edge,0.35_hp,15,P,S)
 CALL Check(S/=0,'nondecreasing pressure refused')
 CALL HCOX_FireInject_Profile(Flux,PBL,Edge,0.0_hp,0,P,S)
 CALL Check(S==0.AND.P(1)==Flux.AND.ALL(P(2:)==0),'legacy surface zero-control')
 PRINT *, 'PASS legacy fallback assertions:',N
CONTAINS
 SUBROUTINE Check(OK,Label)
 LOGICAL, INTENT(IN):: OK
 CHARACTER(LEN=*),INTENT(IN):: Label
 IF(.NOT.OK) THEN
  PRINT *, 'FAIL: ',Label
  STOP 1
 ENDIF
 N=N+1
 END SUBROUTINE
END PROGRAM
