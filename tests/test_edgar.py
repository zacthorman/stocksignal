"""Tests for the EDGAR parsing, all offline.

Every function under test takes an already-decoded payload, which is the reason
the module splits parsing from fetching. Nothing here touches the network, so
the offline path the repo insists on stays intact.
"""

from __future__ import annotations

from datetime import date

import pytest

from stocksignal.sources.edgar import (
    DEBT_TAGS,
    REVENUE_TAGS,
    EdgarClient,
    EdgarError,
    annual_series,
    extract,
    filing_flags,
    growth_deceleration,
    track_record_points,
)


def facts(tag: str, rows: list[dict], taxonomy: str = "us-gaap") -> dict:
    return {"facts": {taxonomy: {tag: {"units": {"USD": rows}}}}}


def row(
    year: int,
    val: float,
    form: str = "10-K",
    fp: str = "FY",
    filed: str = "2025-01-01",
    fy: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """One EDGAR fact in its real shape, including the period.

    `year` is the period the number COVERS, which is what the parser must key
    on. `fy` defaults to the same thing for convenience but can be set
    independently, because in real payloads they routinely differ and that
    divergence is the bug this fixture exists to expose.
    """
    return {
        "fy": year if fy is None else fy,
        "fp": fp,
        "val": val,
        "form": form,
        "filed": filed,
        "start": start if start is not None else f"{year}-01-01",
        "end": end if end is not None else f"{year}-12-31",
    }


def instant(year: int, val: float, form: str = "10-K", filed: str = "2025-01-01") -> dict:
    """A balance sheet fact: a snapshot, so `end` and no `start`."""
    return {
        "fy": year,
        "fp": "FY",
        "val": val,
        "form": form,
        "filed": filed,
        "end": f"{year}-12-31",
    }


# --------------------------------------------------------------------------
# Annual series
# --------------------------------------------------------------------------


def test_only_annual_ten_k_rows_are_used():
    """Quarterly filings carry FY-tagged year-to-date figures, so checking `fp`
    alone lets a Q3 number in as if it were a full year."""
    payload = facts(
        "Revenues",
        [
            row(2024, 100.0),
            row(2024, 75.0, form="10-Q"),
            # A year-to-date figure from a 10-Q: FY-tagged, 10-K-shaped `fy`, but
            # only nine months long. The duration check is what stops it.
            row(2023, 90.0, start="2023-01-01", end="2023-09-30"),
        ],
    )
    s = annual_series(payload, ("Revenues",))
    assert s.values == {2024: 100.0}


def test_the_latest_filing_wins_after_a_restatement():
    """EDGAR returns the same fiscal year from the original 10-K and from every
    later comparative. After a restatement those disagree, and the company's
    current view is the one filed most recently."""
    payload = facts(
        "Revenues",
        [
            row(2023, 500.0, filed="2024-02-01"),
            row(2023, 460.0, filed="2026-02-01"),  # restated, later filing
        ],
    )
    assert annual_series(payload, ("Revenues",)).values == {2023: 460.0}


def test_tags_are_tried_in_order_and_the_winner_is_recorded():
    """Small caps use different revenue tags, so a surprising number has to be
    traceable back to the tag that produced it."""
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [row(2024, 10.0)]}},
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [row(2024, 12.0)]}
                },
            }
        }
    }
    s = annual_series(
        payload,
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
        ),
    )
    assert s.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert s.values == {2024: 12.0}


def test_a_company_with_no_matching_tag_returns_empty_not_zero():
    s = annual_series(facts("SomethingElse", [row(2024, 1.0)]), ("Revenues",))
    assert s.tag is None
    assert s.values == {}


# --------------------------------------------------------------------------
# Filing flags
# --------------------------------------------------------------------------


def submissions(pairs: list[tuple[str, str]]) -> dict:
    return {
        "filings": {
            "recent": {
                "form": [f for f, _ in pairs],
                "filingDate": [d for _, d in pairs],
            }
        }
    }


def test_offerings_inside_the_window_are_flagged():
    f = filing_flags(
        submissions([("424B5", "2026-07-01"), ("10-Q", "2026-07-02")]),
        as_of=date(2026, 8, 17),
    )
    assert f.dilution_risk is True
    assert f.dilution_filings == (("424B5", "2026-07-01"),)


def test_an_old_offering_falls_out_of_the_window():
    f = filing_flags(submissions([("424B5", "2025-01-01")]), as_of=date(2026, 8, 17))
    assert f.dilution_risk is False


def test_the_nearest_eight_k_is_the_catalyst():
    f = filing_flags(
        submissions([("8-K", "2026-08-01"), ("8-K", "2026-08-14")]),
        as_of=date(2026, 8, 17),
    )
    assert f.latest_catalyst == "2026-08-14"
    assert f.catalyst_days_ago == 3


def test_form_fours_are_counted_in_their_own_window():
    f = filing_flags(
        submissions([("4", "2026-08-01"), ("4", "2026-07-01"), ("4", "2025-01-01")]),
        as_of=date(2026, 8, 17),
    )
    assert f.insider_filings == 2


def test_a_filing_dated_in_the_future_is_ignored():
    """Acceptance timestamps occasionally run ahead of the as-of date in a
    backtest context, and a negative age would otherwise sort first as the
    freshest catalyst."""
    f = filing_flags(submissions([("8-K", "2026-09-01")]), as_of=date(2026, 8, 17))
    assert f.catalyst_days_ago is None


def test_malformed_dates_do_not_raise():
    f = filing_flags(submissions([("8-K", "not-a-date"), ("4", "")]), as_of=date(2026, 8, 17))
    assert f.catalyst_days_ago is None
    assert f.insider_filings == 0


# --------------------------------------------------------------------------
# Track record, one of only two template categories that can be automated
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("revenues", "expected", "why"),
    [
        # Five years of revenue give FOUR year-on-year comparisons, so an
        # unbroken five-year record is a four-year streak and lands on 10.
        # That is the arithmetic of the template's own wording rather than a
        # bug, and it is pinned here so nobody quietly "fixes" it later.
        ({2021: 1, 2022: 2, 2023: 3, 2024: 4, 2025: 5}, 10, "4-year streak"),
        ({2020: 1, 2021: 2, 2022: 3, 2023: 4, 2024: 5, 2025: 6}, 15, "5-year streak"),
        ({2022: 1, 2023: 2, 2024: 3, 2025: 4}, 10, "3-year streak"),
        ({2023: 5, 2024: 6}, 5, "1-year streak"),
        ({2023: 6, 2024: 5}, 0, "revenue fell"),
        ({2024: 5}, None, "one year cannot show growth"),
    ],
)
def test_track_record_follows_the_templates_rule(revenues, expected, why):
    """1 year of consistent growth = 5, 3 years = 10, 5 years = 15, verbatim."""
    assert track_record_points(revenues) == expected, why


def test_the_streak_breaks_at_the_first_down_year():
    """1, 9, 2, 3, 4 counted back from the most recent is up, up, then down.
    A two-year streak, so 5 points, and the big year in 2022 buys nothing.
    Consistency is what the category asks for, not the best year in the set."""
    assert track_record_points({2021: 1, 2022: 9, 2023: 2, 2024: 3, 2025: 4}) == 5


# --------------------------------------------------------------------------
# The assembled record
# --------------------------------------------------------------------------


def test_extract_flips_the_capex_sign_once():
    """EDGAR reports capex as a positive outflow and the cash reading wants it
    signed so it adds to operating cash flow. Flipping it here means the three
    consumers downstream cannot disagree about the convention."""
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [row(2024, 100.0)]}},
                "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [row(2024, 30.0)]}},
            }
        }
    }
    out = extract(payload, submissions([]), as_of=date(2026, 8, 17))
    assert out["capex"] == [-30.0]
    assert out["revenue"] == [100.0]
    assert out["tags_used"]["revenue"] == "Revenues"


def test_extract_keeps_the_last_five_years_only():
    rows = [row(y, float(y)) for y in range(2015, 2026)]
    out = extract(facts("Revenues", rows), submissions([]), as_of=date(2026, 8, 17))
    assert out["fiscal_years"] == [2021, 2022, 2023, 2024, 2025]


def test_missing_lines_come_back_as_nulls_not_zeros():
    out = extract(facts("Revenues", [row(2024, 5.0)]), submissions([]), as_of=date(2026, 8, 17))
    assert out["net_income"] == [None]
    assert out["tags_used"]["net_income"] is None


# --------------------------------------------------------------------------
# Fair access
# --------------------------------------------------------------------------


def test_the_client_refuses_to_start_without_a_real_contact():
    """The SEC asks for a contact address so they can get in touch before
    blocking an IP. Sending a fake one risks the block instead of the email."""
    for bad in ("", "stocksignal", "no-email-here"):
        with pytest.raises(EdgarError):
            EdgarClient(contact=bad)


# --------------------------------------------------------------------------
# Real data. These rows were fetched from EDGAR on 2026-08-17 and are pinned
# verbatim, because they are what caught the bug.
# --------------------------------------------------------------------------

RKLB_REVENUE_ROWS = [
    {
        "fy": 2026,
        "fp": "FY",
        "form": "10-K",
        "filed": "2026-02-26",
        "val": 601799000,
        "start": "2025-01-01",
        "end": "2025-12-31",
    },
    # Labelled fy=2025 but it is the FY2023 comparative inside the FY2025 10-K.
    {
        "fy": 2025,
        "fp": "FY",
        "form": "10-K",
        "filed": "2026-02-26",
        "val": 244592000,
        "start": "2023-01-01",
        "end": "2023-12-31",
    },
    {
        "fy": 2024,
        "fp": "FY",
        "form": "10-K",
        "filed": "2025-02-27",
        "val": 436214000,
        "start": "2024-01-01",
        "end": "2024-12-31",
    },
    {
        "fy": 2023,
        "fp": "FY",
        "form": "10-K",
        "filed": "2024-02-28",
        "val": 244592000,
        "start": "2023-01-01",
        "end": "2023-12-31",
    },
    {
        "fy": 2022,
        "fp": "FY",
        "form": "10-K",
        "filed": "2023-03-07",
        "val": 210996000,
        "start": "2022-01-01",
        "end": "2022-12-31",
    },
    {
        "fy": 2021,
        "fp": "FY",
        "form": "10-K",
        "filed": "2022-03-24",
        "val": 62237000,
        "start": "2021-01-01",
        "end": "2021-12-31",
    },
]


def test_real_rklb_rows_are_keyed_by_period_not_by_fy():
    """The regression test for the bug that keying on `fy` introduced.

    Six rows, five distinct periods. The `fy=2025` row is the FY2023
    comparative and must land on 2023, agreeing with the `fy=2023` row rather
    than overwriting 2025.
    """
    payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": RKLB_REVENUE_ROWS}
                }
            }
        }
    }
    s = annual_series(payload, REVENUE_TAGS)
    assert s.values == {
        2021: 62237000.0,
        2022: 210996000.0,
        2023: 244592000.0,
        2024: 436214000.0,
        2025: 601799000.0,
    }
    # The specific number the bug got wrong: 2025 is 601.8M, not 244.6M.
    assert s.values[2025] == 601799000.0


def test_the_real_rows_produce_a_five_year_growth_streak():
    """Downstream proof that the fix matters. Under the old keying, 2025 read
    as 244.6M against 2024's 436.2M, an invented fall that ended the streak and
    scored Track Record 0. Rocket Lab has in fact grown revenue every year."""
    revenue = {
        2021: 62237000.0,
        2022: 210996000.0,
        2023: 244592000.0,
        2024: 436214000.0,
        2025: 601799000.0,
    }
    assert track_record_points(revenue) == 10  # four comparisons, four up


def test_a_balance_sheet_fact_has_no_start_and_still_counts():
    """Instantaneous facts carry `end` only. Requiring `start` would silently
    drop the entire balance sheet, and with it the cash runway."""
    payload = facts(
        "CashAndCashEquivalentsAtCarryingValue",
        [
            instant(2025, 420e6),
            instant(2024, 271e6),
        ],
    )
    s = annual_series(payload, ("CashAndCashEquivalentsAtCarryingValue",))
    assert s.values == {2024: 271e6, 2025: 420e6}


def test_a_june_year_end_keeps_the_statements_aligned():
    """A company whose year ends in June reports FY2025 income for
    2024-07-01 to 2025-06-30 and its FY2025 balance at 2025-06-30. Keying both
    on `end` puts them on the same year; keying the income statement on its
    midpoint would put them a year apart."""
    income = annual_series(
        facts("Revenues", [row(0, 50.0, start="2024-07-01", end="2025-06-30")]),
        ("Revenues",),
    )
    balance = annual_series(
        facts(
            "CashAndCashEquivalentsAtCarryingValue",
            [
                {
                    "fy": 2025,
                    "fp": "FY",
                    "form": "10-K",
                    "filed": "2025-08-01",
                    "val": 9.0,
                    "end": "2025-06-30",
                }
            ],
        ),
        ("CashAndCashEquivalentsAtCarryingValue",),
    )
    assert list(income.values) == [2025]
    assert list(balance.values) == [2025]


# --------------------------------------------------------------------------
# Micron. A non-calendar fiscal year, fetched 2026-08-17, and the case that
# makes `fy` keying not merely wrong but destructive: the SAME fact appears
# under two different `fy` values, so one silently overwrites the other.
# --------------------------------------------------------------------------

MU_REVENUE_ROWS = [
    # Micron's FY2018, ended August 2018. It appears twice, labelled fy=2019 in
    # one 10-K and fy=2020 in the next, because both restate it as a
    # comparative. Neither label is the year the money was earned.
    {
        "fy": 2019,
        "fp": "FY",
        "form": "10-K",
        "filed": "2019-10-17",
        "val": 30391000000,
        "start": "2017-09-01",
        "end": "2018-08-30",
    },
    {
        "fy": 2020,
        "fp": "FY",
        "form": "10-K",
        "filed": "2020-10-19",
        "val": 30391000000,
        "start": "2017-09-01",
        "end": "2018-08-30",
    },
    # ...and the real FY2020 also carries fy=2020, so under `fy` keying these
    # two collide and whichever parsed last wins.
    {
        "fy": 2020,
        "fp": "FY",
        "form": "10-K",
        "filed": "2020-10-19",
        "val": 21435000000,
        "start": "2019-08-30",
        "end": "2020-09-03",
    },
    {
        "fy": 2021,
        "fp": "FY",
        "form": "10-K",
        "filed": "2021-10-08",
        "val": 27705000000,
        "start": "2020-09-04",
        "end": "2021-09-02",
    },
    {
        "fy": 2022,
        "fp": "FY",
        "form": "10-K",
        "filed": "2022-10-07",
        "val": 30758000000,
        "start": "2021-09-03",
        "end": "2022-09-01",
    },
    {
        "fy": 2024,
        "fp": "FY",
        "form": "10-K",
        "filed": "2024-10-04",
        "val": 25111000000,
        "start": "2023-09-01",
        "end": "2024-08-29",
    },
]


def test_a_non_calendar_year_lands_on_the_right_year():
    """Micron's years end in late August or early September, so no period is a
    calendar year and `fy` never matches the period. Every value below is the
    published figure for that fiscal year."""
    payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": MU_REVENUE_ROWS}
                }
            }
        }
    }
    s = annual_series(payload, REVENUE_TAGS)
    assert s.values == {
        2018: 30391000000.0,
        2020: 21435000000.0,
        2021: 27705000000.0,
        2022: 30758000000.0,
        2024: 25111000000.0,
    }


def test_the_duplicate_fact_does_not_collide_under_period_keying():
    """The FY2018 figure appears under fy=2019 and fy=2020. Keying on `fy` would
    put 30.39bn into a 2020 slot that belongs to 21.43bn, and the answer would
    depend on dict ordering. Keying on the period sends both copies to 2018,
    where they agree, and leaves 2020 to the number that actually is 2020."""
    payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": MU_REVENUE_ROWS}
                }
            }
        }
    }
    values = annual_series(payload, REVENUE_TAGS).values
    assert values[2018] == 30391000000.0
    assert values[2020] == 21435000000.0


def test_a_fifty_three_week_year_stays_inside_the_annual_band():
    """Micron's FY2020 ran 370 days. A tighter band than 300 to 400 would drop
    it and leave a hole in the middle of the revenue series."""
    payload = facts(
        "Revenues",
        [
            {
                "fy": 2020,
                "fp": "FY",
                "form": "10-K",
                "filed": "2020-10-19",
                "val": 21435000000,
                "start": "2019-08-30",
                "end": "2020-09-03",
            },
        ],
    )
    assert annual_series(payload, ("Revenues",)).values == {2020: 21435000000.0}


def test_a_quarter_is_rejected_even_when_it_carries_a_ten_k_form():
    """Amended 10-Ks carry quarterly contexts too. The duration is the filter,
    not the form alone."""
    payload = facts(
        "Revenues",
        [
            {
                "fy": 2024,
                "fp": "FY",
                "form": "10-K",
                "filed": "2025-01-01",
                "val": 99.0,
                "start": "2024-10-01",
                "end": "2024-12-31",
            },
        ],
    )
    assert annual_series(payload, ("Revenues",)).values == {}


# --------------------------------------------------------------------------
# Maturity: the one unguided category whose QUESTION is arithmetic
# --------------------------------------------------------------------------


def test_deceleration_uses_the_median_so_a_base_year_cannot_dominate():
    """Rocket Lab's real growth rates are 239, 16, 78, 38 per cent. The 239 is a
    company going from almost no revenue to some, which is a base effect rather
    than a growth rate. Against the MEAN of the prior three the latest reads as
    a 73 point slowdown, which describes 2022 rather than the business. Against
    the median it is 40 points, which is the honest number."""
    revenue = {2021: 62.2e6, 2022: 211.0e6, 2023: 244.6e6, 2024: 436.2e6, 2025: 601.8e6}
    assert growth_deceleration(revenue) == pytest.approx(-40.0, abs=1.0)


def test_steady_growth_shows_no_deceleration():
    revenue = {2021: 100.0, 2022: 120.0, 2023: 144.0, 2024: 172.8, 2025: 207.4}
    assert growth_deceleration(revenue) == pytest.approx(0.0, abs=0.5)


def test_a_clear_slowdown_reads_negative():
    revenue = {2021: 100.0, 2022: 150.0, 2023: 225.0, 2024: 337.0, 2025: 355.0}
    assert growth_deceleration(revenue) < -20


def test_deceleration_needs_four_years_to_say_anything():
    """Three revenues give two growth rates, and one prior rate is not a trend
    to have departed from."""
    assert growth_deceleration({2023: 1.0, 2024: 2.0, 2025: 3.0}) is None


def test_deceleration_refuses_a_zero_or_negative_base():
    assert growth_deceleration({2021: 0.0, 2022: 5.0, 2023: 6.0, 2024: 7.0, 2025: 8.0}) is None


# --------------------------------------------------------------------------
# Tag coverage, driven by companies that broke it
# --------------------------------------------------------------------------


def test_a_drawn_revolving_facility_counts_as_debt():
    """Sezzle reports 139,991,000 drawn under LongTermLineOfCredit at 2025 year
    end and files nothing under any LongTermDebt tag. Before this tag was in
    the group, the balance reading abstained on the debt check for a company
    with real borrowings. Abstaining is better than reporting zero, but it is
    still the wrong answer when the filing states the number."""
    payload = facts("LongTermLineOfCredit", [row(2025, 139_991_000, start=None, end="2025-12-31")])
    series = annual_series(payload, DEBT_TAGS)
    assert series.tag == "LongTermLineOfCredit"
    assert series.values[2025] == pytest.approx(139_991_000)


def test_the_named_long_term_debt_tags_still_win_over_the_facility():
    """Order matters: a company reporting both should read the debt line, not
    the facility, or a drawn revolver gets counted twice across the two."""
    assert DEBT_TAGS.index("LongTermDebt") < DEBT_TAGS.index("LongTermLineOfCredit")
    assert DEBT_TAGS.index("LongTermDebtNoncurrent") < DEBT_TAGS.index("LongTermLineOfCredit")
