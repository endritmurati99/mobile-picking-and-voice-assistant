# Quality Alert AI Field Semantics

## Purpose

This note fixes the meaning of the Quality Alert AI fields used by Odoo, FastAPI, and n8n in Wave A.

## Field Definitions

- `description`
  - Original description entered by the picker.
  - Remains unchanged.
  - Primary user-authored problem statement.

- `ai_enhanced_description`
  - Linguistically improved version of the original description.
  - Must not invent new facts.
  - May clarify wording, grammar, or structure only.

- `ai_photo_analysis`
  - Visual finding based on attached photos.
  - Must describe only what is visible in the images.
  - Must not include an operational recommendation.

- `ai_summary`
  - Internal system reasoning summary.
  - Stays out of the operator main card and belongs in chatter or audit context.

- `ai_recommended_action`
  - Concrete operational recommendation.
  - Action-oriented, not descriptive.

- `ai_disposition`
  - Operational classification of the alert.
  - Examples: `sellable`, `rework`, `quarantine`, `scrap`.
  - In Odoo the visible label is `Einstufung`.

- `ai_confidence`
  - Numeric confidence score for the current AI result.

- `ai_evaluation_status`
  - Technical processing status of the asynchronous quality evaluation.
  - Expected values: `pending`, `completed`, `failed`.
  - In Odoo the visible label is `Analyse-Status`.

- `ai_last_analyzed_at`
  - Timestamp of the most recent successful AI writeback.
  - In Odoo the visible label is `Analysiert am`.

## Odoo UI Mapping

The Odoo operator main card is named `Systembewertung`.

Only these fields belong in that main card:

- `ai_evaluation_status`
- `ai_disposition`
- `ai_recommended_action`
- `ai_last_analyzed_at`

Detailed reasoning does not belong in the main card:

- `ai_summary`
- `ai_enhanced_description`
- `ai_photo_analysis`
- technical provider/model metadata

If the async handoff to `quality-alert-created` fails before analysis starts:

- the alert remains created in Odoo
- `ai_evaluation_status` is set to `failed`
- `ai_failure_reason` stores the dispatch error
- the failure is posted to chatter

## Example Content

- `description`
  - `Artikel beschädigt`

- `ai_enhanced_description`
  - `Artikel ist beschädigt. Die Verpackung weist eine sichtbare Delle auf.`

- `ai_photo_analysis`
  - `Auf dem Foto ist eine eingedrückte Kartonecke mit aufgerissener Außenverpackung sichtbar.`

- `ai_summary`
  - `Der Artikel weist einen sichtbaren Verpackungsschaden auf. Eine manuelle Prüfung ist erforderlich.`

- `ai_recommended_action`
  - `Ware sperren und manuelle Sichtprüfung anfordern.`
