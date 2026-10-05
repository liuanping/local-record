"""配置加载：config.yaml + 顶层默认值。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .paths import config_path, storage_dir

# 顶层默认值（config.yaml 缺失字段时的兜底；浅合并即可，字段都在顶层）
DEFAULTS: dict = {
    "app": {"name": "Local Record", "version": "1.0.0"},
    "llama_server": {
        "release_tag": "b11274", "host": "127.0.0.1", "port": 8091,
        "startup_timeout_sec": 300, "hard_timeout_sec": 600,
        "ctx_size": 16384, "threads": 0, "gpu_layers": 0,
        "max_new_tokens": 4096, "enable_thinking": False,
        "extra_args": [],
    },
    "model": {"filename": ""},
    "asr": {"sample_rate": 16000, "chunk_seconds": 8.0, "backend": "paraformer",
            "speech_min_ratio": 0.06,
            "paraformer": {"model_dir": "asr/paraformer",
                           "model_filename": "model.int8.onnx",
                           "tokens_filename": "tokens.txt"},
            "punctuation": {"enabled": True, "model_dir": "asr/punct",
                            "model_filename": "model.onnx",
                            "tokens_filename": "tokens.json"}},
    "recorder": {"device": None, "sample_rate": 16000, "channels": 1,
                 "dtype": "int16", "save_wav": True, "prefer_wasapi": True,
                 "normalize_save": True},
    "player": {"device": None, "volume": 0.8, "autoplay_after_stop": False},
    "ui": {"theme": "dark"},
    "ocr": {"backend": "auto", "det_model": "PP-OCRv6_det",
            "rec_model": "PP-OCRv6_rec", "device": "cpu",
            "use_doc_orientation_classify": False,
            "use_textline_orientation": True, "pdf_dpi": 200},
    "prompts": {"summarize": "", "qa": "", "locate": ""},
    "logging": {"level": "INFO"},
}


def load_config() -> dict:
    path = config_path()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    merged = dict(DEFAULTS)
    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def storage_path(cfg: dict, dotted_key: str) -> Path:
    """把 config 里以 storage/ 为基准的相对路径解析为绝对路径。

    例如 storage_path(cfg, "asr.sense_voice.model_dir")
    -> <storage>/asr/sense-voice
    """
    node: object = cfg
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return storage_dir()
        node = node[part]
    if isinstance(node, str):
        return storage_dir() / node
    return storage_dir()
