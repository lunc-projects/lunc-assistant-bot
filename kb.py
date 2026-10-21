"""Knowledge base — intentionally EMPTY / generic.
LUNC Assistant Bot is a standalone project, separate from the owner's other projects.
No other project info is included.
Owner can add per-group FAQs later via a future /kb_add admin command; v1 ships blank.
"""
KB = {}

def kb_as_text() -> str:
    return "No project-specific knowledge base is configured. This is a standalone general AI assistant. Answer generally and do not claim project-specific knowledge."

def find_kb_answer(q: str):
    return None
