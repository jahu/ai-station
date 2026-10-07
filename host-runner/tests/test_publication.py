import pytest
from ai_station_runner.gitops import GitError
from ai_station_runner.publication import github_repository


@pytest.mark.parametrize(
    "url",
    ["https://github.com/owner/repo.git", "git@github.com:owner/repo.git", "https://github.com/owner/repo"],
)
def test_publication_normalizes_only_explicit_github_origins(url):
    assert github_repository(url) == "owner/repo"


@pytest.mark.parametrize(
    "url",
    [
        "https://token@github.com/owner/repo",
        "https://github.com.evil.invalid/owner/repo",
        "https://github.com/owner/repo?token=secret",
        "http://github.com/owner/repo",
        "/tmp/repository",
        "file:///tmp/repository",
        "ssh://other.invalid/owner/repo",
        "git@github.com:owner/..",
        "https://github.com/owner/repo\nhttps://other.invalid/owner/repo",
    ],
)
def test_publication_rejects_credentials_local_paths_and_other_hosts(url):
    with pytest.raises(GitError):
        github_repository(url)
