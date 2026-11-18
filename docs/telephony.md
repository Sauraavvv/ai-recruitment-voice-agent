# Telephony (Exotel)

Status: **enablement in progress**. Verified protocol details are filled in during [Phase 5](phases/phase-05-telephony-poc.md). Nothing below is to be coded against until marked verified.

## 1. Enablement tracker (started in Phase 0)

The whole voice pipeline depends on question 2. If the answer is "no" or "not on your plan", stop and decide the telephony approach before Phase 5 (plan.md Module E).

| # | Question for Exotel | Answer | Date | Ticket / contact |
|---|---|---|---|---|
| 1 | Account activation and KYC status; ExoPhone (virtual number) for outbound caller ID | Account active on a **free trial** (500 credits) with a trial number. Trial restrictions not yet confirmed. The existing custom app "makanmantraa1 Landing Flow" belongs to another project; leave it untouched | 2026-11-18 | Dashboard |
| 2 | Does our account/plan support **bidirectional real-time audio streaming** on outbound calls (Voicebot/stream applet)? | Not in the **Available Apps** marketplace (that tab lists third-party apps such as SquadVoice). Next: check the applet list in the flow builder (Custom Apps → CREATE), then ask support | 2026-11-18 | |
| 3 | Stream audio format: encoding, sample rate, channels, chunk-size rules | | | |
| 4 | Can we send audio back on the stream? Are playback-control messages (clear / mark) supported? | | | |
| 5 | How do we attach our own id (call attempt id) so it comes back in webhooks and the stream start message? | | | |
| 6 | Status callback payload and the full list of call statuses | | | |
| 7 | Concurrent-call limit on the account; per-minute cost | | | |
| 8 | DND/NCPR scrubbing and calling-hour rules for recruitment calls | | | |
| 9 | Webhook authentication options or source IP ranges | | | |
| 10 | Call recording availability and how recording URLs are accessed | | | |

## 2. Verified protocol (Phase 5)

_Empty until measured on a real call. Each fact gets a doc link and the date it was confirmed._

## 3. Test-call log (Phase 5)

| Date | Attempt id | Case | Expected | Actual | Notes |
|---|---|---|---|---|---|

## 4. Go / no-go (Phase 5)

_Pending._
