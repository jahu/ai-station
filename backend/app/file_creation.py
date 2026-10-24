"""Deterministic current-instruction selection for bounded local file creation."""

import re


def requested(content, *, agent=False):
    from app.conversation_data_reference import instruction
    from app.conversation_data_reference import requested as refers_to_data
    from app.http_fetch import prompt_public_urls

    text = instruction(content)
    if not text or prompt_public_urls(text) or refers_to_data(content):
        return False
    if re.search(
        r"\b(?:analy[sz](?:e|es|ing)|przeanalizuj|uploaded|existing|attached|załączon\w*|zalaczon\w*|istniej\w*)\b",
        text,
        re.I,
    ):
        return False
    if re.search(
        r"\b(?:from|using|z|na podstawie)\b.{0,50}\b(?:files?|data|csv|xlsx|sources?|stron\w*|plik\w*|dany\w*|arkusz\w*)\b",
        text,
        re.I,
    ):
        return False
    if re.search(
        r"\b(?:current|live|latest|aktualn\w*|najnowsz\w*)\b.{0,35}\b(?:prices?|rates?|news|cen\w*|kurs\w*|notowa\w*)\b",
        text,
        re.I,
    ):
        return False
    verb = r"(?:creat(?:e|es|ing)|generat(?:e|es|ing)|make|write|build|stw[oó]rz|utw[oó]rz|wygeneruj|zr[oó]b|tworzy|tworzy[łl]|generuje)"
    target = r"(?:xlsx|csv|excel|spreadsheet|workbook|arkusz\w*|text file|plik(?:u)? tekstow\w*)"
    prefix = (
        ""
        if agent
        else r"^(?:(?:please|now|then|and|proszę|prosze|teraz)\s+){0,3}(?:(?:can|could|would) you\s+)?"
    )
    modifiers = r"(?:(?:a|an|the|new|blank|sample|example|empty|me|mi|nowy|nową|nowe|pusty|przykładowy|plik|file)\s+){0,6}"
    return bool(re.search(prefix + rf"\b{verb}\s+{modifiers}{target}\b", text, re.I))


def prepare_turn(body, mode):
    if mode not in {"chat", "work", "orchestrator"} or body.action != "auto" or body.data is not None:
        return body
    if (
        any(
            getattr(body, key, None)
            for key in (
                "attachments",
                "image_artifact_ids",
                "audio_artifact_id",
                "speech_text",
                "music",
                "media",
                "github",
                "coding",
                "new_project",
                "project_defaults",
                "continuation",
                "commit",
                "publish",
                "load",
                "stop",
                "upscale_result",
            )
        )
        or body.web_search.query.strip()
        or body.web_search.render_pages
    ):
        return body
    if not requested(body.content):
        return body
    from app.conversation_data import prepare_turn as prepare_data
    from app.conversation_data_schema import DataScope

    return prepare_data(body.model_copy(update={"data": DataScope(operation="create")}))
