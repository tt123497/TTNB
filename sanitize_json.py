#!/usr/bin/env python3
"""
sanitize_json.py — 共享的 JSON 写入工具。
所有写入 data.json 的脚本必须用这个模块的 safe_json_dump / atomic_save。
消灭 lone surrogate 导致的 JSON 损坏。
"""
import json, os, re

_SURROGATE_RE = re.compile(r'[\ud800-\udfff]')


def sanitize(obj):
    """递归清洗所有字符串中的孤立代理对（lone surrogates）"""
    if isinstance(obj, str):
        try:
            obj = obj.encode('utf-8', errors='replace').decode('utf-8')
        except Exception:
            pass
        return _SURROGATE_RE.sub('?', obj)
    elif isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


def safe_json_dump(obj, fp, **kwargs):
    """安全的 json.dump — 确保只会写出合法 UTF-8"""
    cleaned = sanitize(obj)
    return json.dump(cleaned, fp, ensure_ascii=False, indent=2, **kwargs)


def atomic_save(data, path):
    """
    原子写入 JSON 文件 — 先写 .tmp 再 rename，避免写入中途崩溃导致文件损坏。
    同时进行 UTF-8 清洗。
    """
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        safe_json_dump(data, f)
    os.replace(tmp, path)


def atomic_save_with_briefing_history(data, data_path, history_path):
    """
    写入 data.json + briefing-history.json（原子 + UTF-8 清洗）。
    自动将 bHistory 字段分离到独立文件。
    """
    bHistory = data.pop('bHistory', None)

    # 写 data.json
    atomic_save(data, data_path)

    # 写 briefing-history.json
    if bHistory is not None:
        atomic_save(bHistory, history_path)
