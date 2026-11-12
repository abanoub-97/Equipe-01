"""Jeu de données courant et rédactions déjà faites, gardés en mémoire.

Le LLM tourne sur le processeur : environ 15 s par fiche. Pour que les fiches
s'ouvrent tout de suite, les PROSPECT_PREGENERATE premières (10 par défaut) sont
rédigées en arrière-plan dès le chargement d'un jeu de données, une par une.
Deux demandes de la même fiche en même temps n'en lancent qu'une rédaction.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import writer
from .data import Dataset, load_path
from .scoring import score_dataset

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = Path(os.getenv("PROSPECT_DATASET", BASE_DIR / "givaudan_crm_data.csv"))
DEFAULT_MAPPING = os.getenv("PROSPECT_MAPPING")  # fichier JSON, optionnel
PREGENERATE = int(os.getenv("PROSPECT_PREGENERATE", "10"))


class Store:
    def __init__(self) -> None:
        self.dataset: Dataset | None = None
        self.prospects: list[dict] = []
        self.written: dict[str, dict] = {}  # id -> rédaction du LLM
        self.generation = 0  # change à chaque jeu de données
        self.lock = threading.Lock()
        self.id_locks: dict[str, threading.Lock] = {}
        self.llm_lock = threading.Lock()  # une seule rédaction à la fois sur le CPU
        self.users_waiting = 0  # fiches demandées par quelqu'un, prioritaires

    def use(self, ds: Dataset) -> None:
        prospects = score_dataset(ds)
        with self.lock:
            self.dataset, self.prospects, self.written = ds, prospects, {}
            self.id_locks = {}
            self.generation += 1
            gen = self.generation
        if PREGENERATE > 0 and writer.DEFAULT_ENGINE == "llm":
            threading.Thread(target=self._pregenerate, args=(gen,), daemon=True).start()

    def load_default(self) -> None:
        if DEFAULT_DATASET.exists():
            self.use(load_path(DEFAULT_DATASET, DEFAULT_MAPPING))

    def get(self, pid: str) -> dict | None:
        return next((p for p in self.prospects if p["id"] == pid), None)

    def _write_llm(self, p: dict, background: bool = False) -> dict:
        """Rédaction par le LLM, une seule fois par fiche même si on la demande deux fois."""
        with self.lock:
            id_lock = self.id_locks.setdefault(p["id"], threading.Lock())
            if not background:
                self.users_waiting += 1
        try:
            with id_lock:
                done = self.written.get(p["id"])
                if done:
                    return done
                with self.llm_lock:
                    text = writer.write(p, use_llm=True)
                if text["engine"] == "llm":
                    self.written[p["id"]] = text
                return text
        finally:
            if not background:
                with self.lock:
                    self.users_waiting -= 1

    def _pregenerate(self, gen: int) -> None:
        for p in list(self.prospects[:PREGENERATE]):
            # Une fiche demandée par quelqu'un passe avant la pré-rédaction
            while self.users_waiting and gen == self.generation:
                time.sleep(0.5)
            if gen != self.generation:  # un autre jeu de données a été chargé
                return
            self._write_llm(p, background=True)

    def render(self, p: dict, use_llm: bool | None) -> dict:
        """Le prospect au format du front, avec sa rédaction.
        use_llm : True force le LLM, False les règles, None le réglage par défaut."""
        if use_llm is None:
            use_llm = writer.DEFAULT_ENGINE == "llm"
        text = self._write_llm(p) if use_llm else writer.write(p, use_llm=False)
        out = {k: v for k, v in p.items() if not k.startswith("_")}
        out.update(why=text["why"], takeaways=text["takeaways"], questions=text["questions"])
        out["writer"] = text["engine"]
        return out

    def render_list_item(self, p: dict) -> dict:
        """Pour la liste : la rédaction du LLM si elle existe déjà, sinon les règles."""
        text = self.written.get(p["id"]) or writer.write(p, use_llm=False)
        out = {k: v for k, v in p.items() if not k.startswith("_")}
        out.update(why=text["why"], takeaways=text["takeaways"], questions=text["questions"])
        out["writer"] = text["engine"]
        return out

    def info(self) -> dict:
        ds = self.dataset
        if not ds:
            return {"loaded": False}
        return {
            "loaded": True,
            "name": ds.name,
            "rows": len(ds.rows),
            "prospects": len(self.prospects),
            "columns": ds.columns,
            "ignoredColumns": ds.ignored,
            "llmWritten": len(self.written),
            "pregenerate": PREGENERATE,
        }


store = Store()
