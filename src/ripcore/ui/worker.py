"""Exécution des travaux longs sans figer la fenêtre.

Un job de 2 m met plusieurs minutes. S'il tournait dans le fil de l'interface,
Windows afficherait « ne répond pas » et l'opérateur tuerait l'application au
milieu de l'écriture du fichier.

Le travail part donc dans un fil séparé et communique par une file. Tk n'est
touché que depuis le fil principal, dans ``_pomper`` — c'est la règle absolue
de Tk, et l'enfreindre produit des plantages aléatoires impossibles à
reproduire.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

INTERVALLE_MS = 60


@dataclass(slots=True)
class Avancement:
    fait: int
    total: int

    @property
    def fraction(self) -> float:
        return self.fait / self.total if self.total else 0.0

    @property
    def pourcentage(self) -> int:
        return round(self.fraction * 100)


class Tache:
    """Un travail en cours. Une seule à la fois, volontairement.

    Deux jobs simultanés se disputeraient la mémoire et le disque pour un gain
    nul : le tramage sature déjà le processeur.
    """

    def __init__(self, racine: tk.Misc) -> None:
        self._racine = racine
        self._file: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._fil: threading.Thread | None = None
        self._sur_avancement: Callable[[Avancement], None] | None = None
        self._sur_fin: Callable[[Any], None] | None = None
        self._sur_erreur: Callable[[Exception], None] | None = None
        self._trace: str = ""

    @property
    def en_cours(self) -> bool:
        return self._fil is not None and self._fil.is_alive()

    @property
    def derniere_trace(self) -> str:
        """Trace de la dernière erreur, pour le détail technique repliable."""
        return self._trace

    def lancer(
        self,
        travail: Callable[[Callable[[int, int], None]], Any],
        *,
        sur_avancement: Callable[[Avancement], None] | None = None,
        sur_fin: Callable[[Any], None] | None = None,
        sur_erreur: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Démarre ``travail`` en fond. Renvoie False si une tâche tourne déjà.

        ``travail`` reçoit une fonction ``avancement(fait, total)`` qu'il peut
        appeler aussi souvent qu'il veut : elle ne fait qu'empiler dans la file.
        """
        if self.en_cours:
            return False
        self._sur_avancement = sur_avancement
        self._sur_fin = sur_fin
        self._sur_erreur = sur_erreur
        self._trace = ""

        def _rapporter(fait: int, total: int) -> None:
            self._file.put(("avancement", Avancement(fait, total)))

        def _executer() -> None:
            try:
                resultat = travail(_rapporter)
            except Exception as exc:  # remonté proprement dans l'interface
                self._file.put(("erreur", (exc, traceback.format_exc())))
            else:
                self._file.put(("fin", resultat))

        self._fil = threading.Thread(target=_executer, daemon=True)
        self._fil.start()
        self._racine.after(INTERVALLE_MS, self._pomper)
        return True

    def _pomper(self) -> None:
        """Vide la file côté interface. Seul endroit qui touche à Tk."""
        termine = False
        try:
            while True:
                genre, charge = self._file.get_nowait()
                if genre == "avancement":
                    if self._sur_avancement is not None:
                        self._sur_avancement(charge)
                elif genre == "fin":
                    termine = True
                    if self._sur_fin is not None:
                        self._sur_fin(charge)
                elif genre == "erreur":
                    exc, trace = charge
                    self._trace = trace
                    termine = True
                    if self._sur_erreur is not None:
                        self._sur_erreur(exc)
        except queue.Empty:
            pass

        if not termine and self.en_cours:
            self._racine.after(INTERVALLE_MS, self._pomper)
        elif not termine:
            # Le fil s'est arrêté sans rien poster : on repasse une fois pour
            # récupérer un message qui serait arrivé entre-temps.
            self._racine.after(INTERVALLE_MS, self._pomper_final)

    def _pomper_final(self) -> None:
        try:
            while True:
                genre, charge = self._file.get_nowait()
                if genre == "fin" and self._sur_fin is not None:
                    self._sur_fin(charge)
                elif genre == "erreur" and self._sur_erreur is not None:
                    exc, trace = charge
                    self._trace = trace
                    self._sur_erreur(exc)
        except queue.Empty:
            pass
