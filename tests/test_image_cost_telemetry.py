from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from image_generator import _extract_image_bytes
from service_image_api import invoke_vertex_image_generation


class _Inline:
    def __init__(self, data: bytes) -> None:
        self.data = data


class _Part:
    def __init__(self, data: bytes) -> None:
        self.inline_data = _Inline(data)


class _Content:
    def __init__(self, *data: bytes) -> None:
        self.parts = [_Part(value) for value in data]


class _Candidate:
    def __init__(self, *data: bytes) -> None:
        self.content = _Content(*data)


class _Response:
    def __init__(self, *candidates: _Candidate) -> None:
        self.candidates = list(candidates)


class ImageCostTelemetryTests(unittest.TestCase):
    def test_all_response_image_parts_are_counted(self) -> None:
        response = _Response(_Candidate(b"one", b"two"), _Candidate(b"three"))
        self.assertEqual(_extract_image_bytes(response), [b"one", b"two", b"three"])

    def test_successful_custom_generator_records_one_paid_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "generated.jpg"

            def generate(**kwargs):
                kwargs["output_path"].write_bytes(b"generated")
                return kwargs["output_path"]

            outcome = invoke_vertex_image_generation(
                prompt="one image",
                output_path=output,
                project_id="project",
                model_name="gemini-2.5-flash-image",
                generate_fn=generate,
            )
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.image_request_count, 1)
        self.assertEqual(outcome.image_successful_output_count, 1)
        self.assertEqual(outcome.image_failed_request_count, 0)
        self.assertEqual(outcome.image_output_tokens, 1290)

    def test_failed_request_is_not_counted_as_paid_output(self) -> None:
        def generate(**_kwargs):
            raise RuntimeError("failure")

        with tempfile.TemporaryDirectory() as tmp:
            outcome = invoke_vertex_image_generation(
                prompt="one image",
                output_path=Path(tmp) / "missing.jpg",
                project_id="project",
                model_name="gemini-2.5-flash-image",
                generate_fn=generate,
            )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.image_request_count, 1)
        self.assertEqual(outcome.image_successful_output_count, 0)
        self.assertEqual(outcome.image_failed_request_count, 1)


if __name__ == "__main__":
    unittest.main()
