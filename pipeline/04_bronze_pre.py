import dlt
from bronze_common import bronze_reader   # noqa: F401


@dlt.table(
    name="pre_raw",
    comment="Statement presentation detail. `stmt` assigns facts to BS/IS/CF; "
            "`plabel` is the filer's own line-item label -- the best signal for "
            "mapping custom tags to canonical concepts.",
    table_properties={"quality": "bronze"},
)
@dlt.expect("adsh_not_null", "adsh IS NOT NULL")
def pre_raw():
    return bronze_reader("pre")