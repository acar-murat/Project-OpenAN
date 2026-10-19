---
name: tariff-to-battery-rules
description: Convert a tiered (sharp/peak/flat/valley) electricity tariff into base-station battery charge/discharge rules and export them as a CSV in the Deployment import layout. Use when the user imports a time-of-use tariff and asks for a battery charge/discharge strategy, its expected saving, or the CSV to import into Deployment.
context: inline
user-invocable: true
model-invocable: true
allowed-tools: Read Write Bash
metadata:
  version: "0.1.0"
  zh-name: 分时电价转电池充放电规则
  en-name: Tariff to Battery Rules
---

# Tariff to Battery Rules

## When to use

The user has imported a tiered electricity tariff (for example through the optimisation
platform page) and wants a battery charge/discharge strategy for base stations, the saving it
gives, or the CSV to import into the Deployment UI.

## Steps

1. Find the tariff file. The user gives its path, or uploads it to the workspace. Without one,
   use the sample at `$NEXTAGENT_SKILL_ROOT/assets/sample-tariff.csv` and say so.
   The format is in `references/tariff-format.md`: `start_time,end_time,tier,price`.
2. Ask which sites (NE names) the CSV is for if the user has not said; otherwise use
   `--site-count` demo sites.
3. Run the script:

   ```bash
   python "$NEXTAGENT_SKILL_ROOT/scripts/tariff_to_rules.py" --tariff "<tariff path>" --sites "<NE1>,<NE2>"
   ```

   It prints one JSON object. `ok: false` carries an `error` (for example a gap in the
   tariff): tell the user what to fix and stop.
4. Present the strategy as a short table: time window, tier, action (charge / discharge / hold),
   power and SoC at the end of the window. Then the summary: daily cost before and after,
   daily and monthly saving per site, and kWh moved out of peak periods.
5. Give the CSV path from the output (`csv`). The user imports it by hand in the Deployment UI;
   CME then delivers the power strategy to the Huawei power systems.

## Rules the script applies

- Charge in valley periods, up to the SoC ceiling.
- Discharge in peak and sharp-peak periods to carry the site load, down to the SoC floor. The
  floor is the outage reserve and is never used for arbitrage.
- Recharge in a flat period only when it feeds a later, dearer discharge (flat price divided
  by efficiency is below that discharge price).
- When stored energy cannot cover every discharge period, the dearest periods get it first.
- Battery and site figures are in `assets/battery-profile.json`; the CSV columns follow
  `assets/deployment-template.json` (see `references/deployment-template.md`). Both are
  placeholders until HQ supplies the real values: say so when you hand over the CSV.

## Constraints

- Do not write to `NEXTAGENT_SKILL_ROOT`; the script writes results to
  `NEXTAGENT_WORKSPACE_DIR` and scratch data to `NEXTAGENT_TEMP_DIR`.
- Do not use bare relative output paths.
- Demo only: never say the strategy was delivered to the live network. Only Huawei power
  systems are in scope; there is no third-party power or tariff system integration.
