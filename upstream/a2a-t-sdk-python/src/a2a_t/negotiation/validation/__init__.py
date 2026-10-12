"""Negotiation validation pipeline (port of the Java ``a2a-t-negotiation`` ``validation`` package).

Three collaborators: the deterministic rule-level compliance checker of the negotiation context
(UUID shape and round budget) with its adapter to the core rule-checker contract, the LLM-backed
semantic validator enforcing the constant four-key output contract with the ``*.rule_violation``
fallback for unknown and cross-domain codes, and the parameter extractor running the shared core
:class:`~a2a_t.core.validation_pipeline.ValidationPipeline` over both gates — the real implementation
of the generation orchestrator's parameter-extractor seam.
"""

from __future__ import annotations

from .compliance_checker import (
    DefaultNegotiationComplianceChecker,
    NegotiationComplianceChecker,
    NegotiationRuleCheckerAdapter,
    NegotiationRuleCheckResult,
)
from .param_extractor import NegotiationTemplateContentLoader, ParamExtractor
from .semantic_validator import (
    DefaultNegotiationSemanticValidator,
    NegotiationSemanticValidator,
    NegotiationValidationError,
    SemanticValidationResult,
    build_semantic_validation_schema,
    validate_semantic,
)

__all__ = [
    "DefaultNegotiationComplianceChecker",
    "DefaultNegotiationSemanticValidator",
    "NegotiationComplianceChecker",
    "NegotiationRuleCheckResult",
    "NegotiationRuleCheckerAdapter",
    "NegotiationSemanticValidator",
    "NegotiationTemplateContentLoader",
    "NegotiationValidationError",
    "ParamExtractor",
    "SemanticValidationResult",
    "build_semantic_validation_schema",
    "validate_semantic",
]
