# Kee-Suri Global × `im-not-ai` integration audit — 2026-08-27

## Source and license

- Canonical project: <https://github.com/epoko77-ai/im-not-ai>
- Audited snapshot: `0ac1e84f92334f9696e69184478f91c1c6f1dc5e`
- Audited release/manifest version: `2.3.2`
- License: MIT, copyright 2026 epoko77-ai

No third-party executable, prompt file, taxonomy, metric, model client, asset, or
runtime dependency is vendored into GENIE. The integration paraphrases a small
set of editorial principles and records the upstream provenance here.

## What the project does

`im-not-ai` is primarily a Korean post-editing rulebook and agent workflow. It
detects translation-like wording, mechanical parallel structure, repeated
connectors/endings, empty significance language, and other recurring patterns,
then asks a model to edit only the affected spans. Its strongest safety rules
preserve meaning, genre, register, names, numbers, dates, quotations, modality,
and content anchors; edits that become too broad are rolled back.

The upstream installation options include Claude/Copilot marketplaces and a
local `install.sh` that creates global skill/agent links. Its full Claude path
can make multiple model calls, writes `_workspace/` artifacts, and offers an
`update.sh` that fetches upstream changes and reapplies the installer. The Codex
path is a single-call skill. Optional web-service design material mentions API
keys, but it is not part of this integration.

## Safety decision

The upstream integration guide explicitly warns that many rules are
frequency-conditional post-editing rules, not safe generation-time bans. For
example, forbidding every occurrence of an ordinary Korean expression can make
otherwise natural prose more mechanical. GENIE therefore does not copy the
taxonomy or add a generic humanizer pass.

Adopted for Kee-Suri Global only:

1. Source fidelity before naturalness: preserve names, numbers, dates,
   quotations, attribution, causality, and uncertainty/modality.
2. Locality: an item's prose cannot borrow from another rank or merge article
   identities.
3. Removal-only naturalization: empty rhetoric may be omitted, but the model
   cannot invent a concrete conclusion, anecdote, quote, metaphor, or background
   fact to replace it.
4. Internal-copy isolation: schema labels, scaffold notes, instructions, and
   known source-pack template markers are never reader-facing prose.
5. Repetition-aware wording: repeated boilerplate across TOP5 is forbidden,
   while ordinary Korean expressions remain allowed when used naturally.

Rejected:

- global skill/agent installation or symlinks;
- `install.sh`, `update.sh`, or any third-party Python/shell execution;
- upstream model routing, multiple-agent diagnosis/finalization, or extra model
  calls;
- copied taxonomy/metrics/scripts and automatic upstream updates;
- a new blocking validator, delivery gate, or adjudicator;
- changes to customer-send, Scheduler, IAM, Secret Manager, Cloud Run resources,
  Today_Geenee, or Kee-Suri Korea.

## GENIE integration

The existing Global generation prompt carries the bounded rules above on all
three production generation paths: normal, compact MAX_TOKENS recovery, and the
single bounded corrective attempt. The corrective path inherits the same rules
from the normal prompt; it does not create an additional call.

The existing `keysuri_canonical_v1` adjudicator remains the only adjudicator.
Existing visible-surface detectors and customer-send policy are unchanged. The
Kee-Suri Korea prompt is protected by a byte-for-byte SHA-256 regression, and
no Today_Geenee module is touched.

## Verification requirements

- Prompt regressions must prove the Global normal/compact/corrective paths carry
  both the anti-template rules and the source-fidelity/no-invention rules.
- The Korea prompt must remain byte-identical to the pre-integration baseline.
- Targeted tests must pass.
- The authoritative `python3 -m pytest tests -q` suite must pass twice on the
  same candidate bytes before a commit is prepared.
