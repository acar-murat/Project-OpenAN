"""Path segment validation for resource addressing (port of Java ``PathSegments``).

A simple segment is non-blank and free of slashes, backslashes and ``..``
sequences, so that it can never escape the resource root it is resolved
against. The resource-root constant and path assembly are only allowed to live
in one place (see the port plan, section 7.2) — these predicates are that place.
"""

from __future__ import annotations

__all__ = [
    "is_simple_segment",
    "require_simple_relative_path",
    "require_simple_segment",
]


def is_simple_segment(value: str | None) -> bool:
    """Return True when the value is a non-blank simple path segment.

    Args:
        value: candidate path segment such as a language or category identifier.

    Returns:
        True when the value is non-``None``, non-blank and contains no slash,
        backslash or ``..`` sequence; False otherwise.
    """
    return value is not None and value.strip() != "" and "/" not in value and "\\" not in value and ".." not in value


def require_simple_segment(value: str | None, label: str) -> None:
    """Require the value to be a non-blank simple path segment.

    Args:
        value: candidate path segment such as a language or category identifier;
            may be ``None``.
        label: human-readable label describing the segment, used in the failure
            message.

    Raises:
        ValueError: when the value is not a simple path segment.
    """
    if not is_simple_segment(value):
        raise ValueError(f"{label} must be a non-blank simple path segment but was {value}.")


def require_simple_relative_path(value: str | None, label: str) -> None:
    """Require the value to be a non-blank relative path of simple segments.

    Args:
        value: candidate relative path such as a scenario code; may be ``None``.
        label: human-readable label describing the path, used in the failure
            message.

    Raises:
        ValueError: when the value is ``None``, blank or contains a non-simple
            path segment.
    """
    if value is None or value.strip() == "":
        raise ValueError(f"{label} must be a non-blank relative path but was {value}.")
    for segment in value.split("/"):
        if not is_simple_segment(segment):
            raise ValueError(f"{label} must contain only simple path segments but was {value}.")
