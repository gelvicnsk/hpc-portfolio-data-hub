"""Parsing des fichiers TOP500 (CSV / Excel) vers un schéma canonique.

Le format du TOP500 varie selon les éditions :
- noms de colonnes (« Rmax [TFlop/s] », « Rmax [GFlop/s] », « Total Cores »/« Cores »…) ;
- ligne de titre éventuelle au-dessus des en-têtes ;
- séparateurs de milliers (« 1,742,000.00 ») ;
- l'édition n'est pas une colonne : on la déduit du nom de fichier (TOP500_202506.xlsx).

Ce module absorbe ces variations : load_top500.py reçoit toujours les mêmes colonnes
(OUTPUT_COLUMNS), Rmax/Rpeak toujours en TFlop/s. La normalisation des constructeurs
(Bull / Atos / Eviden…) reste dans dbt (seed vendor_mapping), pas ici.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}
HEADER_SEARCH_ROWS = 15

EDITION_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_]?(0[1-9]|1[0-2])(?!\d)")

# nom canonique -> variantes d'en-tête (déjà normalisées), par ordre de priorité
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "rank": ("rank",),
    "system_name": ("name", "system_name", "system"),
    "computer": ("computer", "system_model"),
    "manufacturer": ("manufacturer", "vendor"),
    "site": ("site", "installation_site"),
    "country": ("country",),
    "year": ("year", "installation_year"),
    "segment": ("segment",),
    "cores": ("total_cores", "cores"),
    "power_kw": ("power_kw", "power"),
    "processor": ("processor",),
    "interconnect": ("interconnect_family", "interconnect"),
}

# Rmax / Rpeak : l'unité est dans l'en-tête, on convertit tout en TFlop/s.
# Un en-tête sans unité (« Rmax ») est supposé en TFlop/s.
FLOPS_UNIT_FACTORS: dict[str, float] = {"gflop_s": 1e-3, "tflop_s": 1.0, "pflop_s": 1e3}

TEXT_COLUMNS = (
    "system_name",
    "computer",
    "manufacturer",
    "site",
    "country",
    "segment",
    "processor",
    "interconnect",
)
INTEGER_COLUMNS = ("rank", "year", "cores")
REQUIRED_COLUMNS = ("rank", "manufacturer", "rmax_tflops")

OUTPUT_COLUMNS = (
    "edition",
    "rank",
    "system_name",
    "computer",
    "manufacturer",
    "site",
    "country",
    "year",
    "segment",
    "cores",
    "rmax_tflops",
    "rpeak_tflops",
    "power_kw",
    "processor",
    "interconnect",
    "source_file",
)


def normalize_header(value: object) -> str:
    """« Rmax [TFlop/s] » -> « rmax_tflop_s », « Power (kW) » -> « power_kw »."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def parse_edition(path: str | Path) -> str:
    """TOP500_202506.xlsx -> '2025-06'. Lève ValueError si le nom ne contient pas AAAAMM."""
    name = Path(path).name
    match = EDITION_PATTERN.search(name)
    if match is None:
        raise ValueError(
            f"Impossible de déduire l'édition depuis « {name} » "
            "(nom attendu du type TOP500_AAAAMM.xlsx)"
        )
    year, month = match.groups()
    return f"{year}-{month}"


def _is_header_row(cells: list[object]) -> bool:
    return any(normalize_header(c) == "rank" for c in cells)


def _read_csv(path: Path) -> pd.DataFrame:
    with path.open(encoding="utf-8-sig", errors="replace") as f:
        lines = [line for _, line in zip(range(HEADER_SEARCH_ROWS), f, strict=False)]

    for idx, line in enumerate(lines):
        sep = ";" if line.count(";") > line.count(",") else ","
        cells = next(csv.reader([line], delimiter=sep), [])
        if _is_header_row(cells):
            return pd.read_csv(
                path,
                skiprows=idx,
                sep=sep,
                dtype=str,
                keep_default_na=False,
                encoding="utf-8-sig",
                encoding_errors="replace",
            )
    raise ValueError(
        f"En-tête « Rank » introuvable dans les {HEADER_SEARCH_ROWS} premières lignes de {path.name}"
    )


def _read_excel(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None, dtype=str)
    for idx in range(min(HEADER_SEARCH_ROWS, len(raw))):
        row = raw.iloc[idx].tolist()
        if _is_header_row(row):
            df = raw.iloc[idx + 1 :].reset_index(drop=True)
            df.columns = ["" if pd.isna(c) else str(c) for c in row]
            return df
    raise ValueError(
        f"En-tête « Rank » introuvable dans les {HEADER_SEARCH_ROWS} premières lignes de {path.name}"
    )


def _to_float(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.replace(r"[,\s ]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce").astype("Float64")


def _flops_column(df: pd.DataFrame, prefix: str) -> pd.Series:
    for col in df.columns:
        if col == prefix:
            return _to_float(df[col])
        if col.startswith(f"{prefix}_"):
            unit = col[len(prefix) + 1 :]
            if unit in FLOPS_UNIT_FACTORS:
                return _to_float(df[col]) * FLOPS_UNIT_FACTORS[unit]
    return pd.Series(pd.NA, index=df.index, dtype="Float64")


def read_top500_file(path: str | Path) -> pd.DataFrame:
    """Lit une édition TOP500 et renvoie un DataFrame aux colonnes OUTPUT_COLUMNS."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Format non supporté : {path.suffix} (attendu : {sorted(SUPPORTED_SUFFIXES)})"
        )
    edition = parse_edition(path)

    df = _read_csv(path) if path.suffix.lower() == ".csv" else _read_excel(path)
    df.columns = [normalize_header(c) for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    df = df.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")

    out = pd.DataFrame(index=df.index)
    for canonical, variants in COLUMN_ALIASES.items():
        source = next((v for v in variants if v in df.columns), None)
        out[canonical] = df[source] if source is not None else pd.NA

    out["rmax_tflops"] = _flops_column(df, "rmax")
    out["rpeak_tflops"] = _flops_column(df, "rpeak")
    out["power_kw"] = _to_float(out["power_kw"])
    for col in INTEGER_COLUMNS:
        out[col] = _to_float(out[col]).round().astype("Int64")
    for col in TEXT_COLUMNS:
        out[col] = out[col].astype("string").str.strip()

    missing = [c for c in REQUIRED_COLUMNS if out[c].isna().all()]
    if missing:
        raise ValueError(
            f"{path.name} : colonnes obligatoires absentes ou vides {missing}. "
            f"En-têtes lus : {list(df.columns)}"
        )

    out = out[out["rank"].notna()]  # supprime les lignes de pied de page éventuelles
    out["edition"] = edition
    out["source_file"] = path.name
    return out.loc[:, list(OUTPUT_COLUMNS)].reset_index(drop=True)
