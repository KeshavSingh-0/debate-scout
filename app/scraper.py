"""Playwright scraper for opencaselist.com.

Important caveat: opencaselist is a login-gated, client-rendered (JS) site,
and this project had no credentials available to test against the live
DOM while building it. The selectors below are written defensively -- text
and role based rather than brittle CSS classes -- but the first real run
against each section should be treated as a smoke test. If a step fails,
`ScrapeError` carries a screenshot path (saved next to the download dir) so
the actual page can be inspected and the one failing locator fixed, without
having to touch anything else in this module.

Credentials are only ever held in memory for the lifetime of one tournament
run (never written to the database or disk): `OpenCaselistSession` logs in
once, then every team in the run is fetched as a new page/tab inside that
same authenticated browser context, instead of logging in again per team.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

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
        return ""


async def _click_matching_link(page: Page, text: str, download_dir: Path, what: str) -> None:
    candidate = page.get_by_role("link", name=re.compile(re.escape(text), re.IGNORECASE)).first
    try:
        await candidate.click(timeout=NAV_TIMEOUT_MS)
    except Exception:
        try:
            fallback = page.get_by_text(re.compile(re.escape(text), re.IGNORECASE)).first
            await fallback.click(timeout=NAV_TIMEOUT_MS)
        except Exception as exc:
            raise ScrapeError(
                f"Could not find a link/row for {what} ('{text}') on {page.url}.",
                await _screenshot(page, download_dir, f"missing_{what}"),
            ) from exc
    await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)


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
        assert self._context is not None
        page = await self._context.new_page()
        try:
            await page.goto(f"{BASE_URL}/login", timeout=NAV_TIMEOUT_MS)

            try:
                username_field = page.get_by_label(re.compile("username|e-?mail", re.IGNORECASE)).first
                await username_field.fill(self._username, timeout=NAV_TIMEOUT_MS)
            except Exception:
                try:
                    await page.locator(
                        "input[name='username'], input[type='email'], input[type='text']"
                    ).first.fill(self._username, timeout=NAV_TIMEOUT_MS)
                except Exception as exc:
                    raise ScrapeError(
                        "Could not find a username/email field on the opencaselist login page.",
                        await _screenshot(page, self._download_dir, "login_username"),
                    ) from exc

            try:
                password_field = page.get_by_label(re.compile("password", re.IGNORECASE)).first
                await password_field.fill(self._password, timeout=NAV_TIMEOUT_MS)
            except Exception:
                try:
                    await page.locator("input[type='password']").first.fill(
                        self._password, timeout=NAV_TIMEOUT_MS
                    )
                except Exception as exc:
                    raise ScrapeError(
                        "Could not find a password field on the opencaselist login page.",
                        await _screenshot(page, self._download_dir, "login_password"),
                    ) from exc

            try:
                submit = page.get_by_role("button", name=re.compile("log.?in|sign.?in", re.IGNORECASE)).first
                await submit.click(timeout=NAV_TIMEOUT_MS)
            except Exception as exc:
                raise ScrapeError(
                    "Could not find/click the login submit button on opencaselist.",
                    await _screenshot(page, self._download_dir, "login_submit"),
                ) from exc

            await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
            if page.url.rstrip("/").endswith("/login"):
                raise ScrapeError(
                    "Still on the login page after submitting -- check the opencaselist username/password.",
                    await _screenshot(page, self._download_dir, "login_failed"),
                )
        finally:
            await page.close()

    async def scrape_team_aff(
        self, *, caselist_slug: str, school_name: str, team_code: str
    ) -> ScrapedFile:
        assert self._context is not None
        page = await self._context.new_page()
        try:
            await page.goto(f"{BASE_URL}/caselist/{caselist_slug}", timeout=NAV_TIMEOUT_MS)
            await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
            await _click_matching_link(page, school_name, self._download_dir, "school")
            await _click_matching_link(page, team_code, self._download_dir, "team")

            aff_link = page.get_by_role(
                "link", name=re.compile(r"\baff(irmative)?\b(?!.*neg)", re.IGNORECASE)
            ).first
            try:
                async with page.expect_download(timeout=NAV_TIMEOUT_MS) as download_info:
                    await aff_link.click(timeout=NAV_TIMEOUT_MS)
                download = await download_info.value
                team_dir = self._download_dir / re.sub(r"[^\w.-]+", "_", f"{school_name}_{team_code}")
                team_dir.mkdir(parents=True, exist_ok=True)
                local_path = team_dir / download.suggested_filename
                await download.save_as(str(local_path))
                return ScrapedFile(
                    title=download.suggested_filename, source_url=page.url, local_path=str(local_path)
                )
            except Exception as exc:
                raise ScrapeError(
                    f"Found an 'Aff' link for {school_name} {team_code} but couldn't download it "
                    "as a file -- it may open inline instead of downloading, which needs a small "
                    "scraper tweak.",
                    await _screenshot(page, self._download_dir, "download_failed"),
                ) from exc
        finally:
            await page.close()
