"""Périmètre métier : ne garder que les offres d'un domaine donné, quelle que soit la source.

Le seul périmètre fourni, ``dev_web``, couvre les métiers du développement web :
développeur web, front-end, back-end, full stack, développeur IA appliquée (agents, LLM),
intégrateur web, webmaster, développeur JavaScript / TypeScript / PHP / Python web…

Règles, appliquées au texte canonique (sans accents ni casse, variantes unifiées :
« Développeuse Full-Stack » devient « developpeur fullstack ») :

1. l'intitulé ne doit contenir aucune expression hors sujet (« développeur commercial »,
   « business developer », « technicien support », « embarqué », « COBOL »…) ;
2. l'intitulé doit nommer un rôle de développement (développeur, programmeur,
   intégrateur, webmaster, ingénieur logiciel / IA…) ;
3. une technologie ou un domaine web doit apparaître dans l'intitulé, ou une
   technologie web précise dans la description (le simple mot « web » d'une
   description ne suffit pas : « consultez notre site web »).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_bot.models import JobOffer, canonical_text

DEFAULT_SCOPE = "dev_web"
NO_SCOPE = ("", "aucun", "none")


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


_ROLE = _rx(
    r"\bdeveloppeur",
    r"\bprogrammeur",
    r"\bintegrateur\b",
    r"\bwebmaster\b",
    r"\bsoftware engineer",
    r"\b(?:web|frontend|backend|fullstack|software|ia|ai|llm|ml) engineer",
    r"\bingenieur (?:logiciel|developpement|etudes et developpement|web|ia|llm|frontend|backend|fullstack)",
    r"\btech lead\b",
)

_WEB_TECH = (
    r"\b(?:frontend|backend|fullstack|webmaster)\b",
    r"\b(?:javascript|typescript|ecmascript)\b",
    r"\b(?:react|reactjs|react native|nextjs|vuejs|nuxt|nuxtjs|angular|angularjs|svelte|sveltekit)\b",
    r"\b(?:node|nodejs|nestjs|expressjs|deno|bun)\b",
    r"\b(?:php|symfony|laravel|wordpress|drupal|prestashop|magento|shopify|woocommerce)\b",
    r"\b(?:django|flask|fastapi|ruby on rails|asp net)\b",
    r"\b(?:html|html5|css|css3|sass|scss|tailwind|tailwindcss)\b",
    r"\b(?:graphql|api rest|rest api|apis rest)\b",
    r"\b(?:developpement|applications?|plateformes?) web\b",
    r"\b(?:llms?|ia generative|genai|agentique|agents? ia|agents? conversationnels?|rag|langchain|llamaindex|openai|mcp)\b",
)
# Intitulé : en plus des technologies, les mots du domaine suffisent (« Développeur web »,
# « Développeur IA », « Développeur front »).
_WEB_TITLE = _rx(*_WEB_TECH, r"\b(?:web|ia|ai|vue|front|back|agents?)\b")
_WEB_DESC = _rx(*_WEB_TECH)

_OFF_TOPIC = _rx(
    # « développement » au sens commercial, immobilier, durable…
    r"\bdeveloppeur (?:commercial|d affaires|affaires|business|immobilier|foncier|territorial|rh|de reseaux?|reseaux?)",
    r"\bdeveloppeur (?:de )?projets? (?:eolien|solaire|photovoltaique|enr|energ|immobilier)",
    r"\bbusiness dev", r"\bbiz ?dev",
    r"\bdeveloppement (?:commercial|durable|des ventes|personnel|international|economique|rh|territorial|foncier)",
    r"\bcharge(?:e)? (?:de )?developpement\b",
    # informatique hors développement web
    r"\btechnicien(?:ne)? (?:reseaux?|support|informatique|helpdesk|maintenance|systemes?)",
    r"\b(?:support|helpdesk|help desk|hotline|service desk)\b",
    r"\b(?:data analyst|analyste (?:de )?donnees)\b",
    r"\b(?:embarques?|firmware|microcontroleurs?|automaticien)\b",
    r"\b(?:cobol|mainframe|as ?400|pl1)\b",
)


@dataclass(frozen=True, slots=True)
class Verdict:
    accepted: bool
    reason: str = ""


def judge(offer: JobOffer) -> Verdict:
    """Décide si l'offre relève du développement web (périmètre ``dev_web``)."""
    title = canonical_text(offer.title)
    if _OFF_TOPIC.search(title):
        return Verdict(False, "intitulé hors sujet")
    if not _ROLE.search(title):
        return Verdict(False, "pas un poste de développement")
    if _WEB_TITLE.search(title) or _WEB_DESC.search(canonical_text(offer.description)):
        return Verdict(True)
    return Verdict(False, "aucune technologie web")


def in_scope(offer: JobOffer, scope: str) -> bool:
    """Vrai si l'offre appartient au périmètre ``scope`` (toujours vrai sans périmètre)."""
    if scope.strip().lower() in NO_SCOPE:
        return True
    if scope != DEFAULT_SCOPE:
        raise ValueError(f"Périmètre inconnu : {scope!r}")
    return judge(offer).accepted
