"""Interface en ligne de commande.

Principe de sûreté transverse : **aucune sous-commande ne met la machine en
mouvement sans un drapeau explicite**. `rip send` simule par défaut, et
`--print` — la seule commande qui dépose de l'encre — doit être demandée
nommément.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .calibration import (
    COVERAGE,
    METRICS,
    build_linearization,
    drop_densities,
    read_measurements,
    render_profile_snippet,
)
from .errors import RipError, UnverifiedError
from .halftone.engines import make_halftoner
from .pipeline import JobSpec, run_job, write_target_prn
from .prnfile.reader import probe
from .prnfile.validate import validate_prn
from .profiles import MediaProfile, PrinterProfile
from .targets import channel_id, drop_wedge, lin_wedge


def _load_printer(path: str) -> PrinterProfile:
    return PrinterProfile.load(path)


def _progress(done: int, total: int) -> None:
    pct = done * 100 // total
    print(f"\r  tramage {pct:3d} %  ({done}/{total} lignes)", end="", file=sys.stderr)
    if done >= total:
        print(file=sys.stderr)


# -- sous-commandes ---------------------------------------------------------


def cmd_info(args: argparse.Namespace) -> int:
    for path in args.files:
        print(probe(path).describe())
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    profile = _load_printer(args.profile) if args.profile else None
    worst = 0
    for path in args.files:
        report = validate_prn(path, profile, inspect_body=not args.header_only)
        print(report.render(verbose=args.verbose))
        worst = max(worst, 0 if report.ok else 1)
    return worst


def cmd_preview(args: argparse.Namespace) -> int:
    from .preview import render_preview  # import tardif : dépend de Pillow

    out = render_preview(
        args.file,
        args.output,
        _load_printer(args.profile),
        max_side=args.max_side,
        show_white=not args.no_white,
    )
    print(f"aperçu écrit : {out}")
    return 0


def cmd_rip(args: argparse.Namespace) -> int:
    printer = _load_printer(args.profile)
    media = (
        MediaProfile.load(args.media)
        if args.media
        else MediaProfile(name="(aucun profil média)")
    )
    source = Path(args.source)

    if source.suffix.lower() in {".pdf", ".ps", ".eps", ".ai"}:
        from .inputs.pdf import render_pdf  # import tardif : dépend de Ghostscript

        print(f"rendu {source.name} par Ghostscript…", file=sys.stderr)
        source = render_pdf(
            source, dpi_x=args.dpi_x, dpi_y=args.dpi_y, mode=args.render_mode,
            page=args.page,
        )

    spec = JobSpec(
        source=source,
        output=Path(args.output),
        printer=printer,
        media=media,
        dpi_x=args.dpi_x,
        dpi_y=args.dpi_y,
        width_mm=args.width_mm,
        height_mm=args.height_mm,
        halftone=args.halftone,
        rotate=args.rotate,
        mirror=args.mirror,
        band_lines=args.band_lines,
        page=args.page,
    )
    result = run_job(spec, progress=None if args.quiet else _progress)
    print(result.describe())
    for w in result.warnings:
        print(f"  ⚠ {w}", file=sys.stderr)

    report = validate_prn(spec.output, printer)
    print(report.render())
    return 0 if report.ok else 1


def cmd_target(args: argparse.Namespace) -> int:
    printer = _load_printer(args.profile)
    kind = args.kind
    if kind == "channel-id":
        target = channel_id(printer, dpi_x=args.dpi_x, dpi_y=args.dpi_y)
    elif kind == "drop-wedge":
        target = drop_wedge(printer, dpi_x=args.dpi_x, dpi_y=args.dpi_y)
    elif kind == "lin-wedge":
        halftoner = make_halftoner(
            args.halftone, printer.drop_levels.densities, printer.n_channels
        )
        target = lin_wedge(
            printer, halftoner, dpi_x=args.dpi_x, dpi_y=args.dpi_y, steps=args.steps
        )
    else:  # pragma: no cover - argparse borne les valeurs
        raise RipError(f"mire inconnue : {kind}")

    out = Path(args.output)
    _, header = write_target_prn(target, printer, out)
    print(f"{out}  —  {header.describe()}")
    print(f"  {target.description}")
    print(f"  {len(target.patches)} plages, {target.width_mm:.0f}×"
          f"{target.height_mm:.0f} mm")

    if args.csv:
        csv_path = Path(args.csv)
        lines = ["channel,kind,value,measurement"]
        if kind == "drop-wedge":
            # Le niveau 0 (support nu) n'est pas imprimé mais doit être mesuré.
            for name in printer.channel_names:
                lines.append(f"{name},level,0,")
        for p in target.patches:
            lines.append(f"{p.channel},{p.kind},{p.value:g},")
        csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  grille de saisie : {csv_path}")
    return 0


def cmd_calibrate_drops(args: argparse.Namespace) -> int:
    printer = _load_printer(args.profile)
    values = drop_densities(
        read_measurements(args.measurements),
        1 << printer.bits_per_pixel,
        metric=args.metric,
    )
    print(f"échelle des tailles de goutte ({args.metric}) : {list(values)}")
    print("\nÀ coller dans le profil imprimante :\n")
    print(render_profile_snippet(values))
    return 0


def cmd_calibrate_lin(args: argparse.Namespace) -> int:
    lin = build_linearization(
        read_measurements(args.measurements),
        metric=args.metric,
        notes=args.notes,
    )
    lin.save(args.output)
    print(f"linéarisation écrite : {args.output}")
    for name, curve in sorted(lin.curves.items()):
        mid = float(curve.apply(0.5))
        print(f"  {name:>3} : 50 % demandé → {mid * 100:.1f} % d'encre")
    print("\nRéférencez-la dans le profil média : linearization = \"…\"")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    from .transport import RipReceiveClient  # import tardif

    path = Path(args.file)
    printer = _load_printer(args.profile) if args.profile else None

    report = validate_prn(path, printer)
    print(report.render())
    if not report.ok:
        print("envoi annulé : le fichier n'a pas passé le contrôle.", file=sys.stderr)
        return 1
    if printer is not None and not printer.channel_order_verified and not args.allow_unverified:
        raise UnverifiedError(
            "l'ordre des canaux du profil n'est pas vérifié : le fichier peut "
            "poser chaque encre au mauvais endroit. Imprimez d'abord la mire "
            "« channel-id », ou forcez avec --allow-unverified."
        )

    client = RipReceiveClient(
        host=args.host,
        udp_port=args.udp_port,
        tcp_port=args.tcp_port,
        timeout=args.timeout,
        dry_run=not args.execute,
    )
    if args.execute and not client.ping():
        raise RipError(
            f"{args.host} ne répond pas. BetterPrinterApp est-il lancé, connecté "
            f"à la carte, et le PC sur le bon sous-réseau ?"
        )
    client.send_file(path)
    client.set_print_file(path.name)
    if args.print:
        if not args.execute:
            print("--print sans --execute : rien n'est envoyé (simulation).",
                  file=sys.stderr)
        else:
            client.print_start(confirm=True)

    print(client.render_log())
    if not args.execute:
        print("\n(simulation — ajoutez --execute pour envoyer réellement)")
    return 0


# -- assemblage -------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rip",
        description="RIP pour presses UV à têtes Epson I1600 (sortie .prn).",
    )
    p.add_argument("--version", action="version", version=f"ripcore {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="décrire un ou plusieurs .prn")
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("check", help="contrôler un .prn avant envoi")
    s.add_argument("files", nargs="+")
    s.add_argument("--profile", help="profil imprimante TOML")
    s.add_argument("--header-only", action="store_true",
                   help="ne pas relire le raster (rapide)")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("preview", help="rendre un aperçu PNG d'un .prn")
    s.add_argument("file")
    s.add_argument("--profile", required=True)
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--max-side", type=int, default=1600)
    s.add_argument("--no-white", action="store_true",
                   help="masquer le canal blanc dans l'aperçu")
    s.set_defaults(func=cmd_preview)

    s = sub.add_parser("rip", help="transformer une image ou un PDF en .prn")
    s.add_argument("source")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--profile", required=True, help="profil imprimante TOML")
    s.add_argument("--media", help="profil média TOML (ICC, linéarisation, blanc)")
    s.add_argument("--dpi-x", type=int, default=720)
    s.add_argument("--dpi-y", type=int, default=900)
    s.add_argument("--width-mm", type=float)
    s.add_argument("--height-mm", type=float)
    s.add_argument("--halftone", default="bluenoise",
                   help="bluenoise | errdiff | errdiff:jarvis | errdiff:stucki")
    s.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    s.add_argument("--mirror", action="store_true")
    s.add_argument("--band-lines", type=int, default=512)
    s.add_argument("--page", type=int, default=1, help="page du PDF à rendre")
    s.add_argument("--render-mode", default="CMYK", choices=("CMYK", "RGB"),
                   help="espace de rendu Ghostscript pour les PDF")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(func=cmd_rip)

    s = sub.add_parser("target", help="générer une mire de calibration")
    s.add_argument("kind", choices=("channel-id", "drop-wedge", "lin-wedge"))
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--profile", required=True)
    s.add_argument("--dpi-x", type=int, default=720)
    s.add_argument("--dpi-y", type=int, default=900)
    s.add_argument("--steps", type=int, default=21, help="paliers du coin (lin-wedge)")
    s.add_argument("--halftone", default="bluenoise")
    s.add_argument("--csv", help="écrire une grille de saisie des mesures")
    s.set_defaults(func=cmd_target)

    s = sub.add_parser("calibrate", help="exploiter les mesures d'une mire")
    csub = s.add_subparsers(dest="what", required=True)

    c = csub.add_parser("drops", help="échelle des tailles de goutte")
    c.add_argument("measurements")
    c.add_argument("--profile", required=True)
    c.add_argument("--metric", default=COVERAGE, choices=METRICS)
    c.set_defaults(func=cmd_calibrate_drops)

    c = csub.add_parser("lin", help="courbes de linéarisation")
    c.add_argument("measurements")
    c.add_argument("-o", "--output", required=True)
    c.add_argument("--metric", default=COVERAGE, choices=METRICS)
    c.add_argument("--notes", default="")
    c.set_defaults(func=cmd_calibrate_lin)

    s = sub.add_parser("send", help="envoyer un .prn à BetterPrinter (simulé par défaut)")
    s.add_argument("file")
    s.add_argument("--host", required=True, help="PC qui fait tourner BetterPrinterApp")
    s.add_argument("--profile")
    s.add_argument("--udp-port", type=int, default=8999)
    s.add_argument("--tcp-port", type=int, default=9100)
    s.add_argument("--timeout", type=float, default=3.0)
    s.add_argument("--execute", action="store_true",
                   help="envoyer réellement (sinon : simulation)")
    s.add_argument("--print", action="store_true",
                   help="lancer l'impression après le transfert — DÉPOSE DE L'ENCRE")
    s.add_argument("--allow-unverified", action="store_true",
                   help="passer outre un profil dont l'ordre des canaux n'est pas vérifié")
    s.set_defaults(func=cmd_send)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RipError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrompu", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
