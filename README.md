<div align="center">

# Chalkpress

**把讲座视频变成一册可检索、可打印的讲义 PDF**

🎬 视频 ──→ 📄 讲义 · 关键帧成页 · 字幕随页 · AI 总结开篇 · 全程本地

[![Release](https://img.shields.io/github/v/release/luolin1024/chalkpress?include_prereleases&label=下载)](https://github.com/luolin1024/chalkpress/releases)
[![Platform](https://img.shields.io/badge/平台-Windows%20%7C%20macOS%20%7C%20Linux-blue)](#下载安装)
[![License](https://img.shields.io/badge/许可-PolyForm%20NC%201.0-orange)](#许可与商业授权)
[![Stars](https://img.shields.io/github/stars/luolin1024/chalkpress?style=social)](https://github.com/luolin1024/chalkpress/stargazers)

**[下载最新版](https://github.com/luolin1024/chalkpress/releases)** · [快速上手](#快速上手) · [CLI 用法](#cli) · [常见问题](#常见问题) · [English](./README.en.md)

</div>

---

## 这是什么

看网课时最痛的不是"看"，是**回头找**：视频没法检索、没法打印、拖进度条全靠记忆。

Chalkpress 把一场讲座**压缩成一册讲义**：

```
🎬 视频 ──→ ① 语音转写（Whisper 本地）──→ ② 字幕校对（可选 LLM）
        ──→ ③ 关键帧抽取（场景检测）──→ ④ 字幕×关键帧对齐
        ──→ ⑤ AI 学习笔记（可选）──→ 📄 讲义 PDF
```

| 你得到 | 说明 |
|--------|------|
| `讲义.pdf` | 首页 AI 总结 + 每页一个关键帧画面 + 该时间窗的字幕，**文字层可检索可复制** |
| `字幕.srt` | 全片字幕，可独立导入播放器 |
| `aligned.md` | 字幕×关键帧对照表（Markdown） |
| `summary.md` | AI 结构化学习笔记（配置 LLM 后） |

## 界面预览

**首页** —— 拖入视频即可转换，完成后直接打开产物文件夹：

![Chalkpress 首页](docs/superpowers/imgs/image.png)

**任务列表** —— 数据看板（转换量与节省的观看时长）+ 历史记录查看管理：

![Chalkpress 任务列表](docs/superpowers/imgs/image2.png)

## 为什么是 Chalkpress

- **关键帧成页** —— 场景检测驱动抽帧：内容变化才截，不是机械等间隔
- **字幕随页** —— Whisper 本地转写，字幕对齐到所在画面的时间窗，页面即上下文
- **AI 总结开篇** —— 接任意 OpenAI 兼容视觉模型，生成结构化学习笔记作为 PDF 首页
- **全程本地** —— 转写、抽帧在你电脑上完成，视频不上传；LLM 是唯一可选的外呼
- **场景术语自适应** —— 识别课程领域，把易听错的专业术语缓存复用（软考证被听成软靠正？修掉）
- **暂停与断点续跑** —— 阶段边界可暂停，已完成部分自动保存
- **零配置上手** —— 拖入视频、点开始，其余全部自动

**适合谁**：网课学生 · 做课程笔记的人 · 讲师/培训机构（课后讲义交付）· 内容创作者（视频文字化）

## 下载安装

从 [GitHub Releases](https://github.com/luolin1024/chalkpress/releases) 下载：

| 平台 | 文件 | 说明 |
|---|---|---|
| Windows | `Chalkpress_*_x64-setup.exe` | NSIS 安装向导（简中），per-user 无需管理员 |
| macOS (Apple Silicon) | `Chalkpress_*_aarch64.dmg` | 打开拖入 Applications |
| Linux x64 | `Chalkpress_*_amd64.AppImage` | 赋予执行权限后直接运行 |

应用内置**自动更新**（应用内静默更新）。

## 快速上手

1. 打开 Chalkpress，把视频（或整个课程文件夹）拖入窗口
2. 点 **开始转换**
3. 完成后点 **打开输出文件夹** —— 讲义 PDF 就在视频旁边（`<视频名>_讲义/`）

零配置：语音语言自动识别、字幕模型自动选择、输出语言默认简体中文。
想调整？侧栏 → **设置**：输出语言、简繁、字幕模型、场景灵敏度……每项都有一句话解释。

## CLI

```bash
chalkpress 视频.mp4                       # 全流程
chalkpress 目录/                          # 批量：递归展开目录
chalkpress 视频.mp4 --reuse-srt 已有.srt   # 已有字幕时跳过转写
chalkpress 视频.mp4 --summary-lang zh-en  # 中英对照总结
chalkpress 视频.mp4 --speed turbo         # 转写并发：standard/fast/turbo
chalkpress 视频.mp4 --layout grouped      # 分类输出：markdown/ pdf/ attachments/
chalkpress 视频.mp4 --zh-script traditional  # 繁体输出
```

## AI 分析（可选）

不配置也能用（关键帧 PDF + 字幕）；配置后额外获得字幕校对与结构化总结。

任意 OpenAI 兼容 `/chat/completions` 端点均可（GLM / DeepSeek / SiliconFlow / OpenAI / 本地网关），需支持图片输入：

```bash
export CHALKPRESS_API_BASE="https://open.bigmodel.cn/api/paas/v4"
export CHALKPRESS_API_KEY="sk-..."
export CHALKPRESS_LLM_MODEL="glm-4.6v"
```

也可在 GUI 设置页填写（改动即存，持久生效）。旧 `V2P2_*` 环境变量仍兼容。

## 常见问题

<details>
<summary><b>转写速度多快？</b></summary>

CPU int8 下约实时速度的 2-4 倍（视视频时长与语速）；macOS Apple 芯片自动启用 mlx-whisper GPU 加速，更快。`--speed turbo` 用满全部核心。
</details>

<details>
<summary><b>必须配置 AI 吗？</b></summary>

不必须。不配置 LLM 也能产出「关键帧 PDF + 全片字幕」；配置后才启用字幕校对和 AI 学习笔记。
</details>

<details>
<summary><b>支持英文视频吗？</b></summary>

支持。Whisper 支持 90+ 语种自动识别；`--summary-lang zh-en` 可输出中英对照笔记。
</details>

<details>
<summary><b>我的视频可以上传吗/隐私？</b></summary>

视频**始终不上传**——转写和抽帧全程本地。只有你主动配置 LLM 时，字幕文本与关键帧会发送给你自己配置的模型端点。
</details>

<details>
<summary><b>和剪映/飞书妙记有什么区别？</b></summary>

它们做"转文字"，Chalkpress 做"**讲义**"：关键帧成页（画面+对应字幕在同一页）、可打印可检索的 PDF、AI 结构化总结，且全程本地、批量处理整个课程目录。
</details>

## 技术要点

- **流水线**：`Options → run()/run_batch()` 五段处理链，单个视频失败不中断批量
- **桌面 GUI**：Tauri 2（Svelte），Python 流水线以 PyInstaller sidecar 内嵌
- **本地 ASR**：faster-whisper（CPU int8 全平台）+ mlx-whisper（macOS GPU 加速）
- **可检索 PDF**：reportlab，帧为图、字幕/总结为真实文本层；CJK 字体三平台解析链不缺字
- **配置链**：显式参数 > `CHALKPRESS_*` 环境变量 > config.toml > 内置默认

## 从源码运行

```bash
# CLI（Python ≥ 3.9）
uv pip install -e .
chalkpress 视频.mp4

# GUI（Tauri 2 + Svelte）
corepack pnpm i
corepack pnpm tauri dev     # 开发
corepack pnpm tauri build   # 打包
```

## 路线图

- [x] 桌面 GUI（拖入即转 + 任务看板 + 设置中心）
- [x] 批量/课程目录递归处理
- [x] 三平台安装包 + 应用内自动更新
- [x] 场景术语自适应缓存
- [ ] 多语种界面语言包
- [ ] 云端批量 API（机构版）

## 许可与商业授权

个人/教育/非商业使用：[PolyForm Noncommercial 1.0.0](./LICENSE)。
**闭源 / 商业使用**（培训机构、企业内训等）需获得商业许可，联系作者洽谈。

---

<div align="center">

**觉得有用？给个 ⭐ 让更多人看到**

[下载](https://github.com/luolin1024/chalkpress/releases) · [问题反馈](https://github.com/luolin1024/chalkpress/issues) · [商业授权洽谈](mailto:contact@ai2070.cn)

</div>
