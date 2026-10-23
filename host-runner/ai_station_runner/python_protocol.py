"""Fixed bounded protocol for the optional local Python workload image."""

MAX_SCRIPT = 128 * 1024
MAX_INPUT = 16 * 1024 * 1024
MAX_INPUT_TOTAL = 32 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024
MAX_OUTPUT_TOTAL = 16 * 1024 * 1024
MAX_FILES = 8
MAX_LOG = 2 * 1024 * 1024
MAX_LINE = 6 * 1024 * 1024


def output_names_match(required, optional, actual, *, complete=True):
    """Required prefix, then an ordered subset of the approved optional names."""
    if not all(isinstance(names, list) for names in (required, optional, actual)):
        return False
    approved = required + optional
    if (
        not required
        or len(approved) > MAX_FILES
        or not all(isinstance(name, str) for name in approved + actual)
    ):
        return False
    if len(approved) != len(set(approved)):
        return False
    if actual[: len(required)] != required[: len(actual)]:
        return False
    if len(actual) < len(required):
        return not complete
    cursor = -1
    for name in actual[len(required) :]:
        if name not in optional:
            return False
        index = optional.index(name)
        if index <= cursor:
            return False
        cursor = index
    return True
