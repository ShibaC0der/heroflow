import jira


def add_sdd_label(data: dict):
    issue_key = data["issue_key"]

    jira.add_label(issue_key, "SDD")
