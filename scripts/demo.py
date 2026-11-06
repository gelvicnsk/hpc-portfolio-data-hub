"""Affiche les KPI principaux du Data Hub via l'API (bibliothèque standard uniquement).

Usage : python3 scripts/demo.py [http://localhost:8001]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10) as response:
        return json.load(response)


def wait_for_api(timeout_s: int = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            get("/health")
            return
        except (urllib.error.URLError, ConnectionError):
            if time.monotonic() > deadline:
                sys.exit(f"API injoignable sur {BASE_URL} (voir : make logs)")
            time.sleep(2)


def fmt_eur(value: str | float | None) -> str:
    return "n/a" if value is None else f"{float(value) / 1e6:,.1f} M€".replace(",", " ")


def title(text: str) -> None:
    print(f"\n\033[1m{text}\033[0m\n" + "-" * len(text))


def main() -> None:
    wait_for_api()

    kpis = get("/kpis/portfolio")
    g = kpis["global"]
    title("Portefeuille HPC")
    print(
        f"Projets            : {g['n_projects']} (actifs {g['n_active_projects']}, livrés {g['n_delivered_projects']}, en retard sur planning {g['n_overdue_projects']})"
    )
    print(f"Livraison à l'heure: {g['on_time_delivery_pct']} %")
    print(
        f"Retard moyen       : {g['avg_delay_days']} j ({g['avg_delay_days_when_late']} j pour les projets en retard)"
    )
    print(
        f"Budget             : {fmt_eur(g['total_cost_eur'])} dépensés / {fmt_eur(g['total_budget_eur'])} ({g['budget_variance_pct']} %), {g['n_projects_over_budget']} projets > +5 %"
    )
    print(f"Incidents ouverts  : {g['n_open_incidents']}")

    title("Par segment")
    print(f"{'segment':<12}{'projets':>8}{'à l heure':>11}{'retard j':>10}{'budget %':>10}")
    for row in kpis["by_segment"]:
        print(
            f"{row['scope_value']:<12}{row['n_projects']:>8}{row['on_time_delivery_pct'] or '-':>10}%{row['avg_delay_days'] or '-':>10}{row['budget_variance_pct']:>10}"
        )

    title("Incidents par sévérité")
    for row in kpis["incidents_by_severity"]:
        print(
            f"{row['severity']:<10} {row['n_incidents']:>4} incidents, {row['n_open']:>2} ouverts, résolution moyenne {row['avg_resolution_hours']} h"
        )

    try:
        top = get("/top500/vendors?page_size=6")
        title(f"TOP500 — édition {top['edition']} (par puissance Rmax)")
        print(
            f"{'constructeur':<34}{'systèmes':>9}{'part %':>8}{'Rmax PF':>10}{'part Rmax %':>13}{'GFlops/W':>10}"
        )
        for v in top["items"]:
            print(
                f"{v['vendor_group'][:33]:<34}{v['n_systems']:>9}{v['share_systems_pct']:>8}{v['rmax_pflops']:>10}{v['share_rmax_pct']:>13}{v['energy_efficiency_gflops_w'] or '-':>10}"
            )
    except urllib.error.HTTPError:
        title("TOP500")
        print(
            "Aucune édition chargée : déposer les fichiers dans data/raw/top500/ puis « make pipeline »"
        )

    quality = get("/quality/report")
    title("Qualité des données (dernier dbt build)")
    print("Résumé :", ", ".join(f"{k}={v}" for k, v in quality["summary"].items()))
    for test in quality["tests"]:
        if test["status"] != "pass":
            print(f"  [{test['status']}] {test['test_name']} : {test['failures']} ligne(s)")

    print(f"\nSwagger : {BASE_URL}/docs")


if __name__ == "__main__":
    main()
