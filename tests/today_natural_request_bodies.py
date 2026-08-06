"""Natural-slot identity helpers shared by Today internal-job tests."""

NATURAL_OWNER_REVIEW_BODY = {
    "execution_class": "natural_scheduled",
    "scheduled_slot": "06:30",
    "trigger_source": "scheduled_owner_review",
}

QA_MANUAL_OWNER_REVIEW_BODY = {
    "execution_class": "qa_manual",
    "scheduled_slot": "",
    "trigger_source": "manual_admin",
    "send_owner_email": False,
}
