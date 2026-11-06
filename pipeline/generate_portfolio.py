"""Génère les données synthétiques du portefeuille HPC (reproductibles, seed fixe).

Les vraies données d'un portefeuille de supercalculateurs sont confidentielles : on les
simule avec des distributions réalistes (retards, dépassements, incidents) et des
**anomalies injectées en quantité connue**. Le fichier anomalies.json les liste : la démo
compare ce qui a été injecté à ce que les tests dbt détectent.

Sorties (data/raw/portfolio/) :
    projects.csv, milestones.csv, incidents.csv, costs.csv, anomalies.json

Usage :
    python -m pipeline.generate_portfolio [--seed 42] [--n-projects 60] [--out data/raw/portfolio]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_SEED = 42
DEFAULT_N_PROJECTS = 60
# Date de référence fixe (et non « aujourd'hui ») : mêmes données à chaque exécution.
AS_OF = date(2026, 10, 31)

# Clients fictifs : aucun organisme réel n'est associé à de faux contrats ou retards.
CLIENTS: list[tuple[str, str, str]] = [  # (client, pays, segment)
    ("Institut de recherche Alpha", "France", "recherche"),
    ("Centre de calcul Helios", "Germany", "recherche"),
    ("Consortium EuroSim", "Italy", "recherche"),
    ("Laboratoire Boreal", "Finland", "recherche"),
    ("Universite Polaris", "Netherlands", "academique"),
    ("Universite Copernic", "Poland", "academique"),
    ("Campus Numerique Sud", "France", "academique"),
    ("Service meteo Nimbus", "France", "meteo"),
    ("Agence climat Cirrus", "Germany", "meteo"),
    ("Institut ocean Abysse", "Spain", "meteo"),
    ("Agence defense Rempart", "France", "defense"),
    ("Direction simulation Egide", "France", "defense"),
    ("Groupe energie Voltaire", "France", "industrie"),
    ("Aero Dynamique", "Germany", "industrie"),
    ("Pharma Genomia", "Belgium", "industrie"),
    ("Automobile Cinetique", "Spain", "industrie"),
]

SYSTEM_TYPES = [
    "BullSequana XH3000",
    "BullSequana XH3000 GPU",
    "BullSequana XH2000",
    "Extension de cluster",
    "Stockage HPC",
]

MILESTONES: list[tuple[str, float]] = [  # (jalon, position dans la durée prévue)
    ("Signature du contrat", 0.00),
    ("Conception", 0.15),
    ("Fabrication", 0.45),
    ("Livraison sur site", 0.70),
    ("Installation", 0.80),
    ("Recette", 0.92),
    ("Mise en production", 1.00),
]

SEVERITIES = ["low", "medium", "high", "critical"]
SEVERITY_PROBS = [0.40, 0.35, 0.18, 0.07]
# durée médiane de résolution (heures) : les incidents critiques sont traités en priorité
RESOLUTION_MEDIAN_HOURS = {"low": 200, "medium": 96, "high": 36, "critical": 10}
OPEN_BACKLOG_DAYS = 120
OPEN_BACKLOG_PROB = 0.6
INCIDENT_CATEGORIES = [
    "materiel",
    "reseau",
    "refroidissement",
    "logiciel",
    "stockage",
    "alimentation",
]

# Anomalies injectées : nombre exact, documenté dans le README et anomalies.json
ANOMALY_COUNTS = {
    "duplicate_projects": 3,
    "delivery_before_start": 2,
    "negative_costs": 4,
    "orphan_incidents": 5,
    "incident_closed_before_opened": 2,
    "invalid_severity": 1,
}


@dataclass
class PortfolioData:
    projects: pd.DataFrame
    milestones: pd.DataFrame
    incidents: pd.DataFrame
    costs: pd.DataFrame
    anomalies: dict[str, list[str]] = field(default_factory=dict)

    def tables(self) -> dict[str, pd.DataFrame]:
        return {
            "projects": self.projects,
            "milestones": self.milestones,
            "incidents": self.incidents,
            "costs": self.costs,
        }


def _month_starts(start: date, end: date) -> list[date]:
    months, current = [], date(start.year, start.month, 1)
    while current <= end:
        months.append(current)
        current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
    return months


def _draw_delay_days(rng: np.random.Generator) -> int:
    """~55 % à l'heure (voire en avance), ~30 % en léger retard, ~15 % en fort retard."""
    bucket = rng.choice(3, p=[0.55, 0.30, 0.15])
    if bucket == 0:
        return int(rng.integers(-15, 1))
    if bucket == 1:
        return int(rng.integers(1, 61))
    return int(rng.integers(61, 201))


def _generate_projects(rng: np.random.Generator, n_projects: int) -> tuple[pd.DataFrame, dict]:
    rows, hidden = [], {}
    first_start, last_start = date(2022, 1, 1), date(2026, 6, 30)
    span = (last_start - first_start).days
    for i in range(1, n_projects + 1):
        project_id = f"P{i:04d}"
        client, country, segment = CLIENTS[int(rng.integers(len(CLIENTS)))]
        start = first_start + timedelta(days=int(rng.integers(span)))
        planned_months = int(rng.integers(9, 31))
        planned_delivery = start + timedelta(days=round(planned_months * 30.4))
        delay = _draw_delay_days(rng)
        delivery = planned_delivery + timedelta(days=delay)
        delivered = delivery <= AS_OF
        value = float(np.clip(rng.lognormal(mean=np.log(18e6), sigma=0.9), 2e6, 150e6))
        rows.append(
            {
                "project_id": project_id,
                "client": client,
                "country": country,
                "segment": segment,
                "system_type": SYSTEM_TYPES[int(rng.integers(len(SYSTEM_TYPES)))],
                "contract_value_eur": int(round(value, -3)),
                "start_date": start.isoformat(),
                "planned_delivery": planned_delivery.isoformat(),
                "actual_delivery": delivery.isoformat() if delivered else None,
                "status": "livre" if delivered else "en_cours",
            }
        )
        # informations internes au générateur (non publiées) pour jalons et coûts
        hidden[project_id] = {
            "start": start,
            "planned_delivery": planned_delivery,
            "delay": delay,
            "end": min(delivery, AS_OF),
            "delivered": delivered,
            "value": value,
            "planned_months": planned_months,
            "overrun": bool(rng.random() < 0.20),
        }
    return pd.DataFrame(rows), hidden


def _generate_milestones(rng: np.random.Generator, hidden: dict) -> pd.DataFrame:
    rows, counter = [], 0
    for project_id, h in hidden.items():
        duration = (h["planned_delivery"] - h["start"]).days
        for name, position in MILESTONES:
            counter += 1
            planned = h["start"] + timedelta(days=round(duration * position))
            # le retard s'accumule au fil du projet
            drift = round(h["delay"] * position + rng.normal(0, 4)) if position > 0 else 0
            actual = planned + timedelta(days=drift)
            if actual <= AS_OF:
                status, actual_value = "termine", actual.isoformat()
            else:
                status = "en_retard" if planned < AS_OF else "a_venir"
                actual_value = None
            rows.append(
                {
                    "milestone_id": f"M{counter:05d}",
                    "project_id": project_id,
                    "name": name,
                    "planned_date": planned.isoformat(),
                    "actual_date": actual_value,
                    "status": status,
                }
            )
    return pd.DataFrame(rows)


def _generate_incidents(rng: np.random.Generator, hidden: dict) -> pd.DataFrame:
    rows, counter = [], 0
    as_of_ts = datetime.combine(AS_OF, time(23, 59))
    for project_id, h in hidden.items():
        active_days = max((h["end"] - h["start"]).days, 1)
        for _ in range(int(rng.poisson(active_days / 120))):
            counter += 1
            severity = str(rng.choice(SEVERITIES, p=SEVERITY_PROBS))
            opened = datetime.combine(h["start"], time(8)) + timedelta(
                minutes=int(rng.integers(active_days * 24 * 60))
            )
            hours = rng.lognormal(np.log(RESOLUTION_MEDIAN_HOURS[severity]), 0.8)
            closed: datetime | None = opened + timedelta(hours=float(hours))
            # projets en cours : une partie des incidents récents est encore en traitement
            recent = opened.date() >= AS_OF - timedelta(days=OPEN_BACKLOG_DAYS)
            if not h["delivered"] and recent and rng.random() < OPEN_BACKLOG_PROB:
                closed = None
            rows.append(
                {
                    "incident_id": f"I{counter:05d}",
                    "project_id": project_id,
                    "opened_at": opened.isoformat(timespec="minutes"),
                    "closed_at": closed.isoformat(timespec="minutes")
                    if closed is not None and closed <= as_of_ts
                    else None,
                    "severity": severity,
                    "category": str(rng.choice(INCIDENT_CATEGORIES)),
                }
            )
    return pd.DataFrame(rows)


def _generate_costs(rng: np.random.Generator, hidden: dict) -> pd.DataFrame:
    rows = []
    for project_id, h in hidden.items():
        # budget de coûts = 80 % du contrat, réparti sur la durée prévue
        monthly_budget = h["value"] * 0.80 / h["planned_months"]
        low, high = (1.10, 1.40) if h["overrun"] else (0.85, 1.05)
        for month in _month_starts(h["start"], h["end"]):
            factor = rng.uniform(low, high)
            rows.append(
                {
                    "project_id": project_id,
                    "month": month.isoformat(),
                    "cost_eur": round(monthly_budget * factor, 2),
                    "budget_eur": round(monthly_budget, 2),
                }
            )
    return pd.DataFrame(rows)


def _inject_anomalies(rng: np.random.Generator, data: PortfolioData) -> None:
    p, c, inc = data.projects, data.costs, data.incidents
    anomalies: dict[str, list[str]] = {}

    # projets livrés dont la livraison est antérieure au démarrage (dates inversées)
    delivered = p.index[p["status"] == "livre"].to_numpy()
    targets = rng.choice(delivered, ANOMALY_COUNTS["delivery_before_start"], replace=False)
    for idx in targets:
        start = date.fromisoformat(p.at[idx, "start_date"])
        p.at[idx, "actual_delivery"] = (
            start - timedelta(days=int(rng.integers(5, 40)))
        ).isoformat()
    anomalies["delivery_before_start"] = p.loc[targets, "project_id"].tolist()

    # doublons exacts de projets (double export depuis l'ERP) — sur d'autres projets
    others = p.index.difference(targets).to_numpy()
    dup_idx = rng.choice(others, ANOMALY_COUNTS["duplicate_projects"], replace=False)
    anomalies["duplicate_projects"] = p.loc[dup_idx, "project_id"].tolist()

    # coûts négatifs (avoirs mal saisis)
    neg_idx = rng.choice(c.index.to_numpy(), ANOMALY_COUNTS["negative_costs"], replace=False)
    c.loc[neg_idx, "cost_eur"] = -c.loc[neg_idx, "cost_eur"].abs()
    anomalies["negative_costs"] = (
        c.loc[neg_idx, "project_id"] + "/" + c.loc[neg_idx, "month"]
    ).tolist()

    # incidents : clés orphelines, dates inversées, sévérité hors référentiel (lignes distinctes)
    closed = inc.index[inc["closed_at"].notna()].to_numpy()
    n_orphan = ANOMALY_COUNTS["orphan_incidents"]
    n_inverted = ANOMALY_COUNTS["incident_closed_before_opened"]
    n_invalid = ANOMALY_COUNTS["invalid_severity"]
    picked = rng.choice(closed, n_orphan + n_inverted + n_invalid, replace=False)
    orphan_idx = picked[:n_orphan]
    inverted_idx = picked[n_orphan : n_orphan + n_inverted]
    invalid_idx = picked[n_orphan + n_inverted :]

    for k, idx in enumerate(orphan_idx, start=1):
        inc.at[idx, "project_id"] = f"P9{k:03d}"
    for idx in inverted_idx:
        opened = datetime.fromisoformat(inc.at[idx, "opened_at"])
        inc.at[idx, "closed_at"] = (opened - timedelta(hours=int(rng.integers(2, 48)))).isoformat(
            timespec="minutes"
        )
    inc.loc[invalid_idx, "severity"] = "urgent"

    anomalies["orphan_incidents"] = inc.loc[orphan_idx, "incident_id"].tolist()
    anomalies["incident_closed_before_opened"] = inc.loc[inverted_idx, "incident_id"].tolist()
    anomalies["invalid_severity"] = inc.loc[invalid_idx, "incident_id"].tolist()

    # les doublons sont ajoutés en dernier pour ne pas fausser les tirages précédents
    data.projects = pd.concat([p, p.loc[dup_idx]], ignore_index=True)
    data.anomalies = {k: sorted(v) for k, v in anomalies.items()}


def generate(seed: int = DEFAULT_SEED, n_projects: int = DEFAULT_N_PROJECTS) -> PortfolioData:
    rng = np.random.default_rng(seed)
    projects, hidden = _generate_projects(rng, n_projects)
    data = PortfolioData(
        projects=projects,
        milestones=_generate_milestones(rng, hidden),
        incidents=_generate_incidents(rng, hidden),
        costs=_generate_costs(rng, hidden),
    )
    _inject_anomalies(rng, data)
    return data


def write(data: PortfolioData, out_dir: Path, *, seed: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, df in data.tables().items():
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        paths.append(path)
    manifest: dict[str, Any] = {
        "seed": seed,
        "as_of": AS_OF.isoformat(),
        "row_counts": {name: len(df) for name, df in data.tables().items()},
        "anomalies": {k: {"count": len(v), "ids": v} for k, v in data.anomalies.items()},
    }
    manifest_path = out_dir / "anomalies.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    paths.append(manifest_path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Génère les données synthétiques du portefeuille")
    parser.add_argument("--seed", type=int, default=int(os.getenv("PORTFOLIO_SEED", DEFAULT_SEED)))
    parser.add_argument("--n-projects", type=int, default=DEFAULT_N_PROJECTS)
    parser.add_argument(
        "--out", type=Path, default=Path(os.getenv("DATA_DIR", "data")) / "raw" / "portfolio"
    )
    args = parser.parse_args(argv)

    data = generate(seed=args.seed, n_projects=args.n_projects)
    write(data, args.out, seed=args.seed)
    counts = ", ".join(f"{name}={len(df)}" for name, df in data.tables().items())
    logger.info("Portefeuille généré dans %s (seed=%d) : %s", args.out, args.seed, counts)
    logger.info("Anomalies injectées : %s", {k: len(v) for k, v in data.anomalies.items()})
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
