from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests


log = logging.getLogger("bot.mediawiki")


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
        if method == "GET":
            resp = self.session.get(self.api_url, params=params, headers=headers, timeout=30)
        else:
            resp = self.session.post(self.api_url, data=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise MediaWikiError(f"MediaWiki API error: {data['error']}")
        return data

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

    def get_page_wikitext(self, title: str) -> tuple[str, int]:
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
        revisions = page.get("revisions") or []
        if not revisions:
            raise MediaWikiError(f"no revisions for {title}")
        rev = revisions[0]
        text = rev["slots"]["main"]["content"]
        return text, int(rev["revid"])

    def get_message_collection(self, group_id: str, lang: str) -> dict[str, Any]:
        data = self._request(
            "GET",
            {
                "action": "query",
                "prop": "messagecollection",
                "mcgroup": group_id,
                "mclanguage": lang,
                "mclimit": "max",
            },
        )
        return data["query"]["messagecollection"]

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
        return int(edit.get("newrevid"))
