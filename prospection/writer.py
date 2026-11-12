"""Rédaction de « Pourquoi maintenant », « À retenir » et « Questions à poser ».

Le LLM (Ollama en local, ou une API compatible OpenAI : Groq, Mistral,
Gemini…) ne reçoit que des faits numérotés et sourcés, et doit citer le
numéro du fait qu'il reformule : la source affichée vient du fait, jamais du
LLM. Si le LLM est absent, lent ou répond mal, une rédaction par règles prend
le relais, pour que la démo ne casse jamais.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from pathlib import Path


def _load_env_file() -> None:
    """Lit Equipe-01/.env (non versionné) sans écraser les variables déjà définies."""
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

# « ollama » (local) ou « openai » (toute API compatible : Groq, Mistral, Gemini…)
PROVIDER = os.getenv("PROSPECT_LLM_PROVIDER", "ollama")
BASE_URL = os.getenv("PROSPECT_LLM_BASE_URL", "").rstrip("/")
API_KEY = os.getenv("PROSPECT_LLM_API_KEY", "")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.getenv("PROSPECT_LLM_MODEL", "qwen2.5:3b")
TIMEOUT = float(os.getenv("PROSPECT_LLM_TIMEOUT", "90"))
KEEP_ALIVE = os.getenv("PROSPECT_LLM_KEEP_ALIVE", "30m")
# « llm » par défaut, avec retour aux règles si Ollama ou le modèle manquent.
# Prévoir au moins 3B paramètres : llama3.2:1b invente et parle en « nous ».
DEFAULT_ENGINE = os.getenv("PROSPECT_WRITER", "llm")

# Signes d'une réponse à jeter : consigne recopiée ou texte écrit au nom de Givaudan
_BAD = re.compile(r"phrase courte|majuscule|\b(nous|notre|nos|je)\b", re.I)

SYSTEM = """Tu aides un commercial de Givaudan (arômes et parfums) à préparer un rendez-vous.
On te donne des FAITS numérotés sur un prospect. Tu n'inventes rien : chaque phrase reprend un ou plusieurs faits.
Écris à la troisième personne, sur le prospect (« ils », « l'entreprise »), jamais « nous ».
Réponds uniquement en JSON, en français, avec exactement ces clés :
{"why": "une phrase courte, sans majuscule au début, qui dit pourquoi contacter ce prospect maintenant",
 "takeaways": [{"text": "une phrase claire, avec **gras** sur l'élément clé", "fact": numéro du fait}],
 "questions": [{"text": "une question ouverte à poser au client", "facts": [numéros des faits liés]}]}
Donne 3 takeaways et 4 questions. Chaque phrase fait moins de 20 mots. Les questions font émerger des besoins implicites (goût, formulation, réglementation, calendrier, décision)."""


# Structure imposée au LLM (sortie structurée d'Ollama) : évite les JSON cassés
SCHEMA = {
    "type": "object",
    "properties": {
        "why": {"type": "string"},
        "takeaways": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "fact": {"type": "integer"}},
                "required": ["text", "fact"],
            },
        },
        "questions": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "facts": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["text", "facts"],
            },
        },
    },
    "required": ["why", "takeaways", "questions"],
}


def _tidy(text: str, bold: bool) -> str:
    """Retire les ** en trop (ou tous, si le gras n'est pas voulu)."""
    text = " ".join(html.unescape(text).split()).strip("«»\" ")
    if not bold or text.count("**") % 2:
        text = text.replace("**", "")
    return text[:1].upper() + text[1:]


def _facts_block(p: dict) -> str:
    head = f"Prospect : {p['name']} · {p['segment']} · {p['activity']} · {p['country']} · score {p['score']['total']}/100"
    lines = [f"{i}. {f['text']}" for i, f in enumerate(p["_facts"], 1)]
    return head + "\nFAITS :\n" + "\n".join(lines)


def _ask_openai(p: dict) -> dict | None:
    """Appel d'une API compatible OpenAI (/chat/completions), sans dépendance."""
    try:
        body = json.dumps({
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _facts_block(p)},
            ],
            "temperature": 0.3,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
        }).encode()
        req = urllib.request.Request(
            f"{BASE_URL}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            data = json.load(res)
        return json.loads(data["choices"][0]["message"]["content"])
    except Exception:  # clé absente ou fausse, quota atteint, délai dépassé, JSON invalide
        return None


def _ask_llm(p: dict) -> dict | None:
    if PROVIDER == "openai":
        return _ask_openai(p)
    try:
        from ollama import Client

        client = Client(host=OLLAMA_HOST, timeout=TIMEOUT)
        res = client.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _facts_block(p)},
            ],
            format=SCHEMA,
            options={"temperature": 0.3, "num_predict": 500, "repeat_penalty": 1.15},
            keep_alive=KEEP_ALIVE,  # modèle gardé en mémoire entre deux fiches
        )
        return json.loads(res["message"]["content"])
    except Exception:  # LLM absent, modèle manquant, délai dépassé, JSON invalide
        return None


def _clean(p: dict, out: dict) -> dict | None:
    """Garde seulement ce qui est conforme ; None si l'ensemble est inutilisable."""
    facts = p["_facts"]
    n = len(facts)

    def ref(x) -> int | None:
        try:
            i = int(x)
        except (TypeError, ValueError):
            return None
        return i if 1 <= i <= n else None

    takeaways = []
    for t in out.get("takeaways") or []:
        if isinstance(t, dict) and isinstance(t.get("text"), str) and t["text"].strip():
            i = ref(t.get("fact"))
            if not i:  # un point « À retenir » doit reprendre un fait sourcé
                continue
            takeaways.append({
                "text": _tidy(t["text"], bold=True),
                "source": facts[i - 1]["source"],
                "_fact": i,
            })
    takeaways = takeaways[:3]
    # Numéro du fait -> numéro du point « À retenir » qui le reprend
    point_of = {t["_fact"]: k for k, t in enumerate(takeaways, 1) if t["_fact"]}
    for t in takeaways:
        t.pop("_fact")

    questions = []
    for q in out.get("questions") or []:
        if isinstance(q, dict) and isinstance(q.get("text"), str) and q["text"].strip():
            refs = q.get("facts") or []
            links = sorted({point_of[i] for i in (ref(x) for x in refs) if i in point_of})
            text = _tidy(q["text"], bold=False)
            questions.append({"text": text, "links": links or "contacts"})
    questions = questions[:4]

    why = out.get("why")
    texts = [t["text"] for t in takeaways] + [q["text"] for q in questions] + [str(why)]
    if any(_BAD.search(x) for x in texts):
        return None
    if len(takeaways) < 2 or len(questions) < 2 or not isinstance(why, str) or not why.strip():
        return None
    why = why.strip().rstrip(".")
    return {"why": why[0].lower() + why[1:] + ".", "takeaways": takeaways, "questions": questions}


def _fallback(p: dict) -> dict:
    """Rédaction par règles, à partir des mêmes faits."""
    facts = p["_facts"]
    stage = next((f["text"] for f in facts if f["text"].startswith("Pipeline")), "")
    if p["signals"]:
        s0 = p["signals"][0]
        summary = s0["summary"] or s0["kind"]
        why = summary[0].lower() + summary[1:]
    elif stage:
        why = stage.replace("Pipeline : étape la plus avancée", "projet en cours, au stade")
    else:
        why = "bonne adéquation avec l'offre Givaudan"
    picked = [f for f in facts if not f["text"].startswith("Note d'échange")][:3] or facts[:3]
    takeaways = [{"text": f["text"], "source": f["source"]} for f in picked]
    seg = p["segment"]
    taste = seg == "Taste & Wellbeing"
    questions = [
        {"text": "Où en est votre projet, et quelles sont les prochaines étapes de votre côté ?", "links": [1] if takeaways else "contacts"},
        {
            "text": "Quel profil de goût recherchez-vous, et quelles contraintes de formulation devez-vous respecter ?"
            if taste
            else "Quelle signature olfactive recherchez-vous, et sur quels produits ?",
            "links": [2] if len(takeaways) > 1 else "contacts",
        },
        {"text": "Quelles contraintes réglementaires ou clean label s'appliquent à vos marchés ?", "links": [3] if len(takeaways) > 2 else "contacts"},
        {"text": "Qui valide le choix du fournisseur : R&D, achats ou marketing ?", "links": "contacts"},
    ]
    return {"why": why.rstrip(".") + ".", "takeaways": takeaways, "questions": questions}


def write(p: dict, use_llm: bool | None = None) -> dict:
    """Renvoie why, takeaways, questions et le moteur utilisé ('llm' ou 'regles')."""
    if use_llm is None:
        use_llm = DEFAULT_ENGINE == "llm"
    if use_llm:
        raw = _ask_llm(p)
        if raw:
            cleaned = _clean(p, raw)
            if cleaned:
                return {**cleaned, "engine": "llm"}
    return {**_fallback(p), "engine": "regles"}


def llm_status() -> dict:
    if PROVIDER == "openai":
        return {
            "provider": "openai",
            "baseUrl": BASE_URL,
            "model": MODEL,
            "apiKey": "renseignée" if API_KEY else "absente",
            "defaultWriter": DEFAULT_ENGINE,
        }
    try:
        from ollama import Client

        models = [m.model for m in Client(host=OLLAMA_HOST, timeout=3).list().models]
        return {"ollama": "ok", "model": MODEL, "defaultWriter": DEFAULT_ENGINE, "modelInstalled": any(m.startswith(MODEL) for m in models)}
    except Exception as e:
        return {"ollama": "injoignable", "model": MODEL, "detail": str(e)[:120]}
