# Delegated admin beta authority

The owner's one-time activation is a persistent, revocable authority for only
the exact 12-address admin beta cohort and the three named products. A normal
publication does not need another owner click. Any recipient, disabled-list,
configuration-version, product, date, policy, grant, or kill-switch change
stops delivery before SMTP.

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
that change invalidates the active grant and stops subsequent delivery.

## Activation evidence

Before live mode, run the isolated real-GCS CAS verifier. It must prove immutable
grant readback, generation-conflict rejection, revocation readback, fail-closed
handling of a response lost after commit, reconciliation by fresh read, and
rejection of a stale write after the uncertain commit. The verifier uses an
`admin_safety_validation/admin_beta_cas/...` prefix and never the production
delegation pointer.
