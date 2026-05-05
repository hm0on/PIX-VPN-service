"""Application services (Stage 4+).

Currently exposes :mod:`app.services.support_topic_helper` — a thin module
of async helpers used to bridge the user-side ticket router and the
admin-side support-group topic. The admin-side agent owns the real
implementations; this package only wires them in and re-exports nothing
by default (callers import the submodule directly).
"""

from app.services import support_topic_helper

__all__ = ["support_topic_helper"]
