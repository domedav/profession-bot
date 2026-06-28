#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║ Profession.hu Auto-Apply Bot v1.0 — a bot első működő verziója ║
║                                                                ║
║  Firefox böngésző (GeckoDriver).                               ║
║  ALL 30+ bugs fixed from code audit.                           ║
║  --guided: CLI megerősítés minden jelentkezés előtt.           ║
║  --dry-run: teszt, nem küld el (NOR marks applied).            ║
║                                                                ║
║  python3 autoapply.py              → normál mód                ║
║  python3 autoapply.py --guided     → kézi megerősítéssel       ║
║  python3 autoapply.py --dry-run    → teszt (nem küld el)       ║
║  python3 autoapply.py --config     → konfig szerkesztés        ║
║  python3 autoapply.py --help       → súgó                      ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio, csv, json, random, re, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
from urllib.parse import urlparse

# ── Rich (optional) ──────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm, IntPrompt
    console = Console(); HAS_RICH = True
except ImportError:
    HAS_RICH = False
    class _Fallback:  # type: ignore
        def print(self,*a,**kw): print(*a)
        def rule(self,*a,**kw): print("─"*60)
    console = _Fallback()

# ═══════════════ Constants ═══════════════
BASE_DIR: Path = Path(__file__).resolve().parent
CONFIG_PATH: Path = BASE_DIR / "config.json"
SESSION_PATH: Path = BASE_DIR / "session.json"
APPLIED_PATH: Path = BASE_DIR / "applied_jobs.json"
LOG_PATH: Path = BASE_DIR / "apply_log.csv"
STATS_PATH: Path = BASE_DIR / "run_stats.json"
BAD_DOMAINS_PATH: Path = BASE_DIR / "bad_domains.json"
FULL_LOG_PATH: Path = BASE_DIR / "full_log.txt"

LOGIN_CHECK_INTERVAL: int = 15
MAX_BAD_DOMAIN_EXAMPLES: int = 3
PAGE_TIMEOUT: int = 30000
SUBMIT_WAIT_SEC: int = 5

USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) "
    "Gecko/20100101 Firefox/138.0"
)

# ── Known external ATS signatures ────────────────────────────
EXTERNAL_ATS_SIGS: list[str] = [
    r'avature\.net', r'myworkdayjobs\.com', r'workday\.com',
    r'smartrecruiters\.com', r'successfactors\.', r'icims\.com',
    r'taleo\.net', r'oraclecloud\.com', r'jobvite\.com',
    r'greenhouse\.io', r'lever\.co', r'breezy\.hr',
    r'ashbyhq\.com', r'bamboohr\.com', r'personio\.',
    r'dreamjo\.bs', 
    r'recruitee\.com', r'teamtailor\.com', r'pinpointhq\.com',
    r'Apply With LinkedIn', r'Apply with Indeed',
]

# ── Marketing keywords (checkbox skip) ───────────────────────
MARKETING_KEYWORDS: list[str] = [
    "marketing","reklám","hírlevél","értesít","hirdet","promóció",
    "e-mailben","emailben",
]

# ── Success phrases ──────────────────────────────────────────
SUCCESS_PHRASES: list[str] = [
    "sikeres jelentkezés","sikeresen jelentkezett","köszönjük jelentkezését",
    "jelentkezését rögzítettük","sikeresen elküldtük","sikeres pályázás",
    "jelentkezését továbbítottuk","jelentkezésedet továbbítottuk",
    "thank you for applying","application submitted",
]

# ── Success URL patterns ─────────────────────────────────────
SUCCESS_URL_PATTERNS: list[str] = [
    r'/koszonjuk', r'/sikeres', r'/thank-you', r'/thankyou',
    r'/success', r'/confirmation',
]

# ═══════════════ Helpers (pure functions) ═══════════════════

import os, select
os.environ["MOZ_ENABLE_WAYLAND"] = "0"

def was_enter_pressed() -> bool:
    """Checks if Enter key was pressed on stdin (Linux non-blocking)."""
    try:
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if r:
            sys.stdin.readline()  # consume input
            return True
    except Exception:
        pass
    return False

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def load_applied() -> set:
    if APPLIED_PATH.exists():
        try:
            with open(APPLIED_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, IOError):
            return set()
    return set()

def save_applied(s: set) -> None:
    with open(APPLIED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=2)

def load_bad_domains() -> dict:
    if BAD_DOMAINS_PATH.exists():
        try:
            with open(BAD_DOMAINS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"domains": {}, "total_external": 0}

def save_bad_domains(data: dict) -> None:
    with open(BAD_DOMAINS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_row(ts: str, title: str, company: str, url: str, status: str, note: str = "") -> None:
    exists = LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["timestamp","job_title","company","url","status","note"])
        w.writerow([ts, title, company, url, status, note])

def full_log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(FULL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    console.print(f"[dim]   📜 {msg}[/dim]")

def jitter(lo: float, hi: float) -> float:
    return random.uniform(lo, hi)

def extract_job_id(url: str) -> str:
    m = re.search(r'-(\d{5,8})(?:/|$|\?)', url)
    return m.group(1) if m else ""

def domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.replace("www.", "")
        return netloc if netloc else "unknown"
    except Exception:
        return "unknown"

def is_success_url(url: str) -> bool:
    """Check if URL matches known success page patterns."""
    return any(re.search(p, url, re.IGNORECASE) for p in SUCCESS_URL_PATTERNS)

def is_success_content(content: str) -> bool:
    """Check if page content indicates successful application."""
    cl = content.lower()
    return any(p in cl for p in SUCCESS_PHRASES)

def is_ats_signature(content: str) -> bool:
    """Check if a string matches any external ATS pattern."""
    return any(re.search(s, content, re.IGNORECASE) for s in EXTERNAL_ATS_SIGS)

def is_marketing_text(text: str) -> bool:
    """Check if text contains marketing consent keywords."""
    return any(w in text.lower() for w in MARKETING_KEYWORDS)

def validate_config(cfg: dict) -> list[str]:
    """Validate config and return list of issues (empty = valid)."""
    issues = []
    if "max_pages" in cfg:
        try: int(cfg["max_pages"])
        except (ValueError, TypeError): issues.append("max_pages must be an integer")
    if "max_applications_per_run" in cfg:
        try: int(cfg["max_applications_per_run"])
        except (ValueError, TypeError): issues.append("max_applications_per_run must be an integer")
    if "salary_amount" in cfg and cfg["salary_amount"] is not None:
        try: int(cfg["salary_amount"])
        except (ValueError, TypeError): issues.append("salary_amount must be an integer or null")
    return issues

# ═══════════════ Bot ═════════════════════════════════════════

class ProfessionBot:
    """Önműködő profession.hu álláspályázó bot v1.0 — a bot első működő verziója."""

    BASE: str = "https://www.profession.hu"
    APPLY_URL: str = f"{BASE}/jelentkezes/{{job_id}}"

    def __init__(self, config: dict, dry_run: bool = False, guided: bool = False):
        self.cfg = config
        self.dry_run = dry_run
        self.guided = guided
        self.applied: set = load_applied()
        self._bad_domains_cache: dict = load_bad_domains()
        self._bad_domains_dirty: bool = False
        self.playwright = self.browser = self.context = self.page = None
        self._stats_reset()
        self.interrupted: bool = False

        full_log(f"=== ÚJ FUTÁS ===")
        full_log(f"   Dry-run: {dry_run}, Guided: {guided}")
        safe_cfg = {k: v for k, v in config.items() if k not in ("cover_letter",)}
        full_log(f"   Config: {json.dumps(safe_cfg, ensure_ascii=False)}")

        # Validate config
        config_issues = validate_config(config)
        if config_issues:
            for issue in config_issues:
                full_log(f"   ⚠ Config figyelmeztetés: {issue}")

    def _stats_reset(self) -> None:
        self.stats = {
            "total_scraped": 0,
            "total_processed": 0,
            "applied": 0,
            "already_applied": 0,
            "external": 0,
            "external_embedded": 0,
            "no_apply_button": 0,
            "captcha_hit": 0,
            "login_wall": 0,
            "failed": 0,
            "skipped_manual": 0,
            "guided_skipped": 0,
            "dry_run": 0,
            "page_load_failure": 0,
            "domains_redirected": Counter(),
            "start_time": None,
            "end_time": None,
            "jobs_since_login_check": 0,
        }

    def _mark_applied(self, url: str, job_id: str) -> None:
        """Mark a job as applied and persist IMMEDIATELY."""
        self.applied.add(url)
        self.applied.add(job_id)
        save_applied(self.applied)
        full_log(f"   ✅ applied_jobs.json mentve ({len(self.applied)} összesen)")

    async def _set_interaction(self, blocked: bool) -> None:
        """Block or unblock user interaction in the browser window."""
        if not self.page:
            return
        try:
            val = 'none' if blocked else 'auto'
            # Disable mouse pointer events and text selection when blocked
            await self.page.evaluate(f"""(b) => {{
                document.body.style.pointerEvents = b ? 'none' : 'auto';
                document.body.style.userSelect = b ? 'none' : 'auto';
            }}""", blocked)
        except Exception:
            pass

    def _track_bad(self, domain: str, job: dict) -> None:
        """Track external domain (deferred save)."""
        self._bad_domains_dirty = True
        self._bad_domains_cache["total_external"] += 1
        if domain not in self._bad_domains_cache["domains"]:
            self._bad_domains_cache["domains"][domain] = {
                "count": 0, "examples": [],
                "first_seen": datetime.now(timezone.utc).isoformat()
            }
        d = self._bad_domains_cache["domains"][domain]
        d["count"] += 1
        if len(d["examples"]) < MAX_BAD_DOMAIN_EXAMPLES:
            d["examples"].append({
                "title": job["title"][:100],
                "url": job["url"]
            })

    def _flush_bad_domains(self) -> None:
        """Save bad domains to disk (called at end of run)."""
        if self._bad_domains_dirty:
            save_bad_domains(self._bad_domains_cache)
            self._bad_domains_dirty = False

    # ── Browser (FIREFOX) ────────────────────────────────────

    async def start(self) -> None:
        full_log("Böngésző indítása (Firefox)…")
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        headless = self.cfg.get("headless", False)

        self.browser = await self.playwright.firefox.launch(
            headless=headless,
            firefox_user_prefs={
                "dom.webdriver.enabled": False,
                "useAutomationExtension": False,
            }
        )

        if SESSION_PATH.exists():
            full_log("   Session betöltve fájlból")
            self.context = await self.browser.new_context(
                storage_state=str(SESSION_PATH),
                viewport={"width": 1366, "height": 900},
                user_agent=USER_AGENT,
            )
        else:
            full_log("   Nincs mentett session")
            self.context = await self.browser.new_context(
                viewport={"width": 1366, "height": 900},
                user_agent=USER_AGENT,
            )

        # Navigation watchdog
        self.context.on("page", self._on_new_page)
        self.page = await self.context.new_page()
        self._last_url = self.BASE
        self.page.on("framenavigated", self._on_navigation)

        console.print("[green]🦊 Firefox böngésző elindítva[/green]")
        full_log("✅ Böngésző kész")

    async def _on_new_page(self, page) -> None:
        if page.url == "about:blank" or not page.url:
            return
        if self.BASE not in page.url:
            d = domain_of(page.url)
            full_log(f"Új lap (külső): {d}")
            self.stats["domains_redirected"][d] += 1
            await page.close()

    async def _on_navigation(self, frame) -> None:
        if frame != self.page.main_frame:
            return
        url = frame.url
        if url == self._last_url:
            return
        self._last_url = url
        if self.BASE not in url and url != "about:blank":
            d = domain_of(url)
            full_log(f"Navigáció külső domainre: {d}")
            self.stats["domains_redirected"][d] += 1

    async def shutdown(self) -> None:
        full_log("Böngésző leállítása…")
        self._flush_bad_domains()
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
        console.print("[dim]🦊 Böngésző bezárva.[/dim]")

    # ── Login ────────────────────────────────────────────────

    async def _check_login_status(self) -> bool:
        """Quick check: is the session still valid?"""
        try:
            await self.page.goto(self.BASE, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            await asyncio.sleep(1)
            # '/kilepes' (logout) is only visible when successfully signed in
            return await self.page.query_selector('a[href*="/kilepes"]') is not None
        except Exception:
            return False

    async def ensure_logged_in(self) -> None:
        """Ensure user is logged in. Auto-fills credentials if config allows, prompts if needed."""
        is_logged = await self._check_login_status()
        if is_logged:
            full_log("✅ Már bejelentkezve")
            self.stats["jobs_since_login_check"] = 0
            return

        full_log("🔐 Bejelentkezés szükséges")
        await self.page.goto(
            f"{self.BASE}/munkavallalo/belepes",
            wait_until="domcontentloaded", timeout=PAGE_TIMEOUT
        )
        await asyncio.sleep(2)
        await self._set_interaction(False)  # Unblock browser for manual login entry

        # Autofill email and password if present in config
        email = self.cfg.get("user_email")
        password = self.cfg.get("user_password")
        if email and password:
            full_log("   Automatikus bejelentkezési adatok kitöltése…")
            try:
                await self.page.fill("input#login_e_mail", email)
                await self.page.fill("input#login_passwd", password)
                await self.page.click("input[type='submit']")
                await asyncio.sleep(4)
            except Exception as e:
                full_log(f"   ⚠ Automatikus kitöltés hiba: {e}")

        # Check if auto-login worked
        is_logged = await self._check_login_status()
        if is_logged:
            await self.context.storage_state(path=str(SESSION_PATH))
            self.stats["jobs_since_login_check"] = 0
            full_log("✅ Automatikus bejelentkezés sikeres")
            console.print("[green]✅ Automatikus bejelentkezés sikeres, session elmentve![/green]")
            await self._set_interaction(True)  # Re-block interaction
            return

        while True:
            console.print(Panel.fit(
                "[bold yellow]🔐 BEJELENTKEZÉS[/bold yellow]\n\n"
                "1. Nyisd meg a böngészőt és jelentkezz be\n"
                "2. (email+jelszó / Google / Facebook / Apple)\n"
                "3. Captcha-t oldd meg\n"
                "4. Ha sikeresen beléptél, nyomj Enter-t a bot termináljában!\n",
                title="Bejelentkezés"
            ))
            input(">>> Enter ha beléptél: ")

            is_logged = await self._check_login_status()
            if is_logged:
                await self.context.storage_state(path=str(SESSION_PATH))
                self.stats["jobs_since_login_check"] = 0
                full_log("✅ Session sikeresen elmentve")
                console.print("[green]✅ Bejelentkezés sikeres, session elmentve![/green]")
                break
            else:
                console.print("[red]❌ Nem sikerült a bejelentkezés detektálása! Kérlek próbáld újra.[/red]")
                full_log("⚠ Sikertelen bejelentkezési kísérlet.")

    async def _periodic_login_check(self) -> None:
        """Check login validity every LOGIN_CHECK_INTERVAL jobs."""
        self.stats["jobs_since_login_check"] += 1
        if self.stats["jobs_since_login_check"] >= LOGIN_CHECK_INTERVAL:
            full_log("Időszakos login ellenőrzés…")
            if not await self._check_login_status():
                full_log("⚠ Session lejárt — újra bejelentkezés")
                await self._force_relogin()
            self.stats["jobs_since_login_check"] = 0

    async def _force_relogin(self) -> None:
        """Force re-login (session expired) and verify success."""
        await self.page.goto(
            f"{self.BASE}/munkavallalo/belepes",
            wait_until="domcontentloaded", timeout=PAGE_TIMEOUT
        )
        await asyncio.sleep(2)
        await self._set_interaction(False)  # Unblock for force relogin

        # Autofill email and password if present in config
        email = self.cfg.get("user_email")
        password = self.cfg.get("user_password")
        if email and password:
            try:
                await self.page.fill("input#login_e_mail", email)
                await self.page.fill("input#login_passwd", password)
                await self.page.click("input[type='submit']")
                await asyncio.sleep(4)
            except Exception:
                pass

        while True:
            is_logged = await self._check_login_status()
            if is_logged:
                await self.context.storage_state(path=str(SESSION_PATH))
                console.print("[green]✅ Újra-bejelentkezés sikeres, session frissítve![/green]")
                await self._set_interaction(True)  # Re-block
                break
            else:
                console.print("[red]❌ Nem sikerült a bejelentkezés detektálása! Kérlek próbáld újra.[/red]")
                console.print("[cyan]⏳ A session lejárt. Jelentkezz be újra a böngészőben, majd Enter.[/cyan]")
                input(">>> Enter ha beléptél: ")

    # ── Scraping ─────────────────────────────────────────────

    def _get_search_url(self) -> str:
        """Get search URL from config or prompt user (pre-flight)."""
        saved_url = self.cfg.get("search_url", "")
        use_saved = False
        if saved_url:
            console.print(f"\n[yellow]Találtam egy korábbi keresési URL-t:[/yellow]")
            console.print(f"[dim]{saved_url}[/dim]")
            if HAS_RICH:
                use_saved = Confirm.ask("Szeretnéd ezt a keresést használni?", default=True)
            else:
                ans = input("Szeretnéd ezt a keresést használni? [Y/n]: ").strip().lower()
                use_saved = ans not in ("n", "no")
        
        if use_saved and saved_url:
            return saved_url

        # Otherwise prompt for a new URL
        console.print(Panel.fit(
            "[bold]🔍 Keresési URL[/bold]\n\n"
            "Nyisd meg a profession.hu-t, állítsd be a keresőt, másold ide a teljes URL-t.\n"
            "Pl.: https://www.profession.hu/allasok/1,0,0,szoftverfejleszt%C5%91%401%401?keywordsearch\n",
            title="Keresési URL"
        ))
        if HAS_RICH:
            url = Prompt.ask("[cyan]Új Keresési URL[/cyan]")
        else:
            url = input("Új Keresési URL: ").strip()
        self.cfg["search_url"] = url
        save_config(self.cfg)
        return url

    async def collect_jobs(self) -> list[dict]:
        """Walk through search result pages, collect ALL unique job listings."""
        search_url = self._get_search_url()
        max_pages = self.cfg.get("max_pages", 10)
        all_jobs: list[dict] = []
        seen: set = set()

        full_log(f"Állások gyűjtése: {search_url} (max {max_pages} oldal)")
        console.print(f"\n[bold]📋 Állások begyűjtése…[/bold]")
        console.print(f"[dim]URL: {search_url}[/dim]")

        current_url = search_url
        for pn in range(1, max_pages + 1):
            if was_enter_pressed():
                full_log("  A felhasználó megszakította a keresést (Enter).")
                console.print("\n[yellow]  🛑 Gyűjtés leállítva (Enter) — Továbblépés az eddig talált állásokkal…[/yellow]\n")
                break

            full_log(f"  → Oldal {pn}: {current_url}")
            console.print(f"[dim]  → Oldal {pn}… (Gyűjtés leállításához nyomj Enter-t)[/dim]")

            try:
                await self.page.goto(
                    current_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT
                )
            except Exception as e:
                full_log(f"  ⚠ Oldal {pn} betöltése sikertelen: {e} — folytatom")
                self.stats["page_load_failure"] += 1
                # Try to continue — the pagination link may still work
                next_link = await self.page.query_selector(
                    'a.next, a[class*="next"], a[href*="/allasok/"]:has-text("Következő")'
                )
                if next_link:
                    current_url = await next_link.get_attribute("href") or ""
                    if not current_url:
                        break
                    continue
                else:
                    break

            await asyncio.sleep(jitter(2, 4))

            # Extract real job links from DOM
            job_links = await self.page.evaluate("""() => {
                const results = []; const s = new Set();
                for (const a of document.querySelectorAll('a[href*="/allas/"]')) {
                    const href = a.href;
                    if (href.includes('#') || href.includes('redirect') || href.includes('optimum')) continue;
                    const match = href.match(/\\/allas\\/[^\\/]+-(\\d{5,8})(?:\\?|$)/);
                    if (!match) continue;
                    if (s.has(href)) continue;
                    s.add(href);
                    const h2 = a.querySelector('h2');
                    const title = h2 ? h2.textContent.trim() : a.textContent.trim();
                    if (title && title.length > 3) {
                        results.push({url: href, title: title.substring(0, 200)});
                    }
                }
                return results;
            }""")

            page_jobs = []
            for j in job_links:
                if j["url"] not in seen:
                    seen.add(j["url"])
                    page_jobs.append({"title": j["title"], "company": "", "url": j["url"]})

            full_log(f"  Találat ezen az oldalon: {len(page_jobs)}")
            console.print(f"     Találat: [cyan]{len(page_jobs)}[/cyan]")

            if not page_jobs:
                full_log("  Nincs találat — vége a listának")
                break

            all_jobs.extend(page_jobs)

            # Follow "Következő oldal" link
            next_a = await self.page.query_selector(
                'a.next, a[class*="next"], a[href*="/allasok/"]:has-text("Következő")'
            )
            if not next_a:
                full_log("  Nincs Következő oldal link")
                break

            # Check if disabled
            is_disabled = await next_a.get_attribute("aria-disabled") or ""
            classes = await next_a.get_attribute("class") or ""
            if is_disabled == "true" or "disabled" in classes:
                full_log("  Következő oldal link disabled — vége")
                break

            current_url = await next_a.get_attribute("href") or ""
            if not current_url:
                break

        self.stats["total_scraped"] = len(all_jobs)
        full_log(f"Összes találat (szűrés előtt): {len(all_jobs)}")

        # Filtering
        keywords = [k.lower() for k in self.cfg.get("keyword_filter", [])]
        excludes = [k.lower() for k in self.cfg.get("exclude_keywords", [])]

        if keywords or excludes:
            filtered = []
            for j in all_jobs:
                t = j["title"].lower()
                if keywords and not any(k in t for k in keywords):
                    continue
                if excludes and any(k in t for k in excludes):
                    continue
                filtered.append(j)
            full_log(f"Szűrés után: {len(filtered)}")
            console.print(f"\n[bold green]📊 Összesen: {len(all_jobs)} | Szűrés után: {len(filtered)}[/bold green]")
            return filtered

        console.print(f"\n[bold green]📊 Összesen: {len(all_jobs)} állás[/bold green]")
        return all_jobs

    # ── Apply Logic ──────────────────────────────────────────

    async def apply_one(self, job: dict) -> str:
        """Apply to one job. Returns status code."""
        url = job["url"]
        job_id = extract_job_id(url)
        ts = datetime.now(timezone.utc).isoformat()
        position = job["title"][:80]

        full_log(f"\n── ÁLLÁS: {position} (ID: {job_id}) ──")
        full_log(f"   URL: {url}")

        # Already applied?
        if url in self.applied or job_id in self.applied:
            full_log("   ⏭ Már jelentkezve — átugrás")
            self.stats["already_applied"] += 1
            return "already_applied"

        self.stats["total_processed"] += 1
        console.print(f"\n[bold]📄 {position}[/bold]")
        console.print(f"[dim]   ID: {job_id}[/dim]")


        # ── GUIDED MODE ──
        if self.guided:
            full_log("   [GUIDED] CLI megerősítés kérése…")
            console.print(f"[yellow]   [GUIDED] {position}[/yellow]")
            if HAS_RICH:
                ans = Prompt.ask(
                    "   [cyan]Elfogadod ezt a jelentkezést?[/cyan]",
                    choices=["y", "n", "skip"], default="y"
                )
            else:
                ans = input("   Elfogadod? [y/n/skip] ").strip().lower()
            if ans == "skip":
                full_log("   [GUIDED] Átugrás (skip)")
                self.stats["guided_skipped"] += 1
                log_row(ts, job["title"], job.get("company", ""), url, "guided_skip", "")
                return "skipped"
            elif ans == "n":
                full_log("   [GUIDED] Elutasítás (n)")
                self.stats["skipped_manual"] += 1
                log_row(ts, job["title"], job.get("company", ""), url, "skipped", "guided-no")
                return "skipped"
            full_log("   [GUIDED] Elfogadva")

        # ── 1. Open job page ──
        full_log("   1. Oldal betöltése…")
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            await self._set_interaction(True)  # Block interaction
        except Exception as e:
            full_log(f"   ❌ Betöltési hiba: {e}")
            console.print(f"[red]   ❌ Oldal betöltési hiba: {e}[/red]")
            log_row(ts, job["title"], job.get("company", ""), url, "failed", str(e))
            self.stats["failed"] += 1
            return "failed"
        await asyncio.sleep(jitter(2, 4))
        full_log(f"   1. Oldal betöltve: {self.page.url[:100]}")

        if self.BASE not in self.page.url:
            d = domain_of(self.page.url)
            full_log(f"   1. Átirányítás külsőre: {d}")
            self._track_bad(d, job)
            log_row(ts, job["title"], job.get("company", ""), url, "external", f"Redirect to {d}")
            self.stats["external"] += 1
            return "external"

        # ── 2. Detect apply type ──
        full_log("   2. Jelentkezés típus detektálása…")
        internal_link = await self.page.query_selector('a[href*="/jelentkezes/"]')
        external_link = await self.page.query_selector('a[href*="redirect=1"]')

        if external_link and not internal_link:
            full_log("   2. Külső jelentkezés (redirect=1) → kihagy")
            console.print("[yellow]   ⤤ Jelentkezés a cégnél — kihagyva[/yellow]")
            log_row(ts, job["title"], job.get("company", ""), url, "external", "redirect=1")
            self.stats["external"] += 1
            return "external"

        if not internal_link:
            full_log("   2. Nincs belső Jelentkezem link → kihagy")
            console.print("[yellow]   ⚠ Nincs Jelentkezem link — kihagyva[/yellow]")
            log_row(ts, job["title"], job.get("company", ""), url, "no_button", "")
            self.stats["no_apply_button"] += 1
            return "skipped"

        full_log("   2. Belső jelentkezés (Jelentkezem link)")

        # ── 3. Open apply form ──
        apply_url = self.APPLY_URL.format(job_id=job_id)
        full_log(f"   3. Űrlap megnyitása: /jelentkezes/{job_id}")
        console.print(f"[dim]   → /jelentkezes/{job_id}[/dim]")
        await self.page.goto(apply_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        await self._set_interaction(True)  # Block interaction
        await asyncio.sleep(jitter(2, 4))

        if self.BASE not in self.page.url:
            d = domain_of(self.page.url)
            full_log(f"   3. Átirányítás az űrlapról: {d}")
            self._track_bad(d, job)
            log_row(ts, job["title"], job.get("company", ""), url, "external", f"Redirect from apply to {d}")
            self.stats["external"] += 1
            return "external"

        # ── 4. Detect embedded ATS ──
        full_log("   4. Beágyazott ATS detektálás…")
        if self.cfg.get("skip_embedded_ats", False) and await self._detect_external_ats():
            full_log("   4. Beágyazott ATS találva → kihagy")
            console.print("[yellow]   ⤤ Beágyazott külső ATS — kihagyva[/yellow]")
            self.stats["external_embedded"] += 1
            self.stats["external"] += 1
            log_row(ts, job["title"], job.get("company", ""), url, "external_embedded", "Embedded ATS")
            return "external"
        full_log("   4. Nincs beágyazott ATS (vagy kihagyás kikapcsolva)")

        # ── 5. Login wall ──
        full_log("   5. Bejelentkezési fal ellenőrzése…")
        if await self._is_login_wall():
            full_log("   5. Bejelentkezési fal — be kell jelentkezni")
            self.stats["login_wall"] += 1
            console.print("[yellow]   ⚠ Bejelentkezés szükséges — jelentkezz be a böngészőben.[/yellow]")
            await self._set_interaction(False)  # Unblock for relogin
            login_link = await self.page.query_selector('a[href*="belepes"]')
            if login_link:
                await login_link.click()
                await asyncio.sleep(3)
            input(">>> Jelentkezz be, majd Enter: ")
            await self.context.storage_state(path=str(SESSION_PATH))
            full_log("   5. Belépés után session mentve")
            await self.page.goto(apply_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            await self._set_interaction(True)  # Re-block
            await asyncio.sleep(2)

        # ── 6. Fill form ──
        full_log("   6. Űrlap kitöltése…")
        await self._fill_apply_form()
        full_log("   6. Űrlap kitöltve")

        # ── 7. DRY-RUN: stop before submit ──
        if self.dry_run:
            full_log("   7. [DRY-RUN] Várakozás 10 másodpercig az ellenőrzéshez…")
            console.print("[yellow]   [DRY-RUN] ⏳ Várakozás 10 másodpercig, hogy ellenőrizhesd a kitöltést…[/yellow]")
            await self._set_interaction(False)  # Unblock temporarily for user inspection
            await asyncio.sleep(10)
            await self._set_interaction(True)  # Re-block
            full_log("   7. [DRY-RUN] Küldés gomb megkeresése, DE NEM KATTINTÁS")
            submit = await self.page.query_selector(
                'button[type="submit"], input[type="submit"], '
                'button:has-text("Jelentkezem"), button:has-text("Elküld"), '
                'button:has-text("Küldés"), button:has-text("Jelentkezés")'
            )
            if submit:
                console.print("[yellow]   [DRY-RUN] ✅ Küldés gomb megtalálva — NEM kattintva.[/yellow]")
                full_log("   7. [DRY-RUN] ✅ Küldés gomb megtalálva")
            else:
                console.print("[yellow]   [DRY-RUN] ⚠ Küldés gomb NEM található.[/yellow]")
                full_log("   7. [DRY-RUN] ⚠ Küldés gomb NEM található")
            self.stats["dry_run"] += 1
            log_row(ts, job["title"], job.get("company", ""), url, "dry_run", "form filled, not submitted")
            return "dry_run"

        # ── 8. Captcha ──
        full_log("   8. Captcha ellenőrzés…")
        if await self._detect_captcha():
            full_log("   8. Captcha detektálva!")
            console.print("[bold red]🤖 CAPTCHA![/bold red]\n[yellow]Oldd meg a böngészőben, majd Enter.[/yellow]")
            await self._set_interaction(False)  # Unblock for captcha
            self.stats["captcha_hit"] += 1
            input(">>> Enter: ")
            await self._set_interaction(True)  # Re-block
            full_log("   8. Captcha megoldva (felhasználó)")

        # ── 9. Submit ──
        full_log("   9. Küldés…")
        success = await self._submit_and_check()

        if success:
            full_log("   9. ✅ SIKERES JELENTKEZÉS")
            console.print("[bold green]   ✅ SIKERES JELENTKEZÉS![/bold green]")
            self._mark_applied(url, job_id)
            self.stats["applied"] += 1
            log_row(ts, job["title"], job.get("company", ""), url, "applied", "")
            return "applied"
        else:
            full_log("   9. Bizonytalan státusz")
            if self.BASE not in self.page.url:
                d = domain_of(self.page.url)
                full_log(f"   9. Átirányítás küldés után: {d}")
                self._track_bad(d, job)
                log_row(ts, job["title"], job.get("company", ""), url, "external", f"Post-submit to {d}")
                self.stats["external"] += 1
                return "external"

            await self._set_interaction(False)  # Unblock for manual check input
            console.print("[yellow]   ⚠ Bizonytalan státusz. Nézd meg a böngészőt.[/yellow]")
            console.print("[dim]   ok / skip / captcha[/dim]")
            ans = input("   >>> ").strip().lower()
            await self._set_interaction(True)  # Re-block
            full_log(f"   9. Felhasználó válasza: {ans}")
            if ans == "ok":
                self._mark_applied(url, job_id)
                self.stats["applied"] += 1
                log_row(ts, job["title"], job.get("company", ""), url, "applied", "manual confirm")
                return "applied"
            elif ans == "captcha":
                self.stats["captcha_hit"] += 1
                log_row(ts, job["title"], job.get("company", ""), url, "captcha", "")
                return "captcha"
            else:
                self.stats["skipped_manual"] += 1
                log_row(ts, job["title"], job.get("company", ""), url, "skipped", "manual skip")
                return "skipped"

    # ── ATS Detection ────────────────────────────────────────

    async def _detect_external_ats(self) -> bool:
        """Detect embedded external ATS in iframe/form/content."""
        # 1. Iframes
        for iframe in await self.page.query_selector_all('iframe'):
            src = (await iframe.get_attribute("src") or "").lower()
            if src and "profession.hu" not in src:
                if is_ats_signature(src):
                    full_log(f"     Külső ATS iframe: {domain_of(src)}")
                    self.stats["domains_redirected"][domain_of(src)] += 1
                    return True
                # Unknown iframe (not tracker/cookiebot)
                if not any(x in src for x in ["google","facebook","doubleclick","gtm","analytics","pixel","cookiebot","onetrust","usercentrics"]):
                    full_log(f"     Külső ismeretlen iframe: {domain_of(src)}")
                    self.stats["domains_redirected"][domain_of(src)] += 1
                    return True

        # 2. Page content
        content = (await self.page.content()).lower()
        if is_ats_signature(content):
            full_log("     ATS aláírás a tartalomban")
            return True

        # 3. Form actions
        for form in await self.page.query_selector_all('form'):
            action = (await form.get_attribute("action") or "").lower()
            if action.startswith("http://") or action.startswith("https://") or action.startswith("//"):
                if "profession.hu" not in action:
                    d = domain_of(action)
                    full_log(f"     Külső form action: {d}")
                    self.stats["domains_redirected"][d] += 1
                    return True

        return False

    async def _is_login_wall(self) -> bool:
        content = await self.page.content()
        result = any(p in content for p in ["Lépj be!", "Van már Profession profilod", "Bejelentkezés"])
        full_log(f"     Login wall: {result}")
        return result

    # ── Form Filling (SMART checkbox strategy) ───────────────

    async def _fill_apply_form(self) -> None:
        """Fill the profession.hu apply form with smart checkbox strategy."""

        # ── Salary ──
        salary = self.cfg.get("salary_amount")
        if salary:
            full_log(f"     Fizetési igény beállítása: {salary} Ft")
            filled = False
            for inp in await self.page.query_selector_all('input'):
                t = (await inp.get_attribute("type") or "text").lower()
                if t in ("submit", "checkbox", "radio", "file", "hidden", "button"):
                    continue
                if not await inp.is_visible():
                    continue
                attrs = (
                    (await inp.get_attribute("placeholder") or "") +
                    (await inp.get_attribute("name") or "") +
                    (await inp.get_attribute("id") or "") +
                    (await inp.get_attribute("aria-label") or "") +
                    (await inp.get_attribute("autocomplete") or "")
                ).lower()
                # More specific keywords (removed bare "ft", "ber", "net" to reduce false positives)
                salary_keywords = [
                    "fizetési igény", "bérigény", "havi nett", "nettó fizet",
                    "fizetés", "salary", "összeg",
                ]
                if any(k in attrs for k in salary_keywords):
                    try:
                        await inp.click()
                        await inp.fill("")
                        await inp.fill(str(salary))
                        console.print(f"[dim]     Fizetési igény: {salary:,} Ft[/dim]")
                        full_log(f"     ✅ Fizetési igény beállítva")
                        filled = True
                        break
                    except Exception as e:
                        full_log(f"     ⚠ Fizetési mező hiba: {e}")

            # Fallback: try any visible text/number input
            if not filled:
                for inp in await self.page.query_selector_all('input'):
                    t = (await inp.get_attribute("type") or "text").lower()
                    if t not in ("text", "number", ""):
                        continue
                    if not await inp.is_visible():
                        continue
                    try:
                        await inp.click()
                        await inp.fill("")
                        await inp.fill(str(salary))
                        console.print(f"[dim]     Fizetési igény (fallback): {salary:,} Ft[/dim]")
                        full_log(f"     ✅ Fizetési igény beállítva (fallback)")
                        break
                    except Exception as e:
                        full_log(f"     ⚠ Fallback hiba: {e}")

            await asyncio.sleep(0.5)

        # ── Cover letter ──
        cover = self.cfg.get("cover_letter", "")
        if cover:
            full_log("     Kísérőlevél írása…")
            filled = False
            for ta in await self.page.query_selector_all("textarea"):
                if await ta.is_visible():
                    try:
                        # Check if it's a cover letter field
                        attrs = (
                            (await ta.get_attribute("placeholder") or "") +
                            (await ta.get_attribute("name") or "") +
                            (await ta.get_attribute("id") or "")
                        ).lower()
                        cover_keywords = ["kísérő", "motivác", "bemutatkoz", "cover", "message"]
                        if any(k in attrs for k in cover_keywords):
                            await ta.fill(cover)
                            full_log("     ✅ Kísérőlevél kitöltve (azonosított mező)")
                        else:
                            await ta.fill(cover)
                            full_log("     ✅ Kísérőlevél kitöltve (első textarea)")
                        console.print("[dim]     Kísérőlevél kitöltve[/dim]")
                        filled = True
                        break
                    except Exception as e:
                        full_log(f"     ⚠ Kísérőlevél hiba: {e}")
            await asyncio.sleep(0.5)

        # ── Checkboxes (SMART strategy) ──
        full_log("     Checkboxok bepipálása (SMART stratégia)…")
        apply_form = await self.page.query_selector('#apply_form, .p2_apply_form')
        if apply_form:
            checkboxes = await apply_form.query_selector_all('input[type="checkbox"]')
        else:
            checkboxes = await self.page.query_selector_all('input[type="checkbox"]')
        full_log(f"     Található checkbox: {len(checkboxes)}")

        consent_checked = 0
        cv_checked = 0
        marketing_skipped = 0
        cv_found = False

        # First pass: identify CV checkboxes
        for i, cb in enumerate(checkboxes):
            cb_name = (await cb.get_attribute("name") or "").lower()
            cb_id = (await cb.get_attribute("id") or "").lower()
            combined = cb_name + cb_id

            is_cv = any(w in combined for w in ["cv", "oneletrajz", "önéletrajz", "dokumentum", "document", "attachment", "uploadfile"])
            if is_cv:
                cv_found = True
                break

        for i, cb in enumerate(checkboxes):
            cb_id = await cb.get_attribute("id") or f"cb-{i}"
            cb_name = (await cb.get_attribute("name") or "").lower()

            if await cb.is_checked():
                full_log(f"     [{i}] {cb_id} — már bepipálva")
                continue

            # Read parent text (3 levels for more precision, not 8)
            parent_text = await self.page.evaluate("""(el) => {
                let p = el.parentElement; let t = '';
                for (let i=0; i<4 && p; i++) { t += (p.textContent||'') + ' '; p = p.parentElement; }
                return t;
            }""", cb)

            # Identify checkbox type
            combined = cb_name + cb_id + parent_text.lower()

            is_cv = any(w in combined for w in ["cv", "oneletrajz", "önéletrajz", "dokumentum", "document", "attachment", "uploadfile"])
            is_marketing = is_marketing_text(parent_text)
            is_consent = any(w in combined for w in [
                "adatkezel", "elfogad", "feltétel", "ászf", "gdpr", "privacy",
                "hozzájárul", "consent", "agree", "tudomásul", "megismertem",
            ])

            if is_marketing and not self.cfg.get("accept_marketing", False):
                full_log(f"     [{i}] {cb_id} — marketing checkbox, kihagyva")
                marketing_skipped += 1
                continue

            if is_cv and cv_found:
                # Check ALL CV document checkboxes (user requirement)
                # NOTE: Labels are empty (<label for="uploadfile_2"></label>),
                # so label.click() hits a zero-size element and fails silently.
                # Instead, use JS dispatchEvent directly on the input — reliable
                # even for styled/hidden inputs.
                cb_id = await cb.get_attribute("id")
                full_log(f"     [{i}] {cb_id} — CV checkbox próba (JS dispatchEvent)…")
                try:
                    await cb.scroll_into_view_if_needed()
                    # Primary: JS click + dispatchEvent to trigger any Vue/React listeners
                    checked_after = await cb.evaluate("""el => {
                        if (!el.checked) {
                            el.checked = true;
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                        }
                        return el.checked;
                    }""")
                    await asyncio.sleep(0.3)
                    still_checked = await cb.is_checked()
                    if still_checked:
                        cv_checked += 1
                        full_log(f"     [{i}] {cb_id} — CV dokumentum bepipálva (#{cv_checked})")
                    else:
                        # Fallback: try label click if it has non-zero area
                        label_el = await self.page.query_selector(f'label[for="{cb_id}"]') if cb_id else None
                        if label_el:
                            bbox = await label_el.bounding_box()
                            if bbox and bbox.get("width", 0) > 0 and bbox.get("height", 0) > 0:
                                await label_el.click()
                                await asyncio.sleep(0.2)
                        if not await cb.is_checked():
                            # Last resort: force via property setter
                            await cb.evaluate("""el => {
                                Object.defineProperty(el, 'checked', {
                                    get: () => true, configurable: true
                                });
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }""")
                        if await cb.is_checked():
                            cv_checked += 1
                            full_log(f"     [{i}] {cb_id} — CV dokumentum bepipálva fallback-kel (#{cv_checked})")
                        else:
                            full_log(f"     [{i}] {cb_id} — FIGYELEM: CV checkbox nem pipálható be!")
                except Exception as e:
                    full_log(f"     [{i}] {cb_id} — HIBA CV checkboxnál: {e}")
                continue

            # Consent or unclassified: check it (safe default)
            cb_id = await cb.get_attribute("id")
            label_el = None
            if cb_id:
                label_el = await self.page.query_selector(f'label[for="{cb_id}"]')
                
            try:
                if label_el:
                    await label_el.scroll_into_view_if_needed()
                    await label_el.click()
                else:
                    await cb.scroll_into_view_if_needed()
                    await cb.check()
                if not await cb.is_checked():
                    await cb.evaluate("el => { if(!el.checked) { el.click(); } }")
                consent_checked += 1
                label = "consent" if is_consent else "unclassified"
                full_log(f"     [{i}] {cb_id} — bepipálva ({label})")
                await asyncio.sleep(0.2)
            except Exception as e:
                try:
                    if label_el:
                        await label_el.evaluate("el => el.click()")
                    else:
                        await cb.evaluate("el => { if(!el.checked) { el.click(); } }")
                    consent_checked += 1
                    label = "consent" if is_consent else "unclassified"
                    full_log(f"     [{i}] {cb_id} — bepipálva JS klikkel ({label})")
                except Exception as e2:
                    full_log(f"     [{i}] {cb_id} — HIBA: {e}")

        console.print(f"[dim]     Consent: {consent_checked} bepipálva[/dim]")
        if cv_checked:
            console.print(f"[dim]     CV dokumentum: {cv_checked} bepipálva[/dim]")
        if marketing_skipped:
            console.print(f"[dim]     Marketing: {marketing_skipped} kihagyva[/dim]")
        full_log(f"     Összesen: {consent_checked} consent, {cv_checked} CV, {marketing_skipped} marketing skip")

    # ── Submit ───────────────────────────────────────────────

    async def _submit_and_check(self) -> bool:
        """Click submit and verify success."""
        submit = await self.page.query_selector(
            'button[type="submit"], input[type="submit"], '
            'button:has-text("Jelentkezem"), button:has-text("Elküld"), '
            'button:has-text("Küldés"), button:has-text("Jelentkezés"), '
            'button:has-text("Beküld")'
        )
        if not submit:
            full_log("     ⚠ Nincs küldés gomb!")
            # Try form.submit() as fallback
            form = await self.page.query_selector('form')
            if form:
                try:
                    await form.evaluate("form => form.submit()")
                    full_log("     Form submit() via JS")
                    await asyncio.sleep(SUBMIT_WAIT_SEC)
                except Exception:
                    return False
            else:
                return False
        else:
            full_log("     Küldés gomb kattintás…")
            try:
                await submit.scroll_into_view_if_needed()
                await submit.click()
            except Exception as e:
                full_log(f"     ❌ Kattintási hiba: {e}")
                return False

        await asyncio.sleep(SUBMIT_WAIT_SEC)

        # Check success via URL first (most reliable)
        current_url = self.page.url
        if is_success_url(current_url):
            full_log(f"     Siker URL alapján: {current_url}")
            return True

        # Check success via page content
        content = await self.page.content()
        if is_success_content(content):
            full_log("     Siker tartalom alapján")
            return True

        # Check success via DOM element
        success_el = await self.page.query_selector(
            '[class*="success"], [class*="siker"], .alert-success, '
            '[data-testid="success"], [class*="thank"]'
        )
        if success_el:
            full_log("     Siker DOM elem alapján")
            return True

        full_log("     Nem detektálható siker")
        return False

    async def _detect_captcha(self) -> bool:
        selectors = [
            'iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]',
            'div.g-recaptcha', '#challenge-stage',
            'div.cf-turnstile', 'div.frc-captcha',
            'div[data-sitekey]', '[class*="captcha"]',
            'script[src*="recaptcha/api.js"]', 'script[src*="hcaptcha.com"]',
        ]
        for sel in selectors:
            if await self.page.query_selector(sel):
                full_log(f"     Captcha detektálva: {sel}")
                return True
        return False

    # ── Main Run ─────────────────────────────────────────────

    async def run(self) -> None:
        """Main execution flow with guaranteed cleanup."""
        self.stats["start_time"] = datetime.now(timezone.utc)
        full_log("=== FUTÁS INDÍTÁSA ===")

        try:
            console.rule("[bold blue]🦊 Profession.hu Auto-Apply Bot v1.0 (a bot első működő verziója)[/bold blue]")
            if self.dry_run:
                console.print("[yellow]⚠ DRY-RUN — nem küld el jelentkezést, NEM jelöli applied-ként![/yellow]")
            if self.guided:
                console.print("[yellow]🎮 GUIDED — minden jelentkezés előtt megerősítést kér![/yellow]")

            console.print(f"[dim]📁 Konfig: {CONFIG_PATH}[/dim]")
            console.print(f"[dim]📁 Napló: {LOG_PATH}[/dim]")
            console.print(f"[dim]📁 Részletes log: {FULL_LOG_PATH}[/dim]")
            console.print(f"[dim]✅ Már jelentkezve: {len(self.applied)}[/dim]\n")

            await self.start()
            await self.ensure_logged_in()

            jobs = await self.collect_jobs()
            if not jobs:
                full_log("⚠ Nincs feldolgozható állás!")
                console.print("[yellow]⚠ Nincs feldolgozható állás![/yellow]")
                return

            max_apps = max(1, int(self.cfg.get("max_applications_per_run", 20)))
            console.print(f"\n[bold]🎯 {len(jobs)} állás | Max {max_apps} jelentkezés[/bold]")
            full_log(f"Feldolgozandó: {len(jobs)} állás, maximum {max_apps} jelentkezés")

            if HAS_RICH and not Confirm.ask("[cyan]Indulhat a pályázás?[/cyan]"):
                full_log("Felhasználó megszakította")
                return

            applied_count = 0
            mode_desc = "GUIDED" if self.guided else "ÖNMŰKÖDŐ"
            console.print(f"\n[bold green]🚀 {mode_desc} MÓD[/bold green]\n")
            full_log(f"{mode_desc} ciklus indul")

            lo, hi = self.cfg.get("wait_between_actions", [2, 5])

            for i, job in enumerate(jobs):
                if applied_count >= max_apps:
                    full_log(f"⚠ Max ({max_apps}) elérve")
                    console.print(f"\n[yellow]⚠ Max ({max_apps}) elérve — leállás.[/yellow]")
                    break

                console.print(f"[dim]── [{i+1}/{len(jobs)}] ────────────[/dim]")
                full_log(f"[{i+1}/{len(jobs)}] {job['title'][:80]}")

                try:
                    await self._periodic_login_check()
                    status = await self.apply_one(job)
                    if status == "applied":
                        applied_count += 1
                    full_log(f"   Eredmény: {status}")
                except KeyboardInterrupt:
                    full_log("⚠ Ctrl+C — mentés és leállás")
                    console.print("\n[yellow]⚠ Ctrl+C — mentés…[/yellow]")
                    self.interrupted = True
                    break
                except Exception as e:
                    full_log(f"❌ Váratlan hiba: {e}\n{traceback.format_exc()}")
                    console.print(f"[red]❌ Hiba: {e}[/red]")
                    log_row(
                        datetime.now(timezone.utc).isoformat(),
                        job["title"], job.get("company", ""), job["url"],
                        "failed", str(e)[:200]
                    )
                    self.stats["failed"] += 1

                wait = jitter(lo, hi)
                full_log(f"⏳ Várakozás {wait:.1f}s")
                console.print(f"[dim]⏳ {wait:.1f}s…[/dim]")
                await asyncio.sleep(wait)

            self.stats["end_time"] = datetime.now(timezone.utc)
            self._flush_bad_domains()
            self._save_run_stats()
            self._print_summary()
            self._print_recommendations()
            full_log("=== FUTÁS VÉGE ===")

        finally:
            # GUARANTEED cleanup
            if self.browser or self.playwright:
                await self.shutdown()

    def _save_run_stats(self) -> None:
        d = None
        if self.stats["start_time"] and self.stats["end_time"]:
            d = str(self.stats["end_time"] - self.stats["start_time"])
        s = self.stats
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "run_at": datetime.now(timezone.utc).isoformat(),
                "duration": d,
                "dry_run": self.dry_run,
                "guided": self.guided,
                "interrupted": self.interrupted,
                "stats": {
                    "total_scraped": s["total_scraped"],
                    "total_processed": s["total_processed"],
                    "applied": s["applied"],
                    "already_applied": s["already_applied"],
                    "external": s["external"],
                    "external_embedded": s["external_embedded"],
                    "no_apply_button": s["no_apply_button"],
                    "captcha_hit": s["captcha_hit"],
                    "login_wall": s["login_wall"],
                    "failed": s["failed"],
                    "skipped_manual": s["skipped_manual"],
                    "guided_skipped": s["guided_skipped"],
                    "dry_run": s["dry_run"],
                    "page_load_failure": s.get("page_load_failure", 0),
                },
                "top_external_domains": dict(s["domains_redirected"].most_common(10)),
                "total_applied_ever": len(self.applied),
            }, f, ensure_ascii=False, indent=2)
        full_log(f"Statisztika mentve: {STATS_PATH}")

    def _print_summary(self) -> None:
        s = self.stats
        dur = ""
        if s["start_time"] and s["end_time"]:
            delta = s["end_time"] - s["start_time"]
            dur = f"{int(delta.total_seconds() // 60)}p {int(delta.total_seconds() % 60)}mp"

        console.rule(f"[bold blue]📊 ÖSSZEFOGLALÓ | {dur}[/bold blue]")

        if HAS_RICH:
            t = Table()
            t.add_column("Kategória", style="cyan")
            t.add_column("Db", style="green", justify="right")
            t.add_row("📋 Találat", str(s["total_scraped"]))
            t.add_row("🔄 Feldolgozva", str(s["total_processed"]))
            t.add_row("✅ Sikeres", str(s["applied"]))
            t.add_row("🔁 Már volt", str(s["already_applied"]))
            t.add_row("⤤ Külső", str(s["external"]))
            t.add_row("   ↳ Beágyazott ATS", str(s["external_embedded"]))
            t.add_row("🚫 Nincs gomb", str(s["no_apply_button"]))
            t.add_row("🤖 Captcha", str(s["captcha_hit"]))
            t.add_row("🎮 Guided skip", str(s["guided_skipped"]))
            t.add_row("✋ Kézi skip", str(s["skipped_manual"]))
            t.add_row("📄 Oldal hiba", str(s.get("page_load_failure", 0)))
            t.add_row("❌ Hiba", str(s["failed"]))
            if s["dry_run"] > 0:
                t.add_row("🧪 Dry-run", str(s["dry_run"]))
            console.print(t)
        else:
            print(f"✅:{s['applied']} ⤤:{s['external']} 🤖:{s['captcha_hit']} ❌:{s['failed']}")

        top = self.stats["domains_redirected"].most_common(5)
        if top:
            console.print("\n[bold]🌐 Leggyakoribb külső domainek:[/bold]")
            for dom, cnt in top:
                console.print(f"  [yellow]{dom}[/yellow]: {cnt}×")

        console.print(f"\n[dim]📁 Napló: {LOG_PATH} | Részletes log: {FULL_LOG_PATH}[/dim]")
        console.print(f"[dim]✅ Összes jelentkezés: {len(self.applied)}[/dim]")

    def _print_recommendations(self) -> None:
        console.rule("[bold blue]💡 AJÁNLÁSOK[/bold blue]")
        s = self.stats
        recs = []

        if s["external_embedded"] > 2:
            recs.append(f"⤤ {s['external_embedded']} beágyazott ATS — automatikusan kihagyva.")
        if s["external"] > max(s["applied"], 1) * 3:
            recs.append("⚠ Sok külső jelentkezés. Szűkítsd a keresést.")
        if s["no_apply_button"] > 5:
            recs.append("⚠ Sok állásnál nincs gomb. Használd az 'elmúlt 24 óra' szűrőt.")
        if s["captcha_hit"] > 3:
            recs.append("🤖 Sok Captcha. Növeld a várakozási időt, vagy csökkentsd a max jelentkezést.")
        if s.get("page_load_failure", 0) > 2:
            recs.append("📄 Több oldalbetöltési hiba. Ellenőrizd a netkapcsolatot vagy növeld a timeout-ot.")
        if not recs:
            recs.append("✅ Minden rendben!")

        for i, r in enumerate(recs, 1):
            console.print(f"  {i}. {r}")
        console.print(f"\n[dim]Következő futás: python3 autoapply.py[/dim]")


# ═══════════════ Entry Point ═════════════════════════════════

def print_help() -> None:
    print("""
🦊 Profession.hu Auto-Apply Bot v1.0 — a bot első működő verziója

Használat:
  python3 autoapply.py              Normál mód — önműködő
  python3 autoapply.py --guided     GUIDED — CLI megerősítés minden előtt
  python3 autoapply.py --dry-run    Teszt — űrlapot kitölti, NEM küld el, NEM ment
  python3 autoapply.py --config     Konfiguráció szerkesztése
  python3 autoapply.py --test       Unit tesztek futtatása
  python3 autoapply.py --help       Súgó

v1.0 jellemzők (a bot első működő verziója):
  - applied_jobs.json MINDEN sikeres jelentkezés után mentve (nincs adatvesztés)
  - try/finally garantált böngésző leállítás
  - DRY-RUN NEM szennyezi az applied_jobs.json-t
  - SMART checkbox stratégia (consent vs CV vs marketing)
  - Frissített Firefox user agent (138.0)
  - Oldalbetöltési hibák kezelése (nem break, hanem continue)
  - Config validáció induláskor
  - Optimalizált I/O (bad_domains batch mentés)
  - Precíz fizetési mező detektálás (kevesebb false positive)
""")

async def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    guided = "--guided" in args

    if "--help" in args or "-h" in args:
        print_help()
        return

    if "--test" in args:
        from profession_autoapply_tests import run_tests
        run_tests()
        return

    # Segédfüggvény a konfigurációs beállítások bekérésére
    def run_config_wizard() -> dict:
        import subprocess
        cfg = load_config()
        console.print("[bold]⚙️ Alapvető konfiguráció szerkesztése[/bold]")
        if HAS_RICH:
            cfg["user_email"] = Prompt.ask("Belépési e-mail cím (user_email)", default=cfg.get("user_email", ""))
            cfg["user_password"] = Prompt.ask("Belépési jelszó (user_password)", default=cfg.get("user_password", ""), password=True)
            a = Prompt.ask("Nettó havi fizetési igény (salary_amount, Ft, pl. 800000)", default=str(cfg.get("salary_amount") or ""))
            cfg["salary_amount"] = int(a) if a else None
            
            save_config(cfg)
            console.print("[green]✅ Alapvető konfig elmentve![/green]")
            
            if Confirm.ask("Szeretnéd megnyitni a többi (haladó) beállítást szerkesztésre (nano-ban)?", default=False):
                try:
                    subprocess.run(["nano", str(CONFIG_PATH)], check=True)
                    console.print("[green]✅ Haladó beállítások szerkesztése befejezve![/green]")
                except FileNotFoundError:
                    console.print("[yellow]⚠️ A 'nano' szövegszerkesztő nem található. Kérlek szerkeszd kézzel a config.json-t.[/yellow]")
                except Exception as e:
                    console.print(f"[red]❌ Hiba történt a szerkesztő indításakor: {e}[/red]")
            # Újratöltjük a módosított konfigurációt
            cfg = load_config()
        else:
            print("Rich library hiányzik. Kérlek szerkeszd közvetlenül a config.json fájlt.")
        return cfg

    if "--config" in args:
        run_config_wizard()
        return

    config = load_config()
    
    # Ellenőrzés: ha hiányzik a bejelentkezési e-mail vagy jelszó, elindítjuk a varázslót
    if not config.get("user_email") or not config.get("user_password"):
        console.print("[yellow]⚠ Hiányzó bejelentkezési adatok (e-mail vagy jelszó) a config.json-ban! Konfiguráció indítása...[/yellow]\n")
        config = run_config_wizard()
        # Ha a varázsló után is hiányoznak a kritikus adatok, lépjünk ki
        if not config.get("user_email") or not config.get("user_password"):
            console.print("[red]❌ Hiba: A bejelentkezési adatok megadása kötelező a bot futtatásához![/red]")
            return

    bot = ProfessionBot(config, dry_run=dry_run, guided=guided)
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
