from datetime import date

import pytest

from app.models import CapCategory
from app.services.classification import (
    ClassifiedStock,
    category_for_rank,
    current_universe,
    parse_amfi_csv,
    save_classification,
)


@pytest.mark.parametrize(
    "rank,expected",
    [(1, CapCategory.LARGE), (100, CapCategory.LARGE), (101, CapCategory.MID), (250, CapCategory.MID),
     (251, CapCategory.SMALL), (2000, CapCategory.SMALL)],
)
def test_amfi_rank_boundaries(rank, expected):
    assert category_for_rank(rank) == expected


def test_invalid_rank():
    with pytest.raises(ValueError):
        category_for_rank(0)


def test_parse_amfi_csv_matches_loose_headers_and_skips_non_nse(tmp_path):
    f = tmp_path / "amfi.csv"
    f.write_text(
        "Sr. No.,Company name,ISIN,BSE Symbol,NSE Symbol\n"
        "1,Alpha Ltd,INE000000001,ALPHA,alpha\n"
        "2,Beta Ltd,INE000000002,BETA,\n"
        "101,Gamma Ltd,INE000000003,GAMMA,GAMMA\n",
        encoding="utf-8",
    )
    rows = parse_amfi_csv(f)
    assert [(r.symbol, r.rank, r.category) for r in rows] == [
        ("ALPHA", 1, CapCategory.LARGE),
        ("GAMMA", 101, CapCategory.MID),
    ]
    assert rows[0].isin == "INE000000001"


def test_parse_amfi_csv_rejects_duplicates_and_missing_columns(tmp_path):
    dup = tmp_path / "dup.csv"
    dup.write_text("Rank,Company Name,NSE Symbol\n1,A,AAA\n2,B,AAA\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        parse_amfi_csv(dup)
    bad = tmp_path / "bad.csv"
    bad.write_text("Company Name,NSE Symbol\nA,AAA\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing a column"):
        parse_amfi_csv(bad)


def test_parse_official_amfi_xlsx_layout(tmp_path):
    import openpyxl

    from app.services.classification import parse_amfi_file

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "FINAL"
    ws.append(["Average Market Capitalization of listed companies during the six months ended 30 June 2026"])
    ws.append(["Sr. No.", "Company name", "ISIN", "BSE Symbol", "BSE 6 month Avg", "NSE Symbol", "NSE 6 month Avg",
               "MSEI Symbol", "MSEI 6 month Avg", "Average of All Exchanges (Rs. Cr.)",
               "Categorization as per SEBI Circular dated Oct 6, 2017"])
    ws.append([1, "Reliance Industries Ltd", "INE002A01018", "RELIANCE", 1, "RELIANCE", 1, "-", None, 1, "Large Cap"])
    ws.append([2, "BSE Only Ltd", "INE000000009", "BSEONLY", 1, "-", None, "-", None, 1, "Large Cap"])
    ws.append([101, "Mahindra & Mahindra", "INE101A01026", "M&M", 1, "M&M", 1, "-", None, 1, "Mid Cap"])
    ws.append([260, "Small Co", "INE000000010", "SMALL", 1, "SMALLCO", 1, "-", None, 1, "Small Cap"])
    ws.append([None, None, None, None, None, None, None, None, None, None, None])  # trailing blank
    f = tmp_path / "amfi.xlsx"
    wb.save(f)

    rows = parse_amfi_file(f)
    assert [(r.symbol, r.rank, r.category) for r in rows] == [
        ("RELIANCE", 1, CapCategory.LARGE),
        ("M&M", 101, CapCategory.MID),
        ("SMALLCO", 260, CapCategory.SMALL),
    ]
    assert rows[0].official_category == CapCategory.LARGE and rows[0].isin == "INE002A01018"


def test_official_category_wins_over_rank():
    s = ClassifiedStock("X", "X", 99, official_category=CapCategory.MID)
    assert s.category == CapCategory.MID


def test_versions_are_immutable_and_latest_is_current(factory):
    with factory() as db:
        save_classification(db, [ClassifiedStock("AAA", "A", 1)], "v1", "test", date(2026, 1, 31))
        save_classification(db, [ClassifiedStock("AAA", "A", 150)], "v2", "test", date(2026, 7, 31))
        with pytest.raises(ValueError, match="immutable"):
            save_classification(db, [], "v1", "test", date(2026, 1, 31))
        cv, rows = current_universe(db)
        assert cv.version == "v2"
        assert [(r.symbol, r.cap_category) for r in rows] == [("AAA", "mid-cap")]
