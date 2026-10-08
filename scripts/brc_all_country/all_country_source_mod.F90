! Standalone dynamic source allocator. Not registered with live HEMCO.
MODULE ALL_COUNTRY_SOURCE_MOD
  USE HCO_PRECISION_MOD, ONLY: fp
  USE, INTRINSIC :: IEEE_ARITHMETIC, ONLY: IEEE_IS_FINITE
  IMPLICIT NONE
  PRIVATE
  PUBLIC :: ALL_COUNTRY_SOURCE_ALLOCATE
  PUBLIC :: ALL_COUNTRY_SOURCE_BUNDLE
  INTEGER, PARAMETER :: MAX_ORIGINS=244
CONTAINS
  ! Catalogue-bound transaction: the final UNT slot must receive no new source.
  ! Families are staged together so a late failure publishes none of them.
  PURE SUBROUTINE ALL_COUNTRY_SOURCE_BUNDLE(Parents,Raw,Injected,Parts,Status,RelativeError)
    REAL(fp), INTENT(IN) :: Parents(:),Raw(:,:),Injected(:)
    REAL(fp), INTENT(INOUT) :: Parts(:,:)
    INTEGER, INTENT(OUT) :: Status
    REAL(fp), INTENT(OUT) :: RelativeError
    REAL(fp), ALLOCATABLE :: Trial(:,:)
    REAL(fp) :: FamilyError
    INTEGER :: F,AllocationStatus
    Status=7;RelativeError=0.0_fp
    IF (SIZE(Raw,1)/=MAX_ORIGINS .OR. SIZE(Raw,2)<1 .OR. SIZE(Raw,2)>7) RETURN
    IF (ANY(SHAPE(Parts)/=SHAPE(Raw))) RETURN
    IF (SIZE(Parents)/=SIZE(Raw,2) .OR. SIZE(Injected)/=SIZE(Raw,2)) RETURN
    Status=8
    IF (ANY(Raw(MAX_ORIGINS,:)/=0.0_fp)) RETURN
    ALLOCATE(Trial(SIZE(Raw,1),SIZE(Raw,2)),STAT=AllocationStatus)
    IF (AllocationStatus/=0) THEN
      Status=6
      RETURN
    ENDIF
    Trial=0.0_fp
    DO F=1,SIZE(Raw,2)
      CALL ALL_COUNTRY_SOURCE_ALLOCATE(Parents(F),Raw(:,F),Injected(F),Trial(:,F),Status,FamilyError)
      RelativeError=MAX(RelativeError,FamilyError)
      IF (Status/=0) RETURN
    ENDDO
    Parts=Trial;Status=0
  END SUBROUTINE ALL_COUNTRY_SOURCE_BUNDLE
  PURE SUBROUTINE ALL_COUNTRY_SOURCE_ALLOCATE(Parent,Raw,Injected,Parts,Status,RelativeError)
    REAL(fp), INTENT(IN) :: Parent,Raw(:),Injected
    REAL(fp), INTENT(INOUT) :: Parts(:)
    INTEGER, INTENT(OUT) :: Status
    REAL(fp), INTENT(OUT) :: RelativeError
    REAL(fp), ALLOCATABLE :: Trial(:)
    REAL(fp) :: Total,TrialSum,Tolerance
    INTEGER :: AllocationStatus
    LOGICAL :: SafeSum
    Status=6;RelativeError=0.0_fp
    IF (SIZE(Raw)<1 .OR. SIZE(Raw)>MAX_ORIGINS .OR. SIZE(Parts)/=SIZE(Raw)) RETURN
    Status=1
    IF (.NOT. IEEE_IS_FINITE(Parent) .OR. .NOT. IEEE_IS_FINITE(Injected)) RETURN
    IF (ANY(.NOT. IEEE_IS_FINITE(Raw))) RETURN
    IF (Parent<0.0_fp .OR. Injected<0.0_fp .OR. ANY(Raw<0.0_fp)) RETURN
    CALL NONNEG_SUM(Raw,Total,SafeSum)
    IF (.NOT. SafeSum) RETURN
    IF (Parent==0.0_fp) THEN
      IF (Total>0.0_fp .OR. Injected>0.0_fp) THEN
        Status=2
        RETURN
      ENDIF
      Parts=0.0_fp;Status=0
      RETURN
    ENDIF
    IF (Total==0.0_fp) THEN
      Status=2
      RETURN
    ENDIF
    RelativeError=ABS(Total-Parent)/MAX(Total,Parent)
    IF (RelativeError>2.0e-6_fp) THEN
      Status=3
      RETURN
    ENDIF
    ALLOCATE(Trial(SIZE(Raw)),STAT=AllocationStatus)
    IF (AllocationStatus/=0) THEN
      Status=6
      RETURN
    ENDIF
    Trial=Injected*(Raw/Total)
    IF (ANY(.NOT. IEEE_IS_FINITE(Trial)) .OR. ANY(Trial<0.0_fp)) RETURN
    IF (ANY((Raw==0.0_fp) .AND. (Trial/=0.0_fp))) THEN
      Status=4
      RETURN
    ENDIF
    IF (Injected>0.0_fp .AND. ANY((Raw>0.0_fp) .AND. (Trial==0.0_fp))) THEN
      Status=4
      RETURN
    ENDIF
    Tolerance=5.0e-5_fp
    IF (STORAGE_SIZE(Parent)>32) Tolerance=5.0e-12_fp
    IF (Injected>0.0_fp) THEN
      CALL NONNEG_SUM(Trial,TrialSum,SafeSum)
      IF (.NOT. SafeSum) THEN
        Status=5
        RETURN
      ENDIF
      IF (ABS(TrialSum-Injected)/Injected>Tolerance) THEN
        Status=5
        RETURN
      ENDIF
    ENDIF
    Parts=Trial;Status=0
  END SUBROUTINE ALL_COUNTRY_SOURCE_ALLOCATE
  PURE SUBROUTINE NONNEG_SUM(Values,Total,Valid)
    REAL(fp), INTENT(IN) :: Values(:)
    REAL(fp), INTENT(OUT) :: Total
    LOGICAL, INTENT(OUT) :: Valid
    INTEGER :: O
    Valid=.FALSE.;Total=0.0_fp
    DO O=1,SIZE(Values)
      IF (Values(O)>HUGE(1.0_fp)-Total) RETURN
      Total=Total+Values(O)
    ENDDO
    Valid=IEEE_IS_FINITE(Total)
  END SUBROUTINE NONNEG_SUM
END MODULE ALL_COUNTRY_SOURCE_MOD
