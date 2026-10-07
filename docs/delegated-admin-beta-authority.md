# Delegated admin beta authority

The owner's one-time activation is a persistent, revocable authority for only
the exact current admin beta cohort (maximum 25) and the three named products. A normal
publication does not need another owner click. Unreconciled recipient,
configuration-version, disabled-list, product, date, policy, grant, or
kill-switch changes stop delivery before SMTP.

## Authenticated cohort edits (Owner directive, 2026-10-06)

The add/remove buttons explicitly save the list and carry its existing active
authorization. This is limited to an authenticated admin edit of the exact
pre-edit cohort that already matches a valid ACTIVE grant. It preserves the
parent's product scope and suppression policy. It is not a subscription/consent
collector, a new approval policy, or permission to send on an unknown verdict.
REVOKED, STOPPED, missing or stale pre-edit grants are never auto-activated.

The session-bound signed form binds a server-issued operation ID, action,
old config generation/hash and old pointer generation (and removal target).
After CSRF/authentication, an immutable private intent records the operator,
old/new config identity and parent grant. The pointer is fenced to EDITING
with generation CAS before the config CAS write. EDITING blocks all existing
send boundaries. The exact deterministic new config is tagged with operation
ID. Then a parent-linked immutable grant is created and the same owned fence
is CAS-finalized. Saving, authority connection and actual send eligibility
are displayed separately; no add/remove operation sends mail.

This is a recoverable multi-object saga, not a storage transaction or SMTP
exactly-once claim. Lost responses are reconciled by generation-pinned reads;
an unchanged pending operation is resumed, not replaced. The authenticated
management page and the existing service-owned authority-read boundary may
resume only an existing pointer-bound intent. The internal revalidation read
disables nested recovery, so this path is not recursive. A process crash is
recoverable on the next ordinary authority read without an admin page visit.
Ordinary GET, a stale list or an orphan intent cannot issue rights. A concurrent revoke
wins: a config write may already have committed, but the revoke is never
overwritten or resurrected. External config conflicts are not merged or rolled
back. An immutable applied checkpoint separates historical config application
from current authority linkage. If a later edit wins before the old result is
recorded, the old receipt is SUPERSEDED, not falsely not-saved; absent proof is
UNKNOWN and is never replayed against new state. Removing the final recipient stops delivery rather than granting an
empty cohort.

Admin GET and POST error pages reconcile the exact pending intent before
capturing display state. Subsequent display-only authority reads disable
recovery. List, grant and signed form context are checked against the same
config/pointer generations before returning HTML. An intervening edit, revoke
or unavailable read returns a stale/reload page without mixed headcounts or
usable forms, rather than reporting a mismatched ACTIVE success.

Previously frozen snapshots/commands retain their immutable recipient plans.
They fail final revalidation after the cohort changes. A fresh confirmation
can create a new plan for the same unsent run, keyed by current grant/pointer;
it cannot silently retarget an old approval or replay a submitted publication.
No customer-send, Scheduler, IAM or Secret mutation is part of edit recovery.

## Trust boundary

Codex Work is the trusted second-pass reviewer and submitter. Its HMAC signature
authenticates that configured runner and binds the exact verdict bytes; it does
not independently attest which model produced the review or prove Gmail pixel
inspection. The service records `reviewer_model_independently_verified=false`
for that reason. Operational evidence must retain the Gmail raw MIME, the
received-message render capture, and the final customer render capture that the
trusted Work task actually inspected.

The internal token and reviewer key are read from Secret Manager into process
memory and must not be printed or written to artifacts. The helper cannot select
recipients, change the grant, change the runtime kill switch, or bypass the
service-owned candidate, replay, publication, and final revocation checks.

## Suppression boundary

This cohort uses `ADMIN_DISABLED_RECIPIENTS_V1`: the current admin disabled list
must be empty and is rechecked at the final boundary. There is no claim that a
complaint or bounce provider is automatically ingested. A complaint, bounce, or
requested address change is an anomaly requiring the admin list to be updated;
that change must preserve exclusions. Disabled-list changes invalidate the
active grant and stop subsequent delivery; they are never bypassed by carry.
Authenticated ordinary add/remove follows the narrowly scoped edit flow above.

## Activation evidence

Before live mode, run the isolated real-GCS CAS verifier. It must prove immutable
grant readback, generation-conflict rejection, revocation readback, fail-closed
handling of a response lost after commit, reconciliation by fresh read, and
rejection of a stale write after the uncertain commit. The verifier uses an
`admin_safety_validation/admin_beta_cas/...` prefix and never the production
delegation pointer.
