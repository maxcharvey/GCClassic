PROGRAM TEST_BRC_ORIGIN_SOURCE
  USE HCO_PRECISION_MOD, ONLY: fp
  USE HCOX_ORIGIN_SOURCE_KERNEL_MOD, ONLY: ORIGIN_SOURCE_ALLOCATE
  USE, INTRINSIC :: IEEE_ARITHMETIC, ONLY: IEEE_VALUE,IEEE_QUIET_NAN,IEEE_IS_FINITE
  IMPLICIT NONE
  REAL(fp) :: Raw(3),Parts(3),Relative,Tolerance,Rare,Parent,Injected
  INTEGER :: Status,O,K
  Tolerance=5.0e-5_fp
  IF (STORAGE_SIZE(Parts)>32) Tolerance=5.0e-12_fp
  DO O=1,3
    Raw=0.0_fp;Raw(O)=3.0_fp;Parts=-42.0_fp
    CALL ORIGIN_SOURCE_ALLOCATE(3.0_fp,Raw,1.05_fp,Parts,Status,Relative)
    CALL REQUIRE(Status==0,'pure country status')
    CALL REQUIRE(Parts(O)==1.05_fp,'pure country actual injection')
    DO K=1,3
      IF (K/=O) CALL REQUIRE(Parts(K)==0.0_fp,'zero geographic support')
    ENDDO
    CALL RECEIPT(3.0_fp,1.05_fp)
  ENDDO
  Raw=[1.0_fp,2.0_fp,3.0_fp]
  DO K=1,3
    Injected=REAL(K,fp)*0.35_fp
    CALL ORIGIN_SOURCE_ALLOCATE(6.0_fp,Raw,Injected,Parts,Status,Relative)
    CALL REQUIRE(Status==0,'fraction status')
    CALL REQUIRE(ABS(SUM(Parts)-Injected)<=Tolerance*Injected,'actual source closure')
    CALL REQUIRE(ALL(ABS(Parts-Injected*Raw/6.0_fp)<=Tolerance*Injected),'fractions')
    CALL RECEIPT(6.0_fp,Injected)
  ENDDO
  Rare=1.0e-20_fp
  Raw=[1.0_fp,1.0_fp,Rare]
  CALL ORIGIN_SOURCE_ALLOCATE(2.0_fp,Raw,0.7_fp,Parts,Status,Relative)
  CALL REQUIRE(Status==0 .AND. Parts(3)>0.0_fp,'rare supported source retained')
  CALL REQUIRE(ABS(Parts(3)/(0.35_fp*Rare)-1.0_fp)<=Tolerance,'rare fraction accuracy')
  CALL RECEIPT(2.0_fp,0.7_fp)
  Raw=[1.0_fp,2.0_fp,3.0_fp]*(1.0_fp+1.0e-7_fp)
  CALL ORIGIN_SOURCE_ALLOCATE(6.0_fp,Raw,0.7_fp,Parts,Status,Relative)
  CALL REQUIRE(Status==0,'raw source precision correction')
  CALL REQUIRE(ABS(SUM(Parts)-0.7_fp)<=Tolerance*0.7_fp,'corrected source closure')
  CALL RECEIPT(6.0_fp,0.7_fp)
  Raw=0.0_fp
  CALL ORIGIN_SOURCE_ALLOCATE(0.0_fp,Raw,0.0_fp,Parts,Status,Relative)
  CALL REQUIRE(Status==0 .AND. ALL(Parts==0.0_fp),'empty source')
  CALL RECEIPT(0.0_fp,0.0_fp)
  Parts=-42.0_fp
  CALL ORIGIN_SOURCE_ALLOCATE(1.0_fp,Raw,1.0_fp,Parts,Status,Relative)
  CALL REFUSAL(2,'unsupported positive parent')
  Raw=[1.0_fp,0.0_fp,0.0_fp]
  CALL ORIGIN_SOURCE_ALLOCATE(0.0_fp,Raw,0.0_fp,Parts,Status,Relative)
  CALL REFUSAL(2,'positive raw source without parent')
  CALL ORIGIN_SOURCE_ALLOCATE(2.0_fp,Raw,1.0_fp,Parts,Status,Relative)
  CALL REFUSAL(3,'inconsistent source weights')
  Raw(1)=-1.0_fp
  CALL ORIGIN_SOURCE_ALLOCATE(1.0_fp,Raw,1.0_fp,Parts,Status,Relative)
  CALL REFUSAL(1,'negative source')
  Raw(1)=IEEE_VALUE(1.0_fp,IEEE_QUIET_NAN)
  CALL ORIGIN_SOURCE_ALLOCATE(1.0_fp,Raw,1.0_fp,Parts,Status,Relative)
  CALL REFUSAL(1,'nonfinite source')
  ! Subnormal-free guaranteed representational loss of rare injected material.
  Raw=[TINY(1.0_fp),1.0_fp,0.0_fp];Parent=1.0_fp;Injected=TINY(1.0_fp)
  CALL ORIGIN_SOURCE_ALLOCATE(Parent,Raw,Injected,Parts,Status,Relative)
  CALL REFUSAL(4,'explicit representational underflow')
  Raw=[0.75_fp*HUGE(1.0_fp),0.75_fp*HUGE(1.0_fp),0.0_fp]
  CALL ORIGIN_SOURCE_ALLOCATE(HUGE(1.0_fp),Raw,1.0_fp,Parts,Status,Relative)
  CALL REFUSAL(1,'finite-input overflow refusal')
  WRITE(*,'(a,i0,a)') 'PASS source allocation precision=',STORAGE_SIZE(Parent),' bits; live forcing untested'
CONTAINS
  SUBROUTINE RECEIPT(P,E)
    REAL(fp), INTENT(IN) :: P,E
    WRITE(*,*) 'ALLOC',P,Raw,E,Parts,Relative,Status
  END SUBROUTINE RECEIPT
  SUBROUTINE REQUIRE(Condition,Label)
    LOGICAL, INTENT(IN) :: Condition
    CHARACTER(LEN=*), INTENT(IN) :: Label
    IF (.NOT. Condition) THEN
      WRITE(*,*) 'FAIL ',Label
      STOP 1
    ENDIF
  END SUBROUTINE REQUIRE
  SUBROUTINE REFUSAL(Expected,Label)
    INTEGER, INTENT(IN) :: Expected
    CHARACTER(LEN=*), INTENT(IN) :: Label
    CALL REQUIRE(Status==Expected,Label)
    CALL REQUIRE(ALL(Parts==-42.0_fp),'atomic source refusal')
  END SUBROUTINE REFUSAL
END PROGRAM TEST_BRC_ORIGIN_SOURCE
