"""Direct current-turn composition instructions on explicitly selected images."""

import re

from app.chat_pages import _instruction_text


def requested(content):
    text = re.sub(r"\s+", " ", _instruction_text(content)).strip()
    placement = re.match(
        r"^(?:place|put|insert|umieść|umiesc|wstaw)\s+"
        r"(?:(?:the|this|that|a|an|tę|te|tą|ta|tego|ten)\s+){0,2}"
        r"(?:person|woman|man|subject|object|osobę|osobe|kobietę|kobiete|mężczyznę|mezczyzne|obiekt|przedmiot)\b",
        text,
        re.I,
    )
    if placement and re.search(
        r"\b(?:in|into|on|w|do|na)\s+(?:(?:the|this|that|a|an|tej|tę|te|tym|tego)\s+){0,2}"
        r"(?:scene|image|picture|photo|scenę|scene|scenie|zdjęcie|zdjecie|zdjęciu|zdjeciu|obraz|obrazie)\b",
        text,
        re.I,
    ):
        return True
    return bool(
        re.match(
            r"^(?:combine|merge|compose|recompose|połącz|polacz|skomponuj|przekomponuj)\s+"
            r"(?:(?:the|these|those|both|selected|attached|uploaded|te|oba|obie|wybrane|załączone|zalaczone)\s+){0,3}"
            r"(?:images|pictures|photos|references|obrazy|zdjęcia|zdjecia|fotografie)\b",
            text,
            re.I,
        )
    )
