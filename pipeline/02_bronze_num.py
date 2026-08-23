import dlt
from bronze_common import bronze_reader   # noqa: F401


@dlt.table(
    name="num_raw",
    comment="SEC numeric XBRL facts, as filed, unfiltered. ~181M rows across "
            "69 quarters. `segments` is part of the natural key -- consolidated "
            "totals require blank segments AND blank coreg (see DECISIONS.md).",
    table_properties={"quality": "bronze"},
)
@dlt.expect("adsh_not_null", "adsh IS NOT NULL")
def num_raw():
    return bronze_reader("num")