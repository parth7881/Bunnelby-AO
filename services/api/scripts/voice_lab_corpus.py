from __future__ import annotations

SAMPLES = [
    {
        "id": "hi_calendar",
        "language": "hi",
        "text": "सर, आज सुबह 10 AM पर Project Review है और शाम 8 PM पर business planning event है।",
    },
    {
        "id": "hi_technical",
        "language": "hi",
        "text": "Bunnelby ने Gmail, Google Calendar, GPU और API status check कर लिया है।",
    },
    {
        "id": "hinglish_command",
        "language": "hi",
        "text": "सर, आपका system ready है। VS Code चल रहा है, GPU available है, और कोई urgent calendar conflict नहीं है।",
    },
    {
        "id": "en_command",
        "language": "en",
        "text": "Sir, your system is ready. I checked Gmail and Calendar. There are no urgent conflicts this afternoon.",
    },
    {
        "id": "en_machine",
        "language": "en",
        "text": "Bunnelby online. Core systems stable. Awaiting your command, sir.",
    },
]

# Target perceptual criteria. These are intentionally provider-neutral.
RATING_CRITERIA = {
    "pronunciation": "Hindi/Hinglish words, names, acronyms and clock times sound correct.",
    "clarity": "Every word remains intelligible at normal laptop speaker volume.",
    "authority": "Delivery feels confident, controlled and decisive rather than soft or cheerful.",
    "machine_presence": "Voice has a subtle synthetic command-system identity without sounding distorted.",
    "natural_pacing": "Pauses and tempo feel deliberate, not rushed or sluggish.",
    "latency": "Short replies begin quickly enough for conversational assistant use.",
}
