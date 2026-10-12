"""Data-driven corpus suites: one parametrized test per shipped corpus record.

Each family directory of ``tests/resources/negotiation-cases/`` becomes one suite module — the
port of the Java ``*CorpusSuiteTest`` classes — driving every expanded record through the corpus
engines of :mod:`tests.corpus.engine` (see ``docs-local/python-port-plan-draft.md`` P8 and D21
for the corpus decisions).
"""
