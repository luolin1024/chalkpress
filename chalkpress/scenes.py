"""场景术语包：LLM 识别课程领域场景 → 术语缓存 → 拼音比对修正。

软考静态术语表只覆盖一个领域；本模块让术语修正适配任意场景：
校对前先用一次轻量 LLM 调用判断字幕所属领域场景，并提取该场景下
易被 ASR 听错的高频专业术语，缓存到 config_dir()/term_scenes/<场景>.json。
再次检测到相同场景直接复用缓存（不再调 LLM 提术语）；缓存可在设置页删除。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from .config import LLMConfig, config_dir
from .terms import _is_hanzi, fix_custom

_PROMPT = """你是课程领域分析助手。下面是一段课程视频的语音识别字幕抽样。请判断内容所属的领域场景，并提取该场景下容易被语音识别听错的高频专业术语。

只输出 JSON，格式：
{"scene": "简短场景名，如：软考 / Python编程 / 临床医学", "terms": ["术语1", "术语2"], "confusions": {"误听写法": "标准术语"}}

要求：
- terms 只收 ≥2 个汉字的中文专业术语或固定名词，10~30 个，按误听概率排序；
- confusions 只收「实际被听错成的写法 → 标准术语」，两者均为 ≥2 个汉字的纯中文，
  误听写法与标准写法读音相近但不相同；没有则给空对象；
- 不收普通词汇、英文、数字；
- 场景名不超过 20 字，同一领域尽量使用简短统一的名字（如"软考"而非"软考-软件设计师"）。

字幕抽样：
"""


def scenes_dir() -> Path:
    """场景术语缓存目录（每场景一个 JSON 文件）。"""
    return config_dir() / "term_scenes"


def _scene_path(scene: str) -> Path:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", scene.strip()).strip("-") or "scene"
    return scenes_dir() / f"{slug}.json"


def load_scene(scene: str) -> dict | None:
    try:
        return json.loads(_scene_path(scene).read_text(encoding="utf-8"))
    except Exception:
        return None


def save_scene(scene: str, terms: list[str], direct: dict[str, str] | None = None) -> None:
    d = scenes_dir()
    d.mkdir(parents=True, exist_ok=True)
    payload = {"scene": scene, "terms": terms, "updated_at": int(time.time())}
    if direct:
        payload["direct"] = direct
    _scene_path(scene).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                  encoding="utf-8")


def delete_scene(scene: str) -> bool:
    """删除场景术语缓存；返回是否存在过。"""
    p = _scene_path(scene)
    if not p.exists():
        return False
    p.unlink()
    return True


def list_scenes() -> list[dict]:
    """全部缓存场景（按最近更新排序）：[{scene, count, updated_at}]。"""
    out = []
    d = scenes_dir()
    if not d.is_dir():
        return out
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({"scene": data.get("scene", p.stem),
                        "count": len(data.get("terms", [])),
                        "updated_at": int(data.get("updated_at", 0))})
        except Exception:
            continue
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return out


def detect_scene(texts: list[str], cfg: LLMConfig, timeout: int = 180) -> dict | None:
    """字幕抽样 → {"scene", "terms", "confusions"}；LLM 未按格式回复返回 None。"""
    body = "\n".join(t.strip() for t in texts if t.strip())[:6000]
    if not body:
        return None
    resp = requests.post(
        cfg.api_base + "/chat/completions",
        json={"model": cfg.model,
              "messages": [{"role": "user", "content": _PROMPT + body}],
              "temperature": 0.0, "max_tokens": 2048},
        headers={"Authorization": f"Bearer {cfg.api_key}"}, timeout=timeout)
    resp.raise_for_status()
    text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    scene = str(data.get("scene") or "").strip()[:40]
    if not scene:
        return None
    terms = []
    for t in data.get("terms") or []:
        t = str(t).strip()
        if 2 <= len(t) <= 30 and any("\u4e00" <= c <= "\u9fff" for c in t):
            terms.append(t)
    confusions = {}
    for wrong, right in (data.get("confusions") or {}).items():
        wrong, right = str(wrong).strip(), str(right).strip()
        if (len(wrong) >= 2 and len(right) >= 2 and wrong != right
                and _is_hanzi(wrong) and _is_hanzi(right)):
            confusions[wrong] = right
    return {"scene": scene, "terms": terms[:40], "confusions": confusions}


PACK_BASES = (
    "https://cdn.jsdelivr.net/gh/luolin1024/chalkpress@main/scene-packs",
    "https://raw.githubusercontent.com/luolin1024/chalkpress/main/scene-packs",
)
PACK_FILES = {"软考": "ruankao.json"}  # 预置场景包 → 仓库 scene-packs/ 文件名


def _fetch_pack_payload(fname: str, timeout: int = 12) -> dict:
    """拉取并校验预置场景包载荷。多镜像 × (系统代理→直连) 依次尝试，全失败抛最后一次异常。

    直连兜底：requests 默认走 macOS 系统代理，代理客户端抖动时本地直连
    jsDelivr 往往仍可达——两种路径各试一次，自动获取才不会间歇性失败。
    """
    last_exc: Exception | None = None
    direct_kw = {"http": None, "https": None}  # 显式绕过系统代理
    for base in PACK_BASES:
        for proxies in (None, direct_kw):
            try:
                kwargs = {"timeout": timeout,
                          "headers": {"Accept": "application/json"}}
                if proxies is not None:
                    kwargs["proxies"] = proxies
                resp = requests.get(f"{base}/{fname}", **kwargs)
                resp.raise_for_status()
                data = resp.json()
                terms = [str(t).strip() for t in data.get("terms") or []
                         if len(str(t).strip()) >= 2 and _is_hanzi(str(t).strip())]
                direct = {}
                for wrong, right in (data.get("direct") or {}).items():
                    wrong, right = str(wrong).strip(), str(right).strip()
                    if (len(wrong) >= 2 and len(right) >= 2 and wrong != right
                            and _is_hanzi(wrong) and _is_hanzi(right)):
                        direct[wrong] = right
                if not terms:
                    raise ValueError("场景包术语表为空")
                return {"terms": terms, "direct": direct}
            except Exception as exc:
                last_exc = exc
    raise RuntimeError(f"场景包下载失败（已尝试 {len(PACK_BASES)} 个源 × 代理/直连）：{last_exc}")


def download_pack(name: str = "软考", timeout: int = 30) -> dict:
    """手动拉取预置场景包并落盘（CLI/测试用；GUI 走自动获取，无需用户操作）。"""
    fname = PACK_FILES.get(name)
    if not fname:
        raise KeyError(f"没有名为「{name}」的预置场景包")
    payload = _fetch_pack_payload(fname, timeout)
    save_scene(name, payload["terms"], payload["direct"])
    return {"scene": name, "terms": payload["terms"], "count": len(payload["terms"])}


def _auto_fetch_pack(scene: str) -> dict | None:
    """检测场景命中预置包注册表时自动拉取并按规范名落盘（下次直接命中缓存）；
    任何失败静默返回 None（不阻塞转换，仅用 LLM 现场收集）。"""
    fname = next((f for pack, f in PACK_FILES.items()
                  if scene.startswith(pack) or pack.startswith(scene)), None)
    if not fname:
        return None
    pack_name = next(pack for pack, f in PACK_FILES.items() if f == fname)
    try:
        payload = _fetch_pack_payload(fname)
    except Exception:
        return None
    save_scene(pack_name, payload["terms"], payload["direct"])
    return payload

def _find_cache(scene: str) -> Path | None:
    """缓存定位：精确 slug 命中 → 场景名互为前缀的变体命中（LLM 命名漂移容忍）。"""
    exact = _scene_path(scene)
    if exact.exists():
        return exact
    best: tuple[int, Path] | None = None
    for f in scenes_dir().glob("*.json"):
        name = f.stem
        if scene.startswith(name) or name.startswith(scene):
            if best is None or len(name) > best[0]:
                best = (len(name), f)
    return best[1] if best else None


def apply_scene_terms(segments: list[dict], cfg: LLMConfig,
                      sample_n: int = 80) -> tuple[str, int, int]:
    """场景检测 → 缓存合并 → 就地修正 segments。返回 (场景名, 术语数, 修正处数)。

    场景名为空表示检测未成功（调用方跳过日志）；缓存命中后不再请求 LLM 提词，
    但场景检测本身仍需一次 LLM 调用来确定当前视频属于哪个领域。
    """
    texts = [s["text"] for s in segments if s.get("text", "").strip()]
    if not texts:
        return "", 0, 0
    step = max(1, len(texts) // sample_n)
    info = detect_scene(texts[::step][:sample_n], cfg)
    if not info:
        return "", 0, 0
    scene = info["scene"]
    cached_path = _find_cache(scene)
    cached = load_scene(cached_path.stem) if cached_path else {}
    if not cached.get("terms"):
        # 首次遇到该领域：命中预置包注册表则自动拉取一次，全程无需用户操作；
        # 拉取失败静默降级为仅 LLM 现场收集，不阻塞转换
        auto = _auto_fetch_pack(scene)
        if auto:
            cached = {"terms": auto["terms"], "direct": auto.get("direct") or {}}
    merged = list(dict.fromkeys(cached.get("terms", []) + info["terms"]))
    direct = dict(cached.get("direct") or {})
    direct.update(info.get("confusions") or {})
    n = 0
    if merged or direct:
        from .terms import fix_custom
        for s in segments:
            s["text"], k = fix_custom(s["text"], merged, direct)
            n += k
    if set(merged) != set(cached.get("terms", [])) or (
            direct and direct != cached.get("direct")):
        save_scene(scene, merged, direct)
    return scene, len(merged), n
