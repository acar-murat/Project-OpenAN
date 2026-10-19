# Deployment CSV template (PLACEHOLDER)

HQ has not supplied the Deployment import template yet. Until it does, the script writes the
placeholder layout in `assets/deployment-template.json`, one row per site and charge or
discharge rule (hold rows are left out unless `include_hold_rows` is true):

| Header | Value |
|---|---|
| NE Name | Site / NE name |
| Power Vendor | `Huawei` (only Huawei power systems are in scope) |
| Rule ID | `R01`, `R02`, ... in time order |
| Start Time / End Time | `HH:MM` |
| Action | `CHARGE` / `DISCHARGE` (`IDLE` for hold rows) |
| Power (kW) | Average power over the window |
| SoC Lower Limit (%) / SoC Upper Limit (%) | From `assets/battery-profile.json` |
| Tariff Tier | `sharp`, `peak`, `flat`, `valley` |
| Effective Date | `YYYY-MM-DD` |

To switch to the real template, edit only `assets/deployment-template.json`: list the real
headers under `columns`, each with either a `field` the script computes or a fixed `value`, set
`action_codes` to the codes Deployment expects, and set `placeholder` to `false`. The demo page
and the Skill both read this file.
