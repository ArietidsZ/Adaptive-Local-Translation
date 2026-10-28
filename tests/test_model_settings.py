from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from config import Config
from model_loading import resolve_model_directory
from web_server import WebDashboard


def test_dashboard_real_config_roundtrip_preserves_other_settings():
    dashboard = WebDashboard()
    assert dashboard._get_config_msg()["trust_remote_code"] is False
    dashboard._cfg = Config(obs_port=4456, sample_rate=8000)
    dashboard._apply_config({"offline_only": True, "model_cache_dir": "/tmp/models"})
    assert dashboard._get_config_msg()["offline_only"] is True
    assert dashboard._cfg.model_cache_dir == "/tmp/models"
    assert dashboard._cfg.obs_port == 4456
    assert dashboard._cfg.sample_rate == 8000
    dashboard._apply_config({"model_cache_dir": "", "asr_language": ""})
    assert dashboard._cfg.model_cache_dir is None
    assert dashboard._cfg.asr_language is None
    assert dashboard._cfg.offline_only is True


@pytest.mark.parametrize(
    "payload",
    [
        {"offline_only": "false"},
        {"trust_remote_code": 1},
        {"asr_model": ""},
        {"target_lang": 12},
        {"model_cache_dir": []},
    ],
)
def test_invalid_settings_do_not_replace_config(payload):
    dashboard = WebDashboard()
    old = dashboard._cfg
    with pytest.raises(ValueError):
        dashboard._apply_config({"asr_model": "changed", **payload})
    assert dashboard._cfg is old


def test_asr_snapshot_receives_policy_and_returns_local_path(monkeypatch):
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        return "/cached/snapshot"

    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download)
    )
    cfg = Config(model_cache_dir="/cache", offline_only=True)
    assert resolve_model_directory("Qwen/example", cfg) == "/cached/snapshot"
    assert calls == [
        dict(repo_id="Qwen/example", cache_dir="/cache", local_files_only=True)
    ]


def test_local_model_directory_does_not_resolve_snapshot(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    assert resolve_model_directory(str(tmp_path), Config()) == str(tmp_path.resolve())


def test_missing_offline_snapshot_has_no_online_retry(monkeypatch):
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        raise FileNotFoundError("not cached")

    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download)
    )
    with pytest.raises(FileNotFoundError):
        resolve_model_directory("Qwen/missing", Config(offline_only=True))
    assert len(calls) == 1
    assert calls[0]["local_files_only"] is True


def test_translator_loaders_receive_cache_offline_and_trust(monkeypatch):
    import importlib.util
    from pathlib import Path

    calls = []
    model = SimpleNamespace(eval=lambda: None)

    def load_tokenizer(*args, **kwargs):
        calls.append(("tokenizer", args, kwargs))
        return object()

    def load_model(*args, **kwargs):
        calls.append(("model", args, kwargs))
        return model

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=load_tokenizer),
            AutoModelForCausalLM=SimpleNamespace(from_pretrained=load_model),
        ),
    )
    spec = importlib.util.spec_from_file_location(
        "isolated_translator", Path(__file__).parents[1] / "translator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.Translator(Config(model_cache_dir="/cache", offline_only=True))
    assert len(calls) == 2
    for _, _, kwargs in calls:
        assert kwargs["cache_dir"] == "/cache"
        assert kwargs["local_files_only"] is True
        assert kwargs["trust_remote_code"] is False


def test_asr_passes_resolved_local_path_to_qwen(monkeypatch):
    import importlib.util
    from pathlib import Path

    calls = []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float16="float16"))

    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setitem(
        sys.modules,
        "qwen_asr",
        SimpleNamespace(Qwen3ASRModel=SimpleNamespace(from_pretrained=load)),
    )
    spec = importlib.util.spec_from_file_location(
        "isolated_asr", Path(__file__).parents[1] / "asr.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module, "resolve_model_directory", lambda model, cfg: "/cached/asr"
    )
    module.ASR(Config(offline_only=True))
    assert calls[0][0] == ("/cached/asr",)
    assert calls[0][1]["local_files_only"] is True
