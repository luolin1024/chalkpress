# tests/test_terms.py
"""术语表修正的行为契约：纠错有效、防御性不误伤。"""
from chalkpress.terms import fix_terms


def test_exact_pinyin_homophone_replaced():
    got, n = fix_terms("重点啊是学习一个二叉数")
    assert got == "重点啊是学习一个二叉树"
    assert n == 1


def test_correct_term_untouched():
    got, n = fix_terms("接下来学习最小生成树")
    assert got == "接下来学习最小生成树"
    assert n == 0


def test_direct_confusion_fixed():
    got, n = fix_terms("这就是最小生存数问题")
    assert got == "这就是最小生成树问题"
    assert n == 1


def test_fuzzy_requires_same_initial():
    """近音替换只认可同声母的单音节差异：shi→man 不构成近音。"""
    got, n = fix_terms("是二叉树")
    assert got == "是二叉树"
    assert n == 0


def test_no_single_char_substitution():
    """单字条目被禁用：站/栈 同音但不得被替换。"""
    got, n = fix_terms("队列与站")
    assert got == "队列与站"
    assert n == 0


def test_non_cjk_passthrough():
    for text in ("", "hello world", "tuopu排序"):
        got, n = fix_terms(text)
        assert got == text and n == 0
