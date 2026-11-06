"""Tests du parsing TOP500 : formats variables, unités, édition, erreurs."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeline.ingest.top500_parser import (
    OUTPUT_COLUMNS,
    normalize_header,
    parse_edition,
    read_top500_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "top500_sample.csv"


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    target = tmp_path / "TOP500_202506.csv"
    shutil.copy(FIXTURE, target)
    return target


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# --- en-têtes et édition -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rmax [TFlop/s]", "rmax_tflop_s"),
        ("Rmax [GFlop/s]", "rmax_gflop_s"),
        ("Power (kW)", "power_kw"),
        ("  Total Cores ", "total_cores"),
        ("Interconnect Family", "interconnect_family"),
    ],
)
def test_normalize_header(raw: str, expected: str) -> None:
    assert normalize_header(raw) == expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("TOP500_202506.xlsx", "2025-06"),
        ("top500_2024-11.csv", "2024-11"),
        ("TOP500_List_2023_06.xls", "2023-06"),
    ],
)
def test_parse_edition(filename: str, expected: str) -> None:
    assert parse_edition(filename) == expected


def test_parse_edition_invalid_raises() -> None:
    with pytest.raises(ValueError, match="édition"):
        parse_edition("top500_latest.xlsx")


# --- lecture du fichier d'exemple ------------------------------------------------


def test_sample_has_canonical_schema(sample_file: Path) -> None:
    df = read_top500_file(sample_file)
    assert list(df.columns) == list(OUTPUT_COLUMNS)
    assert len(df) == 8
    assert set(df["edition"]) == {"2025-06"}
    assert set(df["source_file"]) == {"TOP500_202506.csv"}


def test_numbers_with_thousand_separators_are_parsed(sample_file: Path) -> None:
    df = read_top500_file(sample_file)
    bravo = df[df["rank"] == 2].iloc[0]
    assert bravo["rmax_tflops"] == pytest.approx(250_000.5)
    assert bravo["cores"] == 1_200_000
    assert bravo["power_kw"] == pytest.approx(8_000)


def test_missing_power_becomes_null(sample_file: Path) -> None:
    df = read_top500_file(sample_file)
    assert df.loc[df["rank"] == 4, "power_kw"].isna().all()


def test_vendor_names_are_kept_raw(sample_file: Path) -> None:
    # Le regroupement Bull / Atos / Eviden est fait dans dbt, pas au parsing.
    df = read_top500_file(sample_file)
    assert {"Bull SAS", "EVIDEN", "Atos", "Eviden"} <= set(df["manufacturer"])


# --- variations de format ----------------------------------------------------------


def test_gflops_are_converted_to_tflops(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "TOP500_201106.csv",
        'Rank,Manufacturer,Rmax [GFlop/s],Rpeak [GFlop/s]\n1,Fujitsu,"8,162,000","8,773,630"\n',
    )
    df = read_top500_file(path)
    assert df.loc[0, "rmax_tflops"] == pytest.approx(8_162.0)
    assert df.loc[0, "rpeak_tflops"] == pytest.approx(8_773.63)


def test_vendor_alias_and_title_row(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "TOP500_202411.csv",
        "TOP500 List - November 2024\n\nRank,Vendor,Cores,Rmax\n1,HPE,100,10.5\n",
    )
    df = read_top500_file(path)
    assert df.loc[0, "manufacturer"] == "HPE"
    assert df.loc[0, "cores"] == 100
    assert df.loc[0, "rmax_tflops"] == pytest.approx(10.5)


def test_semicolon_separator(tmp_path: Path) -> None:
    path = _write(tmp_path, "TOP500_202406.csv", "Rank;Manufacturer;Rmax [TFlop/s]\n1;Lenovo;42\n")
    assert read_top500_file(path).loc[0, "manufacturer"] == "Lenovo"


def test_missing_required_column_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "TOP500_202506.csv", "Rank,Site\n1,Somewhere\n")
    with pytest.raises(ValueError, match="manufacturer"):
        read_top500_file(path)


def test_unsupported_format_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "TOP500_202506.json", "{}")
    with pytest.raises(ValueError, match="non supporté"):
        read_top500_file(path)
