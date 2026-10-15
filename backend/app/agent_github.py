"""Reviewed agent repository scopes; never follow a connector to a new target."""

from app.models import Connector


def reviewed_connector(session, scope):
    if scope is None:
        raise ValueError("Choose a GitHub repository before enabling this tool")
    row = session.get(Connector, str(scope.connector_id), populate_existing=True)
    if row is None or row.kind != "github" or not row.enabled:
        raise ValueError("The reviewed GitHub connector is unavailable; inspect the definition")
    if row.config_json.get("repository") != scope.repository:
        raise ValueError("GitHub repository changed; review and select the target again")
    return row


def report_context(snapshot):
    """Keep full provenance in the artifact, with a bounded local-model excerpt."""
    return {
        "repository": snapshot["repository"],
        "repository_url": snapshot["project"]["url"],
        "snapshot_limit_per_list": 30,
        "context_limit_per_list": 10,
        "captured_at": snapshot["captured_at"],
        "untrusted": True,
        "bounded": True,
        "listed_counts": {key: len(snapshot[key]) for key in ("issues", "pull_requests")},
        "context_excerpted": any(
            len(snapshot[key]) > 10 or any(len(item["title"]) > 180 for item in snapshot[key])
            for key in ("issues", "pull_requests")
        ),
        **{
            key: [
                {"number": item["number"], "title": item["title"][:180], "url": item["url"]}
                for item in snapshot[key][:10]
            ]
            for key in ("issues", "pull_requests")
        },
    }
