"""Customer backend (GENIE x KeeSuri customer web product).

This package is the customer-product persistence/domain foundation. It is
deliberately isolated from the operational GENIE / KeeSuri briefing runtime
(generation, validation, owner review, approval, customer send) that lives in
the flat top-level modules of this repository.

Boundary (canonical: docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md sec. 7):

    generation != validation != owner review != approval
              != customer delivery != customer receipt

Nothing in this package may control Cloud Scheduler, /internal/jobs/*, SMTP,
owner-review approval, Secret Manager, or operational GCS artifacts. The
customer domain answers *who may receive which product on which publication
date*; the existing approved pipeline remains the only authority for *whether a
briefing may be sent at all*.
"""
