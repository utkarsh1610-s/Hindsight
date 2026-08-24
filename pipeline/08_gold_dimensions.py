"""Gold dimensions and the as-of query surface.

dim_company_scd2 tracks company attributes over transaction time -- name,
SIC, fiscal year end all change, and joining on current values would produce
a history that never happened.

v_fundamental_as_of is the production query path: a range scan over
known_from/known_to with no window functions at read time.
"""

import dlt
from pyspark.sql import functions as F, Window, SparkSession

spark = SparkSession.builder.getOrCreate()

OPEN_END = "9999-12-31 00:00:00"


@dlt.table(
    name="hindsight_dev.gold.dim_company_scd2",
    comment="Company attributes over transaction time. One row per CIK per "
            "attribute-change interval, sequenced by filing acceptance.",
    table_properties={"quality": "gold"},
)
@dlt.expect_or_fail("valid_interval", "valid_from_ts < valid_to_ts")
def dim_company_scd2():
    subs = (
        dlt.read("hindsight_dev.silver.sub")
        .select("cik", "name", "sic", "fye", "accepted_ts")
        .filter(F.col("cik").isNotNull())
    )

    per_ts = Window.partitionBy("cik", "accepted_ts").orderBy(F.col("name"))
    subs = (
        subs.withColumn("_rn", F.row_number().over(per_ts))
            .filter(F.col("_rn") == 1).drop("_rn")
    )

    w = Window.partitionBy("cik").orderBy(F.col("accepted_ts").asc())

    attrs = F.concat_ws("|", F.coalesce("name", F.lit("")),
                             F.coalesce("sic", F.lit("")),
                             F.coalesce("fye", F.lit("")))

    changed = (
        subs.withColumn("_attrs", attrs)
            .withColumn("_prev", F.lag("_attrs").over(w))
            .filter(F.col("_prev").isNull() | (F.col("_attrs") != F.col("_prev")))
    )

    return (
        changed
        .withColumn("valid_from_ts", F.col("accepted_ts"))
        .withColumn("valid_to_ts",
                    F.coalesce(F.lead("accepted_ts").over(w),
                               F.lit(OPEN_END).cast("timestamp")))
        .withColumn("version_seq", F.row_number().over(w))
        .withColumn("is_current",
                    F.col("valid_to_ts") == F.lit(OPEN_END).cast("timestamp"))
        .select("cik", "name", "sic", "fye",
                "valid_from_ts", "valid_to_ts", "version_seq", "is_current")
    )


@dlt.table(
    name="hindsight_dev.gold.dim_concept",
    comment="Canonical concept dimension with source-tag lineage.",
    table_properties={"quality": "gold"},
)
def dim_concept():
    return (
        dlt.read("hindsight_dev.silver.concept_map")
        .groupBy("canonical_tag", "statement")
        .agg(
            F.count("*").alias("n_source_tags"),
            F.collect_set("src_tag").alias("source_tags"),
            F.max("mapping_method").alias("mapping_method"),
            F.min("confidence").alias("min_confidence"),
        )
    )