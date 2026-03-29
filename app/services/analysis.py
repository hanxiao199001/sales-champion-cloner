"""
Claude API analysis service.

Takes a structured transcript (with speaker labels) and extracts:
- Call phases (opening, discovery, objection handling, closing)
- Objection handling patterns
- Closing techniques
- Recurring patterns across calls
- Key quotes

This is the core value of the product. Prompt engineering here IS the product.
"""

import json
from anthropic import Anthropic

from app.config import ANTHROPIC_API_KEY

client = Anthropic(api_key=ANTHROPIC_API_KEY)

ANALYSIS_PROMPT = """你是一个资深的房产销售培训专家。你正在分析一位销冠（顶级销售员）的通话录音转写稿。

你的任务是从这份转写稿中提取结构化的销售模式和技巧。

转写稿中，"boss"是销冠（我们要分析的人），"client"是客户。

请分析以下内容并以JSON格式返回：

1. **call_phases** - 通话阶段划分（每个阶段包含：phase_name, start_text, end_text, description, techniques_used）
   常见阶段：开场寒暄、需求挖掘、房源介绍、异议处理、价格谈判、逼单促成、后续安排

2. **objections_handled** - 客户提出的异议及销冠的处理方式（每个包含：objection, response_strategy, exact_quote, effectiveness_notes）

3. **closing_techniques** - 使用的成交技巧（每个包含：technique_name, description, exact_quote, timing_notes）

4. **patterns** - 观察到的销售模式和习惯（每个包含：pattern_name, category, description, frequency_hint, example_quotes）
   category可以是：opening, rapport_building, questioning, presenting, handling_objection, closing, follow_up

5. **key_quotes** - 特别有效或有代表性的话术（每个包含：quote, context, why_effective）

6. **summary** - 一段话总结这通电话的销售策略和风格特点

请确保：
- 引用原文时使用exact_quote字段
- 关注销冠做了什么（不是客户做了什么）
- 特别注意那些不明显的、可能连销冠自己都没意识到的行为模式
- 用中文回复

转写稿：
{transcript}

请以纯JSON格式返回，不要包含markdown代码块标记。"""


PLAYBOOK_INCREMENT_PROMPT = """你是一个资深的房产销售培训专家。你正在帮助更新一位销冠的Playbook（销售手册）。

现有的Playbook模式如下：
{existing_patterns}

新录音的分析结果如下：
{new_analysis}

你的任务是：
1. 识别新分析中出现的新模式（现有Playbook中没有的）
2. 对于已有模式，如果新分析提供了新的例子或细节，标记需要更新的频次和例子
3. 不要删除或重写任何现有模式

请以JSON格式返回：
{{
    "new_patterns": [
        {{
            "category": "opening|objection_handling|closing|discovery|rapport|follow_up",
            "name": "模式名称",
            "description": "描述",
            "example_quotes": ["原文引用"],
            "frequency": 1
        }}
    ],
    "updated_patterns": [
        {{
            "name": "现有模式名称",
            "additional_quotes": ["新的原文引用"],
            "frequency_increment": 1
        }}
    ]
}}

请以纯JSON格式返回，不要包含markdown代码块标记。"""


class AnalysisError(Exception):
    pass


async def analyze_call(transcript_segments: list[dict]) -> dict:
    """
    Analyze a single call transcript and return structured analysis.

    Args:
        transcript_segments: list of {speaker, text, start, end} dicts

    Returns:
        Structured analysis dict with call_phases, objections_handled, etc.

    Raises:
        AnalysisError: on Claude API failure or malformed response
    """
    transcript_text = _format_transcript(transcript_segments)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": ANALYSIS_PROMPT.format(transcript=transcript_text),
                }
            ],
        )
    except Exception as e:
        raise AnalysisError(f"Claude API error: {e}")

    response_text = message.content[0].text

    try:
        analysis = json.loads(response_text)
    except json.JSONDecodeError:
        # Try to extract JSON from response if wrapped in markdown
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        try:
            analysis = json.loads(cleaned)
        except json.JSONDecodeError:
            raise AnalysisError(
                f"Claude returned malformed JSON. Response: {response_text[:500]}"
            )

    required_keys = {"call_phases", "objections_handled", "closing_techniques", "patterns", "key_quotes", "summary"}
    missing = required_keys - set(analysis.keys())
    if missing:
        raise AnalysisError(f"Analysis missing required fields: {missing}")

    return analysis


async def update_playbook_incremental(
    existing_patterns: list[dict], new_analysis: dict
) -> dict:
    """
    Incrementally update the playbook based on new analysis.
    Only adds new patterns or updates frequency/examples. Never removes existing patterns.

    Returns:
        {"new_patterns": [...], "updated_patterns": [...]}
    """
    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": PLAYBOOK_INCREMENT_PROMPT.format(
                        existing_patterns=json.dumps(existing_patterns, ensure_ascii=False, indent=2),
                        new_analysis=json.dumps(new_analysis, ensure_ascii=False, indent=2),
                    ),
                }
            ],
        )
    except Exception as e:
        raise AnalysisError(f"Claude API error during playbook update: {e}")

    response_text = message.content[0].text

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            raise AnalysisError(f"Playbook update returned malformed JSON")

    return result


def _format_transcript(segments: list[dict]) -> str:
    """Format transcript segments into readable text for the prompt."""
    lines = []
    for seg in segments:
        speaker = "销冠" if seg["speaker"] == "boss" else "客户"
        lines.append(f"[{speaker}] {seg['text']}")
    return "\n".join(lines)
