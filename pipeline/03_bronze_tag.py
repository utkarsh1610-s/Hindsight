import dlt
from bronze_common import bronze_reader   # noqa: F401


@dlt.table(
    name="tag_raw",
    comment="XBRL taxonomy entries, standard and filer-custom. `custom`=1 marks "
            "filer-invented concepts. `crdr` carries the sign convention.",
    table_properties={"quality": "bronze"},
)
@dlt.expect("tag_not_null", "tag IS NOT NULL")
def tag_raw():
    return bronze_reader("tag")