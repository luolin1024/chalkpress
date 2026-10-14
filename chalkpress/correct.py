"""LLM 字幕校对：修正 ASR 同音字/近音字错误（可配置，可关闭）。

策略：编号行进出、temperature=0；分块送审（全局编号），解析结果按编号回写，
任何解析异常只影响对应块（未匹配的行保持原文），整体失败由调用方兜底。
"""

from __future__ import annotations

import re
import time

import requests

from .config import LLMConfig

_PROMPT = """你是字幕校对员。下面是语音识别(ASR)输出的中文字幕，可能包含同音字/近音字/分词错误。
请逐条修正明显的识别错误（计算机与软考专有名词按行业习惯写法，例如"主讲老师"而非"主江老师"），要求：
- 不改写句式，不增删内容，不合并/拆分条目，不翻译；
- 无法确定的保持原文。

输入是编号行 `编号|文本`，输出同样格式的编号行 `编号|修正后文本`。
必须覆盖全部编号且顺序一致，除编号行外不要输出任何其他文字。
"""


def correct_transcript(segments, cfg: LLMConfig, timeout: int = 900,
                       chunk_size: int = 100) -> int:
    """就地修正 segments[i]['text']，返回修正条数。失败抛异常由调用方兜底。

    分块送审（全局编号）：长字幕列表单次请求会诱发推理模型长时间空转、
    耗尽 max_tokens 后正文为空（finish=length）；小块请求已实测稳定返回。
    """
    fixed = 0
    failed: list[str] = []
    for start in range(0, len(segments), chunk_size):
        chunk = segments[start:start + chunk_size]
        numbered = "\n".join(
            f"{start + j}|{s['text']}" for j, s in enumerate(chunk, 1))
        try:
            text = _correct_chunk(cfg, numbered, timeout)
        except Exception as exc:  # 单块失败保留其余块的修正，最后汇总上报
            failed.append(f"{start + 1}-{start + len(chunk)}: {exc}")
            continue
        for line in text.splitlines():
            m = re.match(r"^\s*(\d+)\s*[|｜:：、.]\s*(.+)$", line.strip())
            if not m:
                continue
            i = int(m.group(1)) - 1
            new = m.group(2).strip()
            if 0 <= i < len(segments) and new and new != segments[i]["text"]:
                segments[i]["text"] = new
                fixed += 1
    if failed and fixed == 0:
        raise RuntimeError("；".join(failed))
    return fixed


def _correct_chunk(cfg: LLMConfig, numbered: str, timeout: int) -> str:
    for attempt in range(3):
        resp = requests.post(
            cfg.api_base + "/chat/completions",
            json={
                "model": cfg.model,
                "messages": [{"role": "user", "content": _PROMPT + "\n" + numbered}],
                "temperature": 0.0,
                "max_tokens": 16384,
            },
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=timeout,
        )
        # cc-router 上游偶发 502/503/504：退避重试
        if resp.status_code not in (502, 503, 504) or attempt == 2:
            break
        time.sleep(3 * (attempt + 1))
    resp.raise_for_status()
    choice = resp.json()["choices"][0]
    msg = choice["message"]
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError(
            f"校对模型未返回正文（finish={choice.get('finish_reason')}，"
            f"思考 {len(msg.get('reasoning_content') or '')} 字符）；建议增大 max_tokens 或更换模型")
    return text
