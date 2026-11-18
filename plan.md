# AI Recruitment Voice Calling Agent
## Technical Blueprint & AI Coding Agent Execution Plan

**Project type:** Working MVP / Functional prototype  
**Primary objective:** Automate initial recruitment screening through real outbound AI phone calls.  
**Target users:** Internal recruitment team  
**Initial integration:** Google Sheets  
**Initial language:** English  
**Initial calling scale:** 1–2 simultaneous calls  
**Development approach:** Modular Python backend + Next.js frontend

---

# 1. Product objective

Build a web-based recruitment calling platform where recruiters can:

1. Upload candidates through an Excel or CSV file.
2. Review and validate imported candidate details.
3. Select candidates and initiate outbound calls.
4. Have an AI voice agent call each candidate.
5. Conduct a natural recruitment screening conversation.
6. Capture all required candidate information.
7. Generate a transcript and short screening summary.
8. Automatically update candidate information in PostgreSQL.
9. Synchronize candidate information to Google Sheets.
10. View call status, candidate details and summaries through a dashboard.
11. Automatically retry eligible unanswered calls after a configurable interval of 2–4 days.

The application must perform real calls. Do not build a mock calling interface or simulated AI conversation.

## MVP success criteria

The first version is considered successful when:

- A recruiter can upload at least 5 candidates.
- The recruiter can initiate an actual outbound phone call.
- A candidate can speak with the AI agent.
- The agent can ask and understand screening questions.
- The agent can handle normal conversational variations.
- Candidate answers are extracted into structured fields.
- A transcript and summary are generated.
- PostgreSQL is updated automatically.
- Google Sheets is updated automatically.
- The dashboard reflects the correct call status.
- Failed or unanswered calls can be retried.

---

# 2. Technology stack

Use the following stack consistently. Do not introduce alternative frameworks without a technical reason.

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | Next.js + TypeScript | Recruiter dashboard |
| Styling | Tailwind CSS | UI styling |
| Backend | Python + FastAPI | APIs and business logic |
| Validation | Pydantic v2 | Request and response validation |
| ORM | SQLAlchemy 2.x | Database operations |
| Migrations | Alembic | Schema management |
| Database | PostgreSQL | Persistent application data |
| Queue | Redis | Calling queue and temporary state |
| Worker | ARQ or Celery | Background call execution |
| Scheduler | Worker scheduler / APScheduler | Retry scheduling |
| Telephony | Exotel | Indian outbound calls |
| Speech-to-text | Deepgram streaming | Candidate speech transcription |
| LLM | OpenAI API | Conversation and reasoning |
| Text-to-speech | Kitten TTS | AI voice generation |
| Spreadsheet | Google Sheets API | Candidate data synchronization |
| Deployment | Docker Compose | Local and initial deployment |

### Important technology rules

1. Use the OpenAI API, not the ChatGPT consumer application.
2. Keep Kitten TTS behind a dedicated TTS interface.
3. Use Exotel as the initial telephony provider.
4. Confirm Exotel's current account eligibility, outbound calling requirements, audio streaming capability, supported WebSocket protocol and media formats before implementing the telephony adapter.
5. Do not assume that every Exotel product or account supports the same bidirectional streaming features.
6. Use streaming STT wherever supported.
7. Keep the LLM, STT, TTS and telephony components replaceable.
8. Do not use Google Sheets as the primary database.
9. Use PostgreSQL as the source of truth.
10. Keep the first deployment limited to one or two concurrent calls.

---

# 3. High-level system architecture

```text
                    RECRUITER
                        |
                        v
              NEXT.JS DASHBOARD
                        |
                        v
                 FASTAPI BACKEND
                        |
          +-------------+-------------+
          |             |             |
          v             v             v
      POSTGRESQL      REDIS        GOOGLE
      DATABASE        QUEUE        SHEETS
          |             |
          |             v
          |       CALL WORKER
          |             |
          |             v
          |       EXOTEL API
          |             |
          |             v
          |       CANDIDATE PHONE
          |             |
          |             v
          |       AUDIO WEBSOCKET
          |             |
          |             v
          |        AUDIO PIPELINE
          |             |
          |       +-----+------+
          |       |            |
          |       v            v
          |      STT          VAD
          |       |
          |       v
          |    OPENAI LLM
          |       |
          |       v
          |  SCREENING STATE
          |       |
          |       v
          |    KITTEN TTS
          |       |
          |       v
          |   AUDIO CONVERSION
          |       |
          |       v
          |    EXOTEL STREAM
          |       |
          +-------+
                  |
                  v
           CALL COMPLETED
                  |
                  v
          FINAL DATA EXTRACTION
                  |
          +-------+--------+
          |                |
          v                v
       DATABASE       GOOGLE SHEETS
          |
          v
      DASHBOARD
```

## Architecture principles

- The frontend must never directly call the telephony provider.
- All telephony credentials must remain on the backend.
- The call worker must be responsible for initiating outbound calls.
- Webhooks must update call status.
- WebSocket handlers must process live audio.
- Every call attempt must have its own unique identifier.
- Every candidate must have a persistent database record.
- Every call must be linked to a candidate record.
- Database writes must be idempotent.
- Google Sheets synchronization must happen after successful database persistence.
- A Google Sheets failure must not cause the screening data to be lost.

---

# 4. Core application modules

Implement the following modules independently.

## Module A: Candidate management

Responsibilities:

- Create candidates manually.
- Import candidates from Excel and CSV.
- Validate uploaded data.
- Detect duplicate candidates.
- Update candidate details.
- Search candidates.
- Filter candidates by status.
- Link candidates to a job opening.

### Candidate import columns

Required:

- Candidate name
- Phone number
- Job role

Optional:

- Email
- Total experience
- Current company
- Current location
- Resume URL
- Candidate source
- Recruiter notes

### Import process

```text
Upload File
    |
    v
Validate File Extension
    |
    v
Read Excel / CSV
    |
    v
Map Columns
    |
    v
Validate Required Fields
    |
    v
Normalize Phone Numbers
    |
    v
Detect Duplicates
    |
    v
Show Import Preview
    |
    v
Recruiter Confirms
    |
    v
Save Candidates
```

### Duplicate detection

Use normalized phone numbers as the primary duplicate detection key.

Do not automatically overwrite an existing candidate's screening information when importing the same phone number again.

Return an import report:

```json
{
  "total_rows": 10,
  "valid_candidates": 8,
  "duplicate_candidates": 1,
  "invalid_candidates": 1,
  "imported_candidates": 8
}
```

---

## Module B: Recruitment job configuration

Create a basic job management module.

Each job should contain:

- Job title
- Company name
- Job description
- Job location
- Required experience
- Skills
- Screening questions
- Recruiter instructions
- Active/inactive status

For the MVP, support one active job configuration initially.

The calling agent should receive the job configuration associated with each candidate.

Do not hardcode a job description inside the agent's Python code.

---

## Module C: AI screening agent

This is the core intelligence layer.

The agent must conduct a natural English conversation.

### Information to collect

| Field | Expected data type |
|---|---|
| Current location | String |
| Current company | String |
| Total experience | Number |
| Relevant experience | Number |
| Current CTC | Number |
| Expected CTC | Number |
| Notice period | String |
| Reason for job change | String |
| Interested in opportunity | Boolean / unknown |
| Interview availability | String |

Also maintain:

- Candidate name
- Job title
- Call ID
- Screening completion status
- Missing information
- Candidate callback request
- Candidate opt-out status

### Conversation behaviour

The AI agent must:

1. Introduce itself as an AI recruitment assistant.
2. Identify the organization it is calling on behalf of.
3. Explain the recruitment purpose.
4. Ask if this is a convenient time.
5. Ask one primary question at a time.
6. Understand natural language responses.
7. Extract information from responses that contain multiple answers.
8. Avoid asking questions already answered.
9. Ask clarification questions when required.
10. Handle candidate interruptions.
11. Answer simple questions about the job using configured job information.
12. Never invent company or job details.
13. Allow candidates to decline.
14. Offer a callback when the candidate is busy.
15. Confirm important extracted information.
16. End the call politely.

### Example conversation

AI:

"Hello, am I speaking with Rahul Sharma?"

Candidate:

"Yes."

AI:

"Hi Rahul, I'm an AI recruitment assistant calling on behalf of ABC Technologies regarding a job opportunity. Is this a good time for a quick screening conversation?"

Candidate:

"Yes, that's fine."

AI:

"Thank you. Could you tell me where you're currently located?"

Candidate:

"I'm living in Gurgaon and currently working at Infosys."

The agent should extract both:

```json
{
  "current_location": "Gurgaon",
  "current_company": "Infosys"
}
```

It should not ask for the company again.

### Conversation state

Maintain the following state throughout each call:

```json
{
  "candidate_id": "uuid",
  "call_id": "uuid",
  "conversation_status": "in_progress",
  "current_question": "total_experience",
  "collected_data": {
    "current_location": "Gurgaon",
    "current_company": "Infosys",
    "total_experience": null,
    "relevant_experience": null,
    "current_ctc": null,
    "expected_ctc": null,
    "notice_period": null,
    "reason_for_change": null,
    "interested": null,
    "interview_availability": null
  },
  "missing_fields": [
    "total_experience",
    "relevant_experience",
    "current_ctc",
    "expected_ctc",
    "notice_period",
    "reason_for_change",
    "interested",
    "interview_availability"
  ],
  "callback_requested": false,
  "opted_out": false
}
```

### State management rules

- Update state after every candidate response.
- Never discard previously confirmed information.
- Do not replace a valid answer with null.
- Do not invent answers.
- Allow unknown and declined answers.
- Track whether a field was explicitly confirmed.
- Distinguish a missing answer from a candidate refusing to answer.
- Preserve the transcript as the original conversation record.

### Agent output contract

The LLM should return structured output that can be validated with Pydantic.

Use a schema similar to:

```json
{
  "response_text": "Thanks for sharing that. How many years of total experience do you have?",
  "extracted_fields": {
    "current_location": "Gurgaon",
    "current_company": "Infosys"
  },
  "next_action": "ask_question",
  "next_question": "total_experience",
  "conversation_complete": false,
  "callback_requested": false,
  "opt_out": false
}
```

Allowed next actions:

- `ask_question`
- `clarify`
- `answer_candidate`
- `schedule_callback`
- `end_call`
- `escalate`

Validate every response before using it.

Do not rely on free-form LLM text alone to update database fields.

---

## Module D: Voice processing engine

Implement a chained voice pipeline:

```text
Incoming Phone Audio
       |
       v
Audio Stream Handler
       |
       v
Voice Activity Detection
       |
       v
Streaming STT
       |
       v
Transcript
       |
       v
Screening Agent
       |
       v
Response Text
       |
       v
Sentence Chunker
       |
       v
Kitten TTS
       |
       v
Audio Conversion
       |
       v
Telephony Playback
```

### STT service

Create an interface:

```python
class STTProvider:
    async def start_stream(self):
        pass

    async def send_audio(self, audio_chunk: bytes):
        pass

    async def get_transcription(self):
        pass

    async def close(self):
        pass
```

Implement a Deepgram adapter initially.

Keep the provider isolated so it can be replaced later.

### TTS service

Create an interface:

```python
class TTSProvider:
    async def initialize(self):
        pass

    async def synthesize(self, text: str) -> bytes:
        pass

    async def close(self):
        pass
```

Implement Kitten TTS.

Requirements:

- Load the model once per TTS worker.
- Avoid loading the model for every sentence.
- Benchmark first-sentence latency.
- Benchmark complete sentence latency.
- Verify audio quality.
- Validate the output sample rate.
- Return audio in the format expected by the audio pipeline.
- Add a configurable voice.
- Add error handling for model failures.

### Audio conversion

Do not assume that the telephony format and Kitten output format are the same.

The implementation must:

- Inspect the actual incoming media format.
- Inspect the actual outgoing media requirements.
- Convert sample rates as necessary.
- Convert codecs as necessary.
- Maintain correct audio chunk boundaries.
- Avoid sending unsupported audio frames.
- Avoid sending audio from a previous call to another candidate.

Do not hardcode a 24 kHz or 8 kHz format without confirming the provider's actual media protocol.

### VAD and interruption handling

Implement:

- Candidate speech detection.
- End-of-utterance detection.
- Silence timeout.
- Maximum utterance duration.
- Background noise handling.
- Barge-in support.
- TTS playback cancellation when the candidate interrupts.

For the first prototype, prioritize reliable turn-taking over complex emotional or sentiment detection.

---

## Module E: Telephony integration

Use Exotel as the first telephony adapter.

### Required capabilities

- Initiate outbound calls.
- Associate provider call IDs with internal call IDs.
- Receive call status webhooks.
- Connect the call to the audio-processing backend.
- Stream candidate audio.
- Play AI-generated audio.
- Detect call completion.
- Detect busy/no-answer/failure.
- Handle disconnected WebSockets.
- Handle provider timeouts.

### Telephony adapter

Create a provider-independent interface:

```python
class TelephonyProvider:
    async def initiate_call(self, candidate, call_session):
        pass

    async def handle_webhook(self, payload):
        pass

    async def terminate_call(self, provider_call_id):
        pass

    async def get_call_status(self, provider_call_id):
        pass
```

Implement Exotel behind this interface.

### Important implementation gate

Before writing the live audio handler:

1. Obtain Exotel account credentials.
2. Confirm the enabled outbound calling product.
3. Confirm the account supports the required real-time audio integration.
4. Read the current official WebSocket/audio protocol documentation.
5. Create a minimal test call.
6. Verify bidirectional audio.
7. Verify the provider's supported codec and sample rate.
8. Verify call status webhooks.

If the selected account does not expose bidirectional audio streaming, stop and resolve the telephony integration choice before building the full voice pipeline.

Do not create a fake WebSocket implementation and claim that actual calls are working.

---

## Module F: Call orchestration

Responsibilities:

- Create call attempts.
- Validate candidate eligibility.
- Queue calls.
- Prevent duplicate simultaneous calls.
- Start outbound calls.
- Track provider call IDs.
- Process webhooks.
- Update call state.
- Save call results.

### Call states

Use these statuses:

```text
pending
queued
initiating
ringing
in_progress
completed
no_answer
busy
failed
cancelled
callback_requested
retry_scheduled
exhausted
```

Keep screening status separate from telephony status.

Example:

- Call status: completed
- Screening status: partially_completed

This is important because a call can finish without all screening questions being answered.

### Call lifecycle

```text
Recruiter clicks Start
          |
          v
Create Call Attempt
          |
          v
Queue Call
          |
          v
Worker Processes Job
          |
          v
Initiate Exotel Call
          |
          v
Receive Provider Events
          |
          v
Connect Voice Pipeline
          |
          v
Run Screening Conversation
          |
          v
Call Ends
          |
          v
Save Final Results
          |
          v
Update Dashboard
```

---

## Module G: Transcript and summary generation

Store conversation messages with:

- Call ID
- Speaker
- Message text
- Timestamp
- Message sequence number

Example:

```json
[
  {
    "speaker": "assistant",
    "text": "Where are you currently located?",
    "timestamp": "2026-11-18T10:00:00Z"
  },
  {
    "speaker": "candidate",
    "text": "I'm currently in Gurgaon.",
    "timestamp": "2026-11-18T10:00:04Z"
  }
]
```

### Summary format

Generate a concise recruiter-friendly summary containing:

- Candidate profile
- Experience
- Current and expected compensation
- Notice period
- Reason for job change
- Interest in the role
- Interview availability
- Missing information
- Callback request, if applicable

Never classify a candidate as suitable or unsuitable solely from the AI's unsupported opinion.

Use neutral summaries based on collected answers.

---

## Module H: Google Sheets integration

Use the official Google Sheets API.

### Suggested spreadsheet columns

1. Candidate ID
2. Candidate Name
3. Phone Number
4. Email
5. Job Role
6. Current Location
7. Current Company
8. Total Experience
9. Relevant Experience
10. Current CTC
11. Expected CTC
12. Notice Period
13. Reason for Change
14. Interested
15. Interview Availability
16. Call Status
17. Screening Status
18. Attempt Count
19. Last Call Date
20. Next Retry Date
21. Call Summary
22. Transcript Reference
23. Last Updated

### Synchronization rules

- PostgreSQL is the source of truth.
- Synchronize after database transactions commit.
- Use Candidate ID to identify the row.
- Update an existing row instead of appending duplicate rows.
- Retry failed synchronization jobs.
- Log Google API failures.
- Never lose candidate data because Sheets is unavailable.

Create a dedicated `sheets_service.py`.

Do not place Google credentials in frontend code or commit them to Git.

---

## Module I: Retry scheduler

Implement configurable retries.

Default configuration:

```json
{
  "enabled": true,
  "max_attempts": 3,
  "retry_interval_days": 2,
  "retry_on": [
    "no_answer",
    "busy",
    "temporary_failure"
  ],
  "stop_on": [
    "completed",
    "candidate_declined",
    "invalid_number",
    "opted_out"
  ]
}
```

### Retry rules

- Do not retry successful screening calls.
- Do not retry candidates who declined.
- Do not retry candidates who opted out.
- Do not retry invalid phone numbers.
- Do not automatically retry callback requests at an arbitrary interval; respect the requested callback time.
- Prevent duplicate scheduled retries.
- Enforce a maximum number of attempts.
- Record every attempt independently.
- Respect applicable calling-hour and consent requirements.

For the first version, use a two-day interval and allow the recruiter to configure it to 3 or 4 days.

---

# 5. Database schema

Use PostgreSQL and SQLAlchemy.

Create the following tables.

## Table: candidates

```text
id UUID PRIMARY KEY
name VARCHAR
phone VARCHAR
email VARCHAR NULL
job_id UUID
source VARCHAR NULL
resume_url TEXT NULL

current_location VARCHAR NULL
current_company VARCHAR NULL
total_experience FLOAT NULL
relevant_experience FLOAT NULL
current_ctc FLOAT NULL
expected_ctc FLOAT NULL
notice_period VARCHAR NULL
reason_for_change TEXT NULL
interested BOOLEAN NULL
interview_availability TEXT NULL

screening_status VARCHAR
opted_out BOOLEAN DEFAULT FALSE

created_at TIMESTAMP
updated_at TIMESTAMP
```

## Table: jobs

```text
id UUID PRIMARY KEY
job_title VARCHAR
company_name VARCHAR
job_description TEXT
location VARCHAR
required_experience VARCHAR
skills JSONB
screening_questions JSONB
agent_instructions TEXT
is_active BOOLEAN
created_at TIMESTAMP
updated_at TIMESTAMP
```

## Table: call_attempts

```text
id UUID PRIMARY KEY
candidate_id UUID REFERENCES candidates(id)

attempt_number INTEGER
provider VARCHAR
provider_call_id VARCHAR NULL

call_status VARCHAR
start_time TIMESTAMP NULL
end_time TIMESTAMP NULL
duration_seconds INTEGER NULL

recording_url TEXT NULL
failure_reason TEXT NULL

next_retry_at TIMESTAMP NULL
retry_count INTEGER DEFAULT 0

created_at TIMESTAMP
updated_at TIMESTAMP
```

## Table: conversations

```text
id UUID PRIMARY KEY
call_attempt_id UUID REFERENCES call_attempts(id)

transcript JSONB
summary TEXT NULL
extracted_data JSONB

screening_completed BOOLEAN
created_at TIMESTAMP
updated_at TIMESTAMP
```

## Table: sync_logs

```text
id UUID PRIMARY KEY
candidate_id UUID REFERENCES candidates(id)

provider VARCHAR
sync_status VARCHAR
error_message TEXT NULL
synced_at TIMESTAMP NULL

created_at TIMESTAMP
```

## Additional implementation requirements

- Add foreign-key constraints.
- Add indexes for phone, job ID, call status and retry date.
- Add uniqueness or idempotency protections for provider call IDs where appropriate.
- Store timestamps in UTC.
- Use migrations.
- Never store API credentials in database records.

---

# 6. API endpoint design

Use REST APIs with consistent JSON response formats.

## Candidate endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/candidates` | Create candidate |
| GET | `/api/v1/candidates` | List candidates |
| GET | `/api/v1/candidates/{id}` | Candidate details |
| PATCH | `/api/v1/candidates/{id}` | Update candidate |
| DELETE | `/api/v1/candidates/{id}` | Delete candidate |
| POST | `/api/v1/candidates/import` | Upload CSV/Excel |
| GET | `/api/v1/candidates/import/{id}` | Import result |

## Calling endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/calls/start` | Start calling selected candidates |
| POST | `/api/v1/calls/{id}/retry` | Manually retry a call |
| POST | `/api/v1/calls/{id}/cancel` | Cancel eligible call |
| GET | `/api/v1/calls` | List call attempts |
| GET | `/api/v1/calls/{id}` | Call details |
| GET | `/api/v1/calls/{id}/transcript` | Retrieve transcript |

## Dashboard endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/dashboard/stats` | Dashboard metrics |
| GET | `/api/v1/dashboard/activity` | Recent call activity |
| GET | `/api/v1/dashboard/attention` | Candidates needing attention |

## Integration endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/webhooks/exotel` | Telephony status events |
| POST | `/api/v1/webhooks/exotel/stream` | Streaming connection, if required by provider protocol |
| POST | `/api/v1/integrations/google-sheets/sync/{id}` | Manual sync |
| GET | `/api/v1/integrations/google-sheets/status` | Integration status |

The actual WebSocket route and handshake must follow the selected telephony product's official protocol. Do not assume the HTTP webhook and audio WebSocket have identical responsibilities.

---

# 7. Frontend pages

Create a simple recruiter-focused interface.

## Page 1: Dashboard

Display:

- Total candidates
- Calls completed
- Calls pending
- Calls in progress
- Unanswered calls
- Failed calls
- Interested candidates
- Screening completed

Add:

- Recent call activity
- Candidates needing attention
- Calling progress
- Quick start calling action

## Page 2: Candidates

Display a table with:

- Candidate name
- Phone
- Job role
- Experience
- Call status
- Screening status
- Interest
- Last call date
- Actions

Actions:

- View candidate
- Call
- Retry
- View transcript

Add search and status filters.

## Page 3: Upload candidates

Include:

- Upload file
- File format instructions
- Column mapping
- Import preview
- Validation errors
- Duplicate information
- Confirm import button

## Page 4: Candidate details

Display:

- Candidate profile
- Screening answers
- Call history
- Call transcript
- AI summary
- Recording link, if supported and authorized
- Retry action
- Google Sheets sync status

## Page 5: Settings

Display:

- Telephony connection status
- OpenAI connection status
- STT connection status
- TTS status
- Google Sheets status
- Retry configuration
- Organization name
- Agent introduction
- Calling preferences

Do not expose secret API keys in the UI.

---

# 8. Suggested folder structure

```text
ai-recruitment-agent/
│
├── frontend/
│   ├── app/
│   │   ├── dashboard/
│   │   ├── candidates/
│   │   ├── calls/
│   │   ├── settings/
│   │   └── layout.tsx
│   ├── components/
│   ├── hooks/
│   ├── lib/
│   ├── services/
│   └── types/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   │
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── candidates.py
│   │   │       ├── imports.py
│   │   │       ├── calls.py
│   │   │       ├── dashboard.py
│   │   │       ├── settings.py
│   │   │       └── webhooks.py
│   │   │
│   │   ├── agent/
│   │   │   ├── screening_agent.py
│   │   │   ├── prompts.py
│   │   │   ├── state.py
│   │   │   ├── extraction.py
│   │   │   ├── schemas.py
│   │   │   └── conversation_manager.py
│   │   │
│   │   ├── voice/
│   │   │   ├── pipeline.py
│   │   │   ├── websocket_handler.py
│   │   │   ├── audio_processor.py
│   │   │   ├── audio_converter.py
│   │   │   ├── vad.py
│   │   │   ├── chunker.py
│   │   │   └── interruption.py
│   │   │
│   │   ├── providers/
│   │   │   ├── llm/
│   │   │   │   ├── base.py
│   │   │   │   └── openai_provider.py
│   │   │   ├── stt/
│   │   │   │   ├── base.py
│   │   │   │   └── deepgram_provider.py
│   │   │   ├── tts/
│   │   │   │   ├── base.py
│   │   │   │   └── kitten_provider.py
│   │   │   └── telephony/
│   │   │       ├── base.py
│   │   │       └── exotel_provider.py
│   │   │
│   │   ├── services/
│   │   │   ├── candidate_service.py
│   │   │   ├── import_service.py
│   │   │   ├── call_service.py
│   │   │   ├── summary_service.py
│   │   │   └── sheets_service.py
│   │   │
│   │   ├── workers/
│   │   │   ├── call_worker.py
│   │   │   ├── sync_worker.py
│   │   │   └── retry_worker.py
│   │   │
│   │   ├── database/
│   │   │   ├── connection.py
│   │   │   ├── models/
│   │   │   └── migrations/
│   │   │
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── utils/
│   │   └── tests/
│   │
│   ├── requirements.txt
│   └── Dockerfile
│
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── docs/
    ├── architecture.md
    ├── api.md
    ├── telephony.md
    └── setup.md
```

The coding agent may make small structural improvements, but it must preserve separation between API routes, business logic, provider adapters, voice processing and persistence.

---

# 9. Environment configuration

Create `.env.example`.

```env
APP_ENV=development
APP_SECRET_KEY=

DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/recruitment_ai

REDIS_URL=redis://localhost:6379/0

OPENAI_API_KEY=
OPENAI_MODEL=

DEEPGRAM_API_KEY=

EXOTEL_API_KEY=
EXOTEL_API_TOKEN=
EXOTEL_ACCOUNT_SID=
EXOTEL_SUBDOMAIN=
EXOTEL_CALLER_ID=

KITTEN_MODEL_PATH=
KITTEN_VOICE=

GOOGLE_SERVICE_ACCOUNT_JSON=
GOOGLE_SHEET_ID=

MAX_CONCURRENT_CALLS=1
MAX_CALL_ATTEMPTS=3
RETRY_INTERVAL_DAYS=2

PUBLIC_BACKEND_URL=
```

Use the exact environment variables required by the selected Exotel account and product documentation. Do not invent credential names or API paths.

### Secret management rules

- Keep `.env` out of Git.
- Provide `.env.example` without actual credentials.
- Never print API keys in logs.
- Never send provider credentials to the frontend.
- Use a service account with minimum required Google Sheets permissions.
- Validate required settings at application startup.

---

# 10. Development phases and execution order

The AI coding agent must implement the application in the following sequence.

## Phase 0 — Repository and architecture setup

Tasks:

1. Inspect the repository.
2. Create the frontend and backend directories.
3. Initialize Next.js with TypeScript.
4. Initialize FastAPI.
5. Add Docker Compose.
6. Configure PostgreSQL.
7. Configure Redis.
8. Add environment validation.
9. Add health-check endpoints.
10. Create architecture documentation.

Acceptance criteria:

- Frontend starts successfully.
- Backend starts successfully.
- PostgreSQL connection works.
- Redis connection works.
- Health endpoints return valid responses.
- No secrets are committed.

## Phase 1 — Database and candidate management

Tasks:

1. Create SQLAlchemy models.
2. Configure Alembic.
3. Create initial migrations.
4. Implement candidate CRUD.
5. Implement job CRUD.
6. Implement Excel/CSV parsing.
7. Implement validation.
8. Implement duplicate detection.
9. Build upload preview.
10. Build candidate list and detail pages.

Acceptance criteria:

- Recruiter can import candidates.
- Invalid rows are reported.
- Duplicate records are identified.
- Candidate data persists after restart.
- Recruiter can view and update candidates.

## Phase 2 — AI screening logic without telephony

First build and test the agent using text conversations.

Tasks:

1. Configure OpenAI API.
2. Create the system prompt.
3. Define Pydantic schemas.
4. Implement conversation state.
5. Implement field extraction.
6. Implement missing-field tracking.
7. Implement next-question selection.
8. Implement clarification behaviour.
9. Implement callback and opt-out logic.
10. Implement final summary generation.

Acceptance criteria:

- Agent can complete a simulated text screening.
- Agent extracts multiple fields from one answer.
- Agent does not repeat answered questions.
- Agent can handle unclear answers.
- Agent returns valid structured JSON.
- Agent does not invent missing information.

Do not proceed until this phase passes tests.

## Phase 3 — Kitten TTS integration

Tasks:

1. Install the selected Kitten TTS package.
2. Download/configure the intended lightweight English model.
3. Create the TTS provider interface.
4. Load the model once.
5. Generate speech from text.
6. Verify audio output.
7. Benchmark latency.
8. Implement sentence chunking.
9. Add error handling.

Acceptance criteria:

- The TTS service can synthesize arbitrary agent responses.
- Model is not reloaded for each response.
- Audio output can be played in a local test.
- Model output sample rate is known.
- Latency measurements are recorded.

## Phase 4 — STT integration

Tasks:

1. Create the STT provider interface.
2. Integrate Deepgram streaming transcription.
3. Send test microphone audio.
4. Receive partial/final transcripts.
5. Handle silence.
6. Handle transcription errors.
7. Connect final transcripts to the screening agent.

Acceptance criteria:

- Spoken English is transcribed.
- Final transcripts reach the agent.
- Empty or failed transcription does not crash the session.
- Each transcript is linked to its correct call session.

## Phase 5 — Telephony proof of concept

This is the highest-risk integration.

Tasks:

1. Verify Exotel account and product availability.
2. Read the current official integration documentation.
3. Configure a public HTTPS callback endpoint.
4. Implement outbound call initiation.
5. Receive provider webhooks.
6. Establish the required real-time media connection.
7. Inspect inbound audio.
8. Play test audio back to the phone.
9. Verify audio encoding and sample rate.
10. Verify call termination and status updates.

Acceptance criteria:

- One real test call can be initiated.
- Candidate answers the phone.
- Backend receives actual candidate audio.
- Backend can send generated audio back.
- Candidate can hear the AI.
- Call disconnects correctly.
- Provider events update the correct call attempt.

Do not fake any part of this integration.

## Phase 6 — Complete voice conversation

Tasks:

1. Connect incoming audio to VAD.
2. Connect VAD to STT.
3. Connect STT to the screening agent.
4. Connect agent output to Kitten TTS.
5. Connect TTS audio to the telephony stream.
6. Implement conversational turn management.
7. Implement interruption handling.
8. Implement silence and timeout handling.
9. Implement call completion logic.
10. Save transcript messages.

Acceptance criteria:

- Candidate can complete a real screening call.
- Agent can ask the required questions.
- Agent understands candidate answers.
- Agent can handle natural variations.
- Agent stops playback when the candidate interrupts, where supported by the media protocol.
- No audio crosses between candidate sessions.

## Phase 7 — Structured data and Google Sheets

Tasks:

1. Implement final extraction.
2. Validate final screening data.
3. Save results to PostgreSQL.
4. Generate summary.
5. Configure Google service account.
6. Implement Sheets API client.
7. Create sheet row lookup by Candidate ID.
8. Implement row insert/update.
9. Add synchronization logs.
10. Add retry for temporary sync failures.

Acceptance criteria:

- Completed calls update candidate records.
- Partial calls preserve collected information.
- Summary is available.
- Google Sheet receives the correct data.
- Repeated synchronization does not create duplicate rows.
- A temporary Sheets failure does not lose the database record.

## Phase 8 — Dashboard and call controls

Tasks:

1. Implement dashboard statistics.
2. Implement call status table.
3. Implement call initiation UI.
4. Implement candidate detail page.
5. Implement transcript view.
6. Implement summary view.
7. Implement call history.
8. Implement manual retry.
9. Implement live status refresh.
10. Implement error and loading states.

Acceptance criteria:

- Dashboard metrics reflect actual database values.
- Recruiter can initiate and monitor calls.
- Recruiter can view screening information.
- Recruiter can retry eligible candidates.
- Dashboard never relies on fake static statistics.

## Phase 9 — Automatic retry

Tasks:

1. Create retry configuration.
2. Implement retry scheduler.
3. Implement eligibility checks.
4. Implement attempt limits.
5. Prevent duplicate retry jobs.
6. Handle callback requests separately.
7. Handle opt-outs.
8. Display retry status in the dashboard.

Acceptance criteria:

- Eligible no-answer calls are scheduled.
- Retry happens after configured days.
- Maximum attempts are enforced.
- Declined and opted-out candidates are never retried.
- Candidate callback requests are handled at their requested time where feasible.

## Phase 10 — Final testing and deployment

Tasks:

1. Add integration tests.
2. Test actual calls.
3. Test invalid numbers.
4. Test busy/no-answer.
5. Test call disconnection.
6. Test partial screening.
7. Test Google Sheets failure.
8. Test retry scheduling.
9. Test concurrent call isolation.
10. Add deployment configuration.
11. Add setup documentation.
12. Conduct an end-to-end demo.

Acceptance criteria:

A recruiter can upload candidates, initiate real calls, complete screening, view summaries and see the updated Google Sheet.

---

# 11. Testing strategy

Do not depend only on manual testing.

## Unit tests

Test:

- Candidate validation
- Phone normalization
- Duplicate detection
- Pydantic schemas
- Extraction validation
- Conversation state
- Missing-field detection
- Retry eligibility
- Sheets row mapping

## Agent conversation tests

Test these candidate responses:

1. Candidate answers one question normally.
2. Candidate answers two or more questions together.
3. Candidate provides an unclear answer.
4. Candidate refuses to provide salary.
5. Candidate asks what the job is about.
6. Candidate is busy.
7. Candidate requests a callback.
8. Candidate declines the opportunity.
9. Candidate asks not to be called again.
10. Candidate provides information that contradicts an earlier answer.

## Voice tests

Test:

- Clear speech
- Background noise
- Long pauses
- Short answers
- Candidate interruption
- Silence
- STT failure
- TTS failure
- Telephony disconnection

## End-to-end test

Use one authorized test candidate first.

Verify:

```text
Candidate Uploaded
       |
       v
Candidate Record Created
       |
       v
Call Initiated
       |
       v
Candidate Answers
       |
       v
AI Conversation
       |
       v
Screening Data Extracted
       |
       v
Transcript Saved
       |
       v
Summary Generated
       |
       v
PostgreSQL Updated
       |
       v
Google Sheet Updated
       |
       v
Dashboard Updated
```

---

# 12. Non-functional requirements

The coding agent must also implement:

### Reliability

- Provider timeouts.
- Retry handling for temporary API errors.
- Idempotent webhooks.
- Idempotent database updates.
- Session cleanup.
- Graceful shutdown.
- Error logging.

### Security

- Backend-only API keys.
- Authentication for recruiter dashboard.
- Protected API routes.
- HTTPS for public endpoints.
- Secure credential storage.
- Access controls for transcripts and recordings.
- Candidate opt-out enforcement.

### Observability

Log:

- Candidate ID
- Call attempt ID
- Provider call ID
- STT latency
- LLM latency
- TTS latency
- Audio processing errors
- Call duration
- Sheets sync status

Never log sensitive credentials or unnecessarily expose full candidate information.

### Performance

For the first MVP:

- Start with one concurrent call.
- Test two concurrent calls before enabling that configuration.
- Keep TTS model warm.
- Avoid blocking the FastAPI event loop with CPU-heavy inference.
- Use bounded audio buffers.
- Clean up WebSocket resources after every call.

---

# 13. Important scope exclusions for the first release

Do not build these unless the core demo is already working:

- Bulk calling at hundreds of calls simultaneously.
- Multiple organizations and multi-tenancy.
- CRM integrations.
- Job portal scraping.
- Automated candidate sourcing.
- Resume parsing.
- Interview calendar booking.
- Complex analytics.
- Candidate ranking based on subjective AI judgments.
- Multiple languages.
- Advanced emotion detection.

The first release must focus on one reliable English-language screening workflow.

---

# 14. Definition of Done

The MVP is complete only when all of the following are verified:

- [ ] Frontend and backend run successfully.
- [ ] Recruiter can upload an Excel/CSV file.
- [ ] Candidate data is saved in PostgreSQL.
- [ ] Recruiter can select a candidate.
- [ ] Backend initiates an actual outbound call.
- [ ] Candidate can hear the AI introduction.
- [ ] Candidate can respond using speech.
- [ ] STT transcribes candidate speech.
- [ ] OpenAI generates context-aware responses.
- [ ] Kitten TTS generates the agent voice.
- [ ] Candidate hears the generated response.
- [ ] Agent collects the required recruitment fields.
- [ ] Agent handles unanswered questions and callbacks.
- [ ] Transcript is saved.
- [ ] Screening summary is generated.
- [ ] Candidate record is updated.
- [ ] Google Sheet is updated.
- [ ] Dashboard displays the actual call status.
- [ ] Manual retry works.
- [ ] Automatic retry works for eligible calls.
- [ ] Opt-outs are enforced.
- [ ] At least three complete test calls have been verified.

---

# 15. MASTER PROMPT FOR THE AI CODING AGENT

Copy the following instructions into your coding agent after opening the project repository.

---

You are acting as a Senior Python Backend Engineer, AI Engineer, Voice AI Engineer and Full-Stack Developer.

Your task is to build a complete, functional AI Recruitment Voice Calling Agent according to the technical blueprint in this document.

## Project goal

Build an application where recruiters upload candidate information, an AI agent calls candidates using real outbound telephony, conducts natural recruitment screening conversations, extracts information, generates summaries and updates PostgreSQL and Google Sheets.

This must be a functional product prototype. Do not build a mock-only application.

## Mandatory technology stack

- Frontend: Next.js + TypeScript + Tailwind CSS
- Backend: Python + FastAPI
- Database: PostgreSQL
- ORM: SQLAlchemy 2.x
- Migrations: Alembic
- Queue: Redis
- Worker: ARQ or Celery
- LLM: OpenAI API
- STT: Deepgram streaming
- TTS: Kitten TTS
- Telephony: Exotel
- Spreadsheet: Google Sheets API
- Deployment: Docker Compose

## Engineering instructions

1. First inspect the existing repository.
2. Do not overwrite existing user files without understanding their purpose.
3. Create a clear implementation plan before coding.
4. Follow the development phases in this document.
5. Implement one phase at a time.
6. Keep backend modules modular and independently testable.
7. Use async FastAPI endpoints where appropriate.
8. Use Pydantic v2 for validation.
9. Use SQLAlchemy models and Alembic migrations.
10. Keep all credentials in environment variables.
11. Add unit tests for core business logic.
12. Add integration tests for external provider adapters where practical.
13. Never hardcode fake candidate data into production dashboard metrics.
14. Never simulate a real phone call and mark it as successful.
15. Never claim that a provider integration works before an actual test call succeeds.
16. Never use mock responses as the production AI response path.
17. Do not skip error handling.
18. Do not skip database persistence.
19. Do not skip transcript storage.
20. Do not skip Google Sheets synchronization.
21. Follow the actual provider API documentation instead of inventing endpoints or payload formats.

## Critical architecture requirements

- Use a stateful screening agent.
- Maintain one isolated session per call.
- Use streaming STT.
- Use OpenAI for reasoning and response generation.
- Use Kitten TTS for speech generation.
- Stream or chunk TTS output where the telephony protocol permits it.
- Implement VAD and interruption handling.
- Implement provider webhook processing.
- Implement idempotency for call events.
- Separate telephony status from screening status.
- Store each call attempt separately.
- Keep PostgreSQL as the source of truth.
- Synchronize Google Sheets after successful database persistence.
- Implement a retry scheduler with a maximum of three attempts.
- Do not retry candidates who declined or opted out.

## Development workflow

For every phase:

1. Explain what you intend to implement.
2. Identify the files you will create or modify.
3. Implement the module.
4. Run formatting and type checks where applicable.
5. Run relevant tests.
6. Fix errors before moving forward.
7. Update README and technical documentation.
8. Report completed functionality.
9. List anything that requires credentials or manual provider configuration.
10. Never mark an incomplete integration as complete.

## Work in this order

Phase 0: Repository and infrastructure setup.

Phase 1: Database, candidate management and Excel import.

Phase 2: Text-based recruitment screening agent.

Phase 3: Kitten TTS.

Phase 4: Deepgram STT.

Phase 5: Exotel real outbound calling and audio streaming proof of concept.

Phase 6: Complete real-time voice pipeline.

Phase 7: Structured extraction, transcripts, summaries and Google Sheets.

Phase 8: Recruiter dashboard and call controls.

Phase 9: Retry scheduler.

Phase 10: End-to-end testing and deployment.

## Strict development rules

- Do not implement the entire project in one enormous code-generation step.
- Do not create unnecessary abstractions.
- Do not introduce LangChain or another agent framework unless a specific technical requirement justifies it.
- Prefer straightforward Python services and explicit state management.
- Do not expose secrets to the browser.
- Do not mix database logic into API route handlers.
- Do not mix provider-specific logic into the core agent.
- Do not make network calls from the frontend directly to Exotel, Deepgram or OpenAI.
- Do not use a mock calling service as a substitute for real telephony.
- Do not automatically call candidates without configured consent and calling eligibility.
- Keep the initial voice language English.
- Do not expand the MVP scope without explaining why.

## First task

Start with Phase 0 only.

Before writing code:

1. Inspect the repository.
2. Identify the current environment.
3. Check installed Python and Node versions.
4. Propose the exact folder structure.
5. Create a concise implementation checklist.
6. Identify external credentials that will be needed.
7. Identify the Exotel real-time audio integration dependency as an early technical risk.

Then implement Phase 0, run the project and report the result.

Do not proceed to Phase 1 until Phase 0 is verified and the user has reviewed the result.

---

# 16. External accounts and credentials checklist

Before attempting the full real-call implementation, arrange:

| Service | Required setup |
|---|---|
| OpenAI | API key and enabled API billing |
| Deepgram | API key and streaming access |
| Kitten TTS | Selected English model and local installation |
| Exotel | Account, outbound calling setup, approved caller ID and required streaming capability |
| Google Cloud | Project with Google Sheets API enabled |
| Google Sheets | Spreadsheet and service-account access |
| Hosting | Public HTTPS backend URL for telephony callbacks |

Do not place real credentials in the master prompt or source code. Add them through `.env`.

# 17. Recommended first working milestone

Your first milestone should not be the dashboard.

Build and verify this:

```text
Recruiter
   |
   v
Select one test candidate
   |
   v
Click Start Call
   |
   v
Exotel calls your phone
   |
   v
AI introduces itself
   |
   v
You answer in English
   |
   v
AI understands your response
   |
   v
AI responds using Kitten TTS
   |
   v
You complete the screening
   |
   v
System saves structured answers
   |
   v
Google Sheet updates
```

Once this works reliably, the dashboard, upload flow and retry system become much more straightforward to build.

**Final development priority:** Real calling → Natural conversation → Correct extraction → Reliable persistence → Google Sheets → Dashboard → Retry automation.

This order minimizes the biggest integration risk and prevents spending most of the development time on a UI that cannot perform the actual task.