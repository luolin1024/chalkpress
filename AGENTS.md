# Repository Guidelines

## Project Overview

**Chalkpress** (repo: video2pdf2) — lecture video → printable handout PDF: scene-detected keyframe pages + aligned key subtitles + optional visual-LLM study notes. Pipeline: scene-change keyframe extraction (content-driven, not per-subtitle), local Whisper ASR, subtitle×keyframe alignment, OpenCC simplified/traditional conversion, optional LLM subtitle proofreading and structured study-note summary. Cross-platform (Windows/macOS/Linux); falls back to `imageio-ffmpeg`'s static binary when system ffmpeg is absent; LLM is any OpenAI-compatible `/chat/completions` endpoint (no SDK). Licensed PolyForm Noncommercial 1.0.0.

Docs, comments, log/UI strings are **Chinese**; code identifiers are English snake_case. Brand name is **Chalkpress** (window titles, installer, artifacts); Python package dir is `chalkpress/`.

## Architecture & Data Flow

Layered, fully synchronous, single-process:

```
UI shells            cli.py (argparse)  /  gui.py (tkinter, sidebar + 转换/设置 panes)
  ↓ call unchanged
Orchestrator         pipeline.run(Options, log, progress) -> Result ; pipeline.run_batch()
  ↓ 5 numbered stages (+ progress events)
Stage modules        asr → correct → textproc → keyframes → align → analyze → pdf
                     (+ scenes.py: LLM 场景术语缓存，term_fix 开启且配置 LLM 时在校对前应用)
Infrastructure       config.py (LLMConfig/LangPack/config.toml/logs_dir)  binaries.py (ffmpeg)
                     update.py (GitHub Releases check + asset download)
```

`pipeline.run()` stages (each logged `[1/5]`…`[5/5]`; emits progress events `stage`/`stage_done`/`frames`/`detected_lang`/`video_done` via the optional `progress` callback):

1. **Subtitles** — `asr.extract_audio` (16k mono PCM wav) → `asr.transcribe` (returns `(segments, detected_lang)`; faster-whisper CPU int8; mlx-whisper on macOS) or `align.parse_srt` when `--reuse-srt` → `textproc.convert` per segment (简繁规范先行：whisper 繁体输出会触发校对模型空转) → `terms.fix_terms`（可选，`--term-fix`/config `term_fix`，软考术语表拼音比对，零 LLM；通用版默认关）→ optional `correct.correct_transcript`（LLM 分块校对，100 条/块；runs when detected language is zh, including `language=auto`）→ `asr.write_srt`.
2. **Keyframes** — `keyframes.plan_frame_times` (ffmpeg scene detection via `detect_cuts`, segment start/end sampling, `min_gap`) → `extract_frames` with average-hash dedup (`_ahash`/`_hamming`).
3. **Align** — `align.align` bins each subtitle by midpoint into the window `(prev_frame_ts, frame_ts]` → `window_markdown` writes `<stem>.aligned.md`.
4. **LLM summary** — `analyze.summarize`（关键帧先经 `_frame_data_url` 压缩重编码再 base64）+ zh/en prompt template; **skipped gracefully when no LLM config**; on 400/413/415/422 retries text-only.
5. **PDF** — `pdf.build_pdf` (reportlab landscape A4; CJK font chain: `CHALKPRESS_FONT` → `chalkpress/fonts/` → platform list → `STSong-Light` CID).

Output per video: `<stem>_讲义/` containing `<stem>.pdf|.srt|.aligned.md|.summary.md` and `keyframes/NN_MMmSSs.jpg` (plus temp `audio.wav`, deleted unless `--keep-wav`). `Options.output_layout` (`original` default | `grouped`) switches to categorized subdirs — `markdown/` (both `.md`), `pdf/`, `attachments/` (frames; srt stays at root); `pipeline._layout_dirs` is the single source of truth. Both md files embed keyframe images via relative links computed from the md file's dir (`align.window_markdown`/`align.frames_gallery` take `img_rel`).

**Intermediate data shapes** (the cross-module contract):
- segment dict: `{"start": float, "end": float, "text": str}` — mutated in place by `correct.py` and the textproc loop.
- window dict: `{"start": prev_ts, "end": ts, "subs": [segment, ...]}` — parallel array to `list[KeyFrame]`.
- Dataclasses: `Options`/`Result` (pipeline), `KeyFrame(ts, path)` (keyframes), `LLMConfig(api_base, api_key, model)`, `LangPack` (config).

`run_batch()` isolates failures: returns `list[Result | Exception]`, polls `cancel_check` between videos, emits `video_start`/`video_error`/`batch_done`, copies options via `dataclasses.replace`. Only `gui.py` uses threads (one worker + `queue.Queue` drained by `root.after(120, ...)`; progress events and update-check results travel the same queue); cancellation is cooperative.

**Config resolution chain** `explicit arg > CHALKPRESS_* env (legacy V2P2_* accepted) > config.toml > built-in default` recurs in four places — keep new config options consistent: `load_llm_config` (config.py), `resolve_options` (pipeline.py), `ffmpeg()` (binaries.py), `register_cjk_font` (pdf.py). Config dir is platform data dir `/chalkpress/`; `_migrate_old_config()` one-time copies legacy `v2p2/config.toml`. Logs (GUI, opt-in via 设置→保留运行日志) go to `logs_dir()`.

## Key Directories

| Path | Purpose |
|---|---|
| `chalkpress/` | The entire package (single flat module, ~16 small files incl. update.py) |
| `packaging/chalkpress.iss` | Inno Setup installer script (per-user, zh-CN wizard via bundled ISL) |
| `chalkpress.spec` | Local PyInstaller spec (onedir + macOS `.app`) |
| `.github/workflows/build-binaries.yml` | Only CI: 3-OS build matrix + release job (rolling `latest` prerelease on main, versioned release on `v*` tags) |

## Development Commands

```bash
# Install (uv preferred; or python3 -m venv + pip)
uv venv .venv && uv pip install -e . --python .venv/bin/python
uv pip install -e ".[mac]"        # optional: mlx-whisper ASR acceleration on Apple Silicon

# Run
chalkpress video.mp4              # CLI, full pipeline (entry: chalkpress/cli.py:main)
chalkpress video.mp4 --language zh --summary-lang zh-en --scene-threshold 0.15
chalkpress 目录/                   # batch: dirs expanded recursively (expand_videos)
python -m chalkpress ...          # identical to `chalkpress` (CLI only — NOT the GUI)
chalkpress-gui                    # tkinter GUI (entry: chalkpress/gui.py:main)
python run_gui.py                 # tri-mode frozen entry: --cli → CLI, file args → GUI preload, none → empty GUI

# Package (requires whisper model staged first)
python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='build/model')"
pyinstaller chalkpress.spec
```

No lint/format/typecheck tooling is configured. CI (`.github/workflows/build-binaries.yml`) triggers on push to `main`, tags `v*`, or manual dispatch; builds macOS-arm64/Windows-x64/Linux-x64 bundles on Python 3.13 via uv (PyInstaller onedir, name `chalkpress`, whisper model frozen at `models/faster-whisper-small`); also builds macOS dmg + Windows Inno setup.exe; a `release` job merges artifacts and publishes to GitHub Releases (rolling `latest` prerelease on main push, versioned release on tags; needs `contents: write`, scoped to that job).

## Code Conventions & Common Patterns

- **`from __future__ import annotations` in every module** — enables PEP 604 unions (`str | None`) on the Python ≥3.9 floor. Keep it in new files.
- **Lazy imports for optional/heavy deps inside functions**: `faster_whisper`, `mlx_whisper`, `opencc`, `tomllib`, `imageio_ffmpeg`, `requests` (update.py). Module level: stdlib + pillow/reportlab only. This is also a packaging requirement — PyInstaller needs `--collect-all` on the heavy packages because static analysis can't see lazy imports.
- **Graceful degradation for optional stages, hard raises for core**: unconfigured LLM → skip summary with log; LLM proofread failure → keep original text; missing ffmpeg → `RuntimeError`; missing video → `FileNotFoundError('视频不存在：…')`.
- **Injected logger + optional progress callback, no `logging` module**: `def run(opt, log=print, progress=None)`; `_emitter(progress)` wraps the callback so GUI event-handler exceptions never break the pipeline. GUI writes the log lines to a file in `logs_dir()` only when 保留运行日志 is on.
- **Raw `requests.post` to `{api_base}/chat/completions`** with `Authorization: Bearer` — no OpenAI SDK (`correct.py`, `analyze.py`).
- **Adding a language = append a `LangPack` entry to `LANG_PACK`** (config.py) — "语言即数据"; note `analyze.py` uses the English prompt template only when `code.startswith("en")`.
- **Underscore-private helpers are imported across modules** (e.g. `from .align import _mmss`) — accepted here, don't "fix" by duplicating.
- **GUI visual tokens** (gui.py): colors `BG/#F5F5F7 SIDE/#E9E9EC CARD/#FFF INK/#1D1D1F INK2/#6E6E73 LINE/#D9D9DE GREEN/#2F5D50`; CJK font = PingFang SC / Microsoft YaHei UI / Noto Sans CJK SC; ttk theme `clam` with `CP.*` styles; `Switch` is a self-drawn Canvas toggle; `draw_logo` paints the mark (green tile + handout page + play triangle) — keep sidebar/пacked-card anchors (`self.acts`, `self.stop_btn`) stable when touching pack order.
- CLI exit codes: `0` ok, `1` no videos/error, `2` any batch item failed, `130` KeyboardInterrupt.
- Env vars: `CHALKPRESS_API_BASE`, `CHALKPRESS_API_KEY`, `CHALKPRESS_LLM_MODEL`, `CHALKPRESS_FFMPEG`, `CHALKPRESS_FONT` (legacy `V2P2_*` still accepted); plus `HF_ENDPOINT=https://hf-mirror.com` auto-fallback when huggingface.co is unreachable (set before `huggingface_hub` import).

## Important Files

| File | Why it matters |
|---|---|
| `chalkpress/pipeline.py` | Orchestrator; `Options`, `Result`, `resolve_options`, 5-stage `run(log, progress)`, fault-tolerant `run_batch(…, progress)`. The only module UIs should call. |
| `chalkpress/gui.py` | Full tkinter app: sidebar (转换/设置), zero-config 转换页 (drop zone → plan chips → run → done stats), settings cards with per-item explainers, log-file switch, update check/download. |
| `chalkpress/config.py` | `LLMConfig`, `LangPack`, `LANG_PACK`, `load_llm_config`, `config_dir/config_path/logs_dir/_migrate_old_config`, hand-rolled TOML read/write (scalars only). |
| `chalkpress/update.py` | GitHub Releases check (`fetch_latest`/`is_newer`), platform asset picking, streamed `download`, `reveal`. |
| `chalkpress/asr.py` | Whisper backend dispatch returning `(segments, detected_lang)`, PyAV bypass (wave→numpy float32), HF mirror fallback, bundled-model resolution (`sys._MEIPASS`). |
| `chalkpress/binaries.py` | `@lru_cache ffmpeg()` resolver: `CHALKPRESS_FFMPEG` → `PATH` → `imageio_ffmpeg`. |
| `run_gui.py` | Frozen-app entry (spec + CI); contains load-bearing PyInstaller workarounds (tqdm lock, resource_tracker exit) — don't remove. |
| `chalkpress.spec` | Authoritative local packaging: onedir + macOS `.app`, freezes `build/model` → `models/faster-whisper-small`, `collect_all` ×6, `console=False`. |
| `packaging/chalkpress.iss` | Windows installer: per-user (`PrivilegesRequired=lowest`), desktop icon task, LZMA2; version injected via `/DAppVersion` from pyproject. |

**Stale-doc traps**: version lives in both `pyproject.toml` and `chalkpress/__init__.__version__` — keep in sync (0.2.0 as of the GUI overhaul). Release assets are named `chalkpress-{platform}`; renaming them breaks `update.pick_asset` matching (it greps "macos"/"windows"/"linux" in asset names).

## Runtime/Tooling Preferences

- Python `>=3.9` floor; CI builds on 3.13. **uv** is the de-facto package manager (README + CI); setuptools ≥68 backend; `packages = ["chalkpress"]`; scripts `chalkpress` / `chalkpress-gui`.
- Dependencies are floor-pinned only (no upper caps): pillow, reportlab, requests, opencc-python-reimplemented, imageio-ffmpeg, faster-whisper; optional `[mac]` extra: mlx-whisper.
- `.gitignore`: `.venv/`, `__pycache__/`, `*.egg-info/`, `build/`, `dist/`, `output/` — never commit any of these; `build/model` holds the staged whisper model for packaging.

## Testing & QA

**There are zero tests** — no test files, no pytest/tox config, no test extra, and CI runs no tests, lint, or typecheck; CI only proves the 3-platform bundles *build* (import-graph freeze + artifact existence). Never claim "test suite passes" here.

Verification guidance for changes:

- **Pipeline/CLI/GUI changes**: run a real conversion on a small mp4 (`chalkpress clip.mp4 -o output/test`) and inspect the produced `.pdf`/`.srt`/`.aligned.md`; exercise `--reuse-srt`, batch-directory, and no-LLM-config paths explicitly. For GUI work, instantiate `App` offscreen (`root.withdraw()`, pump `update()`) or launch the real window and screenshot it — never trust that layout code runs without seeing it.
- **Unit-testable pure functions** (no ffmpeg/models/LLM needed) if you add a test suite: `textproc.detect_zh_script/resolve_zh_script/convert`, `align.parse_srt/_sec/align/window_markdown`, `config.lang_pack/load_llm_config/save-load round-trip`, `update.parse_version/is_newer/pick_asset`, `keyframes.plan_frame_times` (monkeypatch `detect_cuts`), `keyframes._ahash/_hamming/_stamp`, `binaries.ffmpeg()` (monkeypatch env, clear `lru_cache`), `correct_transcript` reply parsing (stub `requests.post`).
- **Packaging changes**: after touching imports of heavy deps, re-verify the `collect_all` list in `chalkpress.spec`/CI still covers them — lazy imports are invisible to PyInstaller static analysis.
