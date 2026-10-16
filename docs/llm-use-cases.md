# LLM use cases and intent wording

Where the energy-saving function asks an LLM something, how each answer is checked, and how to
measure how much the result depends on the user's wording.

## 1. The LLM use cases

| # | Use case | Who asks | Prompt | Answer | Checked by |
|---|---|---|---|---|---|
| 1 | **Classify**: is this text an energy-saving intent? | OSS (R-INT-4, LLD §11.1 step 3) | `mocks/llm/prompts.py` `CLASSIFY_PROMPT` (ours) | `{"is_energy_saving_intent": bool, "confidence": 0..1}`, nothing else | `parse_classification` rejects extra keys, free text, wrong types |
| 2 | **Extract**: region, saving mode, experience target | OSS (R-INT-6, R-INT-7, R-INT-11) | `EXTRACT_PROMPT` (ours) | the three fields, `null` when not stated | `parse_extraction` checks the enumerations and adds `missing_fields` for `awaiting_supplement` |
| 3 | **Select**: which stored workflow (PSOP) runs the intent | Orchestration Center (`retrieval._retrieve_names_by_intent`) | upstream `get_retrieve_psop_prompt`, loaded unchanged | JSON array of PSOP names | the upstream parser; `scripts/llm_eval.py` checks the pick |
| 4 | **A2A-T slot extraction and validation** | A2A-T SDK inside the Energy Agent and MAE | SDK prompt resources | `negotiation.semantic_rejected` or accepted | SDK; model sensitivity is open item O-2 |

Use cases 1 and 2 are ours to design. Use case 3's prompt is upstream and stays unchanged (LLD
v10.4 §0.0); what we control is the text of each PSOP the prompt lists: its `name`,
`description`, `user_intent`, `tags` and step descriptions. Use case 4 is not covered here.

All user text is treated as data (R-EAS-5): each prompt says so, and each answer is parsed to a
fixed shape before anything is forwarded.

## 2. The phrasing set

`mocks/llm/cases.py` holds 24 ways of wording a request, each with the right answer for every
use case:

- **UC1 standard wording**: "Run power-band energy saving for Accra Central" and close variants.
- **UC1 in other words**: "Cut the electricity bill of the sites in Kumasi", "Lower our tariff
  band charges at Takoradi", lower case, "in"/"at" instead of "for", targets stated in words
  ("keep at least 10 Mbps", "experience first, no degradation"), Turkish, Chinese, typos, and an
  indirect complaint ("We pay too many cedis for power...").
- **Close neighbours**: battery charge and discharge (UC2), night-time cell sleep, a question
  about past savings. These sound like energy saving but are not UC1.
- **Not energy saving**: the SPN fault workflow, a power *outage*, "Save the report as PDF",
  an unrelated request, and a prompt-injection attempt.

The select use case runs against two workflow lists:

- `dev`: what the dev stack stores today (the upstream SPN sample and UC1).
- `extended`: `dev` plus three hypothetical energy workflows (UC2 battery planning, cell sleep,
  saving report). They are not registered anywhere; they test whether a model can tell close
  workflows apart before more energy use cases are stored.

## 3. Running it

```bash
python scripts/llm_eval.py                              # the mock, in process (also run by pytest)
OPENAN_EVAL_LLM_URL=https://api.openai.com/v1/chat/completions \
OPENAN_EVAL_LLM_MODEL=gpt-4o-mini OPENAN_EVAL_LLM_API_KEY=... \
python scripts/llm_eval.py --target openai --repeat 3 --report .dev/llm-eval.md
```

Any OpenAI-compatible endpoint works (the same provider type the Orchestration Center's
`models.yaml` uses): OpenAI, a gateway in front of Azure OpenAI, vLLM, Ollama, DeepSeek, Qwen.
`--repeat 3` runs each prompt three times at temperature 0, so a case passes only if the model is
right every time; this separates wording sensitivity from randomness. `--only select` limits the
run to one use case. The report lists every wrong answer with the text, the expected answer and
what the model said.

With the same variables set, `pytest mocks/tests/test_llm.py::test_real_model_phrasings` runs the
whole set and fails on any wrong answer; without them it is skipped.

CI runs the mock against every case the mock is meant to handle, and the dev-stack job dispatches
"Cut the electricity bill of the sites in Kumasi" through the Orchestration Center and requires
the UC1 workflow to run for Kumasi.

## 4. What was word-sensitive, and what changed

Measured with the mock (no real model was available for this change).

| Wording | Before | After |
|---|---|---|
| "Cut the electricity bill of the sites in Kumasi" | no workflow (`dev`); UC2 battery planning (`extended`) | UC1 |
| "Energy saving **in** Kumasi" (Energy Agent region) | ran for **Accra Central**, the default, without saying so | Kumasi |
| "save energy in accra central" (lower case) | default region | Accra Central |
| "Diagnose the power outage at the Kumasi sites" | UC1 | no workflow |
| "Save the report as PDF" | UC1 | no workflow |
| "How much energy did last month's saving run save?" | UC1 (`dev`) | no workflow; the report workflow in `extended` |

Changes, all on our side (no upstream code touched):

1. **UC1 PSOP text uses the words users use.** `user_intent` and `tags` now mention the
   electricity bill, electricity cost, power consumption and tariff, so a model (or the mock)
   does not need the phrase "power-band energy saving" to pick UC1
   (`mocks/energy_agent/workflow.py`).
2. **Region parsing in the Energy Agent** accepts "for", "in" and "at", and the known regions in
   any case. Before, "in Kumasi" quietly ran Accra Central.
3. **The mock LLM folds words into concepts** (bill, tariff, cost, cedis → cost; cut, reduce,
   lower, save → saving), skips workflows that lack a specialised concept the intent names
   (battery, cell sleep, fault, past runs), and needs a shared concept more specific than
   "save" or "report". It also answers the classify and extract prompts.

Chinese text, typos, the indirect complaint and the injection attempt are marked as real-model
cases: the keyword mock is not built for them and they are reported but not counted against it.

## 5. Recommendations

- **Run the set against the candidate production model before GA** (`--repeat 3`), together
  with the A2A-T validation check already required by O-2. Keep the report with the model choice.
- **Classify before select.** OSS's order (classify, then validate, then submit) keeps fault and
  report requests away from workflow selection; the Execution Center's direct dispatch skips that
  gate, so its intents should be worded as requests.
- **Never default the region in production.** The mock Energy Agent falls back to Accra Central
  when it finds no region. OSS should use the extract prompt and return `awaiting_supplement`
  with `region` missing instead (R-INT-7).
- **Give every new energy PSOP a distinct `user_intent` and tags** in the user's own words, and add
  its phrasings and close neighbours to `mocks/llm/cases.py` when it is stored.
