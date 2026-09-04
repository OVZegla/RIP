"""Client du protocole RipReceive de BetterPrinter.

C'est le point d'entrée (b) du §30 du dossier SAV : on parle à l'application
existante, pas à la carte. BetterPrinter garde la main sur le weave, la plume,
le nettoyage, les lampes et le dongle — nous ne fournissons que le raster.

    UDP 8999  commandes courtes  (XLeft, Clean, State, Progress…)
    TCP 9100  transfert de fichier et commandes longues (SetPrintFile,
              SetPrintPara, PrintStart…)

⚠️ **Le vocabulaire est établi, la syntaxe exacte des arguments ne l'est pas.**
Le dossier liste les noms de commandes (reconstruits de `RipReceive.dll` et du
client `BetterInfase.dll`) mais pas le format précis des paramètres de
`SetPrintFile` / `SetPrintPara` / `SetRipPara`. La façon rapide et sûre de le
lever : capturer au Wireshark une impression réelle lancée depuis UltraPrint,
et recopier les chaînes observées dans un fichier de commandes
(``--commands mon-dialecte.toml``).

D'ici là, ce client fonctionne en **simulation par défaut** : il montre ce qu'il
enverrait sans rien envoyer.
"""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import TransportError

DEFAULT_UDP_PORT = 8999
DEFAULT_TCP_PORT = 9100  # RR_GetTcpPort(), 0x238C par défaut
DISCOVERY_PORT = 8999

# Vocabulaire relevé dans RipReceive.dll / BetterInfase.dll.
MOVES = (
    "XLeft", "XRight", "YFront", "YBack", "ZUp", "ZDown",
    "UFront", "UBack", "XReset", "YReset", "ZReset",
)
PRINT = ("SetPrintFile", "SetPrintPara", "SetRipPara", "PrintStart",
         "Pause", "Continue", "Stop")
SERVICE = ("Clean", "InSignal", "Out", "IsOnOff")
STATUS = ("State", "Progress")

_STATE_RE = re.compile(r"State:\s*(-?\d+)")
_PROGRESS_RE = re.compile(r"Progress:\s*([-+]?\d*\.?\d+)")
_XRASTER_RE = re.compile(r"GegXRasterPos:\s*([-+]?\d*\.?\d+)")
_ERROR_RE = re.compile(r":(err|error)\b", re.IGNORECASE)


@dataclass(slots=True)
class Exchange:
    """Une commande envoyée et sa réponse — journal complet du dialogue."""

    channel: str  # "udp" | "tcp"
    sent: str
    received: str = ""
    simulated: bool = False

    def __str__(self) -> str:
        tag = "SIMULÉ" if self.simulated else self.channel.upper()
        arrow = f" → {self.received!r}" if self.received else ""
        return f"[{tag}] {self.sent!r}{arrow}"


@dataclass(slots=True)
class RipReceiveClient:
    """Client texte de BetterPrinter.

    ``dry_run=True`` (défaut) n'ouvre aucune socket : chaque appel est journalisé
    et renvoie une réponse vide. Passer en réel est une décision explicite.
    """

    host: str
    udp_port: int = DEFAULT_UDP_PORT
    tcp_port: int = DEFAULT_TCP_PORT
    timeout: float = 3.0
    dry_run: bool = True
    encoding: str = "ascii"
    log: list[Exchange] = field(default_factory=list)

    # -- primitives ----------------------------------------------------------

    def command(self, text: str) -> str:
        """Commande courte en UDP. Renvoie la réponse brute (256 o max)."""
        if self.dry_run:
            ex = Exchange("udp", text, simulated=True)
            self.log.append(ex)
            return ""
        payload = text.encode(self.encoding, errors="strict")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(self.timeout)
                sock.sendto(payload, (self.host, self.udp_port))
                data, _ = sock.recvfrom(256)
        except socket.timeout:
            raise TransportError(
                f"pas de réponse de {self.host}:{self.udp_port} en {self.timeout} s "
                f"pour {text!r}. BetterPrinterApp est-il lancé et connecté à la "
                f"carte ?"
            ) from None
        except OSError as exc:
            raise TransportError(
                f"échec UDP vers {self.host}:{self.udp_port} : {exc}"
            ) from exc

        reply = data.decode(self.encoding, errors="replace")
        self.log.append(Exchange("udp", text, reply))
        if _ERROR_RE.search(reply):
            raise TransportError(f"{text!r} refusée : {reply!r}")
        return reply

    def send_bytes(self, payload: bytes, label: str) -> str:
        """Envoi long en TCP (fichier .prn, commandes à arguments)."""
        if self.dry_run:
            ex = Exchange("tcp", f"{label} ({len(payload)} o)", simulated=True)
            self.log.append(ex)
            return ""
        try:
            with socket.create_connection(
                (self.host, self.tcp_port), timeout=self.timeout
            ) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(payload)
                try:
                    reply = sock.recv(256).decode(self.encoding, errors="replace")
                except socket.timeout:
                    reply = ""  # certaines commandes n'accusent pas réception
        except OSError as exc:
            raise TransportError(
                f"échec TCP vers {self.host}:{self.tcp_port} : {exc}"
            ) from exc
        self.log.append(Exchange("tcp", f"{label} ({len(payload)} o)", reply))
        if _ERROR_RE.search(reply):
            raise TransportError(f"{label} refusé : {reply!r}")
        return reply

    # -- état ----------------------------------------------------------------

    def state(self) -> int | None:
        m = _STATE_RE.search(self.command("State"))
        return int(m.group(1)) if m else None

    def progress(self) -> float | None:
        m = _PROGRESS_RE.search(self.command("Progress"))
        return float(m.group(1)) if m else None

    def x_raster_pos(self) -> float | None:
        m = _XRASTER_RE.search(self.command("GegXRasterPos"))
        return float(m.group(1)) if m else None

    def ping(self) -> bool:
        """Vrai si l'application répond. Aucun effet machine."""
        try:
            return self.state() is not None or self.dry_run
        except TransportError:
            return False

    # -- job -----------------------------------------------------------------

    def send_file(self, path: str | Path, chunk: int = 1 << 20) -> str:
        """Transfère un `.prn` par le canal TCP, en flux. Ne lance rien.

        Un job mural pèse plusieurs gigaoctets : il est envoyé par blocs, jamais
        chargé en mémoire.
        """
        p = Path(path)
        if not p.is_file():
            raise TransportError(f"fichier introuvable : {p}")
        size = p.stat().st_size
        label = f"fichier {p.name}"

        if self.dry_run:
            self.log.append(Exchange("tcp", f"{label} ({size} o)", simulated=True))
            return ""
        try:
            with socket.create_connection(
                (self.host, self.tcp_port), timeout=self.timeout
            ) as sock, open(p, "rb") as fh:
                sock.settimeout(self.timeout)
                while True:
                    block = fh.read(chunk)
                    if not block:
                        break
                    sock.sendall(block)
                try:
                    reply = sock.recv(256).decode(self.encoding, errors="replace")
                except socket.timeout:
                    reply = ""
        except OSError as exc:
            raise TransportError(
                f"échec du transfert vers {self.host}:{self.tcp_port} : {exc}"
            ) from exc
        self.log.append(Exchange("tcp", f"{label} ({size} o)", reply))
        if _ERROR_RE.search(reply):
            raise TransportError(f"{label} refusé : {reply!r}")
        return reply

    def set_print_file(self, remote_name: str) -> str:
        """Désigne le fichier à imprimer.

        Syntaxe d'argument **non vérifiée** — à confirmer par capture réseau
        d'une impression UltraPrint réelle.
        """
        return self.send_bytes(
            f"SetPrintFile{remote_name}".encode(self.encoding),
            f"SetPrintFile {remote_name}",
        )

    def print_start(self, *, confirm: bool = False) -> str:
        """Lance l'impression. Exige ``confirm=True`` : ça met la machine en route."""
        if not confirm:
            raise TransportError(
                "print_start() exige confirm=True — cette commande met la machine "
                "en mouvement et dépose de l'encre"
            )
        return self.send_bytes(b"PrintStart", "PrintStart")

    def pause(self) -> str:
        return self.command("Pause")

    def resume(self) -> str:
        return self.command("Continue")

    def stop(self) -> str:
        return self.command("Stop")

    def render_log(self) -> str:
        return "\n".join(str(e) for e in self.log) or "(aucun échange)"
