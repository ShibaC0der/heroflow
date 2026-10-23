from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Any

from heroflow.config import BitbucketConfig, HttpConfig
from heroflow.engine.state import PullRequest
from heroflow.integrations.http import HttpClient
from heroflow.ports import PrComment

log = logging.getLogger(__name__)

# Команда для heroflow в начале комментария: "/hf поправь имя метода" или "/heroflow ..."
COMMAND = re.compile(r"^\s*/(?:hf|heroflow)\b[:\s]*", re.IGNORECASE)


def _walk(
    comment: dict[str, Any], anchor: dict[str, Any], resolved: bool
) -> Iterator[tuple[dict[str, Any], dict[str, Any], bool]]:
    """Комментарий и все ответы в его треде. Ответы наследуют якорь и статус треда от корня."""
    yield comment, anchor, resolved
    for reply in comment.get("comments") or []:
        yield from _walk(reply, anchor, resolved)


def parse_comments(activities: list[dict[str, Any]], allowed_authors: list[str]) -> list[PrComment]:
    seen: set[int] = set()
    result: list[PrComment] = []
    for item in activities:
        if item.get("action") != "COMMENTED" or "comment" not in item:
            continue
        root = item["comment"]
        anchor = item.get("commentAnchor") or {}
        if anchor.get("orphaned"):
            continue
        for comment, comment_anchor, resolved in _walk(root, anchor, bool(root.get("threadResolved"))):
            cid = comment["id"]
            if cid in seen or resolved:
                continue
            seen.add(cid)
            text = comment.get("text", "")
            if not COMMAND.match(text):
                continue
            author = (comment.get("author") or {}).get("name", "")
            if allowed_authors and author not in allowed_authors:
                log.warning("Пропускаю /hf-комментарий %s от %s: автора нет в allowed_comment_authors", cid, author)
                continue
            line = comment_anchor.get("line")
            result.append(
                PrComment(
                    id=cid,
                    author=author,
                    text=COMMAND.sub("", text, count=1).strip(),
                    file=comment_anchor.get("path"),
                    line=int(line) if line else None,
                )
            )
    return sorted(result, key=lambda c: c.id)


class BitbucketClient:
    def __init__(self, config: BitbucketConfig, http: HttpConfig) -> None:
        self.config = config
        self.client = HttpClient(config.url, config.token, http)
        self.repo_api = f"/rest/api/latest/projects/{config.project}/repos/{config.repo_slug}"

    def _ref(self, branch: str) -> dict[str, Any]:
        return {
            "id": f"refs/heads/{branch}",
            "repository": {"slug": self.config.repo_slug, "project": {"key": self.config.project}},
        }

    def create_pull_request(self, title: str, from_branch: str, to_branch: str, draft: bool = True) -> PullRequest:
        payload = {
            "title": title,
            "description": "",
            "draft": draft,
            "fromRef": self._ref(from_branch),
            "toRef": self._ref(to_branch),
            "reviewers": [],
        }
        response = self.client.request("POST", f"{self.repo_api}/pull-requests", json=payload, ok=(409,))
        if response.status_code == 409:
            log.info("PR из %s уже существует, ищу его", from_branch)
            existing = self.find_open_pull_request(from_branch)
            if existing is None:
                raise RuntimeError(f"Bitbucket вернул 409, но открытый PR из {from_branch} не найден: {response.text}")
            return existing
        return self._to_pr(response.json())

    def find_open_pull_request(self, from_branch: str) -> PullRequest | None:
        response = self.client.request(
            "GET",
            f"{self.repo_api}/pull-requests",
            params={"at": f"refs/heads/{from_branch}", "direction": "OUTGOING", "state": "OPEN"},
        )
        values = response.json().get("values", [])
        return self._to_pr(values[0]) if values else None

    @staticmethod
    def _to_pr(data: dict[str, Any]) -> PullRequest:
        return PullRequest(id=data["id"], url=data["links"]["self"][0]["href"])

    def _activities(self, pull_request_id: int) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self.client.request(
                "GET",
                f"{self.repo_api}/pull-requests/{pull_request_id}/activities",
                params={"start": start, "limit": 500},
            ).json()
            values.extend(page.get("values", []))
            if page.get("isLastPage", True):
                return values
            start = page["nextPageStart"]

    def heroflow_comments(self, pull_request_id: int) -> list[PrComment]:
        return parse_comments(self._activities(pull_request_id), self.config.allowed_comment_authors)
