"""通用术语修正引擎：滑窗拼音比对 + 误听定点替换（确定性，零 LLM 调用）。

ASR 错误以同音/近音字为主（"生存数"→"生成树"等）。把文本按术语最大长度
滑窗取纯汉字 span，与给定术语表的无声调拼音序列比对，命中即替换为标准写法；
≥4 字 span 额外允许编辑距离 ≤1 的近音命中（eng/en 混淆类）；direct 映射
处理近音非同音的定点替换。

误替换防线：
- 只收 ≥2 字条目，且无声调拼音不与常用词冲突（单字如"栈"zhan 与站/占/战
  同音，禁止单字条目）；
- 短 span（<4 字）只做全等拼音匹配，不做模糊匹配。

词表来源由调用方决定：场景术语缓存（scenes.py，任意领域）或内置软考预置包
（HANZI_TERMS/DIRECT_FIXES，仅作为「软考」场景的种子数据，不再无条件生效）。
"""

from __future__ import annotations

from pypinyin import Style, lazy_pinyin

# 纯汉字术语（≥2 字，无声调拼音无常用词冲突）
HANZI_TERMS = [
    # 计算机组成
    "进制转换", "码制", "原码", "反码", "补码", "移码", "校验码", "奇偶校验",
    "海明码", "循环冗余校验", "浮点数", "阶码", "尾数", "主存", "辅存", "高速缓存",
    "编址", "寻址方式", "立即寻址", "间接寻址", "寄存器", "总线", "中断", "流水线",
    "吞吐率", "加速比", "可靠性", "平均无故障时间", "平均修复时间",
    "复杂指令集", "精简指令集",
    # 操作系统
    "进程", "线程", "死锁", "信号量", "互斥", "临界资源", "调度算法", "时间片轮转",
    "优先级调度", "前趋图", "存储管理", "分页存储", "分段存储", "页面置换",
    "并查集", "拓扑", "生成树", "最小生成树", "普里姆", "克鲁斯卡尔", "迪杰斯特拉",
    "顺序查找",
    "位示图", "树形目录", "设备管理", "假脱机", "嵌入式系统", "实时操作系统",
    "微内核",
    # 程序设计语言
    "编译程序", "解释程序", "文法", "正规式", "正规集", "有限自动机",
    "确定有限自动机", "非确定有限自动机", "后缀表达式", "中缀表达式",
    "前缀表达式", "语法树", "传值调用", "引用调用", "动态绑定", "静态绑定",
    # 数据结构
    "线性表", "顺序表", "单链表", "双向链表", "循环链表", "顺序栈", "链栈",
    "循环队列", "稀疏矩阵", "对称矩阵", "三对角矩阵", "二叉树", "满二叉树",
    "完全二叉树", "平衡二叉树", "二叉排序树", "线索二叉树", "哈夫曼树",
    "哈夫曼编码", "先序遍历", "中序遍历", "后序遍历", "层序遍历", "有向图",
    "无向图", "完全图", "连通图", "邻接矩阵", "邻接表", "深度优先搜索",
    "广度优先搜索", "拓扑排序", "关键路径", "最短路径", "二分查找", "分块查找",
    "哈希表", "时间复杂度", "空间复杂度",
    # 数据库
    "关系模式", "候选码", "主键", "外键", "函数依赖", "事务", "并发控制",
    "封锁协议", "两段锁", "存储过程", "触发器", "实体联系图", "数据字典",
    "反规范化", "数据仓库", "数据挖掘",
    # 网络
    "子网掩码", "网际协议", "传输控制协议", "用户数据报协议", "域名解析",
    "动态主机配置", "路由器", "交换机", "网关", "防火墙", "局域网", "城域网",
    "广域网", "以太网", "无线局域网", "介质访问控制", "曼彻斯特编码",
    "差分曼彻斯特编码", "脉码调制", "波特率", "信道容量", "域名系统",
    # 信息安全
    "对称加密", "非对称加密", "数字签名", "数字证书", "报文摘要", "公钥",
    "私钥", "认证中心", "拒绝服务", "跨站脚本", "特洛伊木马", "计算机病毒",
    "入侵检测", "访问控制",
    # 软件工程
    "需求分析", "概要设计", "详细设计", "软件测试", "白盒测试", "黑盒测试",
    "单元测试", "集成测试", "确认测试", "系统测试", "回归测试", "用例图",
    "类图", "顺序图", "状态图", "活动图", "通信图", "构件图", "部署图",
    "数据流图", "控制流图", "内聚", "耦合", "模块化", "信息隐蔽", "软件维护",
    "适应性维护", "完善性维护", "预防性维护", "改正性维护", "软件质量",
    "成本估算", "关键路径法", "甘特图", "里程碑", "风险管理", "配置管理",
    "版本控制", "敏捷开发", "极限编程", "需求工程", "软件复用", "设计模式",
    "单例模式", "工厂模式", "观察者模式", "策略模式", "装饰器模式", "代理模式",
    "适配器模式", "外观模式", "桥接模式", "组合模式", "享元模式", "命令模式",
    "备忘录模式", "访问者模式", "职责链", "中介者", "解释器", "原型模式",
    "模板方法", "状态模式",
    # 知识产权与标准化
    "著作权", "专利权", "商标权", "商业秘密", "软件保护条例", "著作权法",
    "发明创造", "实用新型", "外观设计", "职务作品", "委托创作",
]

# 定点替换：误听写法 → 标准写法（近音非同音、或含 ASCII 的词条）
DIRECT_FIXES = {
    "生存数": "生成树",      # shengcun vs shengcheng
    "升成树": "生成树",
}

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


BUILTIN_SCENE = "软考"  # 内置软考预置包对应的场景缓存名


def builtin_terms() -> list[str]:
    """软考预置场景包的标准术语表（作为 BUILTIN_SCENE 缓存的种子数据）。"""
    return list(HANZI_TERMS)


def builtin_direct() -> dict[str, str]:
    """软考预置场景包的误听定点替换（误听写法 → 标准写法）。"""
    return dict(DIRECT_FIXES)


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
