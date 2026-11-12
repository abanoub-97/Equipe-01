"""Score explicable des prospects, sur la grille du front (wireframe v2).

Potentiel /60 (adéquation /35, taille /15, dynamique /10), Opportunité /30,
Accessibilité /10. Le score vient de règles lisibles, pas du LLM : chaque point
peut être justifié devant un commercial. Les pondérations sont en tête de
fichier pour être ajustées sans toucher au reste.
"""

from __future__ import annotations

from collections import Counter
from statistics import mean

from .data import Dataset

DIVISIONS = {"Taste & Wellbeing", "Fragrance & Beauty"}

# Intérêt de chaque catégorie pour l'offre Givaudan (0 à 1)
CATEGORY_FIT = {
    "Fine Fragrances": 1.0,
    "Beverages": 0.95,
    "Active Beauty": 0.9,
    "Dairy": 0.9,
    "Sweet Goods": 0.85,
    "Fragrance Ingredients": 0.8,
    "Savoury": 0.8,
    "Consumer Products": 0.7,
}
DEFAULT_FIT = 0.6

# Valeur de chaque étape du pipeline pour l'opportunité (0 à 1)
STAGE_MOMENTUM = {
    "Negotiation": 0.9,
    "Evaluation/Sampling": 0.7,
    "Brief Received": 0.5,
    "Lead": 0.3,
    "Closed Won": 0.5,  # déjà client : potentiel de vente additionnelle
    "Closed Lost": 0.05,
}
OPEN_STAGES = ["Negotiation", "Evaluation/Sampling", "Brief Received", "Lead"]

PROOF = {"+": 1, "++": 2, "+++": 3}

FR = {
    # étapes
    "Negotiation": "négociation",
    "Evaluation/Sampling": "évaluation d'échantillons",
    "Brief Received": "brief reçu",
    "Lead": "premier contact",
    "Closed Won": "affaire gagnée",
    "Closed Lost": "affaire perdue",
    # rôles
    "Marketing": "Marketing",
    "Technical": "Technique (R&D)",
    "Purchasing": "Achats",
    "Regulatory": "Réglementaire",
    "Decision-maker": "Décision",
    # régions
    "Europe": "Europe",
    "North America": "Amérique du Nord",
    "Latin America": "Amérique latine",
    "Asia-Pacific": "Asie-Pacifique",
    "Middle East & Africa": "Moyen-Orient et Afrique",
    # catégories
    "Fine Fragrances": "Parfumerie fine",
    "Fragrance Ingredients": "Ingrédients de parfumerie",
    "Active Beauty": "Actifs cosmétiques",
    "Consumer Products": "Produits de grande consommation",
    "Sweet Goods": "Produits sucrés",
    "Beverages": "Boissons",
    "Savoury": "Produits salés",
    "Dairy": "Produits laitiers",
}


def fr(v: str) -> str:
    return FR.get(v, v)


def _num(v: str) -> float | None:
    try:
        return float(v.replace(",", ".").replace(" ", ""))
    except (AttributeError, ValueError):
        return None


def _first(rows: list[dict[str, str]], key: str) -> str:
    return next((r[key] for r in rows if r.get(key)), "")


def _percentile(values: list[float], v: float) -> float:
    if not values:
        return 0.5
    return sum(x <= v for x in values) / len(values)


def score_dataset(ds: Dataset) -> list[dict]:
    """Calcule le score et les faits de chaque prospect, triés par score."""
    groups = ds.by_prospect()
    volumes = sorted(
        v for rows in groups.values() if (v := _num(_first(rows, "volume"))) is not None
    )
    max_count = max((len(r) for r in groups.values()), default=1)

    prospects = [_score_one(pid, rows, volumes, max_count, ds.name) for pid, rows in groups.items()]
    prospects.sort(key=lambda p: p["score"]["total"], reverse=True)
    for i, p in enumerate(prospects, 1):
        p["score"]["rank"] = i
    return prospects


def _score_one(pid: str, rows: list[dict], volumes: list[float], max_count: int, source: str) -> dict:
    segment = _first(rows, "segment")
    category = _first(rows, "category")
    region = _first(rows, "region")
    stages = Counter(r["stage"] for r in rows if r.get("stage"))
    roles = Counter(r["role"] for r in rows if r.get("role"))
    proofs = [PROOF[r["proof"]] for r in rows if r.get("proof") in PROOF]
    volume = _num(_first(rows, "volume"))
    freq = _num(_first(rows, "frequency"))
    returning = _first(rows, "returning").lower() in {"true", "1", "oui", "yes"}
    n = len(rows)
    facts: list[dict] = []  # faits sourcés, donnés au rédacteur
    src = f"CRM · {n} interaction{'s' if n > 1 else ''}"

    # --- Potentiel ---
    fit_w = CATEGORY_FIT.get(category, DEFAULT_FIT)
    fit = round((20 if segment in DIVISIONS else 10) + 15 * fit_w)
    if volume is not None:
        pct = _percentile(volumes, volume)
        size_pts = 11 * pct
        facts.append({"text": f"Volume moyen commandé : {volume:,.0f} kg par commande".replace(",", " "), "source": src})
    else:
        pct, size_pts = 0.5, 5.5
    if freq is not None:
        size_pts += 4 * max(0.0, 1 - (freq - 1) / 11)
        facts.append({"text": f"Commande environ tous les {freq:.0f} mois", "source": src})
    size_pts = round(min(15, size_pts))
    dyn = round(min(10, 6 * n / max_count + (4 * mean(proofs) / 3 if proofs else 2)))

    # --- Opportunité ---
    open_stage = next((s for s in OPEN_STAGES if stages.get(s)), None)
    main_stage = open_stage or ("Closed Won" if stages.get("Closed Won") else "Closed Lost" if stages else None)
    opp_notes: list[str] = []
    opp = 0
    if stages:
        # Dynamique du pipeline : moyenne des étapes de tous les échanges, pour
        # distinguer un compte qui négocie souvent d'un compte surtout perdu
        momentum = mean(STAGE_MOMENTUM.get(s, 0.3) for s in stages.elements())
        opp = round(24 * momentum)
        opp_notes.append(f"Dynamique du pipeline ({sum(stages.values())} échanges) · {opp} pts")
        facts.append({"text": f"Pipeline : étape la plus avancée « {fr(main_stage)} »", "source": src})
        if stages.get("Negotiation"):
            facts.append({"text": f"{stages['Negotiation']} échange(s) en négociation", "source": src})
    strong = sum(p == 3 for p in proofs)
    if proofs:
        bonus = round(4 * strong / len(proofs))
        if bonus:
            opp += bonus
            opp_notes.append(f"Preuves fortes (+++) : {strong} sur {len(proofs)} · +{bonus} pts")
    if stages.get("Closed Won") and open_stage:
        opp += 2
        opp_notes.append("Déjà client avec un projet en cours · +2 pts")
        facts.append({"text": "Déjà client Givaudan, avec un nouveau projet ouvert", "source": src})
    if stages.get("Closed Lost"):
        facts.append({"text": f"{stages['Closed Lost']} affaire(s) perdue(s) par le passé", "source": src})
    signals = _signals(rows)
    for sg in signals:
        when = f" · {sg['date']}" if sg["date"] else ""
        facts.insert(0, {"text": f"{sg['kind']} : {sg['summary']}", "source": f"{sg['source']}{when}"})
    if signals:
        bonus = min(8, 2 * len(signals))
        opp += bonus
        opp_notes.append(f"Signaux externes : {len(signals)} · +{bonus} pts")
    opp = min(30, opp)

    # --- Accessibilité ---
    acc = 0
    acc_notes: list[str] = []
    if roles.get("Decision-maker"):
        acc += 4
        acc_notes.append("Décideur déjà rencontré")
    acc += round(3 * min(len(roles), 5) / 5)
    if roles:
        acc_notes.append(f"{len(roles)} fonction(s) rencontrée(s) : " + ", ".join(fr(r) for r in roles))
        facts.append({"text": "Interlocuteurs rencontrés : " + ", ".join(fr(r) for r in roles), "source": src})
    named = {r["contact_name"] for r in rows if r.get("contact_name")}
    if named:
        acc += min(4, 2 * len(named))
        acc_notes.append(f"{len(named)} interlocuteur(s) identifié(s) par leur nom")
    if any(r.get("contact_email") for r in rows):
        acc += 1
        acc_notes.append("E-mail professionnel connu")
    if returning:
        acc += 3
        acc_notes.append("Client existant")
    acc = min(10, acc)

    potential = fit + size_pts + dyn
    total = potential + opp + acc

    # Taille : colonne du fichier si elle existe, sinon déduite du volume
    size = _first(rows, "size") or ("GE" if pct >= 0.85 else "ETI" if pct >= 0.4 else "PME")
    transcripts = list(dict.fromkeys(r["transcript"] for r in rows if r.get("transcript")))
    for t in transcripts[:3]:
        facts.append({"text": f"Note d'échange : {t}", "source": src})

    return {
        "id": _slug(pid),
        "name": _first(rows, "name") or pid.replace("_", " "),
        "segment": segment or "Non renseigné",
        "activity": fr(category) if category else "Non renseignée",
        "country": _first(rows, "country") or fr(region) or "Non renseigné",
        "city": _first(rows, "city"),
        "size": size,
        "revenue": _first(rows, "revenue") or None,
        "reach": "Internationale" if len({r.get("region") for r in rows}) > 1 else "Régionale",
        "website": _first(rows, "website"),
        "why": "",  # rempli par le rédacteur
        "score": {
            "total": total,
            "rank": 0,
            "reliability": "élevée" if n >= 10 else "moyenne" if n >= 5 else "faible",
            "sources": n,
            "axes": [
                {
                    "label": "Potentiel",
                    "value": potential,
                    "max": 60,
                    "items": [
                        {"label": "Adéquation avec l'offre Givaudan", "value": fit, "max": 35},
                        {"label": "Taille & solidité", "value": size_pts, "max": 15},
                        {"label": "Dynamique d'innovation", "value": dyn, "max": 10},
                    ],
                },
                {
                    "label": "Opportunité",
                    "value": opp,
                    "max": 30,
                    "items": [{"label": "Pipeline et signaux", "value": opp, "max": 30}],
                    "notes": opp_notes,
                },
                {
                    "label": "Accessibilité",
                    "value": acc,
                    "max": 10,
                    "items": [{"label": "Interlocuteurs et lien Givaudan", "value": acc, "max": 10}],
                    "notes": acc_notes,
                },
            ],
        },
        "signals": signals,
        "takeaways": [],
        "questions": [],
        "contacts": _contacts(rows, roles),
        "history": _history(stages, returning),
        # Interne : ne part pas dans l'API
        "_facts": facts,
        "_source": source,
    }


def _slug(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _signals(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r.get("signal_kind") or r.get("signal_summary"):
            out.append(
                {
                    "kind": r.get("signal_kind") or "Lancement produit",
                    "summary": r.get("signal_summary", ""),
                    "source": r.get("signal_source") or "Jeu de données",
                    "date": r.get("date", ""),
                }
            )
    return out


def _contacts(rows: list[dict], roles: Counter) -> list[dict]:
    named = {}
    for r in rows:
        if r.get("contact_name"):
            named.setdefault(r["contact_name"], r)
    if named:
        return [
            {
                "name": name,
                "role": fr(r.get("role", "")) or "Interlocuteur",
                "buyingRole": fr(r.get("role", "")) or "Non précisé",
                "email": r.get("contact_email", ""),
                "recommended": i == 0,
            }
            for i, (name, r) in enumerate(named.items())
        ]
    # Données anonymisées : un interlocuteur par fonction, sans nom
    order = ["Decision-maker", "Technical", "Purchasing", "Marketing", "Regulatory"]
    present = sorted(roles, key=lambda r: order.index(r) if r in order else 99)
    return [
        {
            "name": f"Contact {fr(r)}",
            "role": f"Nom non communiqué · {roles[r]} échange(s)",
            "buyingRole": fr(r),
            "email": "",
            "recommended": i == 0,
        }
        for i, r in enumerate(present)
    ]


def _history(stages: Counter, returning: bool) -> str:
    if not stages:
        return "Aucun échange connu avec Givaudan."
    parts = [f"{c} × {fr(s)}" for s, c in stages.most_common()]
    head = "Client existant. " if returning else ""
    return f"{head}Historique CRM : " + ", ".join(parts) + "."
