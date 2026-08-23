import dlt
from pyspark.sql import functions as F, SparkSession

spark = SparkSession.builder.getOrCreate()

VALID_QTRS = [0, 1, 4]


def _typed_num():
    """Cast facts and evaluate the contract.

    _reject_reason marks rows that are BROKEN (unparseable, impossible).
    Out-of-scope rows -- segment-level, non-USD, custom tags, qtrs 2/3 --
    are valid data we simply don't want, and are filtered rather than
    quarantined. Conflating the two makes the quarantine rate meaningless.
    """
    return (
        dlt.read_stream("num_raw")
        .withColumn("ddate_dt",  F.to_date("ddate", "yyyyMMdd"))
        .withColumn("qtrs_i",    F.col("qtrs").cast("smallint"))
        .withColumn("value_dec", F.col("value").cast("decimal(28,4)"))
        .withColumn("is_consolidated",
            (F.col("segments").isNull() | (F.trim("segments") == ""))
            & (F.col("coreg").isNull()  | (F.trim("coreg")  == ""))
        )
        .withColumn("is_custom_tag", ~F.col("version").startswith("us-gaap"))
        .withColumn("_reject_reason",
            F.when(F.col("ddate_dt").isNull(), "ddate_unparseable")
             .when(F.col("value").isNotNull() & F.col("value_dec").isNull(),
                   "value_uncastable")
             .when(F.col("ddate_dt") < F.lit("1990-01-01"), "ddate_implausible")
        )
    )


@dlt.table(
    name="hindsight_dev.silver.num",
    comment="Consolidated USD facts mapped to canonical concepts. Grain: "
            "(adsh, src_tag, ddate, qtrs, uom). segments/coreg blank by "
            "construction -- see DECISIONS.md for why that matters.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_fail("ddate_not_null", "ddate IS NOT NULL")
@dlt.expect("value_not_null", "value IS NOT NULL")
@dlt.expect("qtrs_valid", "qtrs IN (0,1,4)")
def num():
    cmap = spark.read.table("hindsight_dev.silver.concept_map")

    return (
        _typed_num()
        .filter(
            F.col("_reject_reason").isNull()
            & F.col("qtrs_i").isin(VALID_QTRS)
            & F.col("is_consolidated")
            & (F.col("uom") == "USD")
            & ~F.col("is_custom_tag")
            & F.col("value_dec").isNotNull()
        )
        .join(F.broadcast(cmap), F.col("tag") == F.col("src_tag"), "inner")
        .select(
            "adsh",
            F.col("tag").alias("src_tag"),
            "canonical_tag", "statement",
            F.col("ddate_dt").alias("ddate"),
            F.col("qtrs_i").alias("qtrs"),
            "uom",
            F.col("value_dec").alias("value"),
            "version", "footnote", "quarter", "_ingested_at",
        )
    )


@dlt.table(
    name="hindsight_dev.silver.num_quarantine",
    comment="Facts failing type or domain checks, with reason. Out-of-scope "
            "rows (segments, non-USD, custom tags, qtrs 2/3, unmapped) are "
            "NOT here -- they are counted in silver.exclusions.",
    table_properties={"quality": "quarantine"},
)
def num_quarantine():
    return (
        _typed_num()
        .filter(F.col("_reject_reason").isNotNull())
        .select("adsh", "tag", "version", "ddate", "qtrs", "uom", "value",
                "segments", "coreg", "_reject_reason", "quarter")
    )