"""Energy Agent policy guard (LLD v10.4 §11.10, §11.11).

Runs before the Energy Agent opens a feasibility negotiation, so a request that
breaks operator policy never reaches MAE and the agent never reports ``agreed``
for it. It is separate from MAE's own feasibility verdict.

Environment (empty means "no limit", which suits development; production sets all three):

* ``ENERGY_AGENT_POLICY_REGION_ALLOWLIST``: comma-separated regions the agent may act on
  (case-insensitive).
* ``ENERGY_AGENT_POLICY_MIN_EXPERIENCE_FLOOR``: lowest rate floor in Mbps any schedule period
  may ask for. A period with experience target ``none`` counts as 0 Mbps; ``no_degradation``
  always passes.
* ``ENERGY_AGENT_POLICY_MAX_SAVING_TARGET``: highest numeric ``saving_target`` (percent) an
  intent may carry. UC1 intents carry saving modes, not a number, so this applies only when one
  is given.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

POLICY_VIOLATION = "policy_violation"


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reasons": list(self.reasons)}


def _optional_float(value: str | None) -> float | None:
    return float(value) if value and value.strip() else None


@dataclass(frozen=True)
class PolicyGuard:
    region_allowlist: frozenset[str] = field(default_factory=frozenset)
    min_experience_floor_mbps: float | None = None
    max_saving_target: float | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> PolicyGuard:
        env = os.environ if env is None else env
        regions = env.get("ENERGY_AGENT_POLICY_REGION_ALLOWLIST", "")
        return cls(
            region_allowlist=frozenset(r.strip().casefold() for r in regions.split(",") if r.strip()),
            min_experience_floor_mbps=_optional_float(env.get("ENERGY_AGENT_POLICY_MIN_EXPERIENCE_FLOOR")),
            max_saving_target=_optional_float(env.get("ENERGY_AGENT_POLICY_MAX_SAVING_TARGET")),
        )

    def check(self, region: str, schedule: list[dict[str, Any]],
              saving_target: float | None = None) -> PolicyDecision:
        reasons = []
        if self.region_allowlist and region.strip().casefold() not in self.region_allowlist:
            reasons.append(f"region {region!r} is not in the allowlist")
        if self.min_experience_floor_mbps is not None:
            for period in schedule:
                target = period.get("experience_target") or {}
                if target.get("type") == "no_degradation":
                    continue
                mbps = float(target.get("mbps") or 0) if target.get("type") == "rate_floor" else 0.0
                if mbps < self.min_experience_floor_mbps:
                    reasons.append(
                        f"period {period.get('start_hour')}-{period.get('end_hour')} asks for {mbps:g} Mbps, "
                        f"below the {self.min_experience_floor_mbps:g} Mbps floor")
        if self.max_saving_target is not None and saving_target is not None \
                and saving_target > self.max_saving_target:
            reasons.append(f"saving target {saving_target:g} is above the {self.max_saving_target:g} limit")
        return PolicyDecision(allowed=not reasons, reasons=tuple(reasons))
