import dlt
from bronze_common import bronze_reader   # noqa: F401


@dlt.table(
    name="sub_raw",
    comment="SEC submissions, as filed. One row per XBRL submission. "
            "`accepted` is the transaction-time axis for the whole warehouse.",
    table_properties={"quality": "bronze", "delta.enableChangeDataFeed": "true"},
)
@dlt.expect("adsh_not_null", "adsh IS NOT NULL")
def sub_raw():
    return bronze_reader("sub")