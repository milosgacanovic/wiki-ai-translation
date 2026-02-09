from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests


log = logging.getLogger("bot.mediawiki")

TRANSLATIONS_PREFIX = "Translations:"


def parse_translation_unit_title(title: str, source_lang: str) -> str | None:
    if not title.startswith(TRANSLATIONS_PREFIX):
        return None
    rest = title[len(TRANSLATIONS_PREFIX) :]
    parts = rest.split("/")
    if len(parts) < 2:
        return None
    lang = parts[-1]
    unit = parts[-2]
    if lang != source_lang or not unit.isdigit():
        return None
    base = "/".join(parts[:-2]).strip()
    if not base:
        return None
    return base


class MediaWikiError(RuntimeError):
    pass


@dataclass
class MediaWikiClient:
    api_url: str
    user_agent: str
    session: requests.Session

    csrf_token: str | None = None

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {"format": "json", "formatversion": 2, **params}
        headers = {"User-Agent": self.user_agent}
        backoff = 1
        badtoken_retry = False
        for attempt in range(5):
            if method == "GET":
                resp = self.session.get(self.api_url, params=params, headers=headers, timeout=30)
            else:
                resp = self.session.post(self.api_url, data=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" not in data:
                return data
            error = data["error"]
            code = str(error.get("code", ""))
            info = str(error.get("info", ""))
            if code == "badtoken" and method == "POST" and "token" in params and not badtoken_retry:
                badtoken_retry = True
                self.csrf_token = self.get_csrf_token()
                params = {**params, "token": self.csrf_token}
                continue
            if code == "ratelimited" or "rate limit" in info.lower():
                if attempt < 4:
                    log.warning("rate limited; backing off %ss", backoff)
                    import time

                    time.sleep(backoff)
                    backoff *= 2
                    continue
            raise MediaWikiError(f"MediaWiki API error: {error}")
        raise MediaWikiError("MediaWiki API error: exceeded retry attempts")

    def get_login_token(self) -> str:
        data = self._request("GET", {"action": "query", "meta": "tokens", "type": "login"})
        token = data["query"]["tokens"]["logintoken"]
        if not token:
            raise MediaWikiError("login token missing")
        return token

    def login(self, username: str, password: str) -> None:
        token = self.get_login_token()
        data = self._request(
            "POST",
            {
                "action": "login",
                "lgname": username,
                "lgpassword": password,
                "lgtoken": token,
            },
        )
        result = data.get("login", {}).get("result")
        if result != "Success":
            raise MediaWikiError(f"login failed: {result}")
        self.csrf_token = self.get_csrf_token()

    def get_csrf_token(self) -> str:
        data = self._request("GET", {"action": "query", "meta": "tokens"})
        token = data["query"]["tokens"]["csrftoken"]
        if not token:
            raise MediaWikiError("csrf token missing")
        return token

    def recent_changes(self, since: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "action": "query",
            "list": "recentchanges",
            "rcprop": "title|ids|timestamp|user|comment",
            "rclimit": limit,
        }
        if since:
            params["rcstart"] = since
        data = self._request("GET", params)
        return data["query"]["recentchanges"]

    def get_page_wikitext(self, title: str) -> tuple[str, int, str]:
        data = self._request(
            "GET",
            {
                "action": "query",
                "prop": "revisions",
                "titles": title,
                "rvprop": "content|ids",
                "rvslots": "main",
            },
        )
        page = data["query"]["pages"][0]
        normalized_title = page.get("title", title)
        revisions = page.get("revisions") or []
        if not revisions:
            raise MediaWikiError(f"no revisions for {title}")
        rev = revisions[0]
        text = rev["slots"]["main"]["content"]
        return text, int(rev["revid"]), normalized_title

    def get_page_revision_id(self, title: str) -> tuple[int, str]:
        data = self._request(
            "GET",
            {
                "action": "query",
                "prop": "revisions",
                "titles": title,
                "rvprop": "ids",
            },
        )
        page = data["query"]["pages"][0]
        if page.get("missing"):
            raise MediaWikiError(f"page missing: {title}")
        normalized_title = page.get("title", title)
        revisions = page.get("revisions") or []
        if not revisions:
            raise MediaWikiError(f"no revisions for {title}")
        rev = revisions[0]
        return int(rev["revid"]), normalized_title

    def iter_translation_base_titles(
        self, source_lang: str = "en"
    ) -> list[str]:
        titles: set[str] = set()
        apcontinue = None
        while True:
            params = {
                "action": "query",
                "list": "allpages",
                "apnamespace": 1198,
                "aplimit": 200,
            }
            if apcontinue:
                params["apcontinue"] = apcontinue
            data = self._request("GET", params)
            for page in data.get("query", {}).get("allpages", []):
                title = page.get("title", "")
                base = parse_translation_unit_title(title, source_lang)
                if base:
                    titles.add(base)
            apcontinue = data.get("continue", {}).get("apcontinue")
            if not apcontinue:
                break
        return sorted(titles)

    def get_message_collection(self, group_id: str, lang: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        mcoffset = None
        while True:
            params: dict[str, Any] = {
                "action": "query",
                "list": "messagecollection",
                "mcgroup": group_id,
                "mclanguage": lang,
                "mclimit": 5000,
                "mcprop": "definition|translation",
            }
            if mcoffset:
                params["mcoffset"] = mcoffset
            data = self._request("GET", params)
            items.extend(data.get("query", {}).get("messagecollection", []))
            mcoffset = data.get("continue", {}).get("mcoffset")
            if not mcoffset:
                break
        return items

    def site_info(self) -> dict[str, Any]:
        data = self._request("GET", {"action": "query", "meta": "siteinfo", "siprop": "general"})
        return data["query"]["general"]

    def edit(self, title: str, text: str, summary: str, bot: bool = True) -> int:
        if not self.csrf_token:
            raise MediaWikiError("csrf token missing; call login() first")
        data = self._request(
            "POST",
            {
                "action": "edit",
                "title": title,
                "text": text,
                "summary": summary,
                "token": self.csrf_token,
                "bot": 1 if bot else 0,
            },
        )
        edit = data.get("edit", {})
        if edit.get("result") != "Success":
            raise MediaWikiError(f"edit failed: {edit}")
        newrevid = edit.get("newrevid")
        if newrevid is None:
            return 0
        return int(newrevid)

    def list_translation_unit_keys(self, norm_title: str, source_lang: str = "en") -> list[str]:
        key_set: set[str] = set()
        try:
            items = self.get_message_collection(f"page-{norm_title}", source_lang)
            for item in items:
                key = str(item.get("key") or "")
                unit_key = key.split("/")[-1]
                if unit_key.isdigit():
                    key_set.add(unit_key)
        except Exception:
            key_set = set()

        if key_set:
            return sorted(key_set, key=lambda k: int(k))

        apcontinue = None
        prefix = f"{norm_title}/"
        while True:
            params = {
                "action": "query",
                "list": "allpages",
                "apnamespace": 1198,
                "apprefix": prefix,
                "aplimit": 200,
            }
            if apcontinue:
                params["apcontinue"] = apcontinue
            data = self._request("GET", params)
            for page in data.get("query", {}).get("allpages", []):
                title = page.get("title", "")
                if not title.endswith(f"/{source_lang}"):
                    continue
                parts = title.split("/")
                if len(parts) >= 3:
                    key = parts[-2]
                    if key.isdigit():
                        key_set.add(key)
            apcontinue = data.get("continue", {}).get("apcontinue")
            if not apcontinue:
                break
        return sorted(key_set, key=lambda k: int(k))

    def translation_review(self, revision_id: int) -> None:
        if not self.csrf_token:
            raise MediaWikiError("csrf token missing; call login() first")
        data = self._request(
            "POST",
            {
                "action": "translationreview",
                "revision": revision_id,
                "token": self.csrf_token,
            },
        )
        result = data.get("translationreview", {}).get("result")
        if result != "Success":
            raise MediaWikiError(f"translationreview failed: {data}")

    def approve_revision(self, revision_id: int) -> None:
        if not self.csrf_token:
            raise MediaWikiError("csrf token missing; call login() first")
        data = self._request(
            "POST",
            {
                "action": "approve",
                "revid": revision_id,
                "token": self.csrf_token,
            },
        )
        result = data.get("approve", {}).get("result")
        if not result:
            raise MediaWikiError(f"approve failed: {data}")
        result_lower = str(result).lower()
        if "success" not in result_lower and "already approved" not in result_lower:
            raise MediaWikiError(f"approve failed: {data}")

    def all_pages_page(
        self, namespace: int = 0, limit: int = 200, apcontinue: str | None = None
    ) -> tuple[list[str], str | None]:
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": namespace,
            "aplimit": limit,
        }
        if apcontinue:
            params["apcontinue"] = apcontinue
        data = self._request("GET", params)
        titles: list[str] = []
        for page in data.get("query", {}).get("allpages", []):
            title = page.get("title")
            if title:
                titles.append(title)
        next_continue = data.get("continue", {}).get("apcontinue")
        return titles, next_continue
