"""Fixed, locally qualified Echo loader selection; no precision or shell API."""

BOUNDED = "bounded_11g"
MEMORY_MIB = 11264
STANDARD_RAM_MIB = 24576


def validate_profile(name, size, steps):
    if name == BOUNDED and (size != 384 or steps < 8):
        raise ValueError("The reduced-RAM avatar profile requires 384x384 and at least 8 steps")
