# tests/test_terms.py
"""术语修正引擎的行为契约：纠错有效、防御性不误伤、direct 定点替换。"""
from chalkpress.terms import BUILTIN_SCENE, builtin_direct, builtin_terms, fix_custom

# 软考预置包全量（行为契约针对真实数据）
SOFT = builtin_terms()


def test_exact_pinyin_homophone_replaced():
    got, n = fix_custom("重点啊是学习一个二叉数", SOFT)
    assert got == "重点啊是学习一个二叉树"
    assert n == 1


def test_correct_term_untouched():
    got, n = fix_custom("接下来学习最小生成树", SOFT)
    assert got == "接下来学习最小生成树"
    assert n == 0


def test_fuzzy_requires_same_initial():
    """近音替换只认可同声母的单音节差异：shi→man 不构成近音。"""
    got, n = fix_custom("是二叉树", SOFT)
    assert got == "是二叉树" and n == 0


def test_no_single_char_substitution():
    """单字条目被禁用：站/栈 同音但不得被替换。"""
    got, n = fix_custom("队列与站", SOFT)
    assert got == "队列与站" and n == 0


def test_non_cjk_passthrough():
    for text in ("", "hello world", "tuopu排序"):
        got, n = fix_custom(text, SOFT)
        assert got == text and n == 0


def test_direct_confusion_fixed():
    """direct 定点替换：近音非同音（拼音匹配覆盖不到）的误听。"""
    got, n = fix_custom("这就是最小生存数问题", SOFT, builtin_direct())
    assert got == "这就是最小生成树问题" and n == 1


def test_builtin_scene_package_consistent():
    """预置包自洽：场景名非空、术语纯汉字≥2字、direct 值都在术语表或可独立成词。"""
    assert BUILTIN_SCENE == "软考"
    assert all(len(t) >= 2 for t in builtin_terms())
    assert all(w != r and r for w, r in builtin_direct().items())
