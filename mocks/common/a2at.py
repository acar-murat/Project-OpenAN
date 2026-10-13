"""A2A-T identifiers shared by the mock MAE and the demo client.

Values match the a2a-t SDK (``a2a_t.core.metadata``) and its ran-energy-saving
sample, so the mocks speak the same wire format as real A2A-T agents.
"""

TASK_T_EXTENSION_URI = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"
NEGOTIATION_T_EXTENSION_URI = (
    "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1"
)
ENERGY_SAVING_TEMPLATE_URI = "Task-T/network-layer/ran-energy-saving/v1"
FEASIBILITY_PROPOSE_TEMPLATE_URI = "Negotiation-T/feasibility-negotiation/propose"
FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI = "Negotiation-T/feasibility-negotiation/accept-reject"
ABORT_TEMPLATE_URI = "Negotiation-T/common/abort"

#: Metadata key the sample client uses to name the template a message follows.
TEMPLATE_URI_METADATA_KEY = "templateUri"
