# EOD Billing & Analytics Agent — Core Services LLD

Scope: the deterministic reconciliation layer, analytics layer, and LLM narrative + grounding
layer. REST transport and frontend are intentionally out of scope here — these services should
be pure, framework-agnostic modules that any API layer (Node/Express, Python/FastAPI, etc.) can
call.

---

## 1. Data Models

```mermaid
classDiagram
    class LineItem {
        +string drugName
        +int qty
        +int unitPricePaise
        +lineTotalPaise() int
    }

    class BillingRecord {
        +string clinicId
        +string visitId
        +DateTime timestamp
        +string doctorId
        +LineItem[] lineItems
        +PaymentMode paymentMode
        +int amountPaidPaise
        +int discountPaise
        +bool isRefund
        +grossBilledPaise() int
    }

    class PaymentMode {
        <<enumeration>>
        CASH
        CARD
        UPI
    }

    class ValidationError {
        +string rowRef
        +string field
        +string reason
        +string rawValue
    }

    class ParseResult {
        +BillingRecord[] validRecords
        +ValidationError[] errors
        +int totalRows
        +hasErrors() bool
    }

    class PaymentModeBreakdown {
        +PaymentMode mode
        +int billedPaise
        +int collectedPaise
        +int outstandingPaise
        +int refundsPaise
    }

    class ReconciliationReport {
        +string clinicId
        +Date reportDate
        +int totalBilledPaise
        +int totalCollectedPaise
        +int totalOutstandingPaise
        +int totalRefundsPaise
        +int visitCount
        +int refundCount
        +PaymentModeBreakdown[] byPaymentMode
    }

    class HourlyRevenue {
        +int hour
        +int revenuePaise
    }

    class MedicineRankEntry {
        +string drugName
        +int value
        +int rank
    }

    class AnalyticsReport {
        +string clinicId
        +Date reportDate
        +HourlyRevenue[] revenueByHour
        +HourlyRevenue peakHour
        +MedicineRankEntry[] topByQuantity
        +MedicineRankEntry[] topByRevenue
    }

    class NarrativeContext {
        +Map~string,string~ values
        +buildFromReports(ReconciliationReport, AnalyticsReport)$ NarrativeContext
        +has(key) bool
        +get(key) string
    }

    class LLMTemplateResponse {
        +string summaryTemplate
    }

    class TracedFigure {
        +string placeholder
        +string displayValue
        +string sourceField
    }

    class NarrativeResult {
        +string text
        +TracedFigure[] tracedFigures
        +NarrativeStatus status
        +string[] warnings
    }

    class NarrativeStatus {
        <<enumeration>>
        SUCCESS
        REJECTED_RETRY
        FAILED_FALLBACK
    }

    BillingRecord "1" *-- "many" LineItem
    BillingRecord --> PaymentMode
    ParseResult "1" o-- "many" BillingRecord
    ParseResult "1" o-- "many" ValidationError
    ReconciliationReport "1" *-- "many" PaymentModeBreakdown
    AnalyticsReport "1" *-- "many" HourlyRevenue
    AnalyticsReport "1" *-- "many" MedicineRankEntry
    NarrativeContext ..> ReconciliationReport : reads
    NarrativeContext ..> AnalyticsReport : reads
    LLMTemplateResponse ..> NarrativeContext : placeholders must exist in
    NarrativeResult "1" *-- "many" TracedFigure
    NarrativeResult --> NarrativeStatus
```

**Design notes**
- `amountPaidPaise`, `unitPricePaise`, `discountPaise` are always `int` — never float, per the
  brief. Enforce this at the model boundary (reject non-integer input rather than rounding).
- `isRefund = true` records carry a negative `amountPaidPaise` — model this as a signed integer,
  not a separate refund object, so summation stays simple and auditable.
- `ParseResult` deliberately separates `validRecords` from `errors` instead of throwing on first
  bad row — the brief wants *all* malformed rows reported, not a fail-fast 500.
- `NarrativeContext` is the **only** thing the LLM ever sees, and the **only** vocabulary it's
  allowed to reference. It's a flat, pre-formatted `key → displayString` map built directly from
  the two report objects (e.g. `"total_billed" → "₹42,850"`). The LLM never receives raw paise
  integers and never writes a number itself — it only writes `{{total_billed}}` and your code
  substitutes the value. This makes grounding structural rather than detected-after-the-fact.

---

## 2. Service Boundaries

```mermaid
flowchart TB
    subgraph Ingestion["Ingestion & Validation Service"]
        A1[parseLog]
        A2[validateRecord]
    end

    subgraph Reconciliation["Reconciliation Service"]
        B1[computeTotals]
        B2[computeByPaymentMode]
    end

    subgraph Analytics["Analytics Service"]
        C1[computeRevenueByHour]
        C2[rankByQuantity]
        C3[rankByRevenue]
    end

    subgraph Narrative["Narrative Service"]
        D0[buildContext]
        D1[buildPrompt]
        D2[callLLM]
        D3[parseTemplateResponse]
        E1[checkNoStrayDigits]
        E2[checkPlaceholdersKnown]
        E3[substitutePlaceholders]
        E4[decideStatus]
    end

    subgraph Orchestrator["Report Orchestrator"]
        F1[generateDailyReport]
    end

    RawLog[/Raw billing log/] --> A1
    A1 --> A2
    A2 --> Ingestion
    Ingestion -- ParseResult --> F1

    F1 -- validRecords --> B1 --> B2
    F1 -- validRecords --> C1 --> C2
    C1 --> C3

    B2 -- ReconciliationReport --> F1
    C3 -- AnalyticsReport --> F1

    F1 -- Report + Analytics --> D0 --> D1 --> D2 --> D3
    D3 -- LLMTemplateResponse --> E1 --> E2 --> E3 --> E4
    D0 -.->|NarrativeContext also passed to| E2
    D0 -.->|and to| E3
    E4 -- NarrativeResult --> F1

    F1 --> Output[/Final response: report + analytics + narrative/]
```

**Why this split**
- **Ingestion**, **Reconciliation**, **Analytics** never import anything LLM-related — they must
  be independently unit-testable and independently *correct*, since the brief grades this layer
  first and treats it as ground truth for everything downstream.
- **Narrative**, **Context Building**, and **Grounding** have been consolidated into a single `NarrativeService` class to reduce file overhead. The grounding logic itself still never talks to the model — it remains as pure string/dict operations (`_check_no_stray_digits`, `_check_placeholders_known`, `_substitute_placeholders`) that are fully unit-testable with hand-written fake LLM template responses.
- **Orchestrator** is the only piece that knows the full pipeline order. It owns retries and the
  fallback decision — services below it stay dumb and single-purpose.

---

## 3. Sequence — End-to-End Report Generation

```mermaid
sequenceDiagram
    participant Caller as Orchestrator
    participant Ing as IngestionService
    participant Rec as ReconciliationService
    participant Ana as AnalyticsService
    participant Nar as NarrativeService
    participant LLM as LLM Provider

    Caller->>Ing: parseLog(rawRows)
    Ing-->>Caller: ParseResult (validRecords, errors)

    Caller->>Rec: computeTotals(validRecords)
    Rec-->>Caller: ReconciliationReport

    Caller->>Ana: computeAnalytics(validRecords)
    Ana-->>Caller: AnalyticsReport

    Caller->>Nar: buildContext(ReconciliationReport, AnalyticsReport)
    Nar-->>Caller: NarrativeContext

    Caller->>Nar: generateNarrative(NarrativeContext)
    Nar->>LLM: request template (JSON mode, keys only, no raw numbers)
    LLM-->>Nar: modelResponse
    Nar->>Nar: parseTemplateResponse()

    alt response is not valid JSON
        Nar-->>Caller: NarrativeResult status FAILED_FALLBACK, deterministic text
    else response is valid JSON
        Nar-->>Caller: LLMTemplateResponse summaryTemplate
        Caller->>Nar: validate(LLMTemplateResponse, NarrativeContext)
        Note over Nar: checks in order -<br/>1. no digits outside placeholders<br/>2. every placeholder key is known<br/>3. substitute and build tracedFigures
        Nar-->>Caller: NarrativeResult status, text, tracedFigures
    end

    opt status is REJECTED_RETRY
        Caller->>Nar: generateNarrative(NarrativeContext), retry with stricter prompt
        Nar->>LLM: request template again
        LLM-->>Nar: modelResponse
        Nar-->>Caller: LLMTemplateResponse
        Caller->>Nar: validate() again
        Nar-->>Caller: NarrativeResult

        opt second attempt still rejected or malformed
            Caller->>Caller: build NarrativeResult status FAILED_FALLBACK, code-generated text only
        end
    end

    Caller-->>Caller: assemble final response
```

**What changed from a naive "ask LLM for a summary" approach**
- The LLM never receives raw report objects or paise values — only a pre-formatted, whitelisted
  `NarrativeContext`. It structurally cannot reference a field you didn't expose (e.g. profit),
  and it has no channel to talk about anything outside that list at all — not even to name it.
- The LLM never writes a number in the output text at all — it writes `{{placeholder}}` tokens.
  Your code performs the only substitution, using values it already trusts.
- `LLMTemplateResponse` is now a single field (`summaryTemplate`). There's no
  self-reported "here's what I couldn't compute" channel — that removes a second surface the
  model could misuse (e.g. inventing a plausible-sounding reason, or listing a metric that
  *is* available as unavailable). Any fixed disclaimer (like the profit note) is appended by
  your own code, unconditionally, not authored or triggered by the model at all.
- Grounding becomes **pure validation of the template + context lookup**, not fuzzy text mining.
  `checkNoStrayDigits` and `checkPlaceholdersKnown` are both simple, deterministic, and trivial
  to unit test with hand-crafted "bad" LLM responses — no network calls needed.
- `TracedFigure[]` (used to render the "Traced Figures" panel) falls out of the substitution
  step for free — it's literally the map of `{{key}} → displayValue → sourceField` you just used,
  not a separately reconstructed match.

---

## 4. Flow — Validation (specific, actionable errors)

```mermaid
flowchart TD
    Start([Row from raw log]) --> Schema{Required fields present<br/>and correctly typed?}
    Schema -- No --> ErrType[ValidationError:<br/>field, reason is missing/wrong type, rowRef]
    Schema -- Yes --> Money{amountPaidPaise,<br/>discountPaise,<br/>unitPricePaise are integers?}
    Money -- No --> ErrMoney[ValidationError:<br/>reason is non-integer paise value]
    Money -- Yes --> Refund{isRefund is true?}
    Refund -- Yes --> RefundSign{amountPaidPaise is negative?}
    RefundSign -- No --> ErrRefund[ValidationError:<br/>reason is refund must be a negative adjustment]
    RefundSign -- Yes --> Ts{timestamp is valid ISO 8601 UTC?}
    Refund -- No --> Ts
    Ts -- No --> ErrTs[ValidationError:<br/>reason is invalid timestamp format]
    Ts -- Yes --> Items{line_items non-empty<br/>and every qty is positive?}
    Items -- No --> ErrItems[ValidationError:<br/>reason is invalid or empty line_items]
    Items -- Yes --> Valid([Record accepted into validRecords])

    ErrType --> Collect[Append to errors list, continue to next row]
    ErrMoney --> Collect
    ErrRefund --> Collect
    ErrTs --> Collect
    ErrItems --> Collect
```

Key rule: **one bad row never aborts the batch.** `parseLog` always returns both
`validRecords` and `errors` — the API layer decides whether "some errors" is a 207-style partial
response or a 422, but the ingestion service itself never throws.

---

## 5. Flow — Grounding by Construction (Template + Placeholder Substitution)

This is the piece that gets auto-graded. Instead of letting the LLM write numbers and then
detecting/matching them after the fact, the LLM is only ever allowed to write **references** to
a whitelisted, pre-formatted context. Grounding becomes validation of structure, not text mining.

**Step A — Build the whitelist context (runs before the LLM call)**

```mermaid
flowchart TD
    Start([ReconciliationReport + AnalyticsReport]) --> Pick[Select only the fields<br/>you're willing to expose<br/>e.g. total_billed, peak_hour, top_qty_drug...]
    Pick --> Format[Format each value exactly as it<br/>should appear on screen:<br/>paise→'₹42,850', hour→'12pm–1pm',<br/>ratio→'89%']
    Format --> Ctx([NarrativeContext:<br/>flat key → displayString map])
```

**Step B — Validate the LLM's template response (runs after the LLM call)**

```mermaid
flowchart TD
    Start([LLMTemplateResponse:<br/>summaryTemplate]) --> D1{Any digit in summaryTemplate<br/>that sits outside a placeholder tag?}
    D1 -- Yes --> RejStray([REJECTED_RETRY:<br/>hardcoded number detected])
    D1 -- No --> D2[Extract every placeholder token from the template]
    D2 --> D3{Every extracted key<br/>exists in NarrativeContext?}
    D3 -- No --> RejUnknown([REJECTED_RETRY:<br/>unknown placeholder key])
    D3 -- Yes --> Sub[Substitute each placeholder<br/>with context.get of that key]
    Sub --> Verify{Any placeholder tag<br/>remains after substitution?}
    Verify -- Yes --> RejLeftover([REJECTED_RETRY:<br/>unresolved placeholder, likely a typo])
    Verify -- No --> Trace[Build TracedFigure list from<br/>the substitution map used above]
    Trace --> Success([status is SUCCESS: text, tracedFigures])
```

**Implementation notes**
- Step A runs once per report generation, independent of the LLM — it's pure formatting logic
  and fully unit-testable without any model involved (assert `context.get("total_billed") ==
  "₹42,850"` given a known report).
- `checkNoStrayDigits` is a single regex: strip all `{{...}}` spans out of the template first,
  then check whether any `\d` remains in what's left. This one check does most of the grounding
  enforcement work that used to require fuzzy number-matching.
- Because the LLM only ever sees context *keys* (e.g. `total_billed`, `peak_hour`,
  `top_qty_drug`), a metric like `profit` — which was never added to the context because cost
  price isn't in the schema — cannot be referenced, computed, or hallucinated as a placeholder.
  There is no LLM-facing field for it to report unavailability through anymore either.
- The "say so plainly if not computable" requirement is satisfied entirely in code, not by the
  model: your `context_builder` maintains a small static list of known-unavailable metrics for
  this domain (e.g. profit, since cost price is never in the schema) and your
  `narrative_service` appends a fixed, pre-written, non-LLM sentence to the final text whenever
  that condition applies — e.g. *"Note: cost data wasn't available today, so this is revenue,
  not profit."* This sentence is identical every time and ships as a constant, so it needs zero
  grounding validation of its own.
- On second retry failure, fall back to a fully code-generated narrative (string formatting only,
  zero LLM text) — guarantees the "never crash / never corrupt" requirement regardless of how the
  model misbehaves.
- When retrying, feed the specific rejection reason back into the prompt (e.g. "you wrote the
  literal number 8400 — use {{peak_hour_revenue}} instead") rather than just repeating the
  original prompt — this meaningfully improves second-attempt success rates.

---

## 6. Suggested Module Layout (language-agnostic)

```
core/
  models/
    billing_record.*
    reconciliation_report.*
    analytics_report.*
    narrative_result.*
  ingestion/
    parser.*
    validator.*
  reconciliation/
    reconciliation_service.*
  analytics/
    analytics_service.*
  narrative/
    narrative_service.*    # Single class containing Context Builder, LLM orchestration, and Grounding logic
  orchestrator/
    report_orchestrator.*
tests/
  fixtures/
    sample_day_happy_path.json
    sample_day_edge_cases.json         # malformed rows, refunds, zero discount
    llm_response_clean_template.json   # well-formed {{placeholder}} response
    llm_response_stray_digit.json      # model wrote a literal number
    llm_response_unknown_key.json      # model invented/hallucinated a placeholder
                                        # e.g. {{profit}} or {{yesterday_revenue}}
    llm_response_malformed_json.json   # not valid JSON at all
  ingestion.test.*
  reconciliation.test.*
  analytics.test.*
  context_builder.test.*
  grounding.test.*
```

Keep the grounding methods within `NarrativeService` testable with zero network calls — they should take an
`LLMTemplateResponse` + a `NarrativeContext` and return a `NarrativeResult`. That lets you write
tests like "feed it a template containing the literal `8400`, assert `status ==
REJECTED_RETRY`" or "feed it `{{profit}}`, assert rejection with reason 'unknown placeholder'" —
all without ever calling the LLM API, which is exactly the scenario they said they grade
automatically.
