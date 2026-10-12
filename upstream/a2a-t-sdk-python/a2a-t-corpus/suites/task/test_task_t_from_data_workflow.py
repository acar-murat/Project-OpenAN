"""Task-T structured-input workflow suite (port of the Java ``TaskTFromDataWorkFlowTest``).

For every scenario directory under ``a2a-t-corpus/suites/task/resources/``, runs the recorded SDK
API flow of each case in ``input_case_from_data.json`` against a real LLM.

Default API flow (also shown in the case files): ``generateTaskPromptFromDataWithSchema`` →
``validateTaskPromptAndDataFilling``.

Filters: ``--corpus-scenario`` and ``--case-filter``, see :mod:`test_task_t_from_text_workflow`.
"""

from __future__ import annotations

import pytest
from engine.constants import FLOW_FROM_DATA, INPUT_CASE_FROM_DATA
from engine.suite import run_case

EXTENSION_FOLDER = "task"
INPUT_CASE_FILE = INPUT_CASE_FROM_DATA
FLOW_TYPE = FLOW_FROM_DATA


@pytest.mark.live
def test_task_t_from_data_workflow(scenario, case, workflow_engine, workflow_context):  # noqa: ANN001
    """Execute one discovered from-data case and compare it against its expectations."""
    run_case(workflow_engine, scenario, case, workflow_context)
