subroutine brc_iso_probe(column, destination, receipt, status, sizes) bind(C)
  use country_bridge_iso
  implicit none
  type(brc_bridge_column), intent(in) :: column
  real(c_double), intent(inout) :: destination(128,4,7)
  type(brc_bridge_receipt), intent(out) :: receipt
  integer(c_int), intent(out) :: status
  integer(c_size_t), intent(out) :: sizes(3)
  sizes = [c_sizeof(column), c_sizeof(column%family(1)), c_sizeof(receipt)]
  status = brc_country_bridge(column, destination, receipt)
end subroutine
