"""Chargement d'un jeu de données de prospects (CSV ou XLSX).

Chaque ligne est une interaction ou un fait sur une entreprise. Les colonnes sont
reconnues par leur nom (voir ALIASES) ; un fichier JSON de correspondance peut
forcer un nom de colonne pour un champ : {"name": "Raison sociale", ...}.
Seule la colonne d'identifiant est obligatoire.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Champ interne -> noms de colonnes acceptés (comparés sans accents ni casse)
ALIASES: dict[str, list[str]] = {
    "id": ["client_id", "id", "company_id", "entreprise_id", "prospect_id"],
    "name": ["name", "company", "company_name", "entreprise", "raison_sociale", "nom"],
    "segment": ["division", "segment", "business_unit"],
    "category": ["category", "categorie", "sector", "secteur", "activite", "activity"],
    "country": ["country", "pays"],
    "city": ["city", "ville"],
    "region": ["region", "zone"],
    "size": ["size", "taille"],
    "revenue": ["revenue", "ca", "chiffre_affaires", "turnover"],
    "employees": ["employees", "effectif", "salaries"],
    "website": ["website", "site", "site_web", "url"],
    "volume": ["avg_order_volume_kg", "volume", "volume_kg"],
    "frequency": ["order_frequency_months", "frequency", "frequence"],
    "returning": ["is_returning_customer", "returning", "client_existant"],
    "stage": ["pipeline_stage", "stage", "etape", "statut"],
    "role": ["stakeholder_role", "role", "contact_role", "fonction"],
    "contact_name": ["contact_name", "contact", "nom_contact"],
    "contact_email": ["contact_email", "email", "mail"],
    "transcript": ["transcript", "notes", "note", "commentaire", "compte_rendu"],
    "proof": ["proof_strength", "proof", "preuve"],
    "date": ["interaction_timestamp", "date", "interaction_date"],
    "signal_kind": ["signal_kind", "signal_type", "type_signal"],
    "signal_summary": ["signal_summary", "signal", "signal_label"],
    "signal_source": ["signal_source", "source"],
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


@dataclass
class Dataset:
    name: str
    columns: dict[str, str]  # champ interne -> colonne du fichier
    rows: list[dict[str, str]] = field(default_factory=list)  # champs internes
    ignored: list[str] = field(default_factory=list)  # colonnes non reconnues

    def by_prospect(self) -> dict[str, list[dict[str, str]]]:
        groups: dict[str, list[dict[str, str]]] = {}
        for r in self.rows:
            if r.get("id"):
                groups.setdefault(r["id"], []).append(r)
        return groups


def _read_table(content: bytes, filename: str) -> list[dict[str, str]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        sheet = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
        it = sheet.iter_rows(values_only=True)
        header = [str(h or "") for h in next(it)]
        return [
            {h: "" if v is None else str(v) for h, v in zip(header, row)}
            for row in it
            if any(v not in (None, "") for v in row)
        ]
    text = content.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def match_columns(header: list[str], mapping: dict[str, str] | None = None) -> dict[str, str]:
    """Associe chaque champ interne à une colonne du fichier."""
    by_norm = {_norm(h): h for h in header if h}
    found: dict[str, str] = {}
    for key, names in ALIASES.items():
        for n in names:
            if n in by_norm:
                found[key] = by_norm[n]
                break
    for key, col in (mapping or {}).items():
        if key not in ALIASES:
            raise ValueError(f"Champ inconnu dans la correspondance : {key}")
        if col not in header:
            raise ValueError(f"Colonne absente du fichier : {col}")
        found[key] = col
    if "id" not in found:
        if "name" not in found:
            raise ValueError(
                "Aucune colonne d'identifiant ou de nom reconnue. "
                f"Colonnes du fichier : {', '.join(h for h in header if h)}"
            )
        found["id"] = found["name"]
    return found


def load(content: bytes, filename: str, mapping: dict[str, str] | None = None) -> Dataset:
    table = _read_table(content, filename)
    if not table:
        raise ValueError("Le fichier ne contient aucune ligne.")
    header = list(table[0].keys())
    cols = match_columns(header, mapping)
    used = set(cols.values())
    # Colonnes vides générées par Excel (« Colonne12 », « Unnamed: 3 »…) : ignorées
    ignored = [
        h for h in header
        if h and h not in used and not re.match(r"^(colonne|unnamed)\W?\d+", _norm(h))
    ]
    rows = [
        {key: (raw.get(col) or "").strip() for key, col in cols.items()}
        for raw in table
    ]
    return Dataset(name=Path(filename).name, columns=cols, rows=rows, ignored=ignored)


def load_path(path: str | Path, mapping_path: str | Path | None = None) -> Dataset:
    path = Path(path)
    mapping = json.loads(Path(mapping_path).read_text("utf-8")) if mapping_path else None
    return load(path.read_bytes(), path.name, mapping)
