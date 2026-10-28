# Responsible AI, privacy and safety

| Risk | What we do |
|---|---|
| **Consent for outreach** | Nobody is messaged unless they explicitly said yes to *that* need (`consent_at` set on the waitlist entry). "No thanks" creates nothing. Entries without consent are skipped even if matched (test: `test_no_consent_no_message`). Messages respect the shopper's stated budget. |
| **PII** | Phone numbers and e-mail addresses are masked before an event is stored, logged or streamed. The assistant is instructed never to ask for contact details, addresses or payment data. Customer ids are opaque. |
| **Hallucination** | The assistant may state availability and price only from tool results; numbers on the owner console come from deterministic code, never from model text. |
| **Prompt injection** | Shopper text is treated as data. Tools take identity and the pending offer from server-set session state, not model arguments; the shopper agent can't change prices, stock or other people's data (test: `test_prompt_injection_text_is_just_a_query`). `join_waitlist` takes no arguments. |
| **Over-automation** | Owner-side agents only *propose*. Orders, listings and messages need an explicit click and are written to an audit log. Suggestions are editable and the estimates say what they assume. |
| **Misleading statistics** | Trend percentages are hidden on tiny baselines; sizing assumptions (`ASSISTANT_REACH`, `CAPTURE_RATE`) are shown in the rationale and configurable; backtests are shown next to forecasts. |
| **Language equity** | English, Hindi and Telugu are first-class (search vocabulary, replies, outreach). Reply language follows the shopper, not the owner. Coverage of other languages depends on Gemini's own capability. |
| **Availability** | Time-outs and a deterministic fallback mean a slow or unavailable model never leaves a shopper without an answer. |
| **Abuse** | Input length caps and control-character stripping, id pattern validation, per-client rate limiting, owner endpoints behind an API key, demo endpoints disabled in production. |

## Before real customers

- Put Firebase Auth / Identity Platform in front of shopper endpoints (so a customer id can't be guessed to read someone's inbox).
- Use a WhatsApp / SMS provider with its own opt-in and template rules; keep `consent_at` as the source of truth and add a STOP/opt-out path.
- Define a retention period for `events` and `notifications`, and a deletion path per customer.
- Review Gemini safety settings and add evaluation sets for each supported language.
- Replace synthetic data with real sales and calibrate `ASSISTANT_REACH` and `CAPTURE_RATE` from a pilot.
