from __future__ import annotations

NEGOTIATION_T_URI_NL = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/NL/v1"
NEGOTIATION_T_URI = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1"
TASK_PROMPT_KEY_NL = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/NL/v1"
TASK_PROMPT_KEY = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"
# Non-NL URI constants are retained for backward compatibility with external consumers
# that may still use the pre-IG1453 URI format. The SDK internally uses the _NL variants.
MAX_IN_PROGRESS_NEGOTIATION_ROUND = 8
