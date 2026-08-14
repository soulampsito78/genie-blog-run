from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from starlette.responses import HTMLResponse as RealHTMLResponse
from starlette.responses import Response as RealResponse

import admin_routes
from main import app


_RUN_CURSOR = "20260814_183000_keysuri_korea_tech_aaaaaaaa"
_NEXT_RUN_CURSOR = "20260813_183000_keysuri_korea_tech_bbbbbbbb"
_INCIDENT_CURSOR = "incident_keysuri_korea_tech_20260814_183000_aaaaaaaa"
_NEXT_INCIDENT_CURSOR = "incident_keysuri_korea_tech_20260813_183000_bbbbbbbb"
_NOTICE_CURSOR = "20260814T183000000000"
_NEXT_NOTICE_CURSOR = "20260813T183000000000"


class AdminRoutePaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous_password = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "pagination-test-secret"
        self.client = TestClient(app)
        self.client.post(
            "/admin/login", data={"password": "pagination-test-secret"}
        )

    def tearDown(self) -> None:
        if self._previous_password is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._previous_password

    @staticmethod
    def _run_page() -> dict:
        return {
            "items": [
                {
                    "artifact_list_summary": True,
                    "run_id": _RUN_CURSOR,
                    "mode": "keysuri_korea_tech",
                    "created_at": "2026-08-14T18:30:00+09:00",
                    "validation_result": "pass",
                    "owner_review_status": "pending_review",
                    "customer_delivery_status": "not_sent",
                    "subject": "페이지 테스트",
                }
            ],
            "cursor": _RUN_CURSOR,
            "next_cursor": _NEXT_RUN_CURSOR,
            "has_more": True,
        }

    def test_run_list_routes_forward_cursor_and_render_next_link(self) -> None:
        cases = (
            ("/admin/reviews", "/admin/reviews"),
            ("/admin/delivery", "/admin/delivery"),
        )
        for request_path, link_path in cases:
            with self.subTest(path=request_path), mock.patch(
                "admin_routes.list_run_artifact_page",
                return_value=self._run_page(),
            ) as list_page, mock.patch(
                "admin_routes._current_recipient_count", return_value=(0, True)
            ):
                response = self.client.get(f"{request_path}?cursor={_RUN_CURSOR}")

            self.assertEqual(response.status_code, 200)
            list_page.assert_called_once_with(limit=50, cursor=_RUN_CURSOR)
            self.assertIn('rel="next"', response.text)
            self.assertIn(
                f'href="{link_path}?cursor={_NEXT_RUN_CURSOR}"', response.text
            )
            self.assertIn(f'href="{link_path}"', response.text)

    def test_history_next_link_preserves_filters_and_alias_path(self) -> None:
        query = (
            "program=keysuri_korea_tech&state=review&date=2026-08-14"
            f"&cursor={_RUN_CURSOR}"
        )
        with mock.patch(
            "admin_routes.list_run_artifact_page", return_value=self._run_page()
        ) as list_page, mock.patch(
            "admin_routes._current_recipient_count", return_value=(0, True)
        ), mock.patch(
            "admin_routes.list_operator_audit_page",
            return_value={
                "items": [],
                "cursor": "",
                "next_cursor": "",
                "has_more": False,
            },
        ):
            response = self.client.get(f"/admin/runs?{query}")

        self.assertEqual(response.status_code, 200)
        list_page.assert_called_once_with(limit=50, cursor=_RUN_CURSOR)
        self.assertIn('rel="next"', response.text)
        self.assertIn("/admin/runs?program=keysuri_korea_tech", response.text)
        self.assertIn("state=review", response.text)
        self.assertIn("date=2026-08-14", response.text)
        self.assertIn(f"cursor={_NEXT_RUN_CURSOR}", response.text)

    def test_review_older_page_never_revives_parent_action(self) -> None:
        parent_id = "20260814_180000_keysuri_korea_tech_cccccccc"
        child_id = "20260814_183000_keysuri_korea_tech_dddddddd"
        child = {
            "run_id": child_id,
            "mode": "keysuri_korea_tech",
            "created_at": "2026-08-14T18:30:00+09:00",
            "validation_result": "pass",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "parent_run_id": parent_id,
        }
        parent = {
            "run_id": parent_id,
            "mode": "keysuri_korea_tech",
            "created_at": "2026-08-14T18:00:00+09:00",
            "validation_result": "pass",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
        }

        def page_for(*, limit: int, cursor: str):
            self.assertEqual(limit, 50)
            if cursor:
                return {
                    "items": [parent],
                    "cursor": parent_id,
                    "next_cursor": "",
                    "has_more": False,
                }
            return {
                "items": [child],
                "cursor": "",
                "next_cursor": parent_id,
                "has_more": True,
            }

        with mock.patch(
            "admin_routes.list_run_artifact_page", side_effect=page_for
        ), mock.patch(
            "admin_routes._current_recipient_count", return_value=(0, True)
        ):
            newest = self.client.get("/admin/reviews")
            older = self.client.get(f"/admin/reviews?cursor={parent_id}")

        self.assertEqual(newest.status_code, 200)
        self.assertIn(child_id, newest.text)
        self.assertEqual(older.status_code, 200)
        self.assertIn(parent_id, older.text)
        self.assertNotIn(">검수하기</a>", older.text)
        self.assertIn(">기록 확인</a>", older.text)

    def test_history_audit_cursor_is_independent_from_run_cursor(self) -> None:
        next_audit_cursor = "evt_20260813T170000000000_bbbbbbbb"
        audit_cursor = "evt_20260814T170000000000_aaaaaaaa"
        run_page = self._run_page()
        audit_page = {
            "items": [],
            "cursor": audit_cursor,
            "next_cursor": next_audit_cursor,
            "has_more": True,
        }
        with mock.patch(
            "admin_routes.list_run_artifact_page", return_value=run_page
        ), mock.patch(
            "admin_routes._current_recipient_count", return_value=(0, True)
        ), mock.patch(
            "admin_routes.list_operator_audit_page", return_value=audit_page
        ) as list_audit:
            response = self.client.get(
                f"/admin/history?cursor={_RUN_CURSOR}&audit_cursor={audit_cursor}"
            )

        self.assertEqual(response.status_code, 200)
        list_audit.assert_called_once_with(limit=50, cursor=audit_cursor)
        self.assertIn(f"cursor={_RUN_CURSOR}", response.text)
        self.assertIn(f"audit_cursor={next_audit_cursor}", response.text)

    def test_incident_route_uses_incident_cursor_page(self) -> None:
        page = {
            "items": [],
            "cursor": _INCIDENT_CURSOR,
            "next_cursor": _NEXT_INCIDENT_CURSOR,
            "has_more": True,
        }
        with mock.patch(
            "natural_run_incident_store.list_incident_page", return_value=page
        ) as list_page, mock.patch(
            "admin_routes.list_run_artifacts", return_value=[]
        ):
            response = self.client.get(
                f"/admin/incidents?cursor={_INCIDENT_CURSOR}"
            )

        self.assertEqual(response.status_code, 200)
        list_page.assert_called_once_with(limit=50, cursor=_INCIDENT_CURSOR)
        self.assertIn(
            f'href="/admin/incidents?cursor={_NEXT_INCIDENT_CURSOR}"',
            response.text,
        )

    def test_notice_route_uses_notice_cursor_page(self) -> None:
        page = {
            "items": [],
            "cursor": _NOTICE_CURSOR,
            "next_cursor": _NEXT_NOTICE_CURSOR,
            "has_more": True,
        }
        with mock.patch(
            "admin_routes.list_notice_page", return_value=page
        ) as list_page:
            response = self.client.get(f"/admin/notices?cursor={_NOTICE_CURSOR}")

        self.assertEqual(response.status_code, 200)
        list_page.assert_called_once_with(limit=50, cursor=_NOTICE_CURSOR)
        self.assertIn(
            f'href="/admin/notices?cursor={_NEXT_NOTICE_CURSOR}"',
            response.text,
        )

    def test_html_response_is_constructed_before_route_end_sample(self) -> None:
        events: list[str] = []

        class Recorder:
            def record(self, stage: str) -> None:
                events.append(stage)

        def build_response(*args, **kwargs):
            events.append("response_constructed")
            return RealHTMLResponse(*args, **kwargs)

        with mock.patch(
            "admin_routes.HTMLResponse", side_effect=build_response
        ):
            response = admin_routes._finish_heavy_admin_projection(
                Recorder(), title="test", inner="<p>ok</p>", active="reviews"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            events,
            ["after_template", "response_constructed", "route_end"],
        )

    def test_raw_json_response_is_constructed_before_route_end_sample(self) -> None:
        events: list[str] = []

        class Recorder:
            def record(self, stage: str) -> None:
                events.append(stage)

        def build_response(*args, **kwargs):
            events.append("response_constructed")
            return RealResponse(*args, **kwargs)

        with mock.patch(
            "admin_routes.MemoryEvidenceRecorder", return_value=Recorder()
        ), mock.patch(
            "admin_routes.load_run_artifact",
            return_value={"run_id": _RUN_CURSOR, "mode": "keysuri_korea_tech"},
        ), mock.patch(
            "admin_routes.Response", side_effect=build_response
        ):
            response = self.client.get(f"/admin/runs/{_RUN_CURSOR}/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            events,
            [
                "route_start",
                "after_projection",
                "after_template",
                "response_constructed",
                "route_end",
            ],
        )


if __name__ == "__main__":
    unittest.main()
