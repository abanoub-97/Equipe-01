"""Tester un jeu de données sans lancer l'API.

  python -m prospection donnees.csv                 classement et score
  python -m prospection donnees.csv --fiche ID      fiche complète (rédaction par règles)
  python -m prospection donnees.csv --fiche ID --llm   rédaction par le LLM (Ollama)
  python -m prospection donnees.xlsx --mapping colonnes.json
"""

from __future__ import annotations

import argparse
import json
import sys

from .data import load_path
from .store import store


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m prospection")
    ap.add_argument("fichier")
    ap.add_argument("--mapping", help="JSON champ -> colonne")
    ap.add_argument("--fiche", help="identifiant du prospect à détailler")
    ap.add_argument("--llm", action="store_true", help="rédiger avec le LLM (sinon : règles)")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()

    ds = load_path(a.fichier, a.mapping)
    store.use(ds)
    info = store.info()
    print(f"{info['name']} : {info['rows']} lignes, {info['prospects']} prospects")
    print("Colonnes reconnues :", ", ".join(f"{k}={v}" for k, v in ds.columns.items()))
    if ds.ignored:
        print("Colonnes ignorées :", ", ".join(ds.ignored))

    if a.fiche:
        p = store.get(a.fiche)
        if not p:
            sys.exit(f"Prospect introuvable : {a.fiche}")
        print(json.dumps(store.render(p, use_llm=a.llm), ensure_ascii=False, indent=2))
        return

    print()
    print(f"{'#':>3}  {'id':<14} {'score':>5}  pot opp acc  {'segment':<20} activité")
    for p in store.prospects[: a.top]:
        pot, opp, acc = (x["value"] for x in p["score"]["axes"])
        print(f"{p['score']['rank']:>3}  {p['id']:<14} {p['score']['total']:>5}  {pot:>3} {opp:>3} {acc:>3}  {p['segment']:<20} {p['activity']}")


if __name__ == "__main__":
    main()
