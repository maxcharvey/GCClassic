PROGRAM test_brc_origin_kernel
  USE Precision_Mod, ONLY: fp
  USE BRC_ORIGIN_KERNEL_MOD
  USE, INTRINSIC :: IEEE_ARITHMETIC
  IMPLICIT NONE
  REAL(fp) :: p(4),lost(4),before(4), state(7,4),parent(7),stock(4),finish(4),r(28)
  REAL(fp) :: total,new, factor,tol
  INTEGER :: status,i,n,seedsize
  INTEGER, ALLOCATABLE :: seed(:)
  tol=1000*EPSILON(1.0_fp)
  p=[1.0_fp,2.0_fp,3.0_fp,4.0_fp]; before=p
  CALL BRC_ORIGIN_SPLIT_LOSS(10.0_fp,7.5_fp,p,lost,status)
  CALL check(status==0 .AND. MAXVAL(ABS(p-before*0.75_fp))<tol,'mixed loss')
  CALL check(MAXVAL(ABS(p+lost-before))<tol,'mass closure')
  p=[1.e-23_fp,2.e-23_fp,3.e-23_fp,4.e-23_fp]
  CALL BRC_ORIGIN_SPLIT_LOSS(1.e-22_fp,0.0_fp,p,lost,status)
  CALL check(status==0 .AND. ALL(p==0.0_fp) .AND. SUM(lost)>0,'actual parent cutoff')
  p=[1.0_fp,0.0_fp,0.0_fp,0.0_fp]
  CALL BRC_ORIGIN_SPLIT_LOSS(0.0_fp,0.0_fp,p,lost,status)
  CALL check(status==0 .AND. p(1)==1 .AND. ALL(lost==0),'zero carrier preserves residual')
  before=p
  CALL BRC_ORIGIN_SPLIT_LOSS(1.0_fp,2.0_fp,p,lost,status)
  CALL check(status/=0 .AND. ALL(p==before),'invalid growth atomic refusal')
  CALL BRC_ORIGIN_SPLIT_LOSS(IEEE_VALUE(1.0_fp,IEEE_QUIET_NAN),0.0_fp,p,lost,status)
  CALL check(status/=0 .AND. ALL(p==before),'nonfinite refusal')
  ! Deterministic full-chain synthetic tests, with fresh precursor and product
  ! origins inherited before each downstream parent operator.
  CALL RANDOM_SEED(SIZE=seedsize);ALLOCATE(seed(seedsize));seed=48271
  CALL RANDOM_SEED(PUT=seed)
  factor=1.7_fp
  DO n=1,256
    CALL RANDOM_NUMBER(r);state=RESHAPE(r,[7,4]);parent=SUM(state,DIM=2)
    stock=(state(1,:)+state(2,:))/factor+SUM(state(3:7,:),DIM=1)
    DO i=1,4
      total=parent(i); new=total*(0.15_fp+0.15_fp*i)
      p=state(i,:)
      CALL BRC_ORIGIN_SPLIT_LOSS(total,new,p,lost,status)
      CALL check(status==0,'chain transition')
      state(i,:)=p;parent(i)=new
      SELECT CASE(i)
      CASE(1)
        state(2,:)=state(2,:)+lost; parent(2)=parent(2)+total-new
      CASE(2)
        state(3,:)=state(3,:)+lost/factor;parent(3)=parent(3)+(total-new)/factor
      CASE(3,4)
        state(5,:)=state(5,:)+lost;parent(5)=parent(5)+total-new
      END SELECT
      CALL check(MAXVAL(ABS(SUM(state,DIM=2)-parent))<tol,'all-seven aggregate closure')
    ENDDO
    finish=(state(1,:)+state(2,:))/factor+SUM(state(3:7,:),DIM=1)
    CALL check(MAXVAL(ABS(finish-stock))<tol,'per-origin carbon-basis closure')
  ENDDO
  PRINT *, 'PASS kernel fp=',fp,' chain_cases=256 cutoff/zero/invalid/mixed carbon closure'
CONTAINS
  SUBROUTINE check(ok,label)
    LOGICAL,INTENT(IN)::ok
    CHARACTER(LEN=*),INTENT(IN)::label
    IF(.NOT.ok)THEN
      PRINT *,'FAIL ',label
      STOP 1
    ENDIF
  END SUBROUTINE
END PROGRAM
