"""Read-only operational truth adapters for Owner Admin System."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol


ACTIVE_PROGRAM_JOBS = {
    "today_genie": "Today_Geenee",
    "keysuri_global_tech": "KeeSuri_Global_Tech",
    "keysuri_korea_tech": "KeeSuri_Korea_Tech",
}


class OperationalReadAdapter(Protocol):
    """Read-only by construction: deliberately has no mutation methods."""

    def read_scheduler_jobs(self) -> List[Dict[str, Any]]: ...

    def read_cloud_run_service(self) -> Dict[str, Any]: ...


class GcpOperationalReadAdapter:
    """GCP REST read adapter using application-default credentials.

    Imports are lazy so Admin can import without GCP/network.  Failures are
    surfaced to the service, never silently presented as live truth.
    """

    def __init__(self, *, project: str, region: str, service_name: str) -> None:
        self.project = project
        self.region = region
        self.service_name = service_name

    def _session(self):
        if not self.project:
            raise RuntimeError("gcp_project_unavailable")
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform.read-only"]
        )
        return AuthorizedSession(credentials)

    def read_scheduler_jobs(self) -> List[Dict[str, Any]]:
        url = (
            "https://cloudscheduler.googleapis.com/v1/"
            f"projects/{self.project}/locations/{self.region}/jobs"
        )
        response = self._session().get(url, timeout=5)
        response.raise_for_status()
        rows = []
        for item in response.json().get("jobs", []):
            rows.append(
                {
                    "name": str(item.get("name") or "").rsplit("/", 1)[-1],
                    "state": str(item.get("state") or "STATE_UNSPECIFIED"),
                    "schedule": str(item.get("schedule") or ""),
                    "timezone": str(item.get("timeZone") or ""),
                    "last_attempt": str(item.get("lastAttemptTime") or ""),
                }
            )
        return rows

    def read_cloud_run_service(self) -> Dict[str, Any]:
        url = (
            "https://run.googleapis.com/v2/"
            f"projects/{self.project}/locations/{self.region}/services/{self.service_name}"
        )
        response = self._session().get(url, timeout=5)
        response.raise_for_status()
        item = response.json()
        annotations = item.get("template", {}).get("annotations", {})
        return {
            "service": self.service_name,
            "serving_revision": str(item.get("latestReadyRevision") or "").rsplit("/", 1)[-1],
            "commit_sha": str(
                annotations.get("GENIE_COMMIT_SHA")
                or annotations.get("COMMIT_SHA")
                or os.getenv("GENIE_COMMIT_SHA", "")
                or os.getenv("COMMIT_SHA", "")
            ),
            "health": "READY" if item.get("latestReadyRevision") else "UNKNOWN",
        }


@dataclass
class OperationalStatusService:
    adapter: OperationalReadAdapter

    def status(self, *, recent_evidence: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        scheduler_error = ""
        run_error = ""
        try:
            scheduler_rows = self.adapter.read_scheduler_jobs()
        except Exception as exc:  # safe unavailable state
            scheduler_rows = []
            scheduler_error = type(exc).__name__
        by_name = {str(row.get("name") or ""): row for row in scheduler_rows}
        programs = []
        for program_id, job_name in ACTIVE_PROGRAM_JOBS.items():
            live = by_name.get(job_name)
            if live:
                programs.append({"program_id": program_id, "provenance": "LIVE", **live})
                continue
            recent = dict(recent_evidence.get(program_id) or {})
            if recent:
                programs.append(
                    {
                        "program_id": program_id,
                        "name": job_name,
                        "provenance": "RECENT EVIDENCE",
                        "state": str(recent.get("status") or "UNKNOWN"),
                        "schedule": "",
                        "timezone": "Asia/Seoul",
                        "last_attempt": str(recent.get("checked_at") or ""),
                    }
                )
            else:
                programs.append(
                    {
                        "program_id": program_id,
                        "name": job_name,
                        "provenance": "UNAVAILABLE",
                        "state": "UNAVAILABLE",
                        "schedule": "",
                        "timezone": "",
                        "last_attempt": "",
                    }
                )
        try:
            cloud_run = {"provenance": "LIVE", **self.adapter.read_cloud_run_service()}
        except Exception as exc:
            run_error = type(exc).__name__
            revision = os.getenv("K_REVISION", "").strip()
            commit = os.getenv("GENIE_COMMIT_SHA", "").strip() or os.getenv("COMMIT_SHA", "").strip()
            if revision or commit:
                cloud_run = {
                    "provenance": "RECENT EVIDENCE",
                    "service": os.getenv("K_SERVICE", "genie-blog-run"),
                    "serving_revision": revision,
                    "commit_sha": commit,
                    "health": "runtime identity only",
                }
            else:
                cloud_run = {
                    "provenance": "UNAVAILABLE",
                    "service": os.getenv("K_SERVICE", "genie-blog-run"),
                    "serving_revision": "",
                    "commit_sha": "",
                    "health": "UNAVAILABLE",
                }
        return {
            "programs": programs,
            "cloud_run": cloud_run,
            "scheduler_error": scheduler_error,
            "cloud_run_error": run_error,
        }


def default_operational_status_service() -> OperationalStatusService:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or os.getenv("PROJECT_ID", "").strip()
    region = os.getenv("GENIE_GCP_REGION", "asia-northeast3").strip()
    service = os.getenv("K_SERVICE", "genie-blog-run").strip()
    return OperationalStatusService(
        GcpOperationalReadAdapter(project=project, region=region, service_name=service)
    )
