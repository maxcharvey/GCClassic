PROGRAM SOURCE_PROBE
  USE HCO_PRECISION_MOD, ONLY: fp
  USE ALL_COUNTRY_SOURCE_MOD
  USE HCOX_ORIGIN_SOURCE_KERNEL_MOD, ONLY: ORIGIN_SOURCE_ALLOCATE
  USE, INTRINSIC :: IEEE_ARITHMETIC
  IMPLICIT NONE
  REAL(fp) :: Raw(244),Parts(244),Parent,Injected,Rel,OldRel
  REAL(fp) :: R3(3),Old(3),New(3),TooLarge(245),RawLarge(245),Empty(0)
  REAL(fp) :: BundleRaw(244,4),BundleParts(244,4),BundleParent(4),BundleInjected(4)
  INTEGER :: Status,OldStatus,I,J,Count
  Count=0
  WRITE(*,'(A,1X,I0)') 'PRECISION_BITS',STORAGE_SIZE(Parent)
  Raw=1.0_fp;Raw(244)=0.0_fp;Parent=243.0_fp;Injected=7.0_fp
  CALL CASE_RUN('all_countries',0)
  DO I=1,243
    Raw(I)=REAL(I,fp)/1024.0_fp
  ENDDO
  Raw(244)=0.0_fp;Parent=0.0_fp
  DO I=1,244
    Parent=Parent+Raw(I)
  ENDDO
  Injected=7.0_fp
  CALL CASE_RUN('asymmetric_countries',0)
  Raw=0.0_fp;Raw(243)=1.0_fp;Parent=1.0_fp;Injected=7.0_fp
  CALL CASE_RUN('unassigned_source',0)
  Raw=0.0_fp;Raw(242)=1.0_fp;Parent=1.0_fp;Injected=7.0_fp
  CALL CASE_RUN('single_country',0)
  Raw=0.0_fp;Raw(1)=1.0_fp;Raw(243)=1.0e-20_fp;Parent=1.0_fp;Injected=7.0_fp
  CALL CASE_RUN('rare_unassigned',0)
  Raw=0.0_fp;Parent=0.0_fp;Injected=0.0_fp
  CALL CASE_RUN('zero_parent',0)
  Raw=1.0_fp;Parent=244.0_fp;Injected=0.0_fp
  CALL CASE_RUN('zero_injected',0)
  Raw=1.0_fp;Parent=244.0_fp;Injected=1.0_fp
  Raw(244)=-1.0_fp
  CALL CASE_RUN('late_negative',1)
  Raw(244)=IEEE_VALUE(0.0_fp,IEEE_QUIET_NAN)
  CALL CASE_RUN('late_nan',1)
  Raw(244)=IEEE_VALUE(0.0_fp,IEEE_POSITIVE_INF)
  CALL CASE_RUN('late_infinity',1)
  Raw=1.0_fp;Parent=-1.0_fp
  CALL CASE_RUN('negative_parent',1)
  Parent=244.0_fp;Injected=-1.0_fp
  CALL CASE_RUN('negative_injected',1)
  Injected=IEEE_VALUE(0.0_fp,IEEE_QUIET_NAN)
  CALL CASE_RUN('nan_injected',1)
  Injected=1.0_fp;Parent=0.0_fp
  CALL CASE_RUN('unsupported_parent',2)
  Raw=0.0_fp;Parent=1.0_fp
  CALL CASE_RUN('unsupported_raw',2)
  Raw=1.0_fp;Parent=200.0_fp
  CALL CASE_RUN('source_closure',3)
  Raw=0.0_fp;Raw(1)=1.0_fp;Raw(244)=NEAREST(0.0_fp,1.0_fp)
  Parent=1.0_fp;Injected=NEAREST(0.0_fp,1.0_fp)
  CALL CASE_RUN('late_underflow',4)
  Raw=HUGE(1.0_fp);Parent=HUGE(1.0_fp);Injected=1.0_fp
  CALL CASE_RUN('sum_overflow',1)
  Parts=-77.0_fp;Raw=1.0_fp;Parent=244.0_fp
  CALL ALL_COUNTRY_SOURCE_ALLOCATE(Parent,Raw,Injected,Parts(:243),Status,Rel)
  CALL REQUIRE(Status==6 .AND. ALL(Parts==-77.0_fp),'shape refusal')
  TooLarge=-77.0_fp;RawLarge=1.0_fp
  CALL ALL_COUNTRY_SOURCE_ALLOCATE(245.0_fp,RawLarge,1.0_fp,TooLarge,Status,Rel)
  CALL REQUIRE(Status==6 .AND. ALL(TooLarge==-77.0_fp),'capacity refusal')
  CALL ALL_COUNTRY_SOURCE_ALLOCATE(0.0_fp,Empty,0.0_fp,Parts,Status,Rel)
  CALL REQUIRE(Status==6 .AND. ALL(Parts==-77.0_fp),'empty refusal')
  WRITE(*,'(A)') 'CHECK shape_capacity_empty PASS'
  DO I=1,400
    DO J=1,3
      R3(J)=REAL(MOD(I*(J+7),101),fp)/13.0_fp
    ENDDO
    Parent=0.0_fp
    DO J=1,3
      Parent=Parent+R3(J)
    ENDDO
    Injected=REAL(I,fp)/17.0_fp;Old=-77.0_fp;New=Old
    CALL ORIGIN_SOURCE_ALLOCATE(Parent,R3,Injected,Old,OldStatus,OldRel)
    CALL ALL_COUNTRY_SOURCE_ALLOCATE(Parent,R3,Injected,New,Status,Rel)
    CALL REQUIRE(Status==OldStatus .AND. Rel==OldRel .AND. ALL(Old==New),'legacy compatibility')
  ENDDO
  WRITE(*,'(A)') 'CHECK legacy_compatibility_400 PASS'
  BundleRaw=1.0_fp;BundleRaw(244,:)=0.0_fp
  BundleParent=243.0_fp;BundleInjected=7.0_fp;BundleParts=-77.0_fp
  CALL ALL_COUNTRY_SOURCE_BUNDLE(BundleParent,BundleRaw,BundleInjected,BundleParts,Status,Rel)
  CALL REQUIRE(Status==0 .AND. ALL(BundleParts(244,:)==0.0_fp),'bundle success')
  CALL REQUIRE(ALL(BundleParts(:243,:)>0.0_fp),'bundle support')
  BundleParts=-77.0_fp;BundleRaw(243,4)=-1.0_fp
  CALL ALL_COUNTRY_SOURCE_BUNDLE(BundleParent,BundleRaw,BundleInjected,BundleParts,Status,Rel)
  CALL REQUIRE(Status==1 .AND. ALL(BundleParts==-77.0_fp),'late family atomicity')
  BundleRaw(243,4)=1.0_fp;BundleRaw(244,4)=1.0_fp
  CALL ALL_COUNTRY_SOURCE_BUNDLE(BundleParent,BundleRaw,BundleInjected,BundleParts,Status,Rel)
  CALL REQUIRE(Status==8 .AND. ALL(BundleParts==-77.0_fp),'UNT source refusal')
  BundleRaw(244,4)=IEEE_VALUE(0.0_fp,IEEE_QUIET_NAN)
  CALL ALL_COUNTRY_SOURCE_BUNDLE(BundleParent,BundleRaw,BundleInjected,BundleParts,Status,Rel)
  CALL REQUIRE(Status==8 .AND. ALL(BundleParts==-77.0_fp),'UNT nan refusal')
  BundleRaw(244,4)=0.0_fp
  CALL ALL_COUNTRY_SOURCE_BUNDLE(BundleParent,BundleRaw(:243,:),BundleInjected,BundleParts,Status,Rel)
  CALL REQUIRE(Status==7 .AND. ALL(BundleParts==-77.0_fp),'bundle mapping shape refusal')
  WRITE(*,'(A)') 'CHECK bundle_success_late_failure_UNT_mapping PASS'
  WRITE(*,'(A,1X,I0)') 'PASS_CASES',Count
CONTAINS
  SUBROUTINE REQUIRE(Condition,Message)
    LOGICAL,INTENT(IN) :: Condition
    CHARACTER(*),INTENT(IN) :: Message
    IF (.NOT. Condition) THEN
      WRITE(*,'(A)') 'FAIL '//Message
      STOP 1
    ENDIF
  END SUBROUTINE REQUIRE
  SUBROUTINE CASE_RUN(Name,Expected)
    CHARACTER(*),INTENT(IN) :: Name
    INTEGER,INTENT(IN) :: Expected
    Parts=-77.0_fp
    CALL ALL_COUNTRY_SOURCE_ALLOCATE(Parent,Raw,Injected,Parts,Status,Rel)
    CALL REQUIRE(Status==Expected,Name//' status')
    IF (Status/=0) CALL REQUIRE(ALL(Parts==-77.0_fp),Name//' atomicity')
    IF (Status==0) THEN
      CALL REQUIRE(ALL(Parts>=0.0_fp),Name//' nonnegative')
      IF (Injected>0.0_fp) CALL REQUIRE(ALL(PACK(Parts,Raw>0.0_fp)>0.0_fp),Name//' support')
      CALL REQUIRE(ALL(PACK(Parts,Raw==0.0_fp)==0.0_fp),Name//' zero support')
    ENDIF
    WRITE(*,'(A,1X,A,1X,I0,3(1X,ES26.17E3))') 'CASE',Name,Status,Parent,Injected,Rel
    IF (Status==0) THEN
      WRITE(*,'(A,244(1X,ES26.17E3))') 'RAW',Raw
      WRITE(*,'(A,244(1X,ES26.17E3))') 'PARTS',Parts
    ENDIF
    Count=Count+1
  END SUBROUTINE CASE_RUN
END PROGRAM SOURCE_PROBE
