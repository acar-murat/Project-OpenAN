"""Negotiation resource domain types.

Port of the Java ``a2a-t-negotiation`` ``resources`` package reduced to its domain type: template
loading is owned by the common resource access layer (D31), so this package carries only
:class:`NegotiationReference` and its addressing validation — no IO, cache or path assembly.
"""

from __future__ import annotations

from .reference import COMMON_TYPE_SEGMENT, NegotiationReference, uri_segment_of

__all__ = ["COMMON_TYPE_SEGMENT", "NegotiationReference", "uri_segment_of"]
