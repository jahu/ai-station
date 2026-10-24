"""Database-only lifecycle mutations shared by UI and conversation controls."""

from app.db import utcnow


def pause_agent(session, agent):
    from app.agent_report_email import revoke as revoke_report_email
    from app.market_email import revoke

    revoke(session, agent.id)
    revoke_report_email(session, agent.id)
    agent.enabled = False
    agent.next_run_at = None
    agent.updated_at = utcnow()
