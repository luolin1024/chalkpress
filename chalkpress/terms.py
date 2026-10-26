"""通用术语修正引擎：滑窗拼音比对 + 误听定点替换（确定性，零 LLM 调用）。

ASR 错误以同音/近音字为主（"生存数"→"生成树"等）。把文本按术语最大长度
滑窗取纯汉字 span，与给定术语表的无声调拼音序列比对，命中即替换为标准写法；
≥4 字 span 额外允许编辑距离 ≤1 的近音命中（eng/en 混淆类）；direct 映射
处理近音非同音的定点替换。

误替换防线：
- 只收 ≥2 字条目，且无声调拼音不与常用词冲突（单字如"栈"zhan 与站/占/战
  同音，禁止单字条目）；
- 短 span（<4 字）只做全等拼音匹配，不做模糊匹配。

词表全部来自调用方：场景术语缓存（scenes.py）或按需下载的场景包
（仓库 scene-packs/，如软考包）——引擎本身不携带任何领域数据。
"""

from __future__ import annotations

from pypinyin import Style, lazy_pinyin

_PINYIN_CACHE: dict[str, tuple] = {}
_INIT_CACHE: dict[str, tuple] = {}


def _py(s: str) -> tuple:
    t = _PINYIN_CACHE.get(s)
    if t is None:
        t = _PINYIN_CACHE[s] = tuple(lazy_pinyin(s))
    return t




def _is_hanzi(s: str) -> bool:
    return all("\u4e00" <= c <= "\u9fff" for c in s)


def _initials(s: str) -> tuple:
    t = _INIT_CACHE.get(s)
    if t is None:
        t = _INIT_CACHE[s] = tuple(lazy_pinyin(s, style=Style.INITIALS))
    return t


def _match_in(index: dict, fuzzy: list, span: str) -> str | None:
    """span（纯汉字）→ 应替换为的术语；完全正确或无需替换返回 None。

    index：无声调拼音序列 → 标准写法；fuzzy：参与近音匹配的 ≥4 字术语。
    返回 span 自身表示"整段消费但不替换"（正确的术语，跳过内部重扫）。
    """
    py = _py(span)
    term = index.get(py)
    if term is not None:
        return None if term == span else term
    if len(span) >= 4:
        # 近音：仅同音节数、恰好一个音节不同、且差异音节声母相同
        # （cun/cheng 这类 en/eng 混淆）。shi/man 声母不同的差异不认可，
        # 否则"是二叉树"会被当成"满二叉树"的近音变体误改。
        hits = set()
        for t in fuzzy:
            pty = _py(t)
            if len(pty) != len(py):
                continue
            diff = [k for k, (a, b) in enumerate(zip(py, pty)) if a != b]
            if len(diff) == 1 and _initials(span)[diff[0]] == _initials(t)[diff[0]]:
                hits.add(t)
        if len(hits) == 1:
            return hits.pop()
    return None



def _walk(text: str, match, maxlen: int) -> tuple[str, int]:
    """按术语最大长度滑窗消费文本，match(span) → 替换术语或 None。"""
    n = 0
    out: list[str] = []
    i = 0
    while i < len(text):
        done = None
        for size in range(min(maxlen, len(text) - i), 1, -1):
            span = text[i:i + size]
            if not _is_hanzi(span):
                continue
            term = match(span)
            if term is not None:
                done = (term, size)
                break
        if done is None:
            out.append(text[i])
            i += 1
        else:
            term, size = done
            out.append(term)
            i += size
            n += term != text[i - size:i]
    return "".join(out), n



def fix_custom(text: str, term_list: list[str],
               direct: dict[str, str] | None = None) -> tuple[str, int]:
    """通用术语表修正：direct 定点替换 + 与软考包相同的滑窗拼音比对。

    返回 (修正后文本, 替换处数)。direct 为 误听写法 → 标准写法 的定点映射
    （近音非同音，拼音匹配覆盖不到的 case）。
    """
    n = 0
    for wrong, right in (direct or {}).items():
        if wrong and wrong in text:
            n += text.count(wrong)
            text = text.replace(wrong, right)
    index: dict = {}
    hanzi: list[str] = []
    for t in term_list:
        t = t.strip()
        if len(t) >= 2 and _is_hanzi(t):
            index.setdefault(_py(t), t)
            hanzi.append(t)
    if not index:
        return text, n
    fuzzy = [t for t in hanzi if len(t) >= 4]
    text, k = _walk(text, lambda span: _match_in(index, fuzzy, span),
                    max(len(t) for t in index.values()))
    return text, n + k
