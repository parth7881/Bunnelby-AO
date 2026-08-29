# AO Prompt 2 — Orchestrator + Intent Routing

## SDK note

The original Prompt 2 named `google-generativeai`. Google now treats that SDK as the legacy SDK and recommends the current `google-genai` SDK. AO uses `google-genai` while keeping the requested Gemini Developer API, `gemini-2.5-flash`, function calling, and free-tier workflow.

## Why `task_log` instead of `messages.intent`

AO keeps chat history and tool-routing audit data separate. A chat message may later trigger more than one tool (for example, Gmail + Calendar in Phase 6), so a separate `task_log` scales better than forcing one intent onto one message row. The log stores the original user message, selected intent, Gemini's short reason, routing status, and timestamp.

## Manual routing tests

| Message | Expected intent |
|---|---|
| `Check my unread emails` | `gmail` |
| `Summarize the latest email from Rahul` | `gmail` |
| `Am I free tomorrow afternoon?` | `calendar` |
| `What meetings do I have on Monday?` | `calendar` |
| `Find my resume PDF on this computer` | `file_search` |
| `Search for files containing quarterly revenue` | `file_search` |
| `Run git status` | `terminal` |
| `Show me my Python version in the terminal` | `terminal` |
| `Explain what a vector database is` | `general_chat` |
| `Give me three startup name ideas` | `general_chat` |

Every successful response intentionally includes `Route:` and `Why:` while Prompt 2 is being debugged. Later phases can hide that routing metadata from the normal UI while preserving it in `task_log`.
