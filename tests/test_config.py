from __future__ import annotations

from pathlib import Path

import pytest

from heroflow.config import BitbucketConfig, HttpConfig


def test_yaml_section_and_env_override(heroflow_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    heroflow_home.mkdir(parents=True)
    (heroflow_home / "config.yaml").write_text(
        "bitbucket:\n  token: from-yaml\n  repo_slug: svc\n  project: PRJ\n  url: https://bb\n"
        "  allowed_comment_authors: [alex]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BB_TOKEN", "from-env")

    config = BitbucketConfig()  # type: ignore[call-arg]

    assert config.token == "from-env"
    assert config.allowed_comment_authors == ["alex"]
    assert config.repo_clone_url == "https://bb/scm/prj/svc.git"


def test_tls_is_verified_by_default() -> None:
    assert HttpConfig().verify is True
    assert HttpConfig(ca_bundle="/etc/ca.pem").verify == "/etc/ca.pem"
    assert HttpConfig(insecure=True).verify is False
