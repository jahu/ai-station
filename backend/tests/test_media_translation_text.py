import json

import pytest
from app.media_translation_text import decode_fields, encode_fields


def test_polish_descriptions_keep_quotes_names_weights_triggers_and_numbers():
    source = {
        "prompt": "Jan Kowalski, portret w stylu ACME, napis „Dzień dobry”, 768x1024, <lora:brand:0.8> (red dress:1.2) brand_trigger",
        "negative": 'bez napisu "Nie zmieniaj mnie" i bez rozmycia',
    }
    encoded, tokens = encode_fields(source, ["Jan Kowalski"])
    assert "Jan Kowalski" not in encoded["prompt"]
    assert "768" not in encoded["prompt"] and "1024" not in encoded["prompt"]
    response = {
        "prompt": encoded["prompt"]
        .replace("portret w stylu", "portrait in the style of")
        .replace("napis", "text"),
        "negative": encoded["negative"]
        .replace("bez napisu", "without text")
        .replace("i bez rozmycia", "and without blur"),
    }
    result = decode_fields(json.dumps(response), source, tokens)
    assert result["prompt"] == source["prompt"].replace(
        "portret w stylu", "portrait in the style of"
    ).replace("napis", "text")
    assert '"Nie zmieniaj mnie"' in result["negative"]
    assert "without blur" in result["negative"]


@pytest.mark.parametrize("change", ["missing", "duplicate", "invented", "cross_field"])
def test_translation_fails_closed_for_changed_placeholder_scope(change):
    source = {"prompt": 'napis "Polski tekst"', "negative": "bez 2 osób"}
    encoded, tokens = encode_fields(source)
    marker = next(iter(tokens["prompt"]))
    value = encoded["prompt"]
    encoded["prompt"] = {
        "missing": value.replace(marker, ""),
        "duplicate": value + marker,
        "invented": value + "__AIS_TRANSLATE_new_1__",
        "cross_field": value.replace(marker, next(iter(tokens["negative"]))),
    }[change]
    with pytest.raises(ValueError, match="protected text"):
        decode_fields(json.dumps(encoded), source, tokens)


def test_already_english_roundtrip_preserves_exact_text_and_model_tokens():
    source = {"prompt": 'A portrait of Ada with "Dzień dobry", Qwen, photo.png and 2 references'}
    encoded, tokens = encode_fields(source)
    assert decode_fields(json.dumps(encoded), source, tokens) == source


@pytest.mark.parametrize(
    "value", ["not json", "[]", '{"unexpected":"field"}', '{"prompt":""}', '{"prompt":2}']
)
def test_invalid_translation_response_is_not_a_success(value):
    source = {"prompt": "czerwony rower"}
    _, tokens = encode_fields(source)
    with pytest.raises(ValueError):
        decode_fields(value, source, tokens)


def test_excessive_tokens_and_reserved_markers_fail_before_inference():
    with pytest.raises(ValueError, match="Too many protected"):
        encode_fields({"prompt": "1 " * 300})
    with pytest.raises(ValueError, match="reserved marker"):
        encode_fields({"prompt": "__AIS_TRANSLATE_fake_1__"})


def test_duplicate_json_fields_and_missing_single_quote_tokens_are_rejected():
    original = {"prompt": "napis 'Dzień dobry'"}
    encoded, tokens = encode_fields(original)
    assert "Dzień dobry" not in encoded["prompt"]
    assert decode_fields(json.dumps(encoded), original, tokens) == original
    with pytest.raises(ValueError, match="valid JSON"):
        decode_fields('{"prompt":"one","prompt":"two"}', original, tokens)


def test_long_multiline_quoted_image_text_is_protected_as_one_literal():
    literal = '"' + "Polski tekst\n" * 220 + '"'
    original = {"prompt": "napis " + literal}
    encoded, tokens = encode_fields(original)
    assert len(tokens["prompt"]) == 1
    assert literal not in encoded["prompt"]
    reply = {"prompt": encoded["prompt"].replace("napis", "text")}
    assert decode_fields(json.dumps(reply), original, tokens) == {"prompt": "text " + literal}


def test_scene_preparation_explicitly_expands_fields_while_other_consumers_keep_their_bound():
    fields = {f"cue_{i}": "A bell" for i in range(18)}
    with pytest.raises(ValueError):
        encode_fields(fields)
    encoded, tokens = encode_fields(fields, max_fields=18)
    assert decode_fields(json.dumps(encoded), fields, tokens) == fields
    with pytest.raises(ValueError):
        encode_fields({**fields, "unexpected": "Extra"}, max_fields=18)
