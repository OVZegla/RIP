"""Exceptions du RIP.

Une règle : rien de ce qui part vers la machine ne doit reposer sur une valeur
devinée. Quand une donnée manque, on lève — on n'extrapole pas.
"""

from __future__ import annotations


class RipError(Exception):
    """Base de toutes les erreurs ripcore."""


class ProfileError(RipError):
    """Profil imprimante ou média incohérent / incomplet."""


class PrnFormatError(RipError):
    """Fichier .prn malformé, ou paramètres d'écriture incohérents."""


class UnverifiedError(RipError):
    """Une donnée non validée sur machine est utilisée là où c'est interdit.

    Levée par exemple quand on tente d'envoyer un job alors que l'ordre des
    canaux du profil n'a pas encore été confirmé par la mire ``channel-id``.
    """


class CalibrationError(RipError):
    """Données de calibration absentes, non monotones ou hors domaine."""


class TransportError(RipError):
    """Échec de dialogue avec BetterPrinter (RipReceive)."""
