"""Mock Energy Agent: the Orchestration Center's host agent for the UC1 workflow.

The real Energy Agent (LLD v10.4 §11.4, §11.5, §11.11) is not built yet. This stand-in lets the
Orchestration Center's Execution Center run UC1 end to end and show every step:
it hosts the upstream ``host_agent`` runtime with an energy-saving ControlPoint,
so it needs the Orchestration Center's virtualenv and ``upstream/orchestration-center``
on ``PYTHONPATH`` (``scripts/dev.py`` sets both). ``workflow.py`` has no upstream
imports, so the workflow definition can be tested anywhere.
"""
