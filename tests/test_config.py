"""Loading, validating and saving config.toml."""

import pytest

from callout.config import TEMPLATE, ConfigError, load_config, save_config


def test_template_config_loads():
    c = load_config(TEMPLATE)
    assert c.broker.port == 7497 and c.broker.trading_mode == "paper"
    assert list(c.enabled_instruments) == ["ES"]


def test_paper_mode_on_live_port_is_rejected(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[broker]\nport = 7496\ntrading_mode = "paper"\n')
    with pytest.raises(ConfigError):
        load_config(f)


def test_unknown_keys_rejected(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[safety]\nmax_postion = 3\n")
    with pytest.raises(ConfigError):
        load_config(f)


def test_settings_file_round_trip(tmp_path):
    c = load_config(TEMPLATE)
    c.safety.max_position = 3
    c.voice.decoys = ["flatline"]
    c.instruments["MES"].enabled = True
    save_config(c, tmp_path / "config.toml")
    back = load_config(tmp_path / "config.toml")
    assert back.safety.max_position == 3 and back.voice.decoys == ["flatline"]
    assert back.instruments["MES"].enabled and back.instruments["ES"].spoken == c.instruments["ES"].spoken
