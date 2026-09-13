import logging
import re
from typing import Any, Dict, List, Optional, Pattern

from src.domain.entities import ApprovalOutcome
from src.persistence.repositories import (
    ApprovalDecisionRepository,
    ClassificationRepository,
    EmailMessageRepository,
    ProposedActionRepository,
)

logger = logging.getLogger(__name__)

_STRONG_SIGNAL_WEIGHT = 0.3
_MEDIUM_SIGNAL_WEIGHT = 0.15

_NEWSLETTER_PROMOTIONAL_LABELS = ("AI/Newsletter", "AI/Promotional")

_SENDER_DOMAIN_ALLOWLIST: Dict[str, str] = {
    "stripe.com": "AI/Billing",
    "paypal.com": "AI/Billing",
    "ups.com": "AI/Shipping",
    "usps.com": "AI/Shipping",
    "fedex.com": "AI/Shipping",
    "dhl.com": "AI/Shipping",
    "amazon.com": "AI/Shipping",
    "accounts.google.com": "AI/Security",
    "github.com": "AI/Security",
}

_TRANSACTIONAL_SUBJECT_PATTERN: Pattern[str] = re.compile(
    r"tracking|invoice|receipt|order\s*#|payment|shipped|delivery",
    re.IGNORECASE,
)
_TRANSACTIONAL_LABELS = ("AI/Shipping", "AI/Billing")


class Evaluator:
    """
    Interface for computing a deterministic agreement score between the
    classifier's predicted label and independent signals extracted from the
    message and its history, replacing model confidence per ADR-0006.

    Attributes:
        None.

    Methods:
        _list_unsubscribe_signal(label: str, headers: Dict[str, str]) -> Optional[bool]:
            Determines whether the List-Unsubscribe header confirms or contradicts the label.

        _sender_domain_signal(label: str, sender_domain: Optional[str]) -> Optional[bool]:
            Determines whether the sender domain allowlist confirms or contradicts the label.

        _transactional_subject_signal(label: str, subject: str) -> Optional[bool]:
            Determines whether a transactional subject pattern confirms or contradicts the label.

        _historical_sender_signal(label: str, sender: str) -> Optional[bool]:
            Determines whether the sender has previously been classified and approved with the same label.

        evaluate_with_signals(label: str, sender: str, sender_domain: Optional[str], subject: str, headers: Dict[str, str], injection_suspected: bool) -> Dict[str, Any]:
            Computes the agreement score together with the outcome of every individual signal.

        evaluate(label: str, sender: str, sender_domain: Optional[str], subject: str, headers: Dict[str, str], injection_suspected: bool) -> float:
            Computes the deterministic agreement score for the supplied classification and signals.
    """

    def _list_unsubscribe_signal(self, label: str, headers: Dict[str, str]) -> Optional[bool]:
        if "List-Unsubscribe" not in headers:
            return None
        return label in _NEWSLETTER_PROMOTIONAL_LABELS

    def _sender_domain_signal(self, label: str, sender_domain: Optional[str]) -> Optional[bool]:
        if not sender_domain or sender_domain not in _SENDER_DOMAIN_ALLOWLIST:
            return None
        return _SENDER_DOMAIN_ALLOWLIST[sender_domain] == label

    def _transactional_subject_signal(self, label: str, subject: str) -> Optional[bool]:
        if not _TRANSACTIONAL_SUBJECT_PATTERN.search(subject):
            return None
        return label in _TRANSACTIONAL_LABELS

    def _historical_sender_signal(self, label: str, sender: str) -> Optional[bool]:
        past_messages = EmailMessageRepository().list_by_sender(sender)
        if not past_messages:
            return None
        classification_repository = ClassificationRepository()
        action_repository = ProposedActionRepository()
        decision_repository = ApprovalDecisionRepository()
        for past_message in past_messages:
            classification = classification_repository.get_by_message_id(past_message.message_id)
            if classification is None or classification.label != label:
                continue
            for action in action_repository.list_by_message_id(past_message.message_id):
                decision = decision_repository.get_by_proposed_action_id(action.id)
                if decision is not None and decision.outcome == ApprovalOutcome.APPROVED:
                    return True
        return None

    def evaluate_with_signals(
        self,
        label: str,
        sender: str,
        sender_domain: Optional[str],
        subject: str,
        headers: Dict[str, str],
        injection_suspected: bool,
    ) -> Dict[str, Any]:
        if injection_suspected:
            logger.info("Agreement score forced to 0.0: injection suspected.")
            return {
                "agreement_score": 0.0,
                "signals": [{"name": "injection_suspected", "outcome": "contradicts"}],
            }

        score = 0.5
        named_signals = [
            ("list_unsubscribe_header", self._list_unsubscribe_signal(label, headers), _STRONG_SIGNAL_WEIGHT),
            ("sender_domain_allowlist", self._sender_domain_signal(label, sender_domain), _STRONG_SIGNAL_WEIGHT),
            ("transactional_subject_pattern", self._transactional_subject_signal(label, subject), _MEDIUM_SIGNAL_WEIGHT),
            ("historical_sender_approval", self._historical_sender_signal(label, sender), _STRONG_SIGNAL_WEIGHT),
        ]
        signal_details: List[Dict[str, str]] = []
        for name, outcome, weight in named_signals:
            if outcome is None:
                signal_details.append({"name": name, "outcome": "not_applicable"})
                continue
            score += weight if outcome else -weight
            signal_details.append({"name": name, "outcome": "confirms" if outcome else "contradicts"})

        score = max(0.0, min(1.0, score))
        logger.info(f"Agreement score successfully computed. Label: {label}. Score: {score:.2f}.")
        return {"agreement_score": score, "signals": signal_details}

    def evaluate(
        self,
        label: str,
        sender: str,
        sender_domain: Optional[str],
        subject: str,
        headers: Dict[str, str],
        injection_suspected: bool,
    ) -> float:
        result = self.evaluate_with_signals(label, sender, sender_domain, subject, headers, injection_suspected)
        return result["agreement_score"]
