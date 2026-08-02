#!/usr/bin/env bash
set -u
set -o pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON311:-}"

die() {
  echo "ISOLATED_DUAL_PROFILE_HARNESS_BLOCKED: $*" >&2
  exit 2
}

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3.11 2>/dev/null || true)"
fi
[[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || die "set PYTHON311 to a Python 3.11 interpreter"
PYTHON_VERSION="$($PYTHON_BIN -c 'import platform; print(platform.python_version())')"
[[ "$PYTHON_VERSION" == 3.11.* ]] || die "Python 3.11 is required; found $PYTHON_VERSION"
echo "HARNESS_PYTHON_VERSION=$PYTHON_VERSION"

counter_value() {
  local counter_root="$1"
  local metric_name="$2"
  local attempt_name="$3"
  if [[ ! -f "$counter_root/$metric_name.measured" || ! -f "$counter_root/$attempt_name" ]]; then
    echo "UNMEASURED"
    return
  fi
  awk 'END {print NR + 0}' "$counter_root/$attempt_name"
}

report_counters() {
  local report_prefix="$1"
  local counter_root="$2"
  local http_value smtp_value gcs_value adc_value
  http_value="$(counter_value "$counter_root" external_network external_network_attempts.log)"
  smtp_value="$(counter_value "$counter_root" smtp smtp_attempts.log)"
  gcs_value="$(counter_value "$counter_root" gcs_client gcs_client_attempts.log)"
  adc_value="$(counter_value "$counter_root" credential credential_attempts.log)"
  echo "${report_prefix}_HTTP_ATTEMPTS=$http_value"
  echo "${report_prefix}_SMTP_ATTEMPTS=$smtp_value"
  echo "${report_prefix}_GCS_CLIENT_ATTEMPTS=$gcs_value"
  echo "${report_prefix}_ADC_ATTEMPTS=$adc_value"
}

if [[ "${1:-}" == "--report-counters" ]]; then
  [[ "$#" == 3 ]] || die "usage: $0 --report-counters PREFIX COUNTER_ROOT"
  report_counters "$2" "$3"
  exit 0
fi
[[ "$#" == 0 ]] || die "unexpected arguments"

if [[ -n "${GENIE_HARNESS_EVIDENCE_ROOT:-}" ]]; then
  [[ "${GENIE_HARNESS_EVIDENCE_ROOT}" == /* ]] || die "GENIE_HARNESS_EVIDENCE_ROOT must be absolute"
  [[ ! -e "${GENIE_HARNESS_EVIDENCE_ROOT}" ]] || die "requested evidence root already exists"
  mkdir -p "${GENIE_HARNESS_EVIDENCE_ROOT}"
  EVIDENCE_ROOT="$(realpath "${GENIE_HARNESS_EVIDENCE_ROOT}")"
else
  EVIDENCE_ROOT="$(mktemp -d /tmp/genie-isolated-dual-profile.XXXXXX)"
fi
[[ -d "$EVIDENCE_ROOT" && ! -L "$EVIDENCE_ROOT" ]] || die "invalid evidence root"
case "$EVIDENCE_ROOT/" in
  "$REPO_ROOT/"*) die "evidence root must be outside the repository" ;;
esac
echo "HARNESS_EVIDENCE_ROOT=$EVIDENCE_ROOT"

ISOLATION_ROOT="$REPO_ROOT/tools/harness_isolation"
SNAPSHOT_TOOL="$REPO_ROOT/tools/devops_harness_snapshot.py"
COMPARATOR_TOOL="$REPO_ROOT/tools/compare_pytest_profiles.py"
for required_file in \
  "$ISOLATION_ROOT/sitecustomize.py" \
  "$SNAPSHOT_TOOL" \
  "$COMPARATOR_TOOL"; do
  [[ -f "$required_file" ]] || die "missing harness support: $required_file"
done

mkdir -p \
  "$EVIDENCE_ROOT/default/source" \
  "$EVIDENCE_ROOT/default/home" \
  "$EVIDENCE_ROOT/default/gcloud" \
  "$EVIDENCE_ROOT/default/tmp" \
  "$EVIDENCE_ROOT/default/pycache" \
  "$EVIDENCE_ROOT/default/pytest" \
  "$EVIDENCE_ROOT/default/counters" \
  "$EVIDENCE_ROOT/isolated/source" \
  "$EVIDENCE_ROOT/isolated/home" \
  "$EVIDENCE_ROOT/isolated/gcloud" \
  "$EVIDENCE_ROOT/isolated/tmp" \
  "$EVIDENCE_ROOT/isolated/pycache" \
  "$EVIDENCE_ROOT/isolated/pytest" \
  "$EVIDENCE_ROOT/isolated/counters" \
  "$EVIDENCE_ROOT/isolated/artifacts" \
  "$EVIDENCE_ROOT/isolated/executions" \
  "$EVIDENCE_ROOT/isolated/index"

BEFORE_SNAPSHOT="$EVIDENCE_ROOT/repository-before.json"
AFTER_SNAPSHOT="$EVIDENCE_ROOT/repository-after.json"
PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" "$SNAPSHOT_TOOL" "$REPO_ROOT" > "$BEFORE_SNAPSHOT" || die "repository snapshot failed"

git -C "$REPO_ROOT" archive HEAD | tar -xf - -C "$EVIDENCE_ROOT/default/source" || die "default source archive failed"
git -C "$REPO_ROOT" archive HEAD | tar -xf - -C "$EVIDENCE_ROOT/isolated/source" || die "isolated source archive failed"

DEFAULT_ENV=(
  "PATH=$(dirname "$PYTHON_BIN"):/usr/bin:/bin:/usr/sbin:/sbin"
  "HOME=$EVIDENCE_ROOT/default/home"
  "CLOUDSDK_CONFIG=$EVIDENCE_ROOT/default/gcloud"
  "GOOGLE_APPLICATION_CREDENTIALS=$EVIDENCE_ROOT/default/no-credentials.json"
  "TMPDIR=$EVIDENCE_ROOT/default/tmp"
  "PYTHONPATH=$ISOLATION_ROOT:$EVIDENCE_ROOT/default/source"
  "PYTHONDONTWRITEBYTECODE=1"
  "PYTHONPYCACHEPREFIX=$EVIDENCE_ROOT/default/pycache"
  "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1"
  "GENIE_HARNESS_ACTIVE=1"
  "GENIE_HARNESS_COUNTER_ROOT=$EVIDENCE_ROOT/default/counters"
)
ISOLATED_ENV=(
  "PATH=$(dirname "$PYTHON_BIN"):/usr/bin:/bin:/usr/sbin:/sbin"
  "HOME=$EVIDENCE_ROOT/isolated/home"
  "CLOUDSDK_CONFIG=$EVIDENCE_ROOT/isolated/gcloud"
  "GOOGLE_APPLICATION_CREDENTIALS=$EVIDENCE_ROOT/isolated/no-credentials.json"
  "TMPDIR=$EVIDENCE_ROOT/isolated/tmp"
  "PYTHONPATH=$ISOLATION_ROOT:$EVIDENCE_ROOT/isolated/source"
  "PYTHONDONTWRITEBYTECODE=1"
  "PYTHONPYCACHEPREFIX=$EVIDENCE_ROOT/isolated/pycache"
  "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1"
  "GENIE_HARNESS_ACTIVE=1"
  "GENIE_HARNESS_COUNTER_ROOT=$EVIDENCE_ROOT/isolated/counters"
  "GENIE_ADMIN_ARTIFACT_ROOT=$EVIDENCE_ROOT/isolated/artifacts"
  "GENIE_EXECUTION_STATE_ROOT=$EVIDENCE_ROOT/isolated/executions"
  "GENIE_METADATA_INDEX_ROOT=$EVIDENCE_ROOT/isolated/index"
  "GENIE_OWNER_REVIEW_EXPOSURE_LOG_PATH=$EVIDENCE_ROOT/isolated/owner-exposure.json"
  "GENIE_CUSTOMER_EXPOSURE_LOG_PATH=$EVIDENCE_ROOT/isolated/customer-exposure.json"
)

prepare_counter_evidence() {
  local counter_root="$1"
  shift
  local -a profile_env=("$@")
  if env -i "${profile_env[@]}" "$PYTHON_BIN" -c \
    'import socket; assert socket.create_connection.__module__ == "sitecustomize"'; then
    : > "$counter_root/external_network.measured"
    : > "$counter_root/external_network_attempts.log"
  fi
  if env -i "${profile_env[@]}" "$PYTHON_BIN" -c \
    'import smtplib; assert smtplib.SMTP.__module__ == "sitecustomize"'; then
    : > "$counter_root/smtp.measured"
    : > "$counter_root/smtp_attempts.log"
  fi
  if env -i "${profile_env[@]}" "$PYTHON_BIN" -c \
    'from google.cloud import storage; assert storage.Client.__module__ == "sitecustomize"'; then
    : > "$counter_root/gcs_client.measured"
    : > "$counter_root/gcs_client_attempts.log"
  fi
  if env -i "${profile_env[@]}" "$PYTHON_BIN" -c \
    'import google.auth; assert google.auth.default.__module__ == "sitecustomize"'; then
    : > "$counter_root/credential.measured"
    : > "$counter_root/credential_attempts.log"
  fi
}

prepare_counter_evidence "$EVIDENCE_ROOT/default/counters" "${DEFAULT_ENV[@]}"
prepare_counter_evidence "$EVIDENCE_ROOT/isolated/counters" "${ISOLATED_ENV[@]}"

DEFAULT_JUNIT="$EVIDENCE_ROOT/default/junit.xml"
ISOLATED_JUNIT="$EVIDENCE_ROOT/isolated/junit.xml"
DEFAULT_LOG="$EVIDENCE_ROOT/default/pytest.log"
ISOLATED_LOG="$EVIDENCE_ROOT/isolated/pytest.log"

(
  cd "$EVIDENCE_ROOT/default/source" || exit 2
  env -i "${DEFAULT_ENV[@]}" "$PYTHON_BIN" -m pytest -q -p no:cacheprovider \
    --basetemp "$EVIDENCE_ROOT/default/pytest" \
    --junitxml "$DEFAULT_JUNIT" \
    tests > "$DEFAULT_LOG" 2>&1
)
DEFAULT_PYTEST_EXIT=$?

(
  cd "$EVIDENCE_ROOT/isolated/source" || exit 2
  env -i "${ISOLATED_ENV[@]}" "$PYTHON_BIN" -m pytest -q -p no:cacheprovider \
    --basetemp "$EVIDENCE_ROOT/isolated/pytest" \
    --junitxml "$ISOLATED_JUNIT" \
    tests > "$ISOLATED_LOG" 2>&1
)
ISOLATED_PYTEST_EXIT=$?

echo "DEFAULT_PYTEST_EXIT=$DEFAULT_PYTEST_EXIT"
tail -n 8 "$DEFAULT_LOG"
echo "ISOLATED_PYTEST_EXIT=$ISOLATED_PYTEST_EXIT"
tail -n 8 "$ISOLATED_LOG"

FAIL=0
[[ "$DEFAULT_PYTEST_EXIT" == 0 || "$DEFAULT_PYTEST_EXIT" == 1 ]] || FAIL=1
[[ "$ISOLATED_PYTEST_EXIT" == 0 || "$ISOLATED_PYTEST_EXIT" == 1 ]] || FAIL=1
[[ -s "$DEFAULT_JUNIT" && -s "$ISOLATED_JUNIT" ]] || FAIL=1

COMPARISON_OUTPUT="$EVIDENCE_ROOT/profile-comparison.txt"
"$PYTHON_BIN" "$COMPARATOR_TOOL" "$DEFAULT_JUNIT" "$ISOLATED_JUNIT" > "$COMPARISON_OUTPUT"
COMPARATOR_EXIT=$?
cat "$COMPARISON_OUTPUT"
echo "PROFILE_COMPARATOR_EXIT=$COMPARATOR_EXIT"
[[ "$COMPARATOR_EXIT" == 0 ]] || FAIL=1

report_junit_details() {
  local report_prefix="$1"
  local junit_path="$2"
  local log_path="$3"
  "$PYTHON_BIN" - "$report_prefix" "$junit_path" "$log_path" <<'PY'
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

prefix, junit_name, log_name = sys.argv[1:]
root = ET.parse(junit_name).getroot()
suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
suite = next((item for item in suites if item.get("name") == "pytest"), suites[0])
errors = int(float(suite.get("errors", "0")))
failed_nodes = []
for case in root.iter("testcase"):
    if case.find("failure") is not None or case.find("error") is not None:
        failed_nodes.append(f"{case.get('classname', '')}::{case.get('name', '')}")
subtests = {"passed": 0, "failed": 0, "skipped": 0}
summary = ""
for line in Path(log_name).read_text(encoding="utf-8", errors="replace").splitlines():
    if re.search(r"\b\d+ (?:passed|failed|skipped|xfailed|xpassed|errors?|subtests?)\b", line):
        summary = line.strip()
    for count, outcome in re.findall(r"(\d+) subtests? (passed|failed|skipped)", line):
        subtests[outcome] = int(count)
print(f"{prefix}_ERRORS={errors}")
print(f"{prefix}_FAILED_NODE_IDS={json.dumps(failed_nodes, ensure_ascii=False, sort_keys=True)}")
print(f"{prefix}_SUBTEST_PASSED={subtests['passed']}")
print(f"{prefix}_SUBTEST_FAILED={subtests['failed']}")
print(f"{prefix}_SUBTEST_SKIPPED={subtests['skipped']}")
print(f"{prefix}_PYTEST_SUMMARY={summary}")
PY
}

report_junit_details DEFAULT "$DEFAULT_JUNIT" "$DEFAULT_LOG"
report_junit_details ISOLATED "$ISOLATED_JUNIT" "$ISOLATED_LOG"
echo "SUBTEST_IDENTITY_COMPARISON=UNMEASURED"

DEFAULT_HTTP="$(counter_value "$EVIDENCE_ROOT/default/counters" external_network external_network_attempts.log)"
DEFAULT_SMTP="$(counter_value "$EVIDENCE_ROOT/default/counters" smtp smtp_attempts.log)"
DEFAULT_GCS="$(counter_value "$EVIDENCE_ROOT/default/counters" gcs_client gcs_client_attempts.log)"
DEFAULT_ADC="$(counter_value "$EVIDENCE_ROOT/default/counters" credential credential_attempts.log)"
ISOLATED_HTTP="$(counter_value "$EVIDENCE_ROOT/isolated/counters" external_network external_network_attempts.log)"
ISOLATED_SMTP="$(counter_value "$EVIDENCE_ROOT/isolated/counters" smtp smtp_attempts.log)"
ISOLATED_GCS="$(counter_value "$EVIDENCE_ROOT/isolated/counters" gcs_client gcs_client_attempts.log)"
ISOLATED_ADC="$(counter_value "$EVIDENCE_ROOT/isolated/counters" credential credential_attempts.log)"
report_counters DEFAULT "$EVIDENCE_ROOT/default/counters"
report_counters ISOLATED "$EVIDENCE_ROOT/isolated/counters"
for measured_value in \
  "$DEFAULT_HTTP" "$DEFAULT_SMTP" "$DEFAULT_GCS" "$DEFAULT_ADC" \
  "$ISOLATED_HTTP" "$ISOLATED_SMTP" "$ISOLATED_GCS" "$ISOLATED_ADC"; do
  [[ "$measured_value" == 0 ]] || FAIL=1
done

PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" "$SNAPSHOT_TOOL" "$REPO_ROOT" --compare "$BEFORE_SNAPSHOT" > "$AFTER_SNAPSHOT"
INVARIANT_EXIT=$?
if [[ "$INVARIANT_EXIT" == 0 ]]; then
  echo "HARNESS_REPOSITORY_INVARIANT=PASS"
else
  echo "HARNESS_REPOSITORY_INVARIANT=FAIL"
  cat "$AFTER_SNAPSHOT"
  FAIL=1
fi

if [[ "$FAIL" == 0 ]]; then
  echo "ISOLATED_DUAL_PROFILE_HARNESS_RESULT=PASS"
else
  echo "ISOLATED_DUAL_PROFILE_HARNESS_RESULT=FAIL"
fi
exit "$FAIL"
