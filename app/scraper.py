"""Playwright scraper for opencaselist.com.

Most of this is now ground-truthed against real saved pages from the site
(caselist listing, school page, team page), not guessed:
  - Caselist URLs have NO "/caselist/" prefix: https://opencaselist.com/{slug}
    (e.g. /ndtceda26, /hspolicy26), and a school page is {slug}/{SchoolName}.
  - A team's link text on its school page is
    "{School} {opencaselist team code} ({Debater One} - {Debater Two})" --
    opencaselist's own team code does NOT match a tournament's entry code
    for the same team (see pairing_parser.py), so teams are matched by
    debater last names instead, which appear in both systems.
  - A team page is a table of rounds (Tournament, Round, Side, Opponent,
    Judge, ...), not a single "Aff file" link. Each row has a Side cell
    ("Aff"/"Neg"), a JS-driven download icon (svg[data-testid="download"])
    that triggers a real browser download, and a separate, directly
    navigable "Preview" link (<a href="https://opencaselist.com/preview?
    path=...">, svg[data-testid="preview"]) that's kept as the result's
    source_url so a person can open it to sanity-check the pick.

  - The login form is also ground-truthed, from a saved copy of the logged-
    out homepage: there is no separate /login route. The root URL itself
    renders a Tabroom.com username/password form (#username, #password,
    a submit button literally labeled "Login" that starts disabled until
    both fields have a value) when logged out, and the caselist chooser
    with a "Logout" link when logged in -- same URL, auth-dependent
    content, which is also how `_login` below checks success.

If a step still fails, `ScrapeError` carries a screenshot path (saved next
to the download dir) for a quick look at the real markup at that point.

Credentials are only ever held in memory for the lifetime of one tournament
run (never written to the database or disk): `OpenCaselistSession` logs in
once, then every team in the run is fetched as a new page/tab inside that
same authenticated browser context, instead of logging in again per team.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

BASE_URL = "https://opencaselist.com"
NAV_TIMEOUT_MS = 20_000


class ScrapeError(Exception):
    def __init__(self, message: str, screenshot_path: str | None = None):
        super().__init__(message)
        self.screenshot_path = screenshot_path


@dataclass
class ScrapedFile:
    title: str
    source_url: str
    local_path: str


async def _screenshot(page: Page, download_dir: Path, tag: str) -> str:
    path = download_dir / f"error_{tag}.png"
    try:
        await page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        logger.debug("Could not save a debug screenshot to %s", path, exc_info=True)
        return ""


async def _fail(message: str, page: Page, download_dir: Path, tag: str, cause: Exception | None = None) -> None:
    """Logs the failure (with the page's current URL for context) and
    raises ScrapeError with a debug screenshot path attached."""
    screenshot = await _screenshot(page, download_dir, tag)
    logger.error("%s (page: %s, screenshot: %s)", message, page.url, screenshot or "not saved")
    if cause is not None:
        raise ScrapeError(message, screenshot) from cause
    raise ScrapeError(message, screenshot)


async def _click_matching_link(page: Page, text: str, download_dir: Path, what: str) -> None:
    logger.debug("Looking for a %s link matching %r on %s", what, text, page.url)
    candidate = page.get_by_role("link", name=re.compile(re.escape(text), re.IGNORECASE)).first
    try:
        await candidate.click(timeout=NAV_TIMEOUT_MS)
    except Exception:
        try:
            fallback = page.get_by_text(re.compile(re.escape(text), re.IGNORECASE)).first
            await fallback.click(timeout=NAV_TIMEOUT_MS)
        except Exception as exc:
            await _fail(
                f"Could not find a link/row for {what} ('{text}') on {page.url}.",
                page,
                download_dir,
                f"missing_{what}",
                exc,
            )
    await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    logger.debug("Clicked %s link matching %r, now on %s", what, text, page.url)


class OpenCaselistSession:
    """Async context manager: logs in once, then exposes scrape_team_aff()
    for each team, reusing the same authenticated browser context."""

    def __init__(self, username: str, password: str, download_dir: Path):
        self._username = username
        self._password = password
        self._download_dir = download_dir
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "OpenCaselistSession":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(accept_downloads=True)
        await self._login()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _login(self) -> None:
        """Ground-truthed against a real saved copy of the logged-out
        homepage: there is no separate /login route -- the login form (a
        Tabroom.com username/password, since opencaselist delegates auth to
        Tabroom) is rendered at the root URL itself, and the same root URL
        renders the caselist chooser with a "Logout" link once authenticated."""
        assert self._context is not None
        page = await self._context.new_page()
        try:
            logger.info("Navigating to opencaselist homepage")
            await page.goto(f"{BASE_URL}/", timeout=NAV_TIMEOUT_MS)

            try:
                await page.locator("#username").fill(self._username, timeout=NAV_TIMEOUT_MS)
                logger.debug("Filled #username field")
            except Exception as exc:
                await _fail(
                    "Could not find the username field on the opencaselist homepage.",
                    page,
                    self._download_dir,
                    "login_username",
                    exc,
                )

            try:
                await page.locator("#password").fill(self._password, timeout=NAV_TIMEOUT_MS)
                logger.debug("Filled #password field")
            except Exception as exc:
                await _fail(
                    "Could not find the password field on the opencaselist homepage.",
                    page,
                    self._download_dir,
                    "login_password",
                    exc,
                )

            try:
                # The submit button starts disabled until both fields have a
                # value; Playwright's click() auto-waits for it to become
                # actionable (enabled) rather than failing immediately.
                submit = page.get_by_role("button", name="Login", exact=True).first
                await submit.click(timeout=NAV_TIMEOUT_MS)
                logger.debug("Clicked Login button")
            except Exception as exc:
                await _fail(
                    "Could not find/click the Login button on opencaselist.",
                    page,
                    self._download_dir,
                    "login_submit",
                    exc,
                )

            await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
            try:
                await page.get_by_role("link", name="Logout", exact=True).wait_for(timeout=NAV_TIMEOUT_MS)
                logger.info("Login confirmed (Logout link present)")
            except Exception as exc:
                toast_text = ""
                try:
                    toast_text = (await page.locator(".Toastify").inner_text(timeout=1000)).strip()
                except Exception:
                    logger.debug("No Toastify error text found after failed login")
                detail = "Login did not succeed -- check the opencaselist/Tabroom username and password."
                if toast_text:
                    detail += f" Site said: {toast_text}"
                await _fail(detail, page, self._download_dir, "login_failed", exc)
        finally:
            await page.close()

    async def _find_team_link(self, page: Page, school_name: str, team_code: str, debaters: list[str]):
        """Team link text looks like "Kentucky CoVi (Camden Coale -
        Isabella Villarreal)". opencaselist's own team code in that text
        doesn't match a tournament's entry code for the same team, so this
        matches on debater last names when available, falling back to the
        (less reliable) team_code substring otherwise."""
        candidates = page.get_by_role("link")
        count = await candidates.count()
        for i in range(count):
            candidate = candidates.nth(i)
            text = (await candidate.inner_text()).strip()
            if not text:
                continue
            if debaters:
                if all(name.lower() in text.lower() for name in debaters):
                    return candidate
            elif team_code.lower() in text.lower():
                return candidate
        return None

    async def scrape_team_aff(
        self, *, caselist_slug: str, school_name: str, team_code: str, debaters: list[str]
    ) -> ScrapedFile:
        assert self._context is not None
        label = f"{school_name} {team_code}"
        page = await self._context.new_page()
        try:
            logger.debug("[%s] Navigating to caselist %s", label, caselist_slug)
            await page.goto(f"{BASE_URL}/{caselist_slug}", timeout=NAV_TIMEOUT_MS)
            await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
            await _click_matching_link(page, school_name, self._download_dir, "school")

            who = " & ".join(debaters) if debaters else team_code
            logger.debug("[%s] Looking for a team link matching debaters: %s", label, who)
            team_link = await self._find_team_link(page, school_name, team_code, debaters)
            if team_link is None:
                await _fail(
                    f"Could not find a team matching {who} on {school_name}'s opencaselist page.",
                    page,
                    self._download_dir,
                    "missing_team",
                )
            await team_link.click(timeout=NAV_TIMEOUT_MS)
            await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
            logger.debug("[%s] On team page: %s", label, page.url)

            # The team page has an "All / Aff / Neg" filter; following the "Aff"
            # filter link (rather than searching row text for "Aff") avoids
            # colliding with that filter tab itself, which is also literally
            # labeled "Aff" and would otherwise be the first match.
            try:
                aff_filter = page.get_by_role("link", name="Aff", exact=True).first
                await aff_filter.click(timeout=NAV_TIMEOUT_MS)
                await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
                logger.debug("[%s] Filtered to Aff rounds: %s", label, page.url)
            except Exception as exc:
                await _fail(
                    f"Could not find the 'Aff' filter on {school_name} {team_code}'s opencaselist page.",
                    page,
                    self._download_dir,
                    "missing_aff_filter",
                    exc,
                )

            # Scoped to tbody, not thead, so this is a data row -- the header
            # row also carries role="row".
            rows = page.locator("tbody[role='rowgroup'] tr[role='row']")
            row_count = await rows.count()
            logger.debug("[%s] Found %d Aff round row(s)", label, row_count)
            if row_count == 0:
                await _fail(
                    f"{school_name} {team_code} has no rounds marked 'Aff' on opencaselist -- "
                    "they may not have posted an affirmative yet.",
                    page,
                    self._download_dir,
                    "no_aff_rounds",
                )
            row = rows.first

            source_url = page.url
            try:
                preview_href = await row.get_by_test_id("preview").locator("xpath=ancestor::a[1]").get_attribute(
                    "href", timeout=NAV_TIMEOUT_MS
                )
                if preview_href:
                    source_url = preview_href
            except Exception:
                logger.debug("[%s] No Preview link found on the Aff row; using the team page as source_url", label)

            try:
                title_cells = row.locator("td")
                tournament_text = (await title_cells.nth(0).inner_text()).strip()
                round_text = (await title_cells.nth(1).inner_text()).strip()
                title = f"{tournament_text} {round_text}".strip() or f"{school_name} {team_code} aff"
            except Exception:
                logger.debug("[%s] Could not read tournament/round cells for a title", label, exc_info=True)
                title = f"{school_name} {team_code} aff"
            logger.debug("[%s] Picked round %r, source_url=%s", label, title, source_url)

            try:
                download_icon = row.get_by_test_id("download")
                async with page.expect_download(timeout=NAV_TIMEOUT_MS) as download_info:
                    await download_icon.click(timeout=NAV_TIMEOUT_MS)
                download = await download_info.value
                team_dir = self._download_dir / re.sub(r"[^\w.-]+", "_", f"{school_name}_{team_code}")
                team_dir.mkdir(parents=True, exist_ok=True)
                local_path = team_dir / download.suggested_filename
                await download.save_as(str(local_path))
                logger.debug("[%s] Downloaded %r to %s", label, download.suggested_filename, local_path)
                return ScrapedFile(title=title, source_url=source_url, local_path=str(local_path))
            except Exception as exc:
                await _fail(
                    f"Found an 'Aff' round for {school_name} {team_code} but couldn't download its "
                    "file -- the download icon's behavior may have changed and needs a scraper tweak.",
                    page,
                    self._download_dir,
                    "download_failed",
                    exc,
                )
                raise  # unreachable; _fail always raises, this satisfies static analysis
        finally:
            await page.close()
