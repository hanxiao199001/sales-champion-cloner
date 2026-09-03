"""
analyze_call / update_playbook_incremental 的单元测试。

不调用真实 Claude API：通过 monkeypatch 替换 anthropic 异步客户端的
messages.create，验证 JSON 解析、markdown 包裹容错、错误映射。
"""

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.services import analysis
from app.services.analysis import AnalysisError, analyze_call, update_playbook_incremental

VALID_ANALYSIS = {
    "call_phases": [],
    "objections_handled": [],
    "closing_techniques": [],
    "patterns": [],
    "key_quotes": [],
    "summary": "测试总结",
}

SEGMENTS = [
    {"speaker": "boss", "text": "您好，我是小王", "start": 0.0, "end": 1.0},
    {"speaker": "client", "text": "你好", "start": 1.0, "end": 2.0},
]


def _fake_message(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _patch_create(monkeypatch, response_text=None, exc=None):
    async def fake_create(**kwargs):
        if exc is not None:
            raise exc
        return _fake_message(response_text)

    monkeypatch.setattr(analysis.client.messages, "create", fake_create)


async def test_analyze_call_success(monkeypatch):
    _patch_create(monkeypatch, json.dumps(VALID_ANALYSIS, ensure_ascii=False))
    result = await analyze_call(SEGMENTS)
    assert result["summary"] == "测试总结"


async def test_analyze_call_strips_markdown_fence(monkeypatch):
    wrapped = "```json\n" + json.dumps(VALID_ANALYSIS, ensure_ascii=False) + "\n```"
    _patch_create(monkeypatch, wrapped)
    result = await analyze_call(SEGMENTS)
    assert result["summary"] == "测试总结"


async def test_analyze_call_missing_fields(monkeypatch):
    _patch_create(monkeypatch, json.dumps({"summary": "只有总结"}))
    with pytest.raises(AnalysisError, match="missing required fields"):
        await analyze_call(SEGMENTS)


async def test_analyze_call_malformed_json(monkeypatch):
    _patch_create(monkeypatch, "这不是JSON")
    with pytest.raises(AnalysisError, match="malformed JSON"):
        await analyze_call(SEGMENTS)


async def test_analyze_call_api_connection_error(monkeypatch):
    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    _patch_create(monkeypatch, exc=exc)
    with pytest.raises(AnalysisError, match="connection error"):
        await analyze_call(SEGMENTS)


async def test_analyze_call_api_status_error(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com")
    response = httpx.Response(429, request=request, json={"error": {"message": "rate limited"}})
    exc = anthropic.RateLimitError("rate limited", response=response, body=None)
    _patch_create(monkeypatch, exc=exc)
    with pytest.raises(AnalysisError, match="HTTP 429"):
        await analyze_call(SEGMENTS)


async def test_update_playbook_incremental(monkeypatch):
    payload = {"new_patterns": [], "updated_patterns": []}
    _patch_create(monkeypatch, json.dumps(payload))
    result = await update_playbook_incremental([], VALID_ANALYSIS)
    assert result == payload
