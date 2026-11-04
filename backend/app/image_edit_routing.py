"""Bounded explicit edit intent; model selection grants no new capability."""

import re
import unicodedata

VERSION = "structural-edit-v1"
_ACTIONS = (
    (
        "object_removal",
        re.compile(r"\b(?:remove|erase|delete|wyjmij|usun(?:ac)?|wymaz(?:ac)?|pozbadz sie|get rid of)\b"),
    ),
    (
        "pose",
        re.compile(
            r"\b(?:change|adjust|alter|zmien(?:ic)?)\s+(?:(?:the|their|her|his|jego|jej)\s+)?(?:pose|posture|position|orientation|poze|pozycje|ulozenie|orientacje)\b"
        ),
    ),
    (
        "pose",
        re.compile(
            r"\b(?:make|have|show|put|pose|change|zmien(?:ic)?|ustaw|pokaz|obroc|posadz)\b.{0,100}?\b(?:sit(?:ting)?|seated|stand(?:ing)?|kneel(?:ing)?|lying|lie down|siedz\w*|stoj\w*|klek\w*|lez\w*)\b"
        ),
    ),
    (
        "pose",
        re.compile(
            r"\b(?:move|raise|lower|rotate|turn|przesun|podnies|opusc|obroc)\b.{0,60}?\b(?:hand|arm|leg|head|body|face|person|bicycle|reke|rece|ramie|noge|nogi|glowe|cialo|twarz|osobe|rower)\b"
        ),
    ),
)
_NEGATION = re.compile(
    r"\b(?:do not|dont|don't|never|avoid|without|not|nie|bez|unikaj|nie nalezy|no need to)(?:\s+\w+){0,2}\s*$"
)


def structural_intent(prompt):
    text = re.sub(r"(?ms)^\s*>.*?$|```.*?(?:```|\Z)", " ", prompt[:10000])
    text = re.sub(r'"[^"\n]*"|„[^”\n]*”|“[^”\n]*”|`[^`\n]*`', " ", text)
    text = re.sub(r"(?<!\w)'[^'\n]*'(?!\w)", " ", text)
    text = "".join(
        c
        for c in unicodedata.normalize("NFKD", text.lower().replace("ł", "l"))
        if not unicodedata.combining(c)
    )
    for clause in re.split(r"[.;!?\n]|\b(?:and|but|oraz|ale)\b", text):
        for reason, pattern in _ACTIONS:
            for match in pattern.finditer(clause):
                if reason == "object_removal" and re.match(
                    r"\s+(?:the\s+)?(?:blur|noise|grain|artifacts|rozmycie|szum|ziarno|artefakty)\b",
                    clause[match.end() :],
                ):
                    continue
                if not _NEGATION.search(clause[max(0, match.start() - 80) : match.start()]):
                    return reason
    return None
