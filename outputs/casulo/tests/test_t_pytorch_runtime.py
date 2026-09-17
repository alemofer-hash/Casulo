from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from casulo.t.cli import main as t_main
from casulo.t.pytorch_runtime import probe_pytorch_runtime


class PyTorchRuntimeTests(unittest.TestCase):
    def test_missing_pytorch_is_explicitly_unavailable(self) -> None:
        report = probe_pytorch_runtime(
            torch_module=None,
            numpy_module=None,
        )

        self.assertFalse(report.available)
        self.assertEqual(report.status, "UNAVAILABLE")
        self.assertEqual(report.eager_autograd, "FAIL")
        self.assertEqual(report.inductor, "SKIPPED")
        self.assertIsNotNone(report.error)

    def test_installed_runtime_executes_eager_autograd(self) -> None:
        try:
            import numpy  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("runtime PyTorch opcional indisponível")

        report = probe_pytorch_runtime()

        self.assertTrue(report.available)
        self.assertEqual(report.eager_autograd, "PASS")
        self.assertEqual(report.inductor, "SKIPPED")
        self.assertIsNone(report.error)
        self.assertIsNone(report.to_dict()["timing"])
        self.assertIsNone(report.to_dict()["energy_joules"])

    def test_cli_doctor_returns_machine_readable_proof(self) -> None:
        try:
            import numpy  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("runtime PyTorch opcional indisponível")

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = t_main(["pytorch-doctor"])

        self.assertEqual(status, 0)
        self.assertIn(
            '"protocol": "casulo-pytorch-runtime/0.1"',
            stdout.getvalue(),
        )
        self.assertIn('"eager_autograd": "PASS"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
