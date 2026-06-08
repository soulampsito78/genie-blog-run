# GENIE Trusted Index Source Replacement Design

Status: design only (no live fetch implementation, no feed value edit, no deploy)

## Scope

- **Today_Geenee-only** (`today_genie`). This document covers market index **source provenance** and **number-table validation** for financial snapshot rows.
- **Not** a Kee-Suri image/manifest document.
- **Not** a review/operation box policy document.
- **Tomorrow_Geenee** is closed/dormant (platform and monetization risk) and is **not** an implementation target here.

## Related policy (boundary alignment only)

Cross-references below are for **surface separation** only. The subject of this document remains **feed/data provenance**, not email review boxes or image watermarks.

- `docs/GENIE_KEYSURI_REVIEW_IMAGE_PIPELINE_HANDOFF_2026_06_05.md` — active Today_Geenee vs Kee-Suri tracks
- `docs/REVIEW_OPERATION_BOX_POLICY.md` — owner/admin vs customer review confirmation separation
- `docs/genie/GENIE_EMAIL_OPERATION_BOX_SEMANTICS_FIX_PLAN.md` — Genie operation box wording vs validation vs delivery

## Semantic separation (feed verification vs owner/customer review)

- Feed row `accuracy_status: verified` means **data/source verification** for index provenance and number-table gates.
- It does **not** mean owner `review_passed`.
- It does **not** mean owner **검수완료**.
- It does **not** mean customer delivery completed (`customer_delivery_status`, SMTP success).
- It must **not** be used as `sent_archived` or as send-complete wording.

## 1) Current problem (confirmed)

- today_genie index rows can be assembled from staged feed JSON without external provenance fields.
- Existing contract keys support provenance (`source_name`, `source_url`/`source_id`, `fetched_at`, `verified_at`, `accuracy_status`) but staged feeds can still remain non-verified.
- Current trace verdict: `FEED_IS_STAGED_WITH_NO_ORIGIN_METADATA`.

## 2) Trusted source priority map (authoritative vs cross-check)

The following map defines the allowed authority order per index. Cross-check sources are not authoritative unless explicitly approved.

```json
{
  "KOSPI": {
    "primary": [
      {
        "source_name": "KRX",
        "source_type": "official_exchange",
        "notes": "Korea Exchange official index/data channel for KOSPI close and day change"
      }
    ],
    "cross_check": []
  },
  "KOSDAQ": {
    "primary": [
      {
        "source_name": "KRX",
        "source_type": "official_exchange",
        "notes": "Korea Exchange official index/data channel for KOSDAQ close and day change"
      }
    ],
    "cross_check": []
  },
  "NIKKEI": {
    "primary": [
      {
        "source_name": "Nikkei Indexes",
        "source_type": "official_index_provider",
        "notes": "Nikkei official current values/download center for Nikkei 225"
      }
    ],
    "cross_check": []
  },
  "SPX": {
    "primary": [
      {
        "source_name": "S&P Dow Jones Indices",
        "source_type": "official_index_provider",
        "notes": "Official S&P 500 close from index owner"
      }
    ],
    "cross_check": [
      {
        "source_name": "AP/Reuters",
        "source_type": "news_wire_cross_check",
        "notes": "Session close narrative cross-check only"
      }
    ]
  },
  "DJI": {
    "primary": [
      {
        "source_name": "S&P Dow Jones Indices",
        "source_type": "official_index_provider",
        "notes": "Official Dow Jones Industrial Average close from index owner"
      }
    ],
    "cross_check": [
      {
        "source_name": "AP/Reuters",
        "source_type": "news_wire_cross_check",
        "notes": "Session close narrative cross-check only"
      }
    ]
  },
  "NASDAQ": {
    "primary": [
      {
        "source_name": "Nasdaq",
        "source_type": "official_exchange_or_index_channel",
        "notes": "Official Nasdaq index page/data channel for Composite close"
      }
    ],
    "cross_check": [
      {
        "source_name": "AP/Reuters",
        "source_type": "news_wire_cross_check",
        "notes": "Session close narrative cross-check only"
      }
    ]
  }
}
```

## 3) Source metadata contract (row-level required fields)

Required for each market snapshot row:

- `symbol`
- `display_name`
- `close`
- `change_pct`
- `as_of`
- `source_name`
- `source_url` or `source_id`
- `fetched_at`
- `verified_at`
- `accuracy_status`

Allowed `accuracy_status`:

- `verified`
- `unverified`
- `source_missing`
- `mismatch`
- `stale`

Authoritative interpretation:

- `verified`: only when source is in the approved primary map and metadata completeness is satisfied.
- `unverified`: source fields partially present but verification not complete.
- `source_missing`: staged/manual numeric row with no provenance.
- `mismatch`: explicit discrepancy against authoritative/cross-check reconciliation.
- `stale`: source timestamp outside freshness window for target briefing date.

## 4) Feed schema examples (design fixtures, not live data)

### 4.1 Korea/Japan feed example with required metadata

```json
{
  "as_of": "2026-04-10",
  "session": "Asia cash close reference",
  "indices": {
    "KOSPI": {
      "close": 0.0,
      "change_pts": 0.0,
      "change_pct": 0.0,
      "source_name": "KRX",
      "source_url": "https://<official-krx-endpoint-or-page>",
      "source_id": "",
      "fetched_at": "2026-04-10T06:00:00+09:00",
      "verified_at": "2026-04-10T06:01:00+09:00",
      "accuracy_status": "verified"
    },
    "KOSDAQ": {
      "close": 0.0,
      "change_pts": 0.0,
      "change_pct": 0.0,
      "source_name": "KRX",
      "source_url": "https://<official-krx-endpoint-or-page>",
      "source_id": "",
      "fetched_at": "2026-04-10T06:00:00+09:00",
      "verified_at": "2026-04-10T06:01:00+09:00",
      "accuracy_status": "verified"
    },
    "NIKKEI": {
      "close": 0.0,
      "change_pts": 0.0,
      "change_pct": 0.0,
      "source_name": "Nikkei Indexes",
      "source_url": "https://<official-nikkei-index-page-or-download>",
      "source_id": "",
      "fetched_at": "2026-04-10T06:00:00+09:00",
      "verified_at": "2026-04-10T06:02:00+09:00",
      "accuracy_status": "verified"
    }
  }
}
```

### 4.2 US overnight feed example with primary + cross-check fields

```json
{
  "as_of": "2026-04-10",
  "session": "US cash close",
  "indices": {
    "SPX": {
      "close": 0.0,
      "change_pts": 0.0,
      "change_pct": 0.0,
      "source_name": "S&P Dow Jones Indices",
      "source_url": "https://<official-spdj-spx-page-or-feed>",
      "source_id": "",
      "cross_check_source_name": "AP/Reuters",
      "cross_check_source_url": "https://<ap-or-reuters-market-close-story>",
      "fetched_at": "2026-04-10T06:00:00+09:00",
      "verified_at": "2026-04-10T06:03:00+09:00",
      "accuracy_status": "verified"
    },
    "NASDAQ": {
      "close": 0.0,
      "change_pts": 0.0,
      "change_pct": 0.0,
      "source_name": "Nasdaq",
      "source_url": "https://<official-nasdaq-index-page-or-feed>",
      "source_id": "",
      "cross_check_source_name": "AP/Reuters",
      "cross_check_source_url": "https://<ap-or-reuters-market-close-story>",
      "fetched_at": "2026-04-10T06:00:00+09:00",
      "verified_at": "2026-04-10T06:03:00+09:00",
      "accuracy_status": "verified"
    },
    "DJI": {
      "close": 0.0,
      "change_pts": 0.0,
      "change_pct": 0.0,
      "source_name": "S&P Dow Jones Indices",
      "source_url": "https://<official-spdj-dji-page-or-feed>",
      "source_id": "",
      "cross_check_source_name": "AP/Reuters",
      "cross_check_source_url": "https://<ap-or-reuters-market-close-story>",
      "fetched_at": "2026-04-10T06:00:00+09:00",
      "verified_at": "2026-04-10T06:03:00+09:00",
      "accuracy_status": "verified"
    }
  }
}
```

## 5) Validation expectations (production gate target)

### 5.1 Structure pass (`number_table_structure_pass`)

- Six required rows present.
- Each row has numeric `close`.
- Each row has parseable `change_pct`.
- Each row has parseable `as_of`.
- Row shape not malformed.

### 5.2 Accuracy verified (`number_table_accuracy_verified`)

For all six rows:

- `accuracy_status == "verified"`
- `source_name` present
- `source_url` or `source_id` present
- `fetched_at` present
- `verified_at` present
- `source_name` must match approved primary source map for that symbol

### 5.3 Accuracy not verified (`number_table_accuracy_not_verified`)

- Structure passes, but any row is missing verification metadata or has non-verified status (`unverified`/`source_missing`).

### 5.4 Accuracy fail (`number_table_accuracy_fail`)

- Any row has `accuracy_status` in `mismatch`/`stale`.
- Any row marked `verified` but required metadata is missing.
- Any row violates source-authority mapping.

## 6) Policy target behavior

- Production today_genie:
  - structure fail => block
  - accuracy fail => block
  - accuracy_not_verified => review_required or block (never production success pass)
- Controlled image-review:
  - accuracy_not_verified => warning allowed with explicit logging

## 7) Non-goals in this step

This document does **not** implement or define:

- Live source fetcher
- Scraping logic
- Feed value edits
- Scheduler trigger or production rollout
- Email send or customer delivery
- Customer `#review-confirmation-box` or owner/admin operation box policy
- Image watermark, image manifest, or Kee-Suri preview asset tracking
- Deployment or send execution
