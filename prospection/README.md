# Service de prospection

Charge un jeu de données de prospects (CSV ou XLSX), calcule un score explicable
et rédige la fiche affichée par le front de `hackathon-app` (types de
`web/src/types.ts`, wireframe v2).

| Fichier       | Rôle |
|---------------|------|
| `data.py`     | Lecture du fichier et reconnaissance des colonnes (`ALIASES`). Une ligne = une interaction ou un fait ; les lignes sont regroupées par prospect. |
| `scoring.py`  | Score sur 100 : Potentiel /60 (adéquation /35, taille /15, dynamique /10), Opportunité /30, Accessibilité /10. Règles et pondérations en tête de fichier. Produit aussi les faits sourcés de chaque prospect. |
| `writer.py`   | « Pourquoi maintenant », « À retenir » et « Questions à poser ». Par LLM via Ollama (défaut, `qwen2.5:3b`), avec retour aux règles si Ollama est absent ou si la réponse est invalide. |
| `store.py`    | Jeu de données courant et rédactions mises en cache, en mémoire. |
| `api.py`      | API FastAPI. |
| `__main__.py` | Test en ligne de commande, sans lancer l'API. |

## Tester un jeu de données

```bash
pip install -r requirements.txt
python -m prospection givaudan_crm_data.csv                  # classement
python -m prospection givaudan_crm_data.csv --fiche client-5591          # rédaction par règles
python -m prospection givaudan_crm_data.csv --fiche client-5591 --llm    # rédaction par le LLM
python -m prospection exemples/prospects-exemple.csv --mapping exemples/correspondance-exemple.json --fiche nordika-foods
```

Seule une colonne d'identifiant ou de nom est obligatoire. Les autres sont
reconnues par leur nom (`client_id`, `division`, `pipeline_stage`, `pays`…,
liste complète dans `ALIASES` de `data.py` ou sur `GET /datasets`). Pour un nom
de colonne non reconnu, un fichier JSON `{"champ": "Nom de la colonne"}`.
Les colonnes inconnues sont listées puis ignorées. Séparateurs acceptés : `,` `;` tabulation.

## Lancer l'API

```bash
uvicorn prospection.api:app --reload --port 8000
```

Swagger : http://localhost:8000/docs

| Route | Rôle |
|-------|------|
| `GET /health` | État du service, du jeu de données et d'Ollama |
| `GET /prospects` | Tous les prospects, triés par score |
| `GET /prospects/{id}` | La fiche ; `?llm=true` force le LLM, `?llm=false` les règles |
| `GET /datasets` | Jeu de données courant, colonnes reconnues et noms acceptés |
| `POST /datasets` | Remplace le jeu de données : `file` (CSV/XLSX), `mapping` (JSON, optionnel) |

## Réglages (variables d'environnement ou fichier `.env`)

Modèle à copier : `.env.example` à la racine du dépôt.

| Variable | Défaut | Rôle |
|----------|--------|------|
| `PROSPECT_DATASET` | `givaudan_crm_data.csv` | Jeu de données chargé au démarrage |
| `PROSPECT_MAPPING` | aucun | Correspondance des colonnes pour ce fichier |
| `PROSPECT_WRITER` | `llm` | `regles` pour une rédaction instantanée, sans LLM |
| `PROSPECT_LLM_MODEL` | `qwen2.5:3b` | Modèle Ollama (`ollama pull qwen2.5:3b`) |
| `PROSPECT_LLM_PROVIDER` | `ollama` | `openai` pour une API compatible OpenAI (Groq, Mistral, Gemini…) |
| `PROSPECT_LLM_BASE_URL` | vide | URL de l'API, ex. `https://api.groq.com/openai/v1` |
| `PROSPECT_LLM_API_KEY` | vide | Clé de l'API, dans `.env` uniquement (jamais commitée) |
| `IA_API_KEY` | vide | Si renseignée, exigée dans l'en-tête `X-API-Key` |

Le LLM ne reçoit que des faits numérotés et sourcés : la source affichée sous
chaque point vient du fait, jamais du modèle. Une réponse qui recopie la
consigne, parle en « nous » ou ne cite aucun fait est rejetée. Avec
`llama3.2:1b`, c'est le cas la plupart du temps : garder un modèle d'au moins
3B paramètres. Compter 15 à 45 s par fiche sur un PC sans GPU ; la fiche est
ensuite gardée en mémoire, et la liste `/prospects` utilise les règles.

## Limites du CRM actuel

`givaudan_crm_data.csv` : 50 clients, 520 interactions, sans nom d'entreprise
ni de contact (PII retirées), horodatages inexploitables et comptes rendus
génériques. Le score s'appuie donc surtout sur le pipeline, les rôles
rencontrés, le volume et la fréquence de commande. Un fichier avec noms,
signaux datés et notes d'échange donne des fiches bien plus riches (voir
`exemples/`).
