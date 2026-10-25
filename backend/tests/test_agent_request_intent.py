"""Creation authority comes from a current request, never an agent-related topic."""

import pytest
from app.chat_policy import agent_draft_requested


@pytest.mark.parametrize(
    "content",
    [
        "Could you please prepare a custom market monitoring agent?",
        "Chciałabym mieć lokalnego agenta, który podsumowuje wiadomości.",
        "I'd like a fourth weather report agent",
        "Create another report agent",
        "Create a daily summary agent",
        "Create a new stock-price monitoring agent",
        "I want you to prepare an agent that reads CSV files",
        "Czy mógłbyś przygotować lokalnego agenta?",
        "Please create an agent that does not send email",
    ],
)
def test_current_creation_request_accepts_politeness_and_agent_descriptors(content):
    assert agent_draft_requested({"content": content})


@pytest.mark.parametrize(
    "content",
    [
        "I would like information on agents",
        "Chciałbym opis agenta",
        "Create a description of an agent",
        "Write a prompt for an agent",
        "Create a list of agents",
        "Prepare a tutorial about agents",
        "Create agent instructions",
        "Could you explain how to prepare an agent?",
        "Chciałbym wiedzieć jak stworzyć agenta",
        '"Create an agent"',
        "> Stwórz agenta",
        "I want you not to create an agent",
    ],
)
def test_information_negation_and_quotes_do_not_grant_creation_authority(content):
    assert not agent_draft_requested({"content": content})
