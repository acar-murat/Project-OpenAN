"""Live-LLM corpus family (D24): real-endpoint sibling of the offline corpus suites.

Everything except the model itself is production assembly — the live engine drives the same
:class:`~tests.corpus.assemblers.TaskApiAssembler` real-builder wiring as the offline engine,
wrapped in the recording client — and the whole family is opt-in through the ``A2AT_TEST_LLM_*``
environment variables (same names as Java, D24): absent any of the three required variables every
live test skips, never fails and never hangs, so ``pytest`` and CI stay offline-deterministic.
"""
