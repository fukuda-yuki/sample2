"""Operation-local reuse of successful deep predecessor closure proofs only.

Callers still read binding references, STOPs, usage and ownership on every call.
No proof survives its outer operation; a new operation rechecks all deep bytes.
This is not a cache for current admission, liveness or readiness decisions.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps


@dataclass
class _Scope:
    verified: set = field(default_factory=set)
    pending: set = field(default_factory=set)


_CURRENT = ContextVar('predecessor_validation_scope', default=None)


@contextmanager
def validation_scope():
    """Nested operations share their caller's scope; outer exit discards it."""
    if _CURRENT.get() is not None:
        yield
        return
    token = _CURRENT.set(_Scope())
    try:
        yield
    finally:
        _CURRENT.reset(token)


def scoped_validation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with validation_scope():
            return function(*args, **kwargs)
    return wrapped


def validate_predecessor_once(key, validate):
    """Memoize a successful bound historical closure check, never a live check.

    The caller computes key from fresh plan/wave/closure references each time.
    Without an explicit operation scope this always performs full validation.
    """
    scope = _CURRENT.get()
    if scope is None:
        return validate()
    if key in scope.verified:
        return True
    if key in scope.pending:
        raise ValueError('Cyclic predecessor closure validation')
    scope.pending.add(key)
    try:
        result = validate()
        if result is not True:
            raise ValueError('Predecessor closure validation did not confirm success')
        scope.verified.add(key)
        return True
    finally:
        scope.pending.remove(key)
