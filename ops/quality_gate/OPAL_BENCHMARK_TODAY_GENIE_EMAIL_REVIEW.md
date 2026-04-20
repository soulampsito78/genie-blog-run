# Internal review gate: today_genie email vs Kee-Suri Opal benchmark

**Use:** Human review before shipping or after material changes to email body, images, or previews.  
**Not a validator:** Does not block API responses automatically.

**Pass target:** First impression at least **competitive with Opal**; **more operationally trustworthy** (governance, handoff, clarity); **not** demo-thin.

Check each row. Any **Fail** needs a fix before claiming “product-grade.”

| # | Criterion | Pass if… |
|---|-----------|----------|
| 1 | **Opening power** | Title + lead grab attention in inbox; feels intentional, not generic “market summary.” |
| 2 | **Briefing authority** | Reads like a premium desk note — concrete hooks, not hollow safety language. |
| 3 | **Visual / text rhythm** | Top image → editorial → bottom image → admin box reads as one linear handoff; pacing supports scanning. |
| 4 | **Product language** | No demo/E2E/staging tone; customer-facing copy sounds shipped. |
| 5 | **Image attractiveness** | Heroes feel memorable and clickable; lighting and framing are competitive with high-end newsletters. |
| 6 | **TOP zone — gaze, crop, commercial pull (`top_v*`)** | All tops: **direct camera (lens) eye contact**; greeting / **camera-facing commercial** energy — premium, warm, alive, click-supporting, refined not vulgar. **Fail if:** any TOP uses **off-camera gaze**; all three tops **same framing/crop** with no role difference; all tops read as **one stiff suit clone**; tops feel **commercially flat** (no magnetism, sterile PS neutrality). |
| 7 | **Same-person identity** | All six `GENIE_EMAIL_today_genie_*` variants clearly one woman; face/body consistent with identity lock; wardrobe follows two-zone policy (per character lock): tops = Zone A premium **studio commercial greeting** closet (may include skirts/dresses, varied crops); bottoms = richer outside-going / lifestyle — not off-brand randomness, not a different persona. |
| 8 | **Two-zone wardrobe richness** | **Tops:** believable premium **studio** closet — tailoring plus skirts/dresses allowed; not trapped as only rigid jacket+trousers; aligns with TOP commercial rules. **Bottoms:** human, lifestyle, relatable without cheap casual drift. **Fail if:** all outside looks still feel like one repeated suit / blazer clone; outdoor closet feels empty; relatable human styling is absent on bottoms; or outfit variation breaks brand identity (low-end athleisure, influencer randomness, teen styling). |
| 9 | **Product vs demo** | Would pay for this or put brand on it; not a scaffold. |
| 10 | **Opal embarrassment test** | Side-by-side with Kee-Suri Opal: Genie is not obviously weaker on finish; governance advantage still visible. |

**Artifacts to review:**  
- Content-only: `genie_today_genie_content_preview.html`  
- Full handoff: `genie_full_email_artifact_preview.html`  
- Six-variant proof: `genie_email_six_variant_proof.html`  
- Character lock: `ops/character_lock/GENIE_TODAY_GENIE_EMAIL_CHARACTER_LOCK.md`

**Reviewer / date:** _________________ / _________________

**Verdict (circle one):** Pass · Conditional pass · Fail

**Notes:**
