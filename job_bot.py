# -*- coding: utf-8 -*-
# ============================================================
#  JOB BOT - Indeed Scraper + Auto-Apply + Boucle horaire
#  Améliorations :
#   - Anti-détection (undetected-chromedriver + stealth)
#   - Candidature simplifiée automatique
#   - Boucle toutes les heures sans intervention
# ============================================================

import time
import random
import os
import schedule
import pandas as pd
import logging

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from bs4 import BeautifulSoup

try:
    import undetected_chromedriver as uc
    USE_UNDETECTED = True
except ImportError:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    USE_UNDETECTED = False
    print("[WARN] undetected-chromedriver non installé. Installe-le avec : pip install undetected-chromedriver")


# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("job_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ==============================
# CONFIGURATION — MODIFIE ICI
# ==============================

CITY = "Nantes"
RADIUS = 10

KEYWORDS = [
    "preparateur de commandes",
    "agent accueil",
    "employe administratif",
    "vendeur"
]

EXCLUSIONS = [
    "permis b obligatoire",
    "vehicule obligatoire"
]

# Tes infos pour les candidatures simplifiées
APPLICANT = {
    "first_name": "Prénom",
    "last_name": "Nom",
    "email": "ton.email@example.com",
    "phone": "0600000000",
    "cv_path": r"C:\Users\TonNom\Documents\CV.pdf",  # Chemin absolu vers ton CV
}

OUTPUT_FILE = "jobs_results.csv"
SEEN_FILE = "seen_jobs.txt"
APPLIED_FILE = "applied_jobs.txt"

DELAY_MIN = 2
DELAY_MAX = 5

# Intervalle de répétition (en heures)
REPEAT_EVERY_HOURS = 1


# ==============================
# UTILITAIRES
# ==============================

def delay(min_s=None, max_s=None):
    """Pause aléatoire pour simuler un comportement humain."""
    min_s = min_s or DELAY_MIN
    max_s = max_s or DELAY_MAX
    t = random.uniform(min_s, max_s)
    time.sleep(t)


def human_type(element, text):
    """Tape du texte caractère par caractère comme un humain."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))


def load_file_set(filepath):
    """Charge un fichier texte ligne par ligne dans un set."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)


def append_to_file(filepath, value):
    """Ajoute une valeur à un fichier texte."""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(value + "\n")


# ==============================
# DRIVER SELENIUM ANTI-DÉTECTION
# ==============================

def init_driver():
    """
    Initialise Chrome avec les options anti-détection.
    Utilise undetected-chromedriver si disponible.
    """
    if USE_UNDETECTED:
        log.info("Démarrage avec undetected-chromedriver (meilleure furtivité)")
        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--lang=fr-FR")
        # Désactive les flags de détection automation
        options.add_argument("--disable-blink-features=AutomationControlled")
        driver = uc.Chrome(options=options, use_subprocess=True)
    else:
        log.warning("Fallback sur Selenium classique (plus détectable)")
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--lang=fr-FR")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        driver = webdriver.Chrome(options=options)
        # Masque navigator.webdriver
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    return driver


# ==============================
# SCRAPER INDEED
# ==============================

def scrape_indeed(driver, keyword):
    """Scrape les offres Indeed pour un mot-clé donné (annonces du jour)."""
    log.info(f"Recherche : {keyword}")

    url = (
        f"https://fr.indeed.com/jobs"
        f"?q={keyword.replace(' ', '+')}"
        f"&l={CITY}"
        f"&radius={RADIUS}"
        f"&fromage=1"  # Annonces du jour uniquement
        f"&sort=date"
    )

    driver.get(url)

    # Simule un scroll humain pour éviter la détection
    delay(1, 2)
    driver.execute_script("window.scrollTo(0, 300)")
    delay(1, 2)

    # Sélecteurs CSS alternatifs (Indeed change souvent)
    selectors = [
        "a.job_seen_beacon",
        "div.job_seen_beacon",
        "[data-jk]",
        ".resultWithShelf",
        "div[class*='job_seen']"
    ]

    cards = []
    for selector in selectors:
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            soup = BeautifulSoup(driver.page_source, "html.parser")
            cards = soup.select(selector)
            if cards:
                log.info(f"Sélecteur fonctionnel : {selector} → {len(cards)} offres")
                break
        except TimeoutException:
            continue

    if not cards:
        log.warning("Aucune offre trouvée — possible CAPTCHA ou changement de structure Indeed")
        # Capture d'écran pour diagnostic
        driver.save_screenshot("debug_screenshot.png")
        log.info("Capture d'écran sauvegardée : debug_screenshot.png")
        return []

    jobs = []
    for card in cards:
        try:
            # Tentative multi-sélecteurs pour le lien
            link = None
            if card.name == "a" and card.get("href"):
                href = card["href"]
            else:
                a_tag = card.find("a", href=True)
                href = a_tag["href"] if a_tag else None

            if not href:
                continue

            link = "https://fr.indeed.com" + href if href.startswith("/") else href

            # Titre
            title_tag = (
                card.select_one("h2 span") or
                card.select_one(".jobTitle span") or
                card.select_one("h2")
            )
            title = title_tag.get_text(strip=True) if title_tag else "Inconnu"

            # Entreprise
            company_tag = (
                card.select_one(".companyName") or
                card.select_one("[data-testid='company-name']") or
                card.select_one(".css-1h7lukg")
            )
            company = company_tag.get_text(strip=True) if company_tag else "Inconnu"

            jobs.append({"title": title, "company": company, "link": link})

        except Exception as e:
            log.debug(f"Erreur parsing carte : {e}")
            continue

    log.info(f"→ {len(jobs)} offres récupérées pour '{keyword}'")
    return jobs


# ==============================
# ANALYSE DESCRIPTION
# ==============================

def analyse_job(driver, job):
    """Ouvre l'offre et vérifie les critères d'exclusion."""
    log.info(f"Analyse : {job['title']} @ {job['company']}")

    try:
        driver.get(job["link"])
    except Exception as e:
        log.warning(f"Erreur chargement page : {e}")
        job["status"] = "error"
        return job

    delay()

    # Vérifie si la page contient une description
    desc_selectors = ["#jobDescriptionText", ".jobsearch-jobDescriptionText", "[data-testid='jobDescription']"]
    desc = ""
    for sel in desc_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            desc = el.text.lower()
            break
        except NoSuchElementException:
            continue

    if not desc:
        log.warning("Description introuvable")
        job["status"] = "error"
        job["description"] = ""
        return job

    # Vérification des exclusions
    for word in EXCLUSIONS:
        if word in desc:
            job["status"] = "excluded"
            log.info(f"  → Exclu (contient : '{word}')")
            job["description"] = desc[:300]
            return job

    # Vérifie si candidature simplifiée disponible
    job["easy_apply"] = detect_easy_apply(driver)
    job["status"] = "accepted"
    job["description"] = desc[:300]
    log.info(f"  → Accepté {'[Easy Apply ✓]' if job.get('easy_apply') else '[Candidature externe]'}")

    return job


# ==============================
# DÉTECTION EASY APPLY
# ==============================

def detect_easy_apply(driver):
    """Détecte si le bouton 'Candidature simplifiée' est présent."""
    easy_apply_texts = [
        "postuler maintenant",
        "candidature simplifiée",
        "easy apply",
        "postuler sur indeed"
    ]
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button, a")
        for btn in buttons:
            if btn.text.strip().lower() in easy_apply_texts:
                return True
    except Exception:
        pass
    return False


# ==============================
# CANDIDATURE SIMPLIFIÉE
# ==============================

def apply_easy(driver, job):
    """
    Tente de postuler automatiquement via 'Candidature simplifiée'.
    Gère les champs les plus courants du formulaire Indeed.
    """
    applied_jobs = load_file_set(APPLIED_FILE)

    if job["link"] in applied_jobs:
        log.info(f"Déjà postulé : {job['title']}")
        return False

    if not job.get("easy_apply"):
        log.info(f"Pas de candidature simplifiée pour : {job['title']}")
        return False

    log.info(f"Tentative de candidature : {job['title']}")

    try:
        driver.get(job["link"])
        delay(2, 3)

        # Clique sur le bouton postuler
        apply_btn = None
        for selector in ["button[id*='apply']", "a[id*='apply']", "button.jobsearch-IndeedApplyButton"]:
            try:
                apply_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                break
            except TimeoutException:
                continue

        if not apply_btn:
            # Recherche par texte
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if "postuler" in btn.text.lower() or "apply" in btn.text.lower():
                    apply_btn = btn
                    break

        if not apply_btn:
            log.warning("Bouton postuler introuvable")
            return False

        # Scroll vers le bouton et clic humain
        driver.execute_script("arguments[0].scrollIntoView(true);", apply_btn)
        delay(0.5, 1)
        ActionChains(driver).move_to_element(apply_btn).pause(0.3).click().perform()
        delay(2, 3)

        # Remplissage du formulaire (multi-étapes possible)
        max_steps = 5
        for step in range(max_steps):
            log.info(f"  Formulaire étape {step + 1}")
            filled = fill_form_step(driver)

            # Cherche le bouton suivant / soumettre
            next_btn = find_next_button(driver)
            if not next_btn:
                log.info("  Fin du formulaire (bouton suivant introuvable)")
                break

            btn_text = next_btn.text.strip().lower()
            next_btn.click()
            delay(1.5, 2.5)

            if any(w in btn_text for w in ["soumettre", "envoyer", "submit", "send"]):
                log.info(f"  ✅ Candidature soumise pour : {job['title']}")
                append_to_file(APPLIED_FILE, job["link"])
                job["applied"] = True
                return True

        return False

    except Exception as e:
        log.error(f"Erreur candidature : {e}")
        return False


def fill_form_step(driver):
    """Remplit les champs visibles du formulaire Indeed."""
    filled = False

    field_map = {
        "first": APPLICANT["first_name"],
        "prenom": APPLICANT["first_name"],
        "last": APPLICANT["last_name"],
        "nom": APPLICANT["last_name"],
        "family": APPLICANT["last_name"],
        "email": APPLICANT["email"],
        "phone": APPLICANT["phone"],
        "telephone": APPLICANT["phone"],
        "mobile": APPLICANT["phone"],
    }

    try:
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='email'], input[type='tel']")
        for inp in inputs:
            if not inp.is_displayed() or not inp.is_enabled():
                continue
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            name_attr = (inp.get_attribute("name") or "").lower()
            label_attr = (inp.get_attribute("aria-label") or "").lower()
            combined = placeholder + name_attr + label_attr

            for key, value in field_map.items():
                if key in combined and not inp.get_attribute("value"):
                    inp.clear()
                    human_type(inp, value)
                    filled = True
                    break

        # Upload CV si champ présent
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        for fi in file_inputs:
            if os.path.exists(APPLICANT["cv_path"]):
                fi.send_keys(APPLICANT["cv_path"])
                filled = True
                delay(1, 2)
            break

    except Exception as e:
        log.debug(f"fill_form_step erreur : {e}")

    return filled


def find_next_button(driver):
    """Trouve le bouton suivant/soumettre dans le formulaire."""
    next_texts = ["suivant", "continuer", "next", "continue", "soumettre", "envoyer", "submit"]
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button[type='submit'], button[type='button']")
        for btn in buttons:
            if btn.is_displayed() and btn.text.strip().lower() in next_texts:
                return btn
        # Fallback : tout bouton visible contenant ces mots
        for btn in buttons:
            for t in next_texts:
                if t in btn.text.strip().lower() and btn.is_displayed():
                    return btn
    except Exception:
        pass
    return None


# ==============================
# SAUVEGARDE CSV
# ==============================

def save_results(jobs):
    """Sauvegarde les résultats dans le CSV en évitant les doublons."""
    if not jobs:
        log.info("Aucune nouvelle offre à sauvegarder.")
        return

    df = pd.DataFrame(jobs)

    if os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0:
        old = pd.read_csv(OUTPUT_FILE)
        df = pd.concat([old, df]).drop_duplicates(subset=["link"])

    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    log.info(f"Résultats sauvegardés : {OUTPUT_FILE} ({len(df)} offres au total)")


# ==============================
# MAIN — UN CYCLE COMPLET
# ==============================

def run_once():
    """Exécute un cycle complet de scraping + analyse + candidature."""
    log.info("=" * 50)
    log.info("DÉMARRAGE D'UN NOUVEAU CYCLE")
    log.info("=" * 50)

    seen = load_file_set(SEEN_FILE)
    log.info(f"Offres déjà vues : {len(seen)}")

    driver = init_driver()
    all_jobs = []

    try:
        for keyword in KEYWORDS:
            jobs = scrape_indeed(driver, keyword)
            delay(1, 2)

            for job in jobs:
                if job["link"] in seen:
                    continue

                result = analyse_job(driver, job)
                append_to_file(SEEN_FILE, job["link"])

                # Tente la candidature si accepté + Easy Apply
                if result["status"] == "accepted" and result.get("easy_apply"):
                    apply_easy(driver, result)
                    delay(3, 5)

                all_jobs.append(result)

    except Exception as e:
        log.error(f"Erreur dans le cycle : {e}")

    finally:
        driver.quit()

    log.info(f"Nouvelles offres ce cycle : {len(all_jobs)}")
    save_results(all_jobs)
    log.info(f"Prochain cycle dans {REPEAT_EVERY_HOURS}h")


# ==============================
# BOUCLE HORAIRE
# ==============================

def main():
    log.info("✅ Job Bot démarré — tourne toutes les heures automatiquement")
    log.info("   Appuie sur CTRL+C pour arrêter\n")

    # Premier lancement immédiat
    run_once()

    # Planification automatique toutes les X heures
    schedule.every(REPEAT_EVERY_HOURS).hours.do(run_once)

    while True:
        schedule.run_pending()
        time.sleep(60)  # Vérifie chaque minute si une tâche doit tourner


# ==============================
# START
# ==============================

if __name__ == "__main__":
    main()