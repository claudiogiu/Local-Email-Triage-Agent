from typing import List, Optional, TypedDict


class TriageGraphState(TypedDict):
    """Identifiers, references, and bounded intermediate results threaded through a single triage run."""

    run_id: str
    message_id: str
    normalized_subject: Optional[str]
    normalized_body: Optional[str]
    classification_label: Optional[str]
    priority_level: Optional[str]
    requires_reply: Optional[bool]
    next_action: Optional[str]
    proposed_action_ids: List[str]
    draft_action_id: Optional[str]
    draft_feedback: Optional[str]
    send_action_id: Optional[str]
    status: str
    error: Optional[str]
