"""Meta layer of the negotiation test corpus: the corpus checked against its own contracts.

Two families of meta tests live here, the port of the Java ``a2a-t-corpus`` double meta layer
(design §6 Q6/§7/§8.4/§8.6):

* :mod:`tests.corpus.meta.test_contract` (Java ``CorpusContractTest``) — the corpus is checked
  against its own contracts instead of the production code, so a hole in the corpus is caught
  before it silently narrows the suites.
* :mod:`tests.corpus.meta.test_sensitivity` (Java ``CorpusSensitivitySelfTest``) — the engine is
  proven sensitive: every class of expectation assertion goes red on one flipped value.
"""
