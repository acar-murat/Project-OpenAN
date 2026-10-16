"""UC1 request bodies the Energy Agent sends to MAE (LLD v10.4 §11.5 and §11.7).

Shared by ``scripts/demo_uc1.py`` and the mock Energy Agent so both speak to the
mock MAE with the same Negotiation-T and Task-T content.
"""

from __future__ import annotations

import uuid
from typing import Any

from mocks.common import uc1_data


def tariff_slot(tariff: dict[str, Any]) -> dict[str, Any]:
    """The part of a price API tariff response that MAE needs."""
    return {key: tariff[key] for key in ("currency", "billing_period", "bands")}


def feasibility_opening(region: str, tariff: dict[str, Any]) -> dict[str, Any]:
    """Negotiation-T ``initiate_feasibility_assessment`` for the UC1 intent."""
    return {
        "category": "goal_achievement",
        "message_class": "initiate_feasibility_assessment",
        "negotiation_id": str(uuid.uuid4()),
        "round": 1,
        "under_evaluation_description": {
            "region": region,
            "schedule": uc1_data.intent_schedule(),
            "power_band_tariff": tariff_slot(tariff),
        },
    }


def feasibility_accept(reply: dict[str, Any]) -> dict[str, Any]:
    """Accept MAE's verdict: a ``feasible_request_confirmation`` (-> AGREED) or an
    ``infeasible_with_proposal`` (-> CLOSED_INFEASIBLE; the counter-proposal goes back to the user)."""
    return {"category": "goal_achievement", "message_class": "accept",
            "accepted": reply["message_class"],
            "negotiation_id": reply["negotiation_id"], "round": reply["round"]}


def feasibility_abort(opening: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
    """Negotiation-T ``common/abort`` after a reply the Energy Agent cannot act on."""
    return {"category": "goal_achievement", "message_class": "abort",
            "negotiation_id": reply.get("negotiation_id") or opening["negotiation_id"],
            "round": reply.get("round") or opening["round"]}


def energy_saving_slots(region: str, tariff: dict[str, Any]) -> dict[str, Any]:
    """Task-T ``ran-energy-saving/v1`` slots for the UC1 intent."""
    return {
        "task_object": region,
        "operation_type": "Create",
        "task_description": f"Power-band energy saving for {region}",
        "task_target": {"schedule": uc1_data.intent_schedule()},
        "task_context": {"power_band_tariff": tariff_slot(tariff)},
    }
