from __future__ import annotations

from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import noetrium_platform.product.operator.query.runtime.route_diagnostics as routes


def test_direct_diagnostic_route_does_not_open_evidence_session() -> None:
    args = Namespace(command="index-status", root=Path("diagnostics"))
    with (
        patch.object(routes, "inspect_diagnostic_index", return_value={"fresh": True}) as inspect,
        patch.object(routes, "open_diagnostic_evidence") as open_evidence,
    ):
        assert routes.route_diagnostics(args) == {"fresh": True}
    inspect.assert_called_once_with(args.root)
    open_evidence.assert_not_called()


def test_unknown_diagnostic_route_is_fail_closed_without_io() -> None:
    args = Namespace(command="not-a-diagnostic-command", root=Path("diagnostics"))
    with patch.object(routes, "open_diagnostic_evidence") as open_evidence:
        assert routes.route_diagnostics(args) is None
    open_evidence.assert_not_called()


@contextmanager
def _evidence_session(root: Path):
    assert root == Path("diagnostics")
    yield "evidence-session"


def test_evidence_diagnostic_route_uses_constant_dispatch_target() -> None:
    args = Namespace(command="verify-evidence", root=Path("diagnostics"))
    with (
        patch.object(routes, "open_diagnostic_evidence", _evidence_session),
        patch.object(routes, "verify_diagnostic_evidence", return_value={"verified": True}) as verify,
    ):
        assert routes.route_diagnostics(args) == {"verified": True}
    verify.assert_called_once_with("evidence-session")
