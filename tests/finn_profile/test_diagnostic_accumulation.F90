! Link against actual HEMCO, with NEW_HP for the repaired version.
! Input rows are captured real source/layer fluxes, not a historical replay.
PROGRAM test_diagnostic_accumulation
  USE HCO_ERROR_MOD
  USE HCO_TYPES_MOD
  USE HCO_STATE_MOD
  USE HCO_DIAGN_MOD
  IMPLICIT NONE
  TYPE(HCO_State), POINTER :: State
  TYPE(DiagnCont), POINTER :: S, C, E, D, Snapshot
  REAL(hp), POINTER :: Area(:,:)
  REAL(hp), ALLOCATABLE :: Source(:,:), Emission(:,:,:), RefS(:,:), RefE(:,:,:)
  REAL(hp), ALLOCATABLE :: Saved(:,:), InputS(:,:), InputE(:,:,:)
  REAL(sp), ALLOCATABLE, TARGET :: External(:,:)
  REAL(hp) :: MaxS, MaxC, MaxE, Closure, Factor
  INTEGER :: RC, Col, NX, NZ, NFields, Field, I, L, Step, Phase, NSteps, Flag
  INTEGER :: Unit, OldCounter
  LOGICAL :: Verbose, RootVerbose, Found
  CHARACTER(LEN=255) :: InputPath
  CHARACTER(LEN=31) :: FieldName
  CALL GET_COMMAND_ARGUMENT(1,InputPath)
  OPEN(NEWUNIT=Unit,FILE=TRIM(InputPath),STATUS='OLD')
  READ(Unit,*) NX,NZ,NFields
  ALLOCATE(State)
  ALLOCATE(State%Config,State%Clock,Area(NX,1))
  State%Config%Err => NULL()
  Verbose=.FALSE.; RootVerbose=.TRUE.
  CALL HCO_ERROR_SET(.TRUE.,State%Config%Err,'*',Verbose,RootVerbose,RC)
  CALL OK()
  State%Config%doVerbose=.FALSE.
  State%NX=NX; State%NY=1; State%NZ=NZ
  State%Clock%ThisYear=2018; State%Clock%ThisMonth=5
  State%Clock%nSteps=0
  Area=1.0_hp
  ALLOCATE(Source(NX,1),Emission(NX,1,NZ),RefS(NX,1),RefE(NX,1,NZ), &
           Saved(NX,1),InputS(NX,1),InputE(NX,1,NZ))
  DO Field=1,NFields
     READ(Unit,*) FieldName
     DO I=1,NX
        READ(Unit,*) InputS(I,1),InputE(I,1,:)
     ENDDO
     State%Diagn => NULL()
     CALL DiagnBundle_Init(State%Diagn)
     CALL DiagnCollection_Create(State%Diagn,NX,1,NZ,1200.0_sp,Area,'test',RC=RC,COL=Col)
     CALL OK()
     State%Diagn%HcoDiagnIDDefault=Col
     CALL Create('source',2,0,S)
     CALL Create('column',2,1,C)
     CALL Create('layers',3,1,E)
     ! An unrelated extension must retain its original SP behavior.
     CALL Diagn_Create(State,'unrelated',ExtNr=1,SpaceDim=2,OutUnit='1', &
                       OutOper='Mean',RC=RC,COL=Col)
     CALL OK()
#ifdef NEW_HP
     CALL Diagn_EnableHP(State,165,RC)
     CALL OK()
     IF (.NOT.S%AccumulateHP.OR..NOT.C%AccumulateHP.OR..NOT.E%AccumulateHP) STOP 1
     CALL DiagnCont_Find(State%Diagn,-1,-1,-1,-1,-1,'unrelated',-1,Found,D,COL=Col)
     IF (.NOT.Found.OR.D%AccumulateHP) STOP 2
#endif
     DO Phase=1,3
        NSteps=2232
        IF (Phase==2) NSteps=2160
        IF (Phase==3) NSteps=7
        RefS=0.0_hp; RefE=0.0_hp
        DO Step=1,NSteps
           State%Clock%nSteps=State%Clock%nSteps+1
           Factor=1.0_hp
           IF (Phase==2) Factor=0.5_hp
           IF (Phase==3) Factor=1.0_hp+REAL(MOD(Step,3),hp)/10.0_hp
           Source=InputS*Factor; Emission=InputE*Factor
           ! Two same-step updates exercise LastUpdateID counter semantics.
           DO L=1,2
              CALL Diagn_Update(State,cName='source',Array2D=Source*0.5_hp,RC=RC)
              CALL OK()
              CALL Diagn_Update(State,cName='column',Array3D=Emission*0.5_hp,RC=RC)
              CALL OK()
              CALL Diagn_Update(State,cName='layers',Array3D=Emission*0.5_hp,RC=RC)
              CALL OK()
           ENDDO
           RefS=RefS+Source*1200.0_hp
           RefE=RefE+Emission*1200.0_hp
        ENDDO
        IF (S%Counter/=NSteps.OR.C%Counter/=NSteps.OR.E%Counter/=NSteps) STOP 3
        CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='source')
        CALL OK()
        Saved=REAL(Snapshot%Arr2D%Val,hp); OldCounter=Snapshot%Counter
        CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='source')
        CALL OK()
        IF (ANY(Saved/=REAL(Snapshot%Arr2D%Val,hp)).OR.Snapshot%Counter/=OldCounter) STOP 4
        CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='column')
        CALL OK()
        CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='layers')
        CALL OK()
        RefS=RefS/(REAL(NSteps,hp)*1200.0_hp)
        RefE=RefE/(REAL(NSteps,hp)*1200.0_hp)
        MaxS=0;MaxC=0;MaxE=0;Closure=0
        DO I=1,NX
           IF (RefS(I,1)==0.0_hp) THEN
              IF (S%Arr2D%Val(I,1)/=0.OR.C%Arr2D%Val(I,1)/=0.OR.ANY(E%Arr3D%Val(I,1,:)/=0)) STOP 5
              CYCLE
           ENDIF
           MaxS=MAX(MaxS,ABS(REAL(S%Arr2D%Val(I,1),hp)-RefS(I,1))/RefS(I,1))
           MaxC=MAX(MaxC,ABS(REAL(C%Arr2D%Val(I,1),hp)-SUM(RefE(I,1,:)))/RefS(I,1))
           MaxE=MAX(MaxE,ABS(SUM(REAL(E%Arr3D%Val(I,1,:),hp))-SUM(RefE(I,1,:)))/RefS(I,1))
           Closure=MAX(Closure,ABS(SUM(REAL(E%Arr3D%Val(I,1,:),hp))-REAL(S%Arr2D%Val(I,1),hp))/RefS(I,1))
        ENDDO
        IF (ANY(E%Arr3D%Val<0).OR.ANY(S%Arr2D%Val<0)) STOP 6
        WRITE(*,'(A,1X,I0,1X,I0,4(1X,ES24.16))') TRIM(FieldName),Phase,NSteps,MaxS,MaxC,MaxE,Closure
#ifdef NEW_HP
        IF (MAX(MaxS,MaxC,MaxE,Closure)>2.0e-6_hp) STOP 7
#endif
     ENDDO
     CALL DiagnBundle_Cleanup(State%Diagn)
  ENDDO
  ! Exercise output/reset modes, filtering, indexed vertical extraction and
  ! external-pointer exclusion against the same actual diagnostic driver.
  State%Diagn => NULL()
  CALL DiagnBundle_Init(State%Diagn)
  CALL DiagnCollection_Create(State%Diagn,NX,1,NZ,1200.0_sp,Area,'modes',RC=RC,COL=Col)
  CALL OK()
  State%Diagn%HcoDiagnIDDefault=Col
  CALL Diagn_Create(State,'inst',ExtNr=165,SpaceDim=2,OutUnit='1',OutOper='Instantaneous',RC=RC)
  CALL OK()
  CALL Diagn_Create(State,'cumul',ExtNr=165,SpaceDim=2,OutUnit='1',OutOper='CumulSum',RC=RC)
  CALL OK()
  CALL Diagn_Create(State,'positive',ExtNr=165,SpaceDim=2,OutUnit='1',OutOper='Mean',RC=RC)
  CALL OK()
  CALL Diagn_Create(State,'level',ExtNr=165,SpaceDim=2,OutUnit='1',OutOper='Mean',LevIdx=2,RC=RC)
  CALL OK()
  ALLOCATE(External(NX,1));External=17.0_sp
  CALL Diagn_Create(State,'external',ExtNr=165,SpaceDim=2,OutUnit='1',Trgt2D=External,RC=RC)
  CALL OK()
#ifdef NEW_HP
  CALL Diagn_EnableHP(State,165,RC)
  CALL OK()
#endif
  DO Step=1,2
     State%Clock%nSteps=State%Clock%nSteps+1
     Source=REAL(Step,hp)*1.25_hp
     Emission=0.0_hp
     Emission(:,:,1)=2.0_hp;Emission(:,:,2)=-3.0_hp;Emission(:,:,3)=4.0_hp
     CALL Diagn_Update(State,cName='inst',Array2D=Source,RC=RC)
     CALL OK()
     CALL Diagn_Update(State,cName='cumul',Array2D=Source,RC=RC)
     CALL OK()
     CALL Diagn_Update(State,cName='positive',Array3D=Emission,PosOnly=.TRUE.,RC=RC)
     CALL OK()
     CALL Diagn_Update(State,cName='level',Array3D=Emission,RC=RC)
     CALL OK()
     CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='inst')
     CALL OK()
     IF(ANY(Snapshot%Arr2D%Val/=REAL(Step,sp)*1.25_sp)) STOP 8
     CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='cumul')
     CALL OK()
     IF(ANY(Snapshot%Arr2D%Val/=REAL(Step*(Step+1)/2,sp)*1.25_sp)) STOP 9
     CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='positive')
     CALL OK()
     IF(ANY(Snapshot%Arr2D%Val/=6.0_sp)) STOP 10
     CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='level')
     CALL OK()
     IF(ANY(Snapshot%Arr2D%Val/=-3.0_sp)) STOP 11
     CALL Diagn_Get(State,.FALSE.,Snapshot,Flag,RC,cName='external')
     CALL OK()
     IF(ANY(Snapshot%Arr2D%Val/=17.0_sp)) STOP 12
#ifdef NEW_HP
     IF(Snapshot%AccumulateHP) STOP 13
#endif
  ENDDO
  CALL DiagnBundle_Cleanup(State%Diagn)
  WRITE(*,'(A)') 'DIAGNOSTIC_STRESS_COMPLETE'
CONTAINS
  SUBROUTINE OK()
    IF(RC/=HCO_SUCCESS) STOP 99
  END SUBROUTINE
  SUBROUTINE Create(Name,Dim,Auto,Dgn)
    CHARACTER(LEN=*),INTENT(IN)::Name
    INTEGER,INTENT(IN)::Dim,Auto
    TYPE(DiagnCont),POINTER::Dgn
    CALL Diagn_Create(State,Name,ExtNr=165,SpaceDim=Dim,OutUnit='kg/m2/s', &
                      OutOper='Mean',AutoFill=Auto,RC=RC,COL=Col)
    CALL OK()
    CALL DiagnCont_Find(State%Diagn,-1,-1,-1,-1,-1,Name,-1,Found,Dgn,COL=Col)
    IF(.NOT.Found) STOP 98
    ! Use the production flux accumulator/normalization, avoiding dependence
    ! on unrelated species/unit initialization in this bounded harness.
    Dgn%AvgFlag=-1;Dgn%TimeAvg=1
  END SUBROUTINE
END PROGRAM
