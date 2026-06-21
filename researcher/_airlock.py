from __future__ import annotations
import shared_contract


class AirlockError(ValueError):
    """Raised when an envelope fails airlock validation.

    This is the load-bearing security boundary between the untrusted
    Web Researcher and the privileged primary agent. Deterministic — no model.
    """


def validate_envelope(raw: str | bytes) -> dict:
    """Validate and sanitize a raw Research findings envelope.

    Raises AirlockError on any validation or schema failure.
    Returns a sanitized envelope dict on success.
    """
    try:
        return shared_contract.validate(raw)
    except ValueError as exc:
        raise AirlockError(str(exc)) from exc
