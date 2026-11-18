# Exotel payloads

- `docs_*.json`: shaped from Exotel's v1 docs (read 2026-11-18).
- `captured_*.json`: recorded on real Phase 5 test calls (2026-11-19), sanitized: SIDs replaced,
  phone numbers and account SID masked, audio payloads replaced by their length.
  - `captured_stream_caller_hangup.json`: Voicebot stream of a call the tester hung up
    (connected, start, first media chunks, the echoed mark, stop).
  - `captured_status_*.json`: StatusCallback bodies as Exotel sent them (form-encoded; shown as
    JSON). The default callback has only Status, CallSid and DateUpdated.
