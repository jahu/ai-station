import json

import pytest
from app.account_credentials import make_password_record, password_matches, username_identity
from app.operator_auth import digest


def test_existing_operator_password_hash_is_accepted_without_password_migration():
    password = "synthetic legacy password"
    salt = b"0123456789abcdef"
    record = {
        "algorithm": "pbkdf2-sha256",
        "salt": salt.hex(),
        "hash": digest(password, salt),
        "iterations": 600_000,
    }
    assert password_matches(record, password)
    assert not password_matches(record, "other password")


def test_new_credentials_are_salted_and_plaintext_is_never_stored():
    password = "synthetic new password"
    first, second = make_password_record(password), make_password_record(password)
    assert first != second and password_matches(first, password) and password_matches(second, password)
    assert password not in json.dumps(first) and first["iterations"] == 600_000


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"algorithm": "other"},
        {"algorithm": "pbkdf2-sha256", "salt": "bad", "hash": []},
        {"algorithm": "pbkdf2-sha256", "salt": "00" * 16, "hash": "00" * 32, "iterations": 10**20},
    ],
)
def test_invalid_records_fail_closed_without_unbounded_hash_work(record):
    assert not password_matches(record, "synthetic new password")


@pytest.mark.parametrize("password", ["short", "x" * 201])
def test_password_creation_bounds_are_enforced_without_echoing_input(password):
    with pytest.raises(ValueError, match="between 12 and 200"):
        make_password_record(password)


@pytest.mark.parametrize(
    "first,second",
    [("Admin", "ADMIN"), ("Straße", "STRASSE"), ("Ｋowalski", "Kowalski"), ("Łukasz", "łukasz")],
)
def test_case_and_normalization_cannot_create_duplicate_login_identities(first, second):
    assert username_identity(first)[1] == username_identity(second)[1]


@pytest.mark.parametrize("value", ["", "a", "a/b", "a\\b", "first last", "admin\x00test", "x" * 65, ".."])
def test_invalid_usernames_cannot_be_used_as_path_like_or_ambiguous_identifiers(value):
    with pytest.raises(ValueError):
        username_identity(value)
