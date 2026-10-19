"""The tariff-to-battery-rules Skill: tariff parsing, strategy, Deployment CSV and the sandbox CLI."""

import csv
import io
import json
import shutil
from pathlib import Path

import pytest

from henan_demo.app import SKILL_ROOT, rules

SAMPLE = (SKILL_ROOT / "assets" / "sample-tariff.csv").read_text(encoding="utf-8")
FLAT_DAY = "start_time,end_time,tier,price\n00:00,24:00,flat,0.6\n"


def strategy(text=SAMPLE, **battery):
    return rules.strategy_from_csv(text, battery)


def test_skill_manifest_follows_the_nextagent_contract():
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    front = text.split("---")[1]
    fields = dict(line.split(":", 1) for line in front.strip().splitlines() if line and not line.startswith(" "))
    assert fields["name"].strip() == SKILL_ROOT.name == "tariff-to-battery-rules"
    assert fields["context"].strip() == "inline"
    assert "model" not in fields and "agent" not in fields
    assert 0 < len(fields["description"].strip()) <= 1024
    extra = {p.name for p in SKILL_ROOT.iterdir() if p.is_dir()} - {"scripts", "references", "assets", "__pycache__"}
    assert not extra


def test_sample_strategy_charges_in_valleys_and_discharges_in_peaks():
    result = strategy()
    by_window = {f"{r['start']}-{r['end']}": r for r in result["rules"]}
    assert by_window["00:00-07:00"]["action"] == "charge"
    assert by_window["19:00-21:00"]["action"] == "discharge"  # the sharp peak always gets energy
    assert by_window["14:00-17:00"]["action"] == "charge"  # flat recharge pays for the evening peaks
    assert by_window["21:00-23:00"]["action"] == "hold"  # nothing left above the floor
    battery = result["battery"]
    for rule in result["rules"]:
        assert battery["soc_min_pct"] - 1e-6 <= rule["soc_end_pct"] <= battery["soc_max_pct"] + 1e-6
        if rule["action"] == "discharge":
            assert rule["power_kw"] <= min(battery["discharge_power_kw"], battery["site_load_kw"]) + 1e-6
        if rule["action"] == "charge":
            assert rule["power_kw"] <= battery["charge_power_kw"] + 1e-6
    # Steady state: the day ends where it starts.
    assert result["rules"][0]["soc_start_pct"] == result["rules"][-1]["soc_end_pct"]
    summary = result["summary"]
    assert summary["daily_saving"] > 0
    expected_after = summary["daily_cost_before"] - summary["daily_saving"]
    assert summary["daily_cost_after"] == pytest.approx(expected_after, abs=0.02)


def test_dearest_period_gets_the_energy_first():
    result = strategy(capacity_kwh=5.0)  # 2.75 kWh usable: not enough for every peak
    by_window = {f"{r['start']}-{r['end']}": r for r in result["rules"]}
    assert by_window["19:00-21:00"]["energy_kwh"] >= by_window["17:00-19:00"]["energy_kwh"]
    assert by_window["21:00-23:00"]["action"] == "hold"


def test_flat_tariff_gives_no_arbitrage():
    result = strategy(FLAT_DAY)
    assert {r["action"] for r in result["rules"]} == {"hold"}
    assert result["summary"]["daily_saving"] == 0


def test_chinese_tiers_and_wrap_past_midnight():
    text = ("start_time,end_time,tier,price\n23:00,07:00,低谷,0.3\n07:00,18:00,平段,0.6\n"
            "18:00,22:00,高峰,1.0\n22:00,23:00,尖峰,1.2\n")
    result = strategy(text)
    windows = [(r["start"], r["end"], r["tier"]) for r in result["rules"]]
    assert ("00:00", "07:00", "valley") in windows and ("23:00", "24:00", "valley") in windows
    assert result["summary"]["daily_saving"] > 0


@pytest.mark.parametrize("text, message", [
    ("start,end,price\n", "header"),
    ("start_time,end_time,tier,price\n00:00,12:00,valley,0.3\n", "gap at 12:00"),
    ("start_time,end_time,tier,price\n00:00,13:00,valley,0.3\n12:00,24:00,peak,1\n", "overlap"),
    ("start_time,end_time,tier,price\n00:00,24:00,cheap,0.3\n", "unknown tier"),
    ("start_time,end_time,tier,price\n00:00,24:00,flat,abc\n", "not a number"),
    ("start_time,end_time,tier,price\n0000,24:00,flat,1\n", "HH:MM"),
])
def test_bad_tariffs_are_explained(text, message):
    with pytest.raises(rules.TariffError, match=message):
        rules.parse_tariff_csv(text)


def test_bad_battery_profile_is_rejected():
    with pytest.raises(rules.TariffError, match="SoC"):
        strategy(soc_min_pct=90, soc_max_pct=80)


def test_deployment_csv_follows_the_template():
    template = rules.load_json_asset("deployment-template.json")
    result = strategy()
    text = rules.deployment_csv(result, ["NE-1", "NE-2"], template, "2026-10-20")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == [c["header"] for c in template["columns"]]
    active = [r for r in result["rules"] if r["action"] != "hold"]
    assert len(rows) - 1 == 2 * len(active)
    first = dict(zip(rows[0], rows[1], strict=True))
    assert first["NE Name"] == "NE-1" and first["Power Vendor"] == "Huawei"
    assert first["Action"] == "CHARGE" and first["SoC Lower Limit (%)"] == "40"
    assert first["Effective Date"] == "2026-10-20"


def test_cli_writes_to_the_workspace_and_temp(tmp_path, monkeypatch, capsys):
    skill = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, skill, ignore=shutil.ignore_patterns("__pycache__"))
    for name, path in (("NEXTAGENT_SKILL_ROOT", skill), ("NEXTAGENT_WORKSPACE_DIR", tmp_path / "ws"),
                       ("NEXTAGENT_TEMP_DIR", tmp_path / "tmp")):
        monkeypatch.setenv(name, str(path))
    monkeypatch.chdir(tmp_path)
    assert rules.main(["--sites", "NE-1,NE-2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["template_is_placeholder"] and out["sites"] == 2
    assert Path(out["csv"]).parent == tmp_path / "ws"
    assert Path(out["csv"]).read_bytes().startswith(b"\xef\xbb\xbf")  # utf-8-sig for Excel
    assert list((tmp_path / "tmp").iterdir())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["skill", "tmp", "ws"]  # no bare relative outputs


def test_cli_reports_a_bad_tariff(tmp_path, monkeypatch, capsys):
    for name in rules.REQUIRED_ENV:
        monkeypatch.setenv(name, str(SKILL_ROOT if name == "NEXTAGENT_SKILL_ROOT" else tmp_path / name))
    bad = tmp_path / "bad.csv"
    bad.write_text("start_time,end_time,tier,price\n00:00,12:00,valley,0.3\n", encoding="utf-8")
    assert rules.main(["--tariff", str(bad)]) == 2
    assert "gap" in json.loads(capsys.readouterr().out)["error"]


def test_cli_needs_the_sandbox_env(monkeypatch):
    for name in rules.REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="Missing NextAgent sandbox env"):
        rules.main([])
