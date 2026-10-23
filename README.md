# Customer Service Chatbot — Production Knowledge-Base Pipeline

A human-readable Streamlit customer-service chatbot with a versioned knowledge-base
update pipeline. The original FAQ chat flow is preserved, but operational work is
split into small modules so each responsibility can be tested independently.

## What Task 1 implements

### 1. New / modified document detection
- The pipeline hashes source files with SHA-256.
- A source fingerprint is stored after a successful update.
- The SQLite document ledger stores each file hash and parsed rows. Unchanged files are reused from the ledger; only new or modified files are parsed again. If the complete source set is unchanged, the pipeline returns `unchanged` and does not rebuild the index.

### 2. Duplicate detection
- Exact file duplicates are detected by SHA-256.
- Normalized-content duplicates are also detected, so a renamed file with the same
  content is not imported twice.
- Duplicate FAQ rows are removed before indexing.

### 3. Invalid-file quarantine
Files in `knowledge_base/incoming/` are checked for:
- supported extension,
- maximum file size,
- valid encoding,
- required CSV/JSON fields,
- non-empty FAQ content.

Invalid incoming files are moved to `data/quarantine/` with a reason in the filename.

Supported formats:
- CSV: `prompt,response`
- JSON: a list of objects containing `prompt` and `response`
- TXT/MD: one `question | answer` pair per line

### 4. Versioning and rollback
Every candidate is stored in:
`data/versions/<version_id>/`

Each version contains:
- `knowledge_base.json`
- `manifest.json`

SQLite stores version status, quality results, audit events and monitoring metrics.

### 5. Quality gate
Before activation, the candidate is evaluated against the currently active FAQ set.
The pipeline compares:
- retrieval accuracy,
- grounding coverage.

An update is rejected if either metric falls more than the configured tolerance.

### 6. Scheduled updates and retries
The scheduler stores jobs in SQLite instead of using `sleep()`.
Failed jobs are retried after:
- 15 minutes,
- 30 minutes,
- 60 minutes.

The same scheduler logic can be called by Windows Task Scheduler, cron, or another
process every minute. It never uses long blocking sleeps, so missed runs are picked up safely on the next tick.

### 7. Maintenance window
Activation is allowed only inside:
`MAINTENANCE_WINDOW_START` → `MAINTENANCE_WINDOW_END`

The admin UI has a **Simulate maintenance window** option so the feature can be
demonstrated without waiting until 2 AM.

### 8. Post-activation health checks and automatic rollback
After activation, a five-minute health window is persisted in the runtime state. The scheduler can close the window with a healthy result or automatically roll back to the exact pre-release version after a failed health check. You can also complete it directly through:
`UpdatePipeline.complete_health_check(version, healthy=False)`

A failed health check automatically rolls back to the previous active version.

### 9. Access control
- `user / user` can use the chatbot.
- `admin / <ADMIN_PASSWORD>` can access update, activation and rollback operations.
- Change the admin password in `.env`.

### 10. Prompt-injection protection
Common requests such as:
- "ignore previous instructions"
- "reveal the system prompt"
- "show your hidden instructions"

are blocked and escalated rather than passed to Gemini.

### 11. Sensitive-data masking
Emails, Indian phone numbers, card-like numbers and common API-key patterns are
masked before monitoring/audit data is stored and before FAQ context is sent to Gemini.

### 12. Monitoring
The monitoring screen tracks:
- request count,
- failures,
- escalations,
- average latency,
- average confidence,
- health-check status,
- audit log,
- knowledge-base version history.

## Project structure

```text
customer_service_chatbot_LLM/
├── dataset/
│   └── dataset.csv                 # existing FAQ dataset
├── knowledge_base/
│   └── incoming/                   # put new documents here
├── data/
│   ├── quarantine/                 # invalid files
│   ├── versions/                   # versioned KB snapshots
│   └── runtime/                    # active-version pointer
├── src/
│   ├── chatbot.py                  # user-facing RAG service
│   ├── config.py                   # .env configuration
│   ├── evaluator.py                # quality/grounding tests
│   ├── knowledge_base.py           # ingestion/version creation
│   ├── monitoring.py               # metrics + health checks
│   ├── retrieval.py                # deterministic local retrieval
│   ├── scheduler.py                # scheduled jobs + retries
│   ├── security.py                 # RBAC, injection detection, masking
│   ├── storage.py                  # SQLite persistence
│   ├── update_pipeline.py          # complete Task 1 workflow
│   └── langchain_helper.py         # compatibility wrapper for old imports
├── tests/
├── .env.example
├── main.py
└── requirements.txt
```

## Windows setup

Use the Python launcher if your system uses `py`:

```bash
py -m pip install -r requirements.txt
```

Create `.env` from `.env.example` and add your Gemini API key if you want LLM-generated
wording. The chatbot can still answer from the FAQ locally when the API key is absent.

Run:

```bash
py -m streamlit run main.py
```

## Testing

```bash
py -m pytest -q
```

The tests cover duplicate documents, invalid files, maintenance-window enforcement,
quality regression, unauthorized admin actions, prompt injection, masking and
automatic rollback.

## Operational flow

```text
Incoming documents
        |
        v
Scan + hash
        |
        +---- duplicate ------> ignore
        |
        +---- invalid --------> quarantine
        |
        v
Build candidate version
        |
        v
Accuracy + grounding quality gate
        |
   rejected / approved
        |
        v
Wait for maintenance window
        |
        v
Activate candidate
        |
        v
5-minute health window
        |
   healthy / failed
        |       |
        |       +------> automatic rollback
        v
Keep version active
```

## Tasks 2-6 (integrated)

The project now also includes a unified `SupportService` and dedicated modules:

- `src/media_analysis.py` — safe upload validation, OCR/text extraction, invoice/message comparison, blur/low-quality clarification, prompt-injection rejection, >30s queue response and retention cleanup.
- `src/ticketing.py` — structured ticket extraction, mandatory-field requests, deduplication, priority, skill/workload/business-hours routing, business-time SLA warning/breach logic, grouping and masked handoff summaries.
- `src/policy_rag.py` — metadata-aware policy retrieval with version/product/region/access/effective/expiry filtering, historical `as_of` queries, malicious-document rejection and mandatory citations.
- `src/sentiment.py` — multilingual/mixed-language sentiment labels, confidence, sarcasm/high-risk detection and escalation/on-call rules.
- `src/multilingual.py` — English/Hindi/Spanish/French detection (including Hinglish), language switching, 10-message context, isolated sessions, 30-minute expiry and 24-hour summary restoration.
- `src/support_service.py` — integration façade used to combine chatbot, language/session, sentiment/escalation, evidence analysis and ticket creation.

All thresholds/timings are configurable through `.env`. The original Task 1 implementation and tests are preserved.
