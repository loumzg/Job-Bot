"""Interface en ligne de commande : ``job-bot`` (ou ``python -m job_bot``)."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from job_bot import __version__
from job_bot.config import Config, ConfigError, load_config, load_dotenv
from job_bot.console import render_summary, supports_unicode, use_color
from job_bot.runner import RunResult, report_context, resolve_location, run_forever, run_once
from job_bot.sources import SourceError, build_sources
from job_bot.storage import SeenStore, export_html

log = logging.getLogger("job_bot")


def _csv_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="job-bot",
        description="Recherche et filtre des offres d'emploi en développement web (France Travail, RSS).",
        epilog="Les options passées ici surchargent le fichier de configuration.",
    )
    p.add_argument("-c", "--config", type=Path, default=Path("config.toml"),
                   help="fichier TOML (défaut : config.toml ; voir config.example.toml)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    g = p.add_argument_group("recherche")
    g.add_argument("-k", "--mots-cles", type=_csv_list, metavar="A,B", help="mots-clés séparés par des virgules")
    g.add_argument("--rome", type=_csv_list, metavar="CODES", help="codes ROME (ex. M1805,D1106)")
    g.add_argument("--secteurs", type=_csv_list, metavar="NAF", help="divisions NAF à 2 chiffres (ex. 47,62)")
    g.add_argument("--contrat", type=_csv_list, metavar="TYPES", help="types de contrat (ex. CDI,CDD)")
    g.add_argument("--depuis", type=int, metavar="JOURS", help="publiées depuis au plus N jours (0 = sans limite)")
    g.add_argument("--max", type=int, metavar="N", help="nombre maximal d'offres par mot-clé et par source")

    g = p.add_argument_group("localisation")
    g.add_argument("--ville", help="nom de ville (résolu en code INSEE via geo.api.gouv.fr)")
    g.add_argument("--commune", metavar="INSEE", help="code INSEE de la commune (prioritaire sur --ville)")
    g.add_argument("--departement", metavar="DEP", help="numéro de département (si pas de commune)")
    g.add_argument("--rayon", type=int, metavar="KM", help="rayon autour de la commune, en km")

    g = p.add_argument_group("filtres")
    g.add_argument("-x", "--exclure", type=_csv_list, metavar="EXPR", help="expressions à exclure, séparées par des virgules")
    g.add_argument("--sans-permis", action="store_true", help="écarte les offres qui exigent un permis")
    g.add_argument("--perimetre", choices=("dev_web", "aucun"),
                   help="périmètre métier (défaut : dev_web, métiers du développement web)")

    g = p.add_argument_group("sources et sorties")
    g.add_argument("-s", "--sources", type=_csv_list, metavar="NOMS", help="france_travail, rss, fixture")
    g.add_argument("--rss", type=_csv_list, metavar="URLS", help="URL(s) de flux RSS/Atom (active la source rss)")
    g.add_argument("--fixture", type=Path, metavar="FICHIER", help="JSON au format France Travail (source fixture)")
    g.add_argument("-f", "--formats", type=_csv_list, metavar="csv,json,html", help="formats d'export")
    g.add_argument("--rapport", type=Path, metavar="FICHIER",
                   help="écrit aussi le rapport HTML à ce chemin précis (y compris avec --dry-run)")
    g.add_argument("-o", "--sortie", type=Path, metavar="DOSSIER", help="dossier d'export")
    g.add_argument("--toutes", action="store_true", help="inclut aussi les offres déjà vues")
    g.add_argument("--dry-run", action="store_true",
                   help="hors ligne : offres fictives fournies (sauf --fixture), rien n'est écrit")

    g = p.add_argument_group("planification")
    g.add_argument("--boucle", action="store_true", help="relance la recherche à intervalle régulier")
    g.add_argument("--intervalle", type=int, metavar="MIN", help="intervalle en minutes (minimum 15)")

    p.add_argument("-v", "--verbose", action="store_true", help="logs détaillés")
    return p


def apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    s, loc = cfg.search, cfg.location
    if args.mots_cles is not None:
        s.keywords = args.mots_cles
    if args.rome is not None:
        s.rome_codes = [c.upper() for c in args.rome]
    if args.secteurs is not None:
        s.sectors = args.secteurs
    if args.contrat is not None:
        s.contract_types = [c.upper() for c in args.contrat]
    if args.depuis is not None:
        s.max_age_days = args.depuis or None
    if args.max is not None:
        s.max_results = args.max
    if args.ville is not None:
        loc.city, loc.commune = args.ville, ""
    if args.commune is not None:
        loc.commune = args.commune
    if args.departement is not None:
        loc.department = args.departement
    if args.rayon is not None:
        loc.radius_km = args.rayon
    if args.exclure is not None:
        cfg.filters.exclusions = args.exclure
    if args.sans_permis:
        cfg.filters.exclude_required_license = True
    if args.perimetre is not None:
        cfg.filters.scope = args.perimetre
    if args.sources is not None:
        cfg.sources = args.sources
    if args.rss:
        cfg.rss_urls = args.rss
        if args.sources is None and "rss" not in cfg.sources:
            cfg.sources.append("rss")
    if args.fixture is not None:
        cfg.fixture_path = args.fixture
    if args.formats is not None:
        cfg.output.formats = [f.lower() for f in args.formats]
    if args.sortie is not None:
        cfg.output.directory = args.sortie
    if args.toutes:
        cfg.output.only_new = False
    if args.intervalle is not None:
        cfg.interval_minutes = args.intervalle
    if args.dry_run:
        cfg.sources = ["fixture"]
        if args.depuis is None:  # les offres fictives ont des dates figées
            cfg.search.max_age_days = None
    return cfg


def setup_logging(log_file: Path | None, verbose: bool) -> None:
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_job_bot", False)]:
        root.removeHandler(handler)  # appels répétés de main() (tests) : pas de doublons
        handler.close()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers[0].setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        handlers.append(fh)
    for handler in handlers:
        handler._job_bot = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def print_offers(result: RunResult, cfg: Config) -> None:
    print(render_summary(
        result.offers,
        fetched=result.fetched,
        keywords=cfg.search.keywords,
        exported=result.exported,
        color=use_color(sys.stdout),
        width=shutil.get_terminal_size().columns,
        unicode=supports_unicode(sys.stdout),
    ))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # console Windows : éviter les erreurs d'encodage
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    load_dotenv()
    try:
        cfg = apply_overrides(load_config(args.config), args)
        cfg.validate()
    except ConfigError as exc:
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        return 2
    if not args.config.exists():
        print(f"(pas de {args.config} : configuration par défaut + options de la ligne de commande)", file=sys.stderr)

    setup_logging(None if args.dry_run else cfg.output.log_file, args.verbose)
    if args.dry_run and args.boucle:
        log.error("--dry-run et --boucle sont incompatibles")
        return 2

    try:
        sources = build_sources(cfg)
    except SourceError as exc:
        log.error("%s", exc)
        return 1
    place = resolve_location(cfg, offline=args.dry_run)
    store = None if args.dry_run else SeenStore(cfg.output.seen_file)

    def cycle() -> int:
        result = run_once(cfg, sources, store, place=place, write=not args.dry_run)
        if args.rapport is not None:
            result.exported.append(export_html(result.offers, args.rapport, report_context(cfg, place, result.fetched)))
            log.info("Rapport : %s", args.rapport)
        print_offers(result, cfg)
        return 1 if result.errors and not result.offers and result.fetched == 0 else 0

    if args.boucle:
        try:
            run_forever(cfg, cycle)
        except KeyboardInterrupt:
            log.info("Arrêt demandé.")
        return 0
    return cycle()


if __name__ == "__main__":
    raise SystemExit(main())
