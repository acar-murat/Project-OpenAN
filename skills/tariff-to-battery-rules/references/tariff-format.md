# Tariff input format

CSV, UTF-8 (a BOM is accepted), one row per time-of-use period:

| Column | Meaning |
|---|---|
| `start_time` | `HH:MM`, inclusive |
| `end_time` | `HH:MM`, exclusive; `24:00` is the end of the day. An end at or before the start wraps past midnight (`23:00,07:00`) |
| `tier` | `sharp`, `peak`, `flat` or `valley`; Chinese names `尖峰`, `高峰`, `平段`, `低谷` (and `峰`, `平`, `谷`, `深谷`) are accepted |
| `price` | Energy price in CNY/kWh |

The periods must cover the whole day with no gaps or overlaps. Neighbouring rows with the same
tier and price are merged.

Example (`assets/sample-tariff.csv`; illustrative figures, not the published Henan tariff):

```csv
start_time,end_time,tier,price
00:00,07:00,valley,0.3012
07:00,10:00,flat,0.6236
10:00,14:00,peak,0.9461
14:00,17:00,flat,0.6236
17:00,19:00,peak,0.9461
19:00,21:00,sharp,1.1353
21:00,23:00,peak,0.9461
23:00,24:00,valley,0.3012
```

To be confirmed with HQ: the tariff format the customer will import (open item in
`docs/henan-demo.md`).
