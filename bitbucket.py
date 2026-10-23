import json

import requests

from config import BitbucketConfig, get_config


def create_pull_request(
        title: str,
        from_ref: str,
        to_ref: str = "refs/heads/master",
        draft: bool = True,
        config: BitbucketConfig | None = None,
):
    config = config or get_config().bitbucket

    url = f"{config.url}/rest/api/latest/projects/{config.project}/repos/{config.repo_slug}/pull-requests"

    payload = {
        "title": title,
        "description": "",
        "state": "OPEN",
        "open": True,
        "closed": False,
        "draft": draft,
        "fromRef": {
            "id": from_ref,
            "repository": {
                "slug": config.repo_slug,
                "project": {
                    "key": config.project
                }
            }
        },
        "toRef": {
            "id": to_ref,
            "repository": {
                "slug": config.repo_slug,
                "project": {
                    "key": config.project
                }
            }
        },
        "locked": False,
        "reviewers": []
    }

    response = requests.request(
        "POST",
        url,
        json=payload,
        headers=_headers(config.token),
        verify=False
    )

    response_json = json.loads(response.text)

    return {
        "id": response_json["id"],
        "url": response_json["links"]["self"][0]["href"]
    }


def get_pr_comments_md(pull_request_id: int) -> str:
    if not pull_request_id:
        return ""

    comments = get_pr_comments(pull_request_id)

    if not comments:
        return ""

    md_builder = []

    for comment in comments:
        comment_text = comment["text"]
        if "anchor" in comment:
            file = comment["anchor"]["file"]
            line = comment["anchor"]["line"]
            md_builder.append(f"- {comment_text}. Файл: {file}:{line}")
        else:
            md_builder.append(f"- {comment_text}")

    return "\n".join(md_builder)


def get_pr_comments(
        pull_request_id: int,
        config: BitbucketConfig | None = None,
) -> list[dict]:
    config = config or get_config().bitbucket

    url = f"{config.url}/rest/api/1.0/projects/{config.project}/repos/{config.repo_slug}/pull-requests/{pull_request_id}/activities?limit=1000"

    response = requests.request(
        "GET",
        url,
        headers=_headers(config.token),
        verify=False
    ).json()

    comments = []
    for item in response.get("values", []):
        if item["action"] == "COMMENTED":
            if _is_valid_heroflow_comment(item):
                comment = {"text": item["comment"]["text"].replace("/heroflow", "").replace("/hf", "").strip()}
                if "commentAnchor" in item:
                    comment["anchor"] = {
                        "file": item["commentAnchor"]["path"],
                        "line": item["commentAnchor"].get("line", ""),
                    }
                comments.append(comment)

    return comments


def _is_valid_heroflow_comment(item: dict) -> bool:
    comment_data = item.get("comment", {})
    anchor_data = item.get("commentAnchor", {})
    comment_text = comment_data.get("text", "")
    return (
            ("/heroflow" in comment_text or "/hf" in comment_text)
            and item.get("action") == "COMMENTED"
            and item.get("commentAction") == "ADDED"
            and not comment_data.get("threadResolved")
            and not anchor_data.get("orphaned")
    )


def _headers(token: str) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
