module country_bridge_iso
  use, intrinsic :: iso_c_binding
  implicit none
  type, bind(C) :: brc_bridge_family
     integer(c_int) :: species_id(5), map_advect(5), hco_id(5), safe
     real(c_double) :: mw, q(128,5), origin(128,4), emission(5), loss(5), bottom
  end type
  type, bind(C) :: brc_bridge_column
     integer(c_int) :: abi, n, units, provenance, step, date, clock, level_order
     real(c_double) :: area, dt, airmw
     real(c_long_double) :: coefficient
     real(c_double) :: air(128), cc(128), ze(128), term(128)
     type(brc_bridge_family) :: family(7)
  end type
  type, bind(C) :: brc_bridge_receipt
     integer(c_int) :: status, family, detail, accepted_families
     real(c_double) :: max_additivity, max_budget
  end type
  interface
     integer(c_int) function brc_country_bridge(column, destination, receipt) bind(C)
       import :: c_int, c_double, brc_bridge_column, brc_bridge_receipt
       type(brc_bridge_column), intent(in) :: column
       real(c_double), intent(inout) :: destination(128,4,7)
       type(brc_bridge_receipt), intent(out) :: receipt
     end function
  end interface
end module
