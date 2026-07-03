"""Config loading: defaults validate, user YAML deep-merges, env overrides win."""

import textwrap

from autogeo.config.loader import config_hash, load_settings


def test_packaged_defaults_validate():
    settings = load_settings()
    assert settings.gate.min_gcps == 5
    bands = {t.era_band: t.max_m for t in settings.gate.rmse_thresholds}
    assert bands["modern_vector"] == 0.5
    assert bands["pre1980_scan"] == 1.5
    assert "tier1" in settings.doctrine.keyword_map
    assert "los_angeles_city" in settings.jurisdictions
    assert settings.jurisdictions["los_angeles_city"].default_crs == "EPSG:2229"
    # baselines carry the accuracy doctrine amendments
    ngs = next(l for l in settings.baselines.overrides if "NGS" in l.name)
    assert ngs.reliability_filter is not None
    plss = next(l for l in settings.baselines.overrides if "PLSS" in l.name)
    assert plss.positional_accuracy_m == 30.0


def test_user_yaml_deep_merges(tmp_path):
    user = tmp_path / "autogeo.yaml"
    user.write_text(textwrap.dedent("""
        gate:
          min_gcps: 8
        llm:
          tier3: {max_calls_per_doc: 1}
    """), encoding="utf-8")
    settings = load_settings(user)
    assert settings.gate.min_gcps == 8
    assert settings.gate.loo_factor == 1.5  # untouched sibling survives
    assert settings.llm.tier3.max_calls_per_doc == 1
    assert settings.llm.tier3.enabled is True  # nested sibling survives
    assert settings.llm.model == "claude-sonnet-5"


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGEO_GATE__MIN_GCPS", "9")
    monkeypatch.setenv("AUTOGEO_LOGGING__LEVEL", "DEBUG")
    settings = load_settings()
    assert settings.gate.min_gcps == 9
    assert settings.logging.level == "DEBUG"


def test_config_hash_stable_and_sensitive(tmp_path):
    a = load_settings()
    b = load_settings()
    assert config_hash(a) == config_hash(b)
    user = tmp_path / "autogeo.yaml"
    user.write_text("gate: {min_gcps: 8}", encoding="utf-8")
    assert config_hash(load_settings(user)) != config_hash(a)


def test_settings_frozen():
    import pytest

    settings = load_settings()
    with pytest.raises(Exception):
        settings.gate = None  # type: ignore[misc]
