"""核心流水线：Options → run()/run_batch() → Result。

CLI 与 GUI 都是薄壳，共用本模块；选项解析顺序：显式传入 > 配置文件 > 内置默认。
处理链：ASR → LLM 字幕校对（可选）→ 简繁规范（OpenCC）→ 关键帧 → 对齐 → LLM 总结（可选）→ PDF。
"""
from __future__ import annotations

import dataclasses
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from . import align, analyze, asr, correct, keyframes, pdf, scenes, textproc
from .config import lang_pack, load_config_file, load_llm_config

# 视频扩展名白名单：CLI 目录展开 / IPC 文件夹枚举共用；TS 侧（对话框过滤器与
# 拖拽正则）跨语言无法共享，改清单时需同步 src/App.svelte 的两处。
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".ts"}


@dataclass
class Options:
    video: Path
    outdir: Path | None = None
    output_layout: str | None = None     # None → 配置文件 → original（原始平铺）
    scene_threshold: float | None = None  # None → 配置文件 → 0.08
    min_gap: float | None = None          # None → 配置文件 → 2.0
    asr_backend: str | None = None        # None → 配置文件 → 自动（按平台选最适配引擎）
    asr_model: str | None = None          # None → 配置文件 → small
    speed: str | None = None              # None → 配置文件 → standard（转写并发档位）
    language: str | None = None           # None → 配置文件 → auto
    zh_script: str | None = None          # None → 配置文件 → auto（按系统 locale）
    auto_correct: bool | None = None      # None → 配置文件 → True（LLM 字幕校对）
    term_fix: bool | None = None          # None → 配置文件 → False（软考术语表修正，通用版默认关）
    reuse_srt: Path | None = None
    summary_lang: str | None = None       # None → 配置文件 → zh
    skip_analysis: bool = False
    skip_pdf: bool = False
    api_base: str | None = None
    api_key: str | None = None
    llm_model: str | None = None
    keep_wav: bool = False


_FILE_OPTION_DEFAULTS = {
    "scene_threshold": 0.08,
    "min_gap": 2.0,
    "asr_backend": None,
    "speed": "standard",
    "asr_model": "small",
    "language": "auto",
    "zh_script": "auto",
    "auto_correct": True,
    "term_fix": False,
    "summary_lang": "zh",
    "output_layout": "original",
}


def resolve_options(opt: Options) -> Options:
    """None 字段回退：配置文件 [options] → 内置默认（显式传入值优先）。"""
    file_cfg = load_config_file().get("options", {})
    updates = {}
    for k, d in _FILE_OPTION_DEFAULTS.items():
        val = getattr(opt, k)
        if val is None:
            updates[k] = file_cfg.get(k, d)
    return dataclasses.replace(opt, **updates)


class PipelinePaused(Exception):
    """用户暂停：阶段边界安全退出，进度已落盘（.progress.json），可断点续跑。"""


def _load_progress(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_progress(path: Path, data: dict) -> None:
    """每个阶段完成后落盘一次；全部完成由 run() 删除该文件。"""
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _layout_dirs(outdir: Path, layout: str) -> dict[str, Path]:
    """输出布局 → 各类产物目录。

    original：summary/（AI 总结）与 aligned/（字幕对照 + keyframes/）两目录，pdf/srt 留根；
    grouped：summary/ aligned/ pdf/ attachments/ 全分类（字幕 srt 仍留在根目录）。
    """
    if layout == "grouped":
        return {"summary": outdir / "summary", "aligned": outdir / "aligned",
                "pdf": outdir / "pdf", "img": outdir / "attachments", "srt": outdir}
    return {"summary": outdir / "summary", "aligned": outdir / "aligned",
            "pdf": outdir, "img": outdir / "aligned" / "keyframes", "srt": outdir}


@dataclass
class Result:
    outdir: Path
    srt: Path | None
    frames: list
    aligned: list
    summary_md: str | None
    summary_path: Path | None
    aligned_path: Path | None
    pdf_path: Path | None
    seconds: float
    duration: float = 0.0


def _emitter(progress):
    """进度事件发射器：GUI 传入 progress 回调，CLI 忽略。"""
    def emit(event, **data):
        if progress:
            try:
                progress(event, **data)
            except Exception:
                pass
    return emit


def run(opt: Options, log=print, progress=None, cancel_check=None) -> Result:
    t0 = time.time()
    opt = resolve_options(opt)
    emit = _emitter(progress)
    video = opt.video.expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"视频不存在：{video}")
    outdir = (opt.outdir or video.with_name(video.stem + "_讲义")).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    dirs = _layout_dirs(outdir, opt.output_layout)
    for d in (dirs["aligned"], dirs["summary"], dirs["pdf"], dirs["img"]):
        d.mkdir(parents=True, exist_ok=True)
    img_rel = Path(os.path.relpath(dirs["img"], dirs["aligned"])).as_posix()
    img_rel_sum = Path(os.path.relpath(dirs["img"], dirs["summary"])).as_posix()
    pack = lang_pack(opt.summary_lang)
    srt_path = dirs["srt"] / f"{video.stem}.srt"
    wav = outdir / "audio.wav"
    prog_path = outdir / ".progress.json"
    prog = _load_progress(prog_path)
    done = set(prog.get("done", []))

    def checkpoint():
        """阶段边界暂停点：此时已完成阶段均已落盘，抛 PipelinePaused 由批量层收尾。"""
        if cancel_check is not None and cancel_check():
            raise PipelinePaused(video.name)

    cfg = None
    if not opt.skip_analysis:
        cfg = load_llm_config(opt.api_base, opt.api_key, opt.llm_model)

    emit("stage", key="asr", name="语音转写")
    checkpoint()
    detected = opt.language or None
    if "asr" in done and srt_path.exists():
        segments = align.parse_srt(srt_path)
        detected = prog.get("detected_lang") or detected
        log(f"[1/5] 断点续跑：复用已完成转写（{len(segments)} 条字幕）")
    elif opt.reuse_srt:
        segments = align.parse_srt(opt.reuse_srt)
        log(f"[1/5] 复用字幕 {opt.reuse_srt}（{len(segments)} 条）")
    else:
        backend = opt.asr_backend or asr.best_backend()
        threads = asr.resolve_threads(opt.speed)
        log(f"[1/5] 抽取音轨 → 本地转写（{backend}/{opt.asr_model}，{threads} 线程）…")
        asr.extract_audio(video, wav)
        lang = None if opt.language in ("auto", "") else opt.language
        segments, detected = asr.transcribe(wav, opt.asr_model, backend, lang,
                                            threads=threads)
        log(f"      {len(segments)} 条原始字幕（检测语言：{detected or '?'}）")
    emit("detected_lang", lang=detected)
    # 先简繁规范再校对：whisper 常输出繁体，繁体原文会与"不翻译/保持原文"
    # 指令冲突，触发推理模型长时间空转直至耗尽 max_tokens（正文为空）
    script = textproc.resolve_zh_script(opt.zh_script)
    if opt.term_fix:
        # 场景术语修正（通用）：AI 识别任意领域 → 收集易听错术语 → 拼音修正；
        # 软考等内置预置包作为场景缓存自动命中，跨视频复用。
        if cfg is None:
            log("      未配置 AI，跳过术语修正（需 AI 识别课程领域）")
        elif segments:
            scenes.seed_builtin_scene()
            try:
                scene, terms_n, fixed = scenes.apply_scene_terms(segments, cfg)
                if scene:
                    log(f"      场景「{scene}」术语 {terms_n} 条，修正 {fixed} 处")
            except Exception as exc:
                log(f"      场景术语检测失败，跳过：{exc}")
    if opt.auto_correct and cfg is not None and segments and detected == "zh":
        emit("stage", key="correct", name="字幕校对")
        log("      LLM 字幕校对（同音字/误听修正）…")
        try:
            fixed = correct.correct_transcript(segments, cfg)
            log(f"      修正 {fixed} 条")
        except Exception as exc:
            log(f"      校对失败，保留原文：{exc}")
        emit("stage_done", key="correct")
    asr.write_srt(segments, srt_path)
    log(f"      {len(segments)} 条字幕（{script}）→ {srt_path.name}")
    done.add("asr")
    prog["done"] = sorted(done)
    prog["detected_lang"] = detected
    _save_progress(prog_path, prog)
    duration = asr.wav_duration(wav) if wav.exists() else keyframes.parse_duration_ffmpeg(video)

    emit("stage", key="frames", name="关键帧对齐")
    checkpoint()
    frames = None
    if "frames" in done:
        try:
            frames = [keyframes.KeyFrame(ts=f["ts"], path=Path(f["path"]))
                      for f in prog.get("frames_manifest", [])
                      if Path(f["path"]).exists()] or None
        except Exception:
            frames = None
        if frames:
            log(f"[2/5] 断点续跑：复用 {len(frames)} 个关键帧")
    if frames is None:
        log(f"[2/5] 场景检测（阈值 {opt.scene_threshold}）→ 抽帧 → 去重 …")
        times = keyframes.plan_frame_times(video, duration, opt.scene_threshold, opt.min_gap)
        frames = keyframes.extract_frames(video, times, dirs["img"])
        log(f"      {len(times)} 个候选 → {len(frames)} 个关键帧")
        prog["frames_manifest"] = [{"ts": f.ts, "path": str(f.path)} for f in frames]
        done.add("frames")
        prog["done"] = sorted(done)
        _save_progress(prog_path, prog)
    emit("frames", count=len(frames))

    log("[3/5] 字幕 × 关键帧 对齐 …")
    aligned = align.align(segments, [f.ts for f in frames])
    aligned_path = dirs["aligned"] / f"{video.stem}.aligned.md"
    aligned_path.write_text(align.window_markdown(aligned, frames, img_rel),
                            encoding="utf-8")
    emit("stage_done", key="frames")

    # 4) LLM 分析（未配置端点则降级跳过）
    summary_md = None
    if opt.skip_analysis:
        log("[4/5] 已指定跳过分析")
    elif cfg is None:
        log("[4/5] 未配置 LLM 端点（配置文件/环境变量 CHALKPRESS_*），跳过分析")
    else:
        checkpoint()
        if "summary" in done and prog.get("summary_md"):
            summary_md = prog["summary_md"]
            log("[4/5] 断点续跑：复用已完成 AI 总结")
        else:
            emit("stage", key="summary", name="AI 总结")
            log(f"[4/5] LLM 分析（{cfg.model}，{len(frames)} 帧）…")
            try:
                summary_md = analyze.summarize(video.stem, duration, aligned,
                                               frames, cfg, pack)
                if summary_md and opt.summary_lang.startswith("zh"):
                    summary_md = textproc.convert(summary_md, script)
            except Exception as exc:  # LLM 不可达/超时：保留字幕与 PDF，仅跳过总结
                log(f"      分析失败，跳过总结：{exc}")
                summary_md = None
            emit("stage_done", key="summary")
        if summary_md:
            # 存干净文本（不含图片廊），续跑重建 PDF 时直接复用
            prog["summary_md"] = summary_md
            done.add("summary")
            prog["done"] = sorted(done)
            _save_progress(prog_path, prog)
    summary_path = None
    if summary_md:
        # 附关键帧图片廊：总结 md 与对照 md 一样内嵌图片，相对链接随布局自适应
        summary_md = summary_md.rstrip() + "\n\n" + align.frames_gallery(frames, img_rel_sum)
        summary_path = dirs["summary"] / f"{video.stem}.summary.md"
        summary_path.write_text(summary_md, encoding="utf-8")

    pdf_path = None
    if opt.skip_pdf:
        log("[5/5] 已指定跳过 PDF")
    else:
        checkpoint()
        emit("stage", key="pdf", name="生成 PDF")
        resume_pdf = dirs["pdf"] / f"{video.stem}.pdf"
        if "pdf" in done and resume_pdf.exists():
            pdf_path = resume_pdf
            log("[5/5] 断点续跑：复用已生成 PDF")
        else:
            log("[5/5] 生成 PDF …")
            pdf_path = pdf.build_pdf(resume_pdf, video.stem,
                                     frames, aligned, summary_md, pack)
            done.add("pdf")
            prog["done"] = sorted(done)
            _save_progress(prog_path, prog)
        emit("stage_done", key="pdf")

    checkpoint()  # 完成前最后一刻暂停：保留进度与中间 wav，续跑零重复
    if wav.exists() and not opt.keep_wav:
        wav.unlink()
    prog_path.unlink(missing_ok=True)

    dt = time.time() - t0
    log(f"完成：{outdir}（{dt:.1f}s）")
    emit("video_done", name=video.name, result=Result(
        outdir=outdir, srt=srt_path if srt_path.exists() else None,
        frames=frames, aligned=aligned, summary_md=summary_md,
        summary_path=summary_path, aligned_path=aligned_path,
        pdf_path=pdf_path, seconds=dt, duration=duration))
    return Result(outdir=outdir, srt=srt_path if srt_path.exists() else None,
                  frames=frames, aligned=aligned, summary_md=summary_md,
                  summary_path=summary_path, aligned_path=aligned_path,
                  pdf_path=pdf_path, seconds=dt, duration=duration)


def run_batch(opt: Options, videos: list[Path], log=print, cancel_check=None,
              progress=None) -> list:
    """批量处理：逐个转换，单个失败不影响后续；暂停在视频间与阶段边界生效。"""
    emit = _emitter(progress)
    results = []
    total = len(videos)
    paused = False
    for i, v in enumerate(videos, 1):
        if cancel_check and cancel_check():
            log(f"已暂停：{total - i + 1} 个视频未处理")
            paused = True
            break
        v = v.expanduser().resolve()
        log(f"═══ [{i}/{total}] {v.name} ═══")
        emit("video_start", index=i, total=total, name=v.name)
        outdir = (opt.outdir / v.stem) if opt.outdir else None
        try:
            results.append(run(dataclasses.replace(opt, video=v, outdir=outdir),
                               log=log, progress=progress, cancel_check=cancel_check))
        except PipelinePaused:
            log(f"⏸ {v.name} 已暂停，进度已保存；再次开始将从断点继续")
            emit("video_paused", name=v.name, index=i, total=total)
            paused = True
            break
        except Exception as exc:  # 单个失败继续下一个
            log(f"✗ {v.name} 失败：{exc}")
            results.append(exc)
            emit("video_error", name=v.name, error=str(exc))
    ok = sum(1 for r in results if isinstance(r, Result))
    if paused:
        emit("batch_paused", ok=ok, total=total)
    else:
        log(f"批量完成：成功 {ok}/{total}")
        emit("batch_done", ok=ok, total=total)
    return results
