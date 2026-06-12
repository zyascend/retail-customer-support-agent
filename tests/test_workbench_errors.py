import unittest

from app.workbench.errors import WorkbenchAPIError, error_payload


class WorkbenchErrorTests(unittest.TestCase):
    def test_error_payload_is_stable(self):
        error = WorkbenchAPIError(
            code="session_not_found",
            message="Session was not found.",
            recoverable=True,
            details={"session_id": "missing"},
        )

        self.assertEqual(
            error_payload(error),
            {
                "error": {
                    "code": "session_not_found",
                    "message": "Session was not found.",
                    "recoverable": True,
                    "details": {"session_id": "missing"},
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
