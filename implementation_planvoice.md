# Gemini Voice Fill — Final Implementation Plan (Phone-First)

## Goal

Add push-to-talk **Voice Fill** to `/phone-print`.  
Dad taps **🎤 Voice Fill**, speaks item details, reviews a phone-friendly confirmation modal, taps **Apply to Form**, and the phone print form is filled — ready for manual review before tapping Print.

Nothing auto-saves or auto-prints. Desktop `/new-stock` is out of scope for v1.

---

## Model Configuration

```env
GEMINI_API_KEY=
GEMINI_VOICE_MODEL=gemini-3.1-flash-lite
GEMINI_VOICE_FALLBACK_MODEL=gemini-3.5-flash
GEMINI_VOICE_TIMEOUT_SECONDS=15
```

- Use `google-genai` SDK.
- Primary: `gemini-3.1-flash-lite`. Fallback: `gemini-3.5-flash` (retry once on model-unavailable error).
- API key stays backend-only. Never exposed in templates or JS.

---

## Phased Execution

| Phase | What gets built |
|---|---|
| 1 | Backend route + service with fake/stub response |
| 2 | Phone UI: button, pre-recording modal, typed fallback |
| 3 | MediaRecorder audio upload wired to backend |
| 4 | Real Gemini call replaces stub |
| 5 | Single-row apply to phone form |
| 6 | Multi-item draft queue |
| 7 | Local coded-price decode/encode + conflict checks |

---

## Proposed Changes

### Backend — New Files

---

#### [NEW] [gemini_voice_service.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/services/gemini_voice_service.py)

- Read `GEMINI_API_KEY`, `GEMINI_VOICE_MODEL` (default `gemini-3.1-flash-lite`), `GEMINI_VOICE_FALLBACK_MODEL` (default `gemini-3.5-flash`), `GEMINI_VOICE_TIMEOUT_SECONDS` (default `15`) from environment.
- Use `google-genai` SDK.
- Accept audio bytes **or** text transcript + context dict.
- Send system instruction (exact text per spec).
- Use `temperature=0.1`, 1 candidate, `response_mime_type="application/json"`.
- If primary model returns a model-not-found / unavailable error, retry once with `GEMINI_VOICE_FALLBACK_MODEL` and include `"model_warning"` in response.
- Validate response against multi-item schema before returning.
- Return `{"ok": False, "error": "..."}` on failure.
- Never store audio. Cap known-words list to 100 before sending.
- Never send price-code digit map to Gemini.

**Validated response schema:**
```json
{
  "ok": true,
  "raw_transcript": "",
  "items": [
    {
      "row_no": 1,
      "fields": {
        "field_key": {
          "value": "string or number",
          "confidence": 0.0,
          "source_text": "",
          "needs_review": false
        }
      },
      "missing_required_fields": [],
      "unmatched_text": [],
      "conflicts": [],
      "notes": []
    }
  ],
  "global_notes": [],
  "model_warning": ""
}
```

---

#### [NEW] [voice.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/routes/voice.py)

```
POST /voice/parse-stock-audio
```

- `multipart/form-data`: `audio`, `template_id`, `template_name`, `template_fields_json`, `existing_values_json`, `known_words_json`, `transcript`
- Validates: at least one of `audio` or `transcript` must be present.
- Delegates to `gemini_voice_service`.
- Returns `application/json`.
- Never writes audio to disk.

---

### Backend — Modified Files

---

#### [MODIFY] [config.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/config.py)

```python
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_VOICE_MODEL = os.getenv("GEMINI_VOICE_MODEL", "gemini-3.1-flash-lite")
GEMINI_VOICE_FALLBACK_MODEL = os.getenv("GEMINI_VOICE_FALLBACK_MODEL", "gemini-3.5-flash")
GEMINI_VOICE_TIMEOUT_SECONDS = int(os.getenv("GEMINI_VOICE_TIMEOUT_SECONDS", "15"))
```

#### [MODIFY] [main.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/main.py)

```python
from app.routes import voice as voice_routes
app.include_router(voice_routes.router)
```

#### [MODIFY] [requirements.txt](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/requirements.txt)

```
google-genai>=0.8
```

# Separate Tally Items from Product Families

Currently, when Tally stock items are imported via ODBC, they are saved as `ProductFamily` records with `category="Imported from Tally"`. This mixes ShopBridge's internal billing families with raw Tally stock items, polluting search results and family management screens. 

This plan proposes creating a dedicated `TallyItem` database model and updating all related routes to ensure ShopBridge data and Tally data remain separate.

> [!IMPORTANT]
> **User Review Required**
> Please review the migration strategy and confirm if you want to completely remove the `tally_stock_item_name` mapping from `ProductFamily`, or keep it strictly as an optional linking field for future accounting sync.

## Open Questions
1. **Mapping:** Currently, `ProductFamily` has a `tally_stock_item_name` column to map a ShopBridge item to a Tally item. Do you want to keep this mapping column so you can link a native ShopBridge barcode family to a Tally item, or do you want it completely removed? (The plan assumes we keep the column for mapping, but we stop creating `ProductFamily` records for *every* Tally item).
2. **Existing Data:** During migration, existing `ProductFamily` records with `category="Imported from Tally"` will be converted into dedicated `TallyItem` records and then deleted from the `ProductFamily` table. Does this sound correct?

## Proposed Changes

### Database & Models

#### [MODIFY] [app/models.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/models.py)
- Create a new `TallyItem` class (SQLAlchemy Model).
  - Columns: `id`, `name` (unique), `active_status`, `created_at`, `updated_at`.

#### [MODIFY] [app/db.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/db.py)
- Add SQLite migration logic to create the `tally_items` table.
- Migrate existing Tally items: 
  - Copy `ProductFamily` records where `category = 'Imported from Tally'` into the new `tally_items` table.
  - Delete those records from `product_families` so they no longer pollute the families view.
- Update `_seed_demo_tally_items()` to seed the new `TallyItem` table instead of `ProductFamily`.

---

### Backend Services & Routes

#### [MODIFY] [app/services/tally_odbc_service.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/services/tally_odbc_service.py)
- Rename `import_stock_items_as_families()` to `import_tally_items()`.
- Update the function to create `TallyItem` records instead of `ProductFamily` records.

#### [MODIFY] [app/routes/tally.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/routes/tally.py)
- Call the updated `import_tally_items()` service function.

#### [MODIFY] [app/routes/pos.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/routes/pos.py)
- **POS Search (`/pos/search`)**: 
  - Update the search query to search the new `TallyItem` table alongside `LabelVariant` and `ProductFamily`.
  - Format Tally search results to use the new `TallyItem.id`.
- **Add Tally Item (`/pos/cart/tally-items/{tally_item_id}/add`)**:
  - Update the route to fetch from the `TallyItem` table instead of `ProductFamily`.
- Ensure POS cart snapshot logic uses the correct `TallyItem.name` when adding an item.

---

### Frontend

#### [MODIFY] [app/templates/tally.html](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/templates/tally.html)
- Update text references from "Product Families" to "Tally Items" to clarify that importing no longer creates ShopBridge families.

#### [MODIFY] [app/templates/pos.html](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/templates/pos.html)
- Ensure the JavaScript search result payload handles the new `TallyItem` response structure smoothly (e.g., passing the correct `tally_item_id`).

## Verification Plan

### Automated Tests
- Run `python scripts/smoke_checks.py` to ensure core POS flows and cart updates are unharmed.
- Run `python -m compileall app scripts` to verify no syntax errors.

### Manual Verification
1. Open the Tally sync screen and click **Import Stock Items** — verify it succeeds without adding new records to the Product Families page.
2. Open the POS screen and search for a known Tally item. Verify it appears as a "Tally item".
3. Select the Tally item from POS search and add it to the cart. Verify the item adds successfully and allows price entry.
4. Go to Product Families — verify all Tally items have been purged and only native ShopBridge families remain.

---

### Frontend — Phone Print Page Only

All Voice Fill HTML and JS are added **directly inside `phone_print.html`** as a clearly delimited self-contained block. No workflow partials are touched. No existing IDs, listeners, or state machines are changed.

---

#### [MODIFY] [phone_print.html](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/templates/phone_print.html)

**HTML additions** — inserted after the existing `phonePrintButton` row (line ~163):

```html
<!-- Voice Fill button -->
<div class="form-actions phone-action-row">
  <button class="button primary phone-voice-fill-button"
          type="button" id="phoneVoiceFillButton" disabled>
    🎤 Voice Fill
  </button>
</div>

<!-- Pre-recording modal -->
<div class="phone-voice-modal-backdrop" id="phoneVoiceFillModal" hidden
     role="dialog" aria-modal="true" aria-labelledby="phoneVoiceModalTitle">
  <div class="phone-voice-modal-panel">
    <h2 id="phoneVoiceModalTitle">Voice Fill — <span id="phoneVoiceTemplateName"></span></h2>
    <div class="phone-voice-field-list" id="phoneVoiceFieldList"></div>
    <div class="phone-voice-example" id="phoneVoiceExample"></div>
    <div id="phoneVoiceRecordingControls">
      <button class="button primary phone-voice-start-btn" type="button"
              id="phoneVoiceStartButton">🎤 Start Speaking</button>
      <div class="phone-voice-countdown" id="phoneVoiceCountdown" hidden></div>
    </div>
    <div id="phoneVoiceTypedFallback" hidden>
      <label>
        Voice not available. Type what dad said here.
        <textarea id="phoneVoiceTranscriptInput" rows="3"></textarea>
      </label>
      <button class="button primary" type="button"
              id="phoneVoiceSendTranscriptButton">Send</button>
    </div>
    <div class="phone-voice-loading" id="phoneVoiceLoading" hidden>
      <span class="phone-voice-spinner"></span> Processing…
    </div>
    <div class="form-actions">
      <button class="button" type="button" id="phoneVoiceCancelButton">Cancel</button>
    </div>
  </div>
</div>

<!-- Confirmation modal -->
<div class="phone-voice-modal-backdrop" id="phoneVoiceFillConfirmModal" hidden
     role="dialog" aria-modal="true" aria-labelledby="phoneVoiceConfirmTitle">
  <div class="phone-voice-modal-panel">
    <h2 id="phoneVoiceConfirmTitle">Voice Fill Result</h2>
    <div class="phone-voice-transcript-block" id="phoneVoiceTranscriptBlock"></div>
    <div id="phoneVoiceConfirmBody"></div>
    <div id="phoneVoiceDraftQueue" hidden></div>
    <div class="form-actions">
      <button class="button primary" type="button" id="phoneVoiceApplyButton">
        Apply to Form
      </button>
      <button class="button" type="button" id="phoneVoiceEditButton">Edit</button>
      <button class="button" type="button" id="phoneVoiceConfirmCancelButton">Cancel</button>
    </div>
  </div>
</div>
```

**JS block** — self-contained, after line 1567 (`</script>`), before `{% endblock %}`:

Key functions:

| Function | Purpose |
|---|---|
| `phoneVoiceBuildFieldMeta()` | Build `template_fields_json` from `phoneRequiredFields()`. Assign `voice_mode` per rules below. |
| `phoneVoiceGetExistingValues()` | Read current form values for `existing_values_json`. |
| `phoneVoiceOpenModal()` | Show pre-recording modal with field list + example speech. |
| `phoneVoiceCloseModal()` | Hide modals, stop recorder. |
| `phoneVoiceStartRecording()` | Request mic via `getUserMedia`. On success → `MediaRecorder`. On denied → show typed fallback. |
| `phoneVoiceStopRecording()` | Stop recorder, call `phoneVoiceSendAudio(blob)`. |
| `phoneVoiceSendAudio(blob)` | `FormData` POST to `/voice/parse-stock-audio`. Show loading. |
| `phoneVoiceSendTranscript()` | POST typed transcript to same route. |
| `phoneVoiceShowConfirm(data)` | Parse `data.items`. Single item → one card. Multiple → cards with row selector. Store remaining in draft queue state. |
| `phoneVoiceLocalCodedPriceCheck(rowData)` | Locally decode `coded_price_spoken` via `phoneDecodeGroup()`. Check against `rate`. Add conflict if mismatch. Never expose digit map to Gemini. |
| `phoneVoiceApplyRow(rowData)` | Fill matching form inputs. Skip barcode. Dispatch `input`+`change`. Call `phoneRefreshPriceState()`, `phoneRefreshReadyState()`, `phoneSaveState()`. Focus first missing/review field. Do NOT submit. |
| `phoneVoiceLoadNextDraftItem()` | Pop next item from queue, show in confirm modal. |

**Voice mode assignment:**

```javascript
const VOICE_MANUAL = new Set(["barcode","qr","qr_code","ean","upc"]);
const VOICE_CODE_REVIEW = new Set([
  "article","article_no","article_number","model","model_no",
  "item_code","shade_code","batch_no"
]);
function phoneVoiceMode(key) {
  const k = key.toLowerCase();
  if (VOICE_MANUAL.has(k)) return "manual_only";
  if (VOICE_CODE_REVIEW.has(k)) return "code_review";
  return "normal";
}
```

**Button enable/disable:** `phoneVoiceFillButton.disabled = !phoneTemplateReady()` — called alongside `phoneRefreshReadyState()`.

**F8 not added** for phone. Desktop can add it later.

---

### CSS

---

#### [MODIFY] [app.css](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/app/static/app.css)

| Selector | Purpose |
|---|---|
| `.phone-voice-fill-button` | Full-width, min-height 52px, primary accent |
| `.phone-voice-modal-backdrop` | Full-screen overlay, dark semi-transparent |
| `.phone-voice-modal-panel` | White card, max-width 480px, scrollable |
| `.phone-voice-field-list` | Stacked field rows with icon prefix |
| `.phone-voice-field-normal` | ✓ green icon |
| `.phone-voice-field-review` | ⚠ amber icon |
| `.phone-voice-field-manual` | ✕ muted icon |
| `.phone-voice-example` | Styled example speech block |
| `.phone-voice-start-btn` | Large, min-height 56px, red accent when active |
| `.phone-voice-countdown` | Countdown badge |
| `.phone-voice-loading` | Spinner + text |
| `.phone-voice-spinner` | CSS keyframe spin |
| `.phone-voice-result-card` | Detected item card in confirm modal |
| `.phone-voice-review-badge` | Amber `⚠ Check` |
| `.phone-voice-conflict-badge` | Red `⚠ Conflict` |
| `.phone-voice-draft-queue-notice` | "N more items waiting" notice |

---

## Coded Price Rules (Local Only)

Gemini may return:
- `rate.value = 450` → fill MRP/rate directly
- `coded_price_spoken.value = "XCPA"` → decode locally via `phoneDecodeGroup()`, propose rate, mark `needs_review: true`
- Both rate + coded_price_spoken → check match locally; mismatch → conflict, block Apply

The `phonePriceCodeSettings.digit_to_code` mapping is **never** sent to backend or Gemini.

---

## Multi-item UX

```
Row 1 of 2
Name: Lakme Kajal
Article: XPF1205 ⚠ Check
Qty: 5   MRP: 500   Rate: 60

[Apply to Form]   [Skip to Row 2]   [Cancel]
```

After Apply:
- Form fills with Row 1.
- Modal closes.
- Notice near button: `1 more voice item waiting → [Load Next]`
- User reviews form → taps Print manually → taps Load Next for Row 2.

No bulk-save. No bulk-print.

---

## Gemini System Instruction

```text
You are parsing Indian retail shop item-entry speech for a POS/barcode system.
Return JSON only matching the schema exactly.
Map values only to the provided template fields. Do not invent fields.
Do not fill manual_only fields (barcode, qr, ean, upc).
For code_review fields (article/model/batch/code), only fill if user clearly says
the field marker. Always set needs_review: true.
Correction words (nahi/nahin/no/actually/instead/matlab/change): use final value.
Hinglish markers: "name me", "naam me", "article me", "qty me", "rate me", etc.
Separated code letters: "X P F one two zero five" → "XPF1205". Dashes → hyphen.
Multi-item separators: "next item", "doosra item", "aur", "item one/two/three",
"first/second/third item", "next product". Return each as a separate entry in items[].
Return missing_required_fields, unmatched_text, conflicts, notes per item.
```

---

## Smoke Checks

#### [MODIFY] [smoke_checks.py](file:///c:/Users/tanis/OneDrive/Desktop/balaji%20cos/App/shopbridge/scripts/smoke_checks.py)

Add 25 checks after the last existing assert, before `print("Smoke checks passed")`:

```python
# ── Voice Fill checks ────────────────────────────────────────────
voice_route_source = (ROOT / "app" / "routes" / "voice.py").read_text(encoding="utf-8")
voice_service_source = (ROOT / "app" / "services" / "gemini_voice_service.py").read_text(encoding="utf-8")
config_source = (ROOT / "app" / "config.py").read_text(encoding="utf-8")

assert_true("phoneVoiceFillButton" in phone_print_markup,
    "Voice Fill button not found in phone_print.html")
assert_true('id="phoneVoiceFillButton"' in phone_print_markup,
    "phoneVoiceFillButton id missing")
assert_true("phoneVoiceFieldList" in phone_print_markup,
    "Pre-recording modal field list is missing")
assert_true("phoneVoiceExample" in phone_print_markup,
    "Pre-recording modal example speech is missing")
assert_true("MediaRecorder" in phone_print_markup,
    "MediaRecorder is not used in phone_print.html")
assert_true("Voice not available. Type what dad said here." in phone_print_markup,
    "Typed fallback text is missing")
assert_true("/voice/parse-stock-audio" in voice_route_source,
    "Backend route /voice/parse-stock-audio not found")
assert_true("gemini-3.1-flash-lite" in voice_service_source,
    "Primary model gemini-3.1-flash-lite missing from service")
assert_true("gemini-3.5-flash" in voice_service_source,
    "Fallback model gemini-3.5-flash missing from service")
assert_true("gemini-2.0-flash-lite" not in voice_service_source,
    "gemini-2.0-flash-lite must not be used as default or fallback")
assert_true("gemini-2.0-flash-lite" not in config_source,
    "gemini-2.0-flash-lite must not appear in config.py")
assert_true("GEMINI_API_KEY" not in phone_print_markup,
    "Gemini API key must not appear in phone_print.html")
assert_true("template_fields_json" in phone_print_markup,
    "template_fields_json not sent from phone UI")
assert_true("existing_values_json" in phone_print_markup,
    "existing_values_json not sent from phone UI")
assert_true("voice_mode" in phone_print_markup,
    "voice_mode not present in field metadata build")
assert_true('"items"' in voice_service_source,
    "Multi-item schema (items) missing from service")
assert_true("phoneVoiceConfirmBody" in phone_print_markup,
    "Confirm modal body is missing")
assert_true("phoneVoiceDraftQueue" in phone_print_markup,
    "Voice draft queue element is missing")
assert_true("manual_only" in phone_print_markup,
    "manual_only voice mode not handled in phone UI")
assert_true("needs_review" in phone_print_markup,
    "needs_review not handled in confirm modal")
assert_true("GEMINI_VOICE_MODEL" in voice_service_source,
    "GEMINI_VOICE_MODEL not read in service")
assert_true("GEMINI_VOICE_FALLBACK_MODEL" in voice_service_source,
    "GEMINI_VOICE_FALLBACK_MODEL not read in service")
assert_true("phoneVoiceLocalCodedPrice" in phone_print_markup
    or "phoneDecodeGroup" in phone_print_markup,
    "Local coded-price decode missing for voice fill conflict check")
assert_true("phoneVoiceTypedFallback" in phone_print_markup,
    "Mic-unavailable typed fallback element missing")
assert_true("phonePrintButton" in phone_print_markup and "phoneFillVariant" in phone_print_markup,
    "Existing phone print manual flow is broken")
```

---

## Verification

```powershell
python -m compileall app scripts
python scripts/smoke_checks.py
```

### Manual Tests

| Speech | Expected |
|---|---|
| `Name me Lakme Kajal qty 5 piece MRP 500 rate 60` | name, qty, mrp, rate filled; no auto-print |
| `Name me Lakme Kajal rate 60 nahi 65 qty 5 MRP 500` | rate = 65 |
| `Name me Lakme Kajal article me X P F 1205 qty 5 MRP 500 rate 60` | article = XPF1205, marked ⚠ |
| `Barcode 8901234567890 name me Lakme Kajal rate 60` | barcode NOT filled |
| `Item one name me Lakme Kajal qty 5 rate 60. Next item name me Maybelline qty 3 rate 75.` | Two cards; apply row 1 only; draft queue shows row 2 |
