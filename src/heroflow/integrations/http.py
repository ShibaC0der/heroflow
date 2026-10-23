from __future__ import annotations

from typing import Any

import requests

from heroflow.config import HttpConfig


class HttpClient:
    """requests с общими для Jira и Bitbucket заголовками, таймаутом и проверкой TLS."""

    def __init__(self, base_url: str, token: str, http: HttpConfig) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Authorization": f"Bearer {token}"})
        self.session.verify = http.verify
        if http.insecure:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def request(self, method: str, path: str, *, ok: tuple[int, ...] = (), **kwargs: Any) -> requests.Response:
        """Запрос с raise_for_status. Коды из `ok` не считаются ошибкой (например, 409)."""
        kwargs.setdefault("timeout", self.http.timeout_s)
        response = self.session.request(method, f"{self.base_url}{path}", **kwargs)
        if response.status_code not in ok:
            response.raise_for_status()
        return response
