import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.workbench.cli import workbench_main


class WorkbenchCLITests(unittest.TestCase):
    def test_print_config_does_not_start_server(self):
        with (
            patch("app.workbench.cli.create_app") as create_app,
            patch("uvicorn.run") as run,
        ):
            exit_code = workbench_main(["--print-config"])

        self.assertEqual(exit_code, 0)
        create_app.assert_not_called()
        run.assert_not_called()

    def test_invokes_uvicorn_with_resolved_config_host_and_port(self):
        app = object()
        with TemporaryDirectory() as tmp:
            with (
                patch("app.workbench.cli.create_app", return_value=app) as create_app,
                patch("uvicorn.run") as run,
            ):
                exit_code = workbench_main(
                    ["--artifact-dir", tmp, "--host", "0.0.0.0", "--port", "9876"]
                )

        self.assertEqual(exit_code, 0)
        create_app.assert_called_once()
        config = create_app.call_args.kwargs["config"]
        self.assertEqual(config.artifact_dir, Path(tmp))
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args, (app,))
        self.assertEqual(kwargs["host"], "0.0.0.0")
        self.assertEqual(kwargs["port"], 9876)
        self.assertFalse(kwargs["reload"])
        self.assertNotIn("factory", kwargs)


if __name__ == "__main__":
    unittest.main()
