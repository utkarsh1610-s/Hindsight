import dlt
from pyspark.sql import functions as F, Window, SparkSession

spark = SparkSession.builder.getOrCreate()

PIT = "hindsight_dev.gold.fact_fundamental_pit"


@dlt.table(
    name="hindsight_dev.gold.dim_rebalance_date",
    comment="Quarter-end observation dates, 2012 onward.",
)
def dim_rebalance_date():
    # 2012 start: XBRL coverage isn't stable before 2011
    return spark.sql("""
        SELECT explode(sequence(
                 DATE'2012-03-31', DATE'2025-12-31', INTERVAL 3 MONTH
               )) AS rebalance_dt
    """).withColumn("rebalance_ts", F.col("rebalance_dt").cast("timestamp"))


@dlt.table(
    name="hindsight_dev.gold.fact_roa_comparison",
    comment="ROA per company per rebalance date under point-in-time and naive "
            "data. Universe identical between arms; only values differ.",
    table_properties={"quality": "gold"},
)
def fact_roa_comparison():
    return spark.sql(f"""
    WITH dates AS (
        SELECT rebalance_dt, rebalance_ts
        FROM hindsight_dev.gold.dim_rebalance_date
    ),
    ni_annual AS (
        SELECT d.rebalance_dt, f.cik, f.ddate, f.value AS pit_value,
               ROW_NUMBER() OVER (PARTITION BY d.rebalance_dt, f.cik
                                  ORDER BY f.ddate DESC) AS rn
        FROM {PIT} f
        JOIN dates d
          ON f.known_from_ts <= d.rebalance_ts
         AND f.known_to_ts   >  d.rebalance_ts
        WHERE f.canonical_tag = 'NET_INCOME'
          AND f.qtrs = 4
          AND f.ddate >  add_months(d.rebalance_dt, -24)
          AND f.ddate <= d.rebalance_dt
    ),
    assets AS (
        SELECT d.rebalance_dt, f.cik, f.ddate, f.value AS pit_value,
               ROW_NUMBER() OVER (PARTITION BY d.rebalance_dt, f.cik
                                  ORDER BY f.ddate DESC) AS rn
        FROM {PIT} f
        JOIN dates d
          ON f.known_from_ts <= d.rebalance_ts
         AND f.known_to_ts   >  d.rebalance_ts
        WHERE f.canonical_tag = 'Assets'
          AND f.qtrs = 0
          AND f.ddate >  add_months(d.rebalance_dt, -24)
          AND f.ddate <= d.rebalance_dt
    ),
    -- today's value for the same period = what a normal warehouse would give you
    current_vals AS (
        SELECT cik, canonical_tag, ddate, qtrs, value AS naive_value
        FROM {PIT}
        WHERE is_current
          AND canonical_tag IN ('NET_INCOME', 'Assets')
    ),
    joined AS (
        SELECT
            n.rebalance_dt,
            n.cik,
            n.ddate  AS ni_ddate,
            a.ddate  AS assets_ddate,
            n.pit_value AS pit_ni,
            a.pit_value AS pit_assets,
            cn.naive_value AS naive_ni,
            ca.naive_value AS naive_assets
        FROM ni_annual n
        JOIN assets   a  ON n.rebalance_dt = a.rebalance_dt AND n.cik = a.cik
                        AND a.rn = 1
        LEFT JOIN current_vals cn ON cn.cik = n.cik AND cn.canonical_tag = 'NET_INCOME'
                                 AND cn.ddate = n.ddate AND cn.qtrs = 4
        LEFT JOIN current_vals ca ON ca.cik = a.cik AND ca.canonical_tag = 'Assets'
                                 AND ca.ddate = a.ddate AND ca.qtrs = 0
        WHERE n.rn = 1
    )
    SELECT
        rebalance_dt, cik, ni_ddate, assets_ddate,
        pit_ni, pit_assets, naive_ni, naive_assets,
        pit_ni   / pit_assets                          AS pit_roa,
        naive_ni / naive_assets                        AS naive_roa,
        (naive_ni     <> pit_ni)     AS ni_revised,
        (naive_assets <> pit_assets) AS assets_revised
    FROM joined
    WHERE pit_assets > 0 AND naive_assets > 0
      AND naive_ni IS NOT NULL AND naive_assets IS NOT NULL
    """)


@dlt.table(
    name="hindsight_dev.gold.fact_roa_ranked",
    comment="Decile assignments under each arm, per rebalance date.",
    table_properties={"quality": "gold"},
)
def fact_roa_ranked():
    df = dlt.read("hindsight_dev.gold.fact_roa_comparison")

    w_pit   = Window.partitionBy("rebalance_dt").orderBy(F.col("pit_roa").desc())
    w_naive = Window.partitionBy("rebalance_dt").orderBy(F.col("naive_roa").desc())

    return (
        df
        .withColumn("pit_decile",   F.ntile(10).over(w_pit))
        .withColumn("naive_decile", F.ntile(10).over(w_naive))
        .withColumn("decile_moved", F.col("pit_decile") != F.col("naive_decile"))
        .select("rebalance_dt", "cik", "pit_roa", "naive_roa",
                "pit_decile", "naive_decile", "decile_moved",
                "ni_revised", "assets_revised")
    )


@dlt.table(
    name="hindsight_dev.gold.agg_bias_by_quarter",
    comment="Disagreement between naive and point-in-time rankings per date.",
    table_properties={"quality": "gold"},
)
def agg_bias_by_quarter():
    return spark.sql("""
    WITH r AS (SELECT * FROM hindsight_dev.gold.fact_roa_ranked)
    SELECT
        rebalance_dt,
        count(*) AS universe,
        round(100.0 * avg(CASE WHEN decile_moved THEN 1 ELSE 0 END), 2)
            AS pct_decile_moved,
        round(100.0 * avg(CASE WHEN ni_revised OR assets_revised THEN 1 ELSE 0 END), 2)
            AS pct_any_input_revised,
        -- decile 1 = highest ROA; this is the slice a strategy would buy
        round(100.0 * (
            sum(CASE WHEN naive_decile = 1 AND pit_decile <> 1 THEN 1 ELSE 0 END)
            / NULLIF(sum(CASE WHEN naive_decile = 1 THEN 1 ELSE 0 END), 0)
        ), 2) AS pct_top_decile_turnover
    FROM r
    GROUP BY rebalance_dt
    """)