import unittest
from unittest.mock import patch

from app.workbench.cli import workbench_main


class WorkbenchCLITests(unittest.TestCase):
    def test_print_config_does_not_start_server(self):
        with patch("uvicorn.run") as run:
            exit_code = workbench_main(["--print-config"])

        self.assertEqual(exit_code, 0)
        run.assert_not_called()

    def test_invokes_uvicorn_with_host_and_port(self):
        with patch("uvicorn.run") as run:
            exit_code = workbench_main(["--host", "127.0.0.1", "--port", "8765"])

        self.assertEqual(exit_code, 0)
        run.assert_called_once()
        _, kwargs = run.call_args
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 8765)


if __name__ == "__main__":
    unittest.main()
