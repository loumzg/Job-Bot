from __future__ import annotations

import pytest

from conftest import make_offer
from job_bot.config import DEFAULT_KEYWORDS, Config
from job_bot.filters import Criteria, apply_filters, matches_keywords
from job_bot.models import canonical_text
from job_bot.perimetre import in_scope, judge
from job_bot.sources import demo_fixture_path
from job_bot.sources.base import SearchQuery
from job_bot.sources.fixture import FixtureSource


@pytest.mark.parametrize(("raw", "expected"), [
    ("Développeuse Full-Stack", "developpeur fullstack"),
    ("Développeur·euse front-end", "developpeur frontend"),
    ("DÉV. BACK END", "developpeur backend"),
    ("Web developer", "web developpeur"),
    ("Intégratrice web", "integrateur web"),
    ("Webmestre", "webmaster"),
    ("Node.js / Vue.js", "nodejs vuejs"),
    ("Intelligence artificielle", "ia"),
])
def test_canonical_variants(raw: str, expected: str) -> None:
    assert canonical_text(raw) == expected


@pytest.mark.parametrize(("title", "description"), [
    # développeur web / front / back / full stack
    ("Développeur web H/F", ""),
    ("Développeuse Front-End", ""),
    ("Dév front", "Intégration des maquettes."),
    ("Développeur back-end", ""),
    ("Développeur·euse fullstack", ""),
    ("Développeur Full Stack", ""),
    ("Web developer", ""),
    # langages et frameworks web
    ("Développeur JavaScript", ""),
    ("Développeur TypeScript / React", ""),
    ("Développeur Vue", ""),
    ("Développeur Angular", ""),
    ("Développeur Node.js", ""),
    ("Développeur PHP Symfony", ""),
    ("Développeur Laravel", ""),
    ("Développeur WordPress", ""),
    # intitulé générique, technologie web dans la description
    ("Ingénieur études et développement", "Applications métier en React et API REST."),
    ("Développeur Python", "Services FastAPI et front Vue.js."),
    ("Analyste programmeur", "Évolutions d'un extranet PHP."),
    # IA appliquée / agents
    ("Développeur IA", ""),
    ("Développeur agentique", ""),
    ("Ingénieur IA appliquée", "Intégration de LLM."),
    ("Développeur Python", "Agents IA, RAG et intégration de LLM."),
    ("AI engineer", ""),
    # intégration et webmastering
    ("Intégrateur web", ""),
    ("Intégratrice HTML/CSS", ""),
    ("Webmaster", ""),
    ("Webmestre éditorial", ""),
])
def test_web_jobs_are_accepted(title: str, description: str) -> None:
    offer = make_offer(title=title, description=description)
    assert judge(offer).accepted, title
    assert in_scope(offer, "dev_web")


@pytest.mark.parametrize(("title", "description"), [
    ("Développeur commercial", "Vente de solutions web."),
    ("Développeuse d'affaires", "Agence web."),
    ("Business developer", "SaaS pour développeurs web."),
    ("Biz dev", "Solutions React."),
    ("Chargé de développement", "Réseau de franchises, site web."),
    ("Responsable développement durable", "En lien avec le développeur web."),
    ("Développeur de projets éoliens", ""),
    ("Développeur immobilier", ""),
    ("Technicien réseau", "Câblage et switchs."),
    ("Technicien support informatique", "Assistance aux développeurs web."),
    ("Helpdesk N1", "Tickets."),
    ("Data analyst", "SQL, Power BI, JavaScript."),
    ("Développeur C embarqué", "Interface web de configuration."),
    ("Développeur systèmes embarqués", "React pour l'outil de test."),
    ("Développeur COBOL", "Migration vers une application web."),
    ("Développeur mainframe", ""),
    ("Développeur C++ temps réel", "Plus d'informations sur notre site web."),
    ("Développeur Java", "Calcul scientifique."),
    ("Chef de projet web", "Pilotage des développeurs."),
    ("Community manager", "Réseaux sociaux et site web."),
    ("Vendeur en magasin", ""),
])
def test_false_positives_are_rejected(title: str, description: str) -> None:
    assert not judge(make_offer(title=title, description=description)).accepted, title


def test_no_scope_keeps_everything() -> None:
    offer = make_offer(title="Vendeur")
    assert in_scope(offer, "aucun") and in_scope(offer, "")
    with pytest.raises(ValueError):
        in_scope(offer, "boulangerie")


def test_keywords_tolerate_variants() -> None:
    offer = make_offer(title="Développeuse Full-Stack", description="Front-end en Vue.js")
    assert matches_keywords(offer, ["developpeur full stack"])
    assert matches_keywords(offer, ["front end"])
    assert matches_keywords(offer, ["vuejs"])
    # mots courts : mot entier seulement (« ia » ne doit pas trouver « spécialisé »)
    assert not matches_keywords(make_offer(title="Développeur spécialisé"), ["developpeur ia"])
    assert matches_keywords(make_offer(title="Développeur IA"), ["développeur ia"])


def test_apply_filters_counts_scope_rejections() -> None:
    offers = [make_offer(id="ok", title="Développeur web"), make_offer(id="no", title="Développeur commercial")]
    kept, rejected = apply_filters(offers, Criteria(scope="dev_web"))
    assert [o.id for o in kept] == ["ok"]
    assert rejected == {"périmètre": 1}


def test_defaults_target_web_development() -> None:
    cfg = Config()
    assert cfg.filters.scope == "dev_web"
    assert cfg.search.rome_codes == ["M1805", "E1101"]
    assert "webmaster" in cfg.search.keywords and "développeur ia" in cfg.search.keywords


def test_demo_offers_split_between_web_jobs_and_false_positives() -> None:
    offers = list(FixtureSource(demo_fixture_path()).search(SearchQuery()))
    criteria = Criteria(keywords=DEFAULT_KEYWORDS, rome_codes=["M1805", "E1101"], scope="dev_web")
    kept, rejected = apply_filters(offers, criteria)
    assert len(kept) == 18
    assert rejected == {"périmètre": 7}
    rejected_titles = {o.title for o in offers} - {o.title for o in kept}
    assert "Développeur commercial B2B H/F" in rejected_titles
    assert "Business developer SaaS" in rejected_titles
