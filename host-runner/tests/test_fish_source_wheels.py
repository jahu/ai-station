from copy import deepcopy

import pytest
from ai_station_runner import fish_source_wheels as build


def recipe():
    return {
        "inputs": [{"kind": "sdist", "name": name, **value} for name, value in build.SOURCES.items()],
        "derived_wheels": deepcopy(build.WHEELS),
    }


def test_fixed_profile_carries_all_and_only_the_reviewed_source_dependencies():
    assert set(build.validate(recipe())) == {"antlr4-python3-runtime", "argbind", "randomname"}


@pytest.mark.parametrize(
    "field,value",
    [("version", "newest"), ("sha256", "0" * 64), ("size_bytes", 1), ("filename", "../source.tar.gz")],
)
def test_changed_source_is_rejected_before_any_process_is_started(field, value):
    frozen = recipe()
    frozen["inputs"][1][field] = value
    with pytest.raises(ValueError, match="source dependency changed"):
        build.validate(frozen)


@pytest.mark.parametrize("action", ["extra", "missing", "duplicate", "unknown"])
def test_recipe_cannot_expand_the_package_build_capability(action):
    frozen = recipe()
    if action == "extra":
        frozen["inputs"].append({"kind": "sdist", "name": "unreviewed"})
    elif action == "missing":
        frozen["inputs"].pop()
    elif action == "duplicate":
        frozen["inputs"][1] = frozen["inputs"][0]
    else:
        frozen["inputs"][1]["name"] = "unreviewed"
    with pytest.raises(ValueError, match="three reviewed"):
        build.validate(frozen)


@pytest.mark.parametrize(
    "field,value", [("filename", "../outside.whl"), ("sha256", "0" * 64), ("size_bytes", 1)]
)
def test_caller_cannot_change_the_expected_built_payload(field, value):
    frozen = recipe()
    frozen["derived_wheels"]["argbind"][field] = value
    with pytest.raises(ValueError, match="reproduced Fish wheels"):
        build.validate(frozen)


def test_preparation_cancellation_before_extra_source_starts(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        build.avatar_source_wheel, "build", lambda *a, **kw: calls.append(kw["python_version"]) or []
    )

    def canceled():
        raise RuntimeError("owned setup stopped")

    with pytest.raises(RuntimeError, match="stopped"):
        build.build(
            "/fixed/python",
            tmp_path,
            recipe(),
            {},
            check=canceled,
            run_command=lambda *a, **kw: pytest.fail("process started"),
        )
    assert calls == [(3, 12, 14)]
