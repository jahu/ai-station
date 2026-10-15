"""Source inventory excludes only reserved untracked execution work directories."""


def source_file_args(*, cached=False):
    return [
        "ls-files",
        *(["--cached"] if cached else []),
        "--others",
        "--exclude-standard",
        "--exclude=/.ai-station-validation-*/",
        "--exclude=/.ai-station-dependencies-*/",
        "-z",
    ]
