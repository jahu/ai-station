import pytest
from app.coding_output import STATIC_SITE, output_check, validation_contract, website_output
from app.runs import create_run, create_task


@pytest.mark.parametrize(
    "goal",
    [
        "Build a new weather website from the reviewed URL",
        "Create a self-contained HTML/CSS page",
        "Odczytaj publiczną stronę i lokalnie zbuduj jej własną nową wersję HTML/CSS",
        "Stwórz nową stronę internetową",
    ],
)
def test_reviewed_website_construction_has_a_static_output_expectation(goal):
    assert website_output(goal) == STATIC_SITE


@pytest.mark.parametrize(
    "goal",
    [
        "Analyze this website",
        "Read a CSV with Python",
        "Build a command line calculator",
        "Create a JSON API",
    ],
)
def test_other_project_work_does_not_require_a_website_archive(goal):
    assert website_output(goal) is None


@pytest.mark.parametrize(
    "files,ok", [(None, False), (set(), False), ({"app.js"}, False), ({"index.html"}, True)]
)
def test_website_output_check_requires_a_verified_entrypoint(files, ok):
    result = output_check(STATIC_SITE, files)
    assert result["succeeded"] is ok and result["source"] == "control_plane"
    assert bool(result["error"]) is not ok
    assert output_check(None, files) is None


def test_validation_expectation_is_bound_to_the_exact_coding_source(session):
    task = create_task(session, title="Website", prompt="Build a website", capability="coding.local")
    source = create_run(
        session,
        task,
        run_type="coding",
        capability="coding.local",
        executor_type="local_proposal",
        parameters={"output_contract": STATIC_SITE},
    )
    validation = create_run(
        session,
        task,
        run_type="validation",
        capability="coding.validate",
        executor_type="project_validation",
        parent_run_id=source.id,
        parameters={"output_contract": STATIC_SITE},
    )
    assert validation_contract(session, validation) == STATIC_SITE
    validation.parameters = {}
    with pytest.raises(ValueError, match="coding source"):
        validation_contract(session, validation)
