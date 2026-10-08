from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/GEOS-Chem/GeosCore/plume_conv_reevap_mod.F90"
CONVECTION = ROOT / "src/GEOS-Chem/GeosCore/convection_mod.F90"
CMAKE = ROOT / "src/GEOS-Chem/GeosCore/CMakeLists.txt"


class SourceContractTests(unittest.TestCase):
    def test_module_is_built_and_default_off(self):
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn("plume_conv_reevap_mod.F90", CMAKE.read_text(encoding="utf-8"))
        self.assertIn("GC_RAS_SURFACE_REEVAP_LEDGER", module)
        self.assertIn("LOGICAL, SAVE :: Enabled          = .FALSE.", module)
        self.assertIn("STATUS='NEW'", module)

    def test_dense_unique_slot_accumulation_and_serial_write(self):
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn("Seen(NX,NY,N_Active_Tags)", module)
        self.assertIn(
            "DO T = 1, N_Active_Tags\n    DO J = 1, NY_Saved\n    DO I = 1, NX_Saved",
            module,
        )
        self.assertIn("GC_RAS_SURFACE_REEVAP_INCLUDE_AGED", module)
        self.assertNotIn("!$OMP CRITICAL", module)
        self.assertNotIn("!$OMP ATOMIC", module)

    def test_record_is_after_unchanged_state_update_and_write_after_parallel(self):
        source = CONVECTION.read_text(encoding="utf-8")
        update = source.index("Q(K) = Q(K) - WETLOSS / BMASS(K)")
        record = source.index("CALL Conv_Reevap_Record_Surface_Omission", update)
        t0_update = source.index("T0_SUM = T0_SUM + WETLOSS", record)
        self.assertLess(update, record)
        self.assertLess(record, t0_update)
        parallel_end = source.index("!$OMP END PARALLEL DO", source.index("Do convection column by column"))
        write = source.index("CALL Conv_Reevap_Write()", parallel_end)
        self.assertLess(parallel_end, write)

    def test_native_diag38_gate_is_unchanged(self):
        source = CONVECTION.read_text(encoding="utf-8")
        self.assertIn("IF ( USE_DIAG38 .and. F(K,NA) > 0.0_fp ) THEN", source)
        self.assertIn("DIAG38(K,NW) = DIAG38(K,NW) + ( WETLOSS * AREA_M2 / NDT )", source)


if __name__ == "__main__":
    unittest.main()
