"""Request/execution ownership propagated to secondary sessions and async work."""

from contextlib import contextmanager
from contextvars import ContextVar

UNBOUND = object()
_scope = ContextVar("ai_station_data_scope", default=UNBOUND)


def current_data_scope():
    return _scope.get()


@contextmanager
def bind_data_scope(scope):
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)
