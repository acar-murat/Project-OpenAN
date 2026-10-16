"""Run the intent phrasings in ``mocks/llm/cases.py`` through a model and report the wrong answers.

Each case goes through the three LLM use cases in ``mocks/llm/prompts.py``:

* ``classify``: is it an energy-saving intent (OSS)?
* ``extract``: region, saving mode, experience target (OSS; only for energy-saving cases).
* ``select``: which stored workflow the Orchestration Center picks, with the upstream prompt,
  once per catalogue (``dev``: what the dev stack stores; ``extended``: plus energy neighbours).

Targets:

* ``mock`` (default): ``mocks.llm.app`` in process. Cases marked ``mock=False`` are reported but
  not counted, since the keyword mock is not built for them.
* ``openai``: any OpenAI-compatible chat endpoint (OpenAI, Azure OpenAI behind a gateway, vLLM,
  Ollama, DeepSeek, Qwen, ...), the same provider type the Orchestration Center uses::

      OPENAN_EVAL_LLM_URL=https://api.openai.com/v1/chat/completions
      OPENAN_EVAL_LLM_MODEL=gpt-4o-mini
      OPENAN_EVAL_LLM_API_KEY=...        # empty for a local server

Wording sensitivity and randomness look the same in one run, so ``--repeat`` runs every prompt
several times and a case passes only if every run is right.

    python scripts/llm_eval.py [--target openai] [--repeat 3] [--only select] [--report out.md]

Exits 1 when a counted case fails.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mocks.llm import app as mock_llm  # noqa: E402
from mocks.llm import prompts  # noqa: E402
from mocks.llm.cases import CASES, IntentCase, catalogues  # noqa: E402

USE_CASES = ("classify", "extract", "select")


@dataclass
class Result:
    use_case: str
    case: IntentCase
    expected: str
    got: list[str] = field(default_factory=list)
    ok: bool = True
    catalogue: str = ""
    target: str = "mock"

    @property
    def counted(self) -> bool:
        return self.case.mock or self.target != "mock"


def openai_chat(url: str, model: str, api_key: str, timeout: float) -> Callable[[str], str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    client = httpx.Client(timeout=timeout, headers=headers)

    def ask(prompt: str) -> str:
        body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}
        for attempt in range(3):
            response = client.post(url, json=body)
            if response.status_code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""
        raise RuntimeError("unreachable")

    return ask


def _region_matches(expected: str | None, got: str | None) -> bool:
    if expected is None or got is None:
        return expected is got
    return expected.strip().lower() == got.strip().lower()


def check_classify(case: IntentCase, answer: str) -> tuple[bool, str]:
    try:
        value = prompts.parse_classification(answer)
    except ValueError as error:
        return False, f"invalid: {error}"
    return value["is_energy_saving_intent"] == case.energy, json.dumps(value)


def check_extract(case: IntentCase, answer: str) -> tuple[bool, str]:
    try:
        value = prompts.parse_extraction(answer)
    except ValueError as error:
        return False, f"invalid: {error}"
    ok = (_region_matches(case.region, value["region"]) and value["saving_mode"] == case.saving_mode
          and value["experience_target"] == case.experience)
    shown = {key: value[key] for key in prompts.REQUIRED_FIELDS}
    return ok, json.dumps(shown, ensure_ascii=False)


def check_select(case: IntentCase, catalogue: str, answer: str) -> tuple[bool, str]:
    try:
        names = prompts.parse_json(answer)
    except ValueError as error:
        return False, f"invalid: {error}"
    if not isinstance(names, list):
        return False, f"invalid: not a list: {names!r}"
    pick = names[0] if names else None
    return pick in case.expected_picks(catalogue), str(pick)


def expected_text(use_case: str, case: IntentCase, catalogue: str = "") -> str:
    if use_case == "classify":
        return str(case.energy).lower()
    if use_case == "extract":
        return json.dumps({"region": case.region, "saving_mode": case.saving_mode,
                           "experience_target": case.experience}, ensure_ascii=False)
    return " or ".join(sorted(str(name) for name in case.expected_picks(catalogue)))


def run(ask: Callable[[str], str], target: str, repeat: int, only: set[str]) -> list[Result]:
    jobs: list[tuple[str, IntentCase, str, str, Callable[[str], tuple[bool, str]]]] = []
    for case in CASES:
        if "classify" in only:
            jobs.append(("classify", case, "", prompts.classify_prompt(case.text),
                         lambda a, c=case: check_classify(c, a)))
        if "extract" in only and case.energy:
            jobs.append(("extract", case, "", prompts.extract_prompt(case.text),
                         lambda a, c=case: check_extract(c, a)))
        if "select" in only:
            for name, psops in catalogues().items():
                jobs.append(("select", case, name, prompts.select_prompt(case.text, list(psops.values())),
                             lambda a, c=case, n=name: check_select(c, n, a)))
    results = []
    for use_case, case, catalogue, prompt, check in jobs:
        result = Result(use_case, case, expected_text(use_case, case, catalogue), catalogue=catalogue,
                        target=target)
        for _ in range(repeat):
            try:
                ok, got = check(ask(prompt))
            except httpx.HTTPError as error:
                ok, got = False, f"error: {error}"
            result.ok &= ok
            result.got.append(got)
        results.append(result)
        print(f"{'PASS' if result.ok else 'FAIL' if result.counted else 'skip'}  {use_case:<8} "
              f"{catalogue:<8} {case.id:<22} {' | '.join(dict.fromkeys(result.got))}", flush=True)
    return results


def report(results: list[Result], target: str, model: str, repeat: int) -> str:
    lines = [f"# Intent wording evaluation: {target} ({model})", "",
             f"{len(CASES)} phrasings, {repeat} run(s) each, temperature 0.", "",
             "| Use case | Catalogue | Passed | Failed | Not counted |", "|---|---|---|---|---|"]
    groups: dict[tuple[str, str], list[Result]] = {}
    for result in results:
        groups.setdefault((result.use_case, result.catalogue), []).append(result)
    for (use_case, catalogue), items in groups.items():
        counted = [r for r in items if r.counted]
        passed = sum(r.ok for r in counted)
        lines.append(f"| {use_case} | {catalogue or '-'} | {passed} | {len(counted) - passed} | "
                     f"{len(items) - len(counted)} |")
    failures = [r for r in results if not r.ok]
    if failures:
        lines += ["", "## Wrong answers", "", "| Use case | Catalogue | Case | Text | Expected | Got | Counted |",
                  "|---|---|---|---|---|---|---|"]
        for r in failures:
            got = " / ".join(dict.fromkeys(r.got)).replace("|", "\\|")
            lines.append(f"| {r.use_case} | {r.catalogue or '-'} | {r.case.id} | {r.case.text} | "
                         f"{r.expected.replace('|', '\\|')} | {got} | {'yes' if r.counted else 'no'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=("mock", "openai"), default="mock")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", choices=USE_CASES, action="append", help="run only these use cases")
    parser.add_argument("--report", type=Path, help="write a Markdown report here")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    if args.target == "openai":
        url = os.environ.get("OPENAN_EVAL_LLM_URL", "")
        model = os.environ.get("OPENAN_EVAL_LLM_MODEL", "")
        if not url or not model:
            print("Set OPENAN_EVAL_LLM_URL and OPENAN_EVAL_LLM_MODEL (and OPENAN_EVAL_LLM_API_KEY) first.")
            return 2
        ask = openai_chat(url, model, os.environ.get("OPENAN_EVAL_LLM_API_KEY", ""), args.timeout)
    else:
        model, ask = "keyword mock", mock_llm.answer

    results = run(ask, args.target, args.repeat, set(args.only or USE_CASES))
    text = report(results, args.target, model, args.repeat)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print("\n" + text)
    return 1 if any(r.counted and not r.ok for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
