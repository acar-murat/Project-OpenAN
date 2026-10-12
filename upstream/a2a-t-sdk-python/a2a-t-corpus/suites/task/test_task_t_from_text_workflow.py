"""Task-T natural-language workflow suite (port of the Java ``TaskTFromTextWorkFlowTest``).

For every scenario directory under ``a2a-t-corpus/suites/task/resources/``, runs the recorded SDK
API flow of each case in ``input_case_from_text.json`` against a real LLM.

Default API flow (also shown in the case files): ``generateTaskPromptFromText`` →
``validateTaskPromptAndDataFilling``.

Filters: ``--corpus-scenario`` (glob, comma-separated) and ``--case-filter`` (glob on case id).
"""

from __future__ import annotations

import pytest
from engine.constants import FLOW_FROM_TEXT, INPUT_CASE_FROM_TEXT
from engine.suite import run_case

EXTENSION_FOLDER = "task"
INPUT_CASE_FILE = INPUT_CASE_FROM_TEXT
FLOW_TYPE = FLOW_FROM_TEXT


@pytest.mark.live
def test_task_t_from_text_workflow(scenario, case, workflow_engine, workflow_context):  # noqa: ANN001
    """Execute one discovered from-text case and compare it against its expectations."""
    run_case(workflow_engine, scenario, case, workflow_context)
