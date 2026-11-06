"""Génère des visuels PNG des tables du Data Hub (LinkedIn, README, présentation).

Sorties dans docs/images/ :
    01_postgres_kpis_segment.png     PostgreSQL : marts.mart_portfolio_kpis
    02_dbt_quality_report.png        PostgreSQL : meta.v_latest_test_results (tests dbt)
    03_duckdb_top500_vendors.png     DuckDB : parts de marché TOP500 (exports Parquet)
    04_dbt_lineage.png               dbt : graphe de lignage, depuis target/manifest.json

Prérequis : Postgres lancé, pipeline exécuté (make pipeline), matplotlib installé.
Usage : python scripts/linkedin_visuals.py
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"

# palette sobre, lisible en clair comme sur le fil LinkedIn
INK, MUTED, GRID, BG = "#1f2937", "#6b7280", "#e5e7eb", "#ffffff"
ACCENT = {"postgresql": "#336791", "duckdb": "#c99a00", "dbt": "#ff694b"}
LAYER_COLORS = {
    "source": "#64748b",
    "seed": "#64748b",
    "staging": "#336791",
    "intermediate": "#7c3aed",
    "marts": "#0f766e",
    "kpi": "#ff694b",
}


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def pg(sql: str) -> pd.DataFrame:
    conninfo = psycopg.conninfo.make_conninfo(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description or []])


def dk(sql: str) -> pd.DataFrame:
    analytics = Path(os.getenv("DATA_DIR", ROOT / "data")) / "analytics"
    if not analytics.is_absolute():
        analytics = ROOT / analytics
    with duckdb.connect(str(analytics / "hub.duckdb"), read_only=True) as con:
        con.execute(f"SET file_search_path = '{analytics.resolve()}'")
        return con.sql(sql).df()


def render_table(
    df: pd.DataFrame,
    *,
    title: str,
    subtitle: str,
    engine: str,
    path: Path,
    highlight: Callable[[pd.Series], bool] | None = None,
    col_widths: list[float] | None = None,
) -> None:
    """Dessine un DataFrame comme une table soignée, avec un bandeau de titre."""
    n_rows, n_cols = df.shape
    fig_w = max(8.0, 1.45 * n_cols, 0.13 * len(title) + 2.2)
    fig_h = 1.15 + 0.29 * (n_rows + 1)
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=200, facecolor=BG)

    fig.text(0.03, 1 - 0.32 / fig_h, title, fontsize=15, weight="bold", color=INK, va="top")
    fig.text(0.03, 1 - 0.74 / fig_h, subtitle, fontsize=9.5, color=MUTED, va="top")
    fig.text(
        0.97,
        1 - 0.36 / fig_h,
        engine,
        fontsize=9,
        weight="bold",
        color="white",
        ha="right",
        va="top",
        bbox={"boxstyle": "round,pad=0.45", "fc": ACCENT[engine.split()[0].lower()], "ec": "none"},
    )

    ax = fig.add_axes((0.03, 0.02, 0.94, 1 - 1.05 / fig_h - 0.02))
    ax.axis("off")
    table = ax.table(
        cellText=df.astype(str).values,
        colLabels=list(df.columns),
        loc="upper center",
        cellLoc="right",
        colLoc="right",
        colWidths=col_widths,
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    table.scale(1, 1.6)

    # texte aligné à gauche, nombres (et %, j) alignés à droite
    # (une valeur vide ou « – » ne rend pas la colonne textuelle)
    numeric = [
        df[c]
        .astype(str)
        .str.replace(r"[\s%j–+\-.,]", "", regex=True)
        .map(lambda v: v == "" or v.isdigit())
        .all()
        and not df[c].astype(str).str.fullmatch(r"\s*–?\s*").all()
        for c in df.columns
    ]

    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_linewidth(0.6)
        align = "right" if numeric[col] else "left"
        cell.set_text_props(ha=align)
        cell._loc = align  # noqa: SLF001 (matplotlib n'expose pas l'alignement par cellule)
        if row == 0:
            cell.set_facecolor("#f3f4f6")
            cell.set_text_props(weight="bold", color=INK)
        else:
            cell.set_facecolor("#fafafa" if row % 2 == 0 else BG)
            cell.set_text_props(color=INK)
            if highlight is not None and highlight(df.iloc[row - 1]):
                cell.set_facecolor("#fff4e5")
                cell.set_text_props(weight="bold", color=INK)

    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.25, facecolor=BG)
    plt.close(fig)
    print("écrit :", path.relative_to(ROOT))


def fmt(value: object, digits: int = 1, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "–"
    return f"{float(value):,.{digits}f}{suffix}".replace(",", " ")


# --- visuels -------------------------------------------------------------------------


def kpis_by_segment() -> None:
    df = pg(
        """
        select scope_value, n_projects, n_active_projects, on_time_delivery_pct,
               avg_delay_days, budget_variance_pct, n_projects_over_budget, n_open_incidents
        from marts.mart_portfolio_kpis
        where scope in ('global', 'segment')
        order by scope = 'global', scope_value
        """
    )
    table = pd.DataFrame(
        {
            "segment": df["scope_value"].replace({"all": "TOTAL"}),
            "projets": df["n_projects"],
            "actifs": df["n_active_projects"],
            "à l'heure": df["on_time_delivery_pct"].map(lambda v: fmt(v, 1, " %")),
            "retard moyen": df["avg_delay_days"].map(lambda v: fmt(v, 1, " j")),
            "écart budget": df["budget_variance_pct"].map(lambda v: fmt(v, 1, " %")),
            "projets > +5 %": df["n_projects_over_budget"],
            "incidents ouverts": df["n_open_incidents"],
        }
    )
    render_table(
        table,
        title="KPI du portefeuille HPC par segment",
        subtitle="marts.mart_portfolio_kpis — 60 projets synthétiques, calculés par dbt",
        engine="PostgreSQL",
        path=OUT / "01_postgres_kpis_segment.png",
        highlight=lambda r: r["segment"] == "TOTAL",
    )


def quality_report() -> None:
    df = pg(
        """
        select test_name, status, coalesce(failures, 0) as failures
        from meta.v_latest_test_results
        where status <> 'pass'
        order by failures desc, test_name
        """
    )
    totals = pg("select status, count(*) as n from meta.v_latest_test_results group by status")
    summary = ", ".join(f"{n} {s}" for s, n in totals.sort_values("status").itertuples(index=False))
    labels = {
        "source_projects_unique_project_id": "Projets en double (source)",
        "incidents_project_exists": "Incidents sur projet inexistant",
        "assert_costs_positive": "Coûts négatifs",
        "assert_delivery_after_start": "Livraison avant démarrage",
        "incidents_closed_after_opened": "Incidents clos avant ouverture",
        "incidents_severity_in_referential": "Sévérité hors référentiel",
    }
    table = pd.DataFrame(
        {
            "anomalie détectée": df["test_name"].map(lambda t: labels.get(t, t)),
            "test dbt": df["test_name"],
            "statut": df["status"],
            "lignes": df["failures"],
        }
    )
    render_table(
        table,
        title="Qualité : 17 anomalies injectées, toutes détectées",
        subtitle=f"meta.v_latest_test_results — dernier dbt build : {summary} (sur {totals['n'].sum()} tests)",
        engine="dbt tests",
        path=OUT / "02_dbt_quality_report.png",
        col_widths=[0.30, 0.42, 0.10, 0.10],
    )


def top500_vendors() -> None:
    df = dk(
        """
        select vendor_group, n_systems, share_systems_pct, rmax_pflops, share_rmax_pct,
               energy_efficiency_gflops_w, best_system_rank, edition
        from mart_top500_vendor_share
        where edition = (select max(edition) from mart_top500_vendor_share)
        order by rank_by_rmax
        limit 8
        """
    )
    if df.empty:
        print("TOP500 vide : visuel 03 ignoré (déposer les fichiers dans data/raw/top500/)")
        return
    table = pd.DataFrame(
        {
            "constructeur": df["vendor_group"],
            "systèmes": df["n_systems"],
            "part (nb)": df["share_systems_pct"].map(lambda v: fmt(v, 1, " %")),
            "Rmax (PFlop/s)": df["rmax_pflops"].map(lambda v: fmt(v, 0)),
            "part (Rmax)": df["share_rmax_pct"].map(lambda v: fmt(v, 1, " %")),
            "GFlops/W": df["energy_efficiency_gflops_w"].map(lambda v: fmt(v, 1)),
            "meilleur rang": df["best_system_rank"],
        }
    )
    render_table(
        table,
        title=f"TOP500 {df['edition'].iloc[0]} : constructeurs classés par puissance",
        subtitle="mart_top500_vendor_share — requête DuckDB sur les exports Parquet (source : top500.org)",
        engine="DuckDB",
        path=OUT / "03_duckdb_top500_vendors.png",
        col_widths=[0.30, 0.10, 0.11, 0.14, 0.12, 0.11, 0.12],
    )


def dbt_lineage() -> None:
    manifest_path = ROOT / "dbt" / "target" / "manifest.json"
    if not manifest_path.exists():
        print("manifest.json absent : lancer dbt build avant (visuel 04 ignoré)")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    nodes: dict[str, tuple[str, str]] = {}  # unique_id -> (libellé, couche)
    for uid, src in manifest.get("sources", {}).items():
        nodes[uid] = (f"raw.{src['name']}", "source")
    for uid, node in manifest.get("nodes", {}).items():
        if node["resource_type"] == "seed":
            nodes[uid] = (node["name"], "seed")
        elif node["resource_type"] == "model":
            name = node["name"]
            layer = (
                "kpi"
                if name.startswith("mart_")
                else node.get("config", {}).get("schema") or "marts"
            )
            nodes[uid] = (name, layer)

    edges = [
        (dep, uid)
        for uid, node in manifest.get("nodes", {}).items()
        if uid in nodes
        for dep in node.get("depends_on", {}).get("nodes", [])
        if dep in nodes
    ]

    columns = {"source": 0, "seed": 0, "staging": 1, "intermediate": 2, "marts": 3, "kpi": 4}
    titles = ["Sources (raw)", "Staging", "Intermediate", "Marts", "KPI"]
    by_col: dict[int, list[str]] = {}
    for uid, (_, layer) in sorted(nodes.items(), key=lambda kv: (kv[1][1] == "seed", kv[1][0])):
        by_col.setdefault(columns[layer], []).append(uid)

    # ordonne chaque colonne selon la position moyenne de ses parents (heuristique de Sugiyama)
    parents: dict[str, list[str]] = {}
    for src, dst in edges:
        parents.setdefault(dst, []).append(src)
    for _ in range(3):
        rank = {uid: i for uids in by_col.values() for i, uid in enumerate(uids)}
        for col in sorted(by_col)[1:]:
            by_col[col].sort(
                key=lambda u: (
                    sum(rank[p] for p in parents.get(u, [])) / max(len(parents.get(u, [])), 1)
                )
            )

    max_rows = max(len(v) for v in by_col.values())
    fig_h = 1.6 + 0.62 * max_rows
    fig, ax = plt.subplots(figsize=(15, fig_h), dpi=200, facecolor=BG)
    ax.set_xlim(-0.6, 4.6)
    ax.set_ylim(-0.8, max_rows + 0.2)
    ax.axis("off")

    pos: dict[str, tuple[float, float]] = {}
    for col, uids in by_col.items():
        offset = (max_rows - len(uids)) / 2
        for i, uid in enumerate(uids):
            pos[uid] = (col, max_rows - 1 - offset - i)
        ax.text(
            col, max_rows - 0.15, titles[col], ha="center", fontsize=11, weight="bold", color=INK
        )

    for src, dst in edges:
        (x1, y1), (x2, y2) = pos[src], pos[dst]
        ax.annotate(
            "",
            xy=(x2 - 0.40, y2),
            xytext=(x1 + 0.40, y1),
            arrowprops={
                "arrowstyle": "-|>",
                "color": "#cbd5e1",
                "lw": 0.9,
                "shrinkA": 0,
                "shrinkB": 0,
                "connectionstyle": "arc3,rad=0.0",
            },
            zorder=1,
        )

    for uid, (x, y) in pos.items():
        label, layer = nodes[uid]
        color = LAYER_COLORS[layer]
        box = FancyBboxPatch(
            (x - 0.40, y - 0.21),
            0.80,
            0.42,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            fc=color,
            ec="none",
            zorder=2,
        )
        ax.add_patch(box)
        ax.text(
            x,
            y,
            label,
            ha="center",
            va="center",
            fontsize=8.6,
            color="white",
            weight="bold",
            zorder=3,
        )

    n_tests = sum(1 for n in manifest.get("nodes", {}).values() if n["resource_type"] == "test")
    ax.text(
        -0.6,
        -0.65,
        f"Graphe de lignage dbt — {len(nodes)} nœuds, {len(edges)} dépendances, {n_tests} tests de données",
        fontsize=10,
        color=MUTED,
    )
    fig.suptitle(
        "Du brut aux KPI : le pipeline dbt",
        x=0.06,
        ha="left",
        fontsize=16,
        weight="bold",
        color=INK,
    )

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "04_dbt_lineage.png"
    fig.savefig(path, bbox_inches="tight", pad_inches=0.3, facecolor=BG)
    plt.close(fig)
    print("écrit :", path.relative_to(ROOT))


if __name__ == "__main__":
    load_env()
    kpis_by_segment()
    quality_report()
    top500_vendors()
    dbt_lineage()