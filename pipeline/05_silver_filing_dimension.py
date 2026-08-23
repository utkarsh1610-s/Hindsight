import dlt
from pyspark.sql import functions as F, SparkSession

spark = SparkSession.builder.getOrCreate()

VALID_FORMS = ["10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-KT/A", "10-QT", "10-QT/A"]


def _typed_sub():
    """Cast Bronze submissions. accepted_ts is the transaction-time axis."""
    return (
        dlt.read_stream("sub_raw")
        .withColumn("accepted_ts", F.to_timestamp("accepted"))
        .withColumn("period_dt",   F.to_date("period", "yyyyMMdd"))
        .withColumn("filed_dt",    F.to_date("filed",  "yyyyMMdd"))
        .withColumn("cik",         F.col("cik").cast("bigint"))
        .withColumn("fy",          F.col("fy").cast("int"))
        .withColumn("prevrpt_flag", F.col("prevrpt") == "1")
        .withColumn("is_amendment", F.col("form").endswith("/A"))
        .withColumn("_valid",
            F.col("accepted_ts").isNotNull()
            & F.col("period_dt").isNotNull()
            & F.col("cik").isNotNull()
            & (F.col("accepted_ts") >= F.col("period_dt").cast("timestamp"))
        )
        .withColumn("_reject_reason",
            F.when(F.col("accepted_ts").isNull(), "accepted_unparseable")
             .when(F.col("period_dt").isNull(),   "period_unparseable")
             .when(F.col("cik").isNull(),         "cik_null")
             .when(F.col("accepted_ts") < F.col("period_dt").cast("timestamp"),
                   "accepted_before_period")
        )
    )


@dlt.table(
    name="hindsight_dev.silver.sub",
    comment="Typed submissions, 10-K/10-Q families only. accepted_ts is transaction time.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_fail("accepted_ts_not_null", "accepted_ts IS NOT NULL")
@dlt.expect_or_fail("cik_not_null", "cik IS NOT NULL")
@dlt.expect("adsh_well_formed", "adsh RLIKE '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'")
def sub():
    return (
        _typed_sub()
        .filter(F.col("_valid") & F.col("form").isin(VALID_FORMS))
        .select("adsh", "cik", "name", "sic", "form", "is_amendment",
                "period_dt", "filed_dt", "accepted_ts", "fy", "fp",
                "fye", "prevrpt_flag", "former", "changed", "detail",
                "quarter", "_ingested_at", "_source_file")
    )


@dlt.table(
    name="hindsight_dev.silver.sub_quarantine",
    comment="Submissions failing the contract, with reason. Silver + quarantine "
            "must reconcile to Bronze.",
    table_properties={"quality": "quarantine"},
)
def sub_quarantine():
    return (
        _typed_sub()
        .filter(~F.col("_valid"))
        .select("adsh", "cik", "form", "period", "accepted", "filed",
                "_reject_reason", "quarter", "_source_file")
    )