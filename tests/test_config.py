# tests/test_config.py
from chalkpress.config import normalize_settings


def test_normalize_defaults():
    cfg = normalize_settings({})
    assert cfg == {"options": {"summary_lang": "zh", "zh_script": "auto",
                               "speed": "standard", "output_layout": "original",
                               "auto_correct": True, "term_fix": False},
                   "app": {"keep_log": True}}


def test_normalize_optional_fields():
    raw = {"options": {"summary_lang": "en", "asr_model": "small",
                       "scene_threshold": 0.05, "min_gap": 5.0,
                       "auto_correct": False},
           "app": {"keep_log": False},
           "llm": {"api_base": " https://api.example.com/v1 ", "api_key": "sk-1",
                   "model": "gpt-4o-mini"}}
    cfg = normalize_settings(raw)
    assert cfg["options"]["asr_model"] == "small"
    assert cfg["options"]["scene_threshold"] == 0.05
    assert cfg["options"]["auto_correct"] is False
    assert cfg["app"] == {"keep_log": False}
    assert cfg["llm"]["api_base"] == "https://api.example.com/v1"


def test_normalize_partial_llm_dropped():
    """llm 三项缺一不可，否则整体丢弃（与旧 GUI 行为一致）。"""
    cfg = normalize_settings({"llm": {"api_base": "https://x", "api_key": "k"}})
    assert "llm" not in cfg


def test_normalize_none_fields_dropped():
    cfg = normalize_settings({"options": {"asr_model": None, "min_gap": None}})
    assert "asr_model" not in cfg["options"]
    assert "min_gap" not in cfg["options"]


def test_normalize_output_layout_fallback():
    """output_layout 仅接受 original/grouped，其他值回退 original。"""
    bad = normalize_settings({"options": {"output_layout": "flat"}})
    assert bad["options"]["output_layout"] == "original"
    ok = normalize_settings({"options": {"output_layout": "grouped"}})
    assert ok["options"]["output_layout"] == "grouped"


def test_privacy_consent_roundtrip(tmp_path, monkeypatch):
    """[privacy] analytics_consent：未写入=None（未询问）；true/false 持久化。"""
    import chalkpress.config as config
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    assert config.load_privacy_consent() is None
    config.save_privacy_consent(True)
    assert config.load_privacy_consent() is True
    config.save_privacy_consent(False)
    assert config.load_privacy_consent() is False


def test_privacy_survives_config_rewrite(tmp_path, monkeypatch):
    """重写 options/app/llm 不清掉 [privacy]（同意状态只由 privacy.set 改变）。"""
    import chalkpress.config as config
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    config.save_privacy_consent(False)
    cfg = config.load_config_file()
    cfg["options"] = {"summary_lang": "en"}
    config.save_config_file(cfg)
    assert config.load_privacy_consent() is False
