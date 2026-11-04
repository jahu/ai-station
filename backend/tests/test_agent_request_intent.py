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


@pytest.mark.parametrize(
    "content",
    [
        "co 15 minut generuj mi zdjęcie gór",
        "Co 15 minut generuj mi zdjecie",
        "Generuj mi zdjęcie gór co 15 minut",
        "Wygeneruj instrumentalną muzykę co 15 minut",
        "Every 15 minutes generate a photograph of mountains",
        "Generate a photograph of mountains every 15 minutes",
        "Please generate an image every hour",
        "Could you generate a photograph every 15 minutes?",
        "Proszę, co 15 minut generuj mi zdjęcie",
        "Codziennie sprawdzaj pogodę",
        "Sprawdzaj cenę bitcoina co 15 minut",
        "Every morning summarize the news",
        "Create a short video every day",
        "Chcę, żebyś co 15 minut generował zdjęcie gór",
    ],
)
def test_direct_recurring_work_requests_authorize_a_disabled_agent_without_agent_keyword(content):
    assert agent_draft_requested({"content": content})


@pytest.mark.parametrize(
    "content",
    [
        '"Co 15 minut generuj mi zdjęcie"',
        "„Co 15 minut generuj mi zdjęcie”",
        "> Co 15 minut generuj mi zdjęcie",
        "`Generate an image every 15 minutes`",
        "Explain how to generate a photograph every 15 minutes",
        "Jak generować zdjęcie co 15 minut?",
        "Czy można generować zdjęcie co 15 minut?",
        "Write a prompt for generating an image every 15 minutes",
        "Napisz skrypt, który generuje zdjęcie co 15 minut",
        'Wygeneruj plakat z napisem "co 15 minut"',
        "Generate a poster saying every 15 minutes",
        "Nie generuj zdjęć co 15 minut",
        "Co 15 minut nie generuj zdjęć",
        "Do not generate an image every 15 minutes",
        "Generate an image, but not every 15 minutes",
        "Generate a photo every 15 minutes, but do not create an agent",
        "Generate a 15-minute film",
        "Co 15 minut?",
    ],
)
def test_duration_quotes_information_and_negated_schedules_do_not_authorize_agents(content):
    assert not agent_draft_requested({"content": content})
