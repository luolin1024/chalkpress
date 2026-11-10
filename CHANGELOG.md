# Changelog

更早的版本说明见 [GitHub Releases](https://github.com/luolin1024/chalkpress/releases)。

## [0.6.1] - 2026-11-08

### Added

- 设置侧新增「关于」入口：应用定位一句话、GitHub 主页 / 问题反馈 / 商业授权直达（系统浏览器打开），版本号与许可说明
- 匿名统计事件扩展：`app_start` 附带 LLM 配置布尔，新增 `batch_start`（批量规模）/ `convert_paused` / `convert_error`（纯计数）/ `feedback_submit`（类型+是否送达），`conversion_done` 附带是否生成 AI 总结——全部不含视频名、内容或路径
- 匿名统计上报落地：每周批量直写飞书多维表格独立「统计」表（复用反馈凭据 app_id/secret，`FEISHU_BITABLE_ANALYTICS_TABLE_ID` 指定表；字段：事件/属性/操作系统/应用版本/匿名ID/时间）；未配置仍只存不发
- 反馈发布通道：新增 ECS 代理提交路径（`CHALKPRESS_FEEDBACK_PROXY_URL`/`CHALKPRESS_FEEDBACK_PROXY_TOKEN` 优先，飞书凭据留服务端；参考实现 `docs/feedback_proxy_server.py`），凭据直连保留为开发路径；Rust 壳编译期注入全部发布配置（CI secrets），任一通道未配置自动停用

## [0.5.2] - 2026-11-05

### Added

- 首次启动隐私确认对话框：一次性征询匿名统计同意（同意/拒绝持久化到 config.toml `[privacy] analytics_consent`，拒绝不影响任何功能）
- 匿名使用统计（`analytics.py`）：同意后本地记录启动/转换完成事件（时间戳、事件名、OS、版本号、页数/耗时计数；随机 UUID 匿名 ID，绝无视频内容/文字/文件名），缓存于 config 数据目录 `analytics_events.json`；每周至多批量上报一次，端点由 `POST_CHALKPRESS_ANALYTICS_URL` 提供——未设置则只存不发、永不联网
- README 商业模式段：个人/教育永久免费（含全部功能）；匿名统计可拒绝；培训机构/企业商用需购买商业授权

### Changed

- 反馈通道切换为直连飞书开放 API 写多维表格（方案 B）：tenant_access_token 内存缓存（expire-300s），提交失败重试 2 次（其间刷新 token 一次），仍失败降级引导 GitHub Issues
- 凭据改为 env 文件（`CHALKPRESS_FEEDBACK_ENV` 指向，默认 `~/.config/chalkpress-feedback.env`，600）或环境变量直接注入（`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_BITABLE_APP_TOKEN` / `FEISHU_BITABLE_TABLE_ID`），不再读取 webhook；凭据永不写入仓库/config.toml；缺失或不完整时设置页反馈入口隐藏并 log 一行 warn

### Removed

- 移除全部 `V2P2_*` 旧环境变量兼容（API_BASE/API_KEY/LLM_MODEL/FFMPEG/FONT）与 v2p2 目录配置迁移——上线新项目无历史包袱，`CHALKPRESS_*` 不受影响

## [0.5.1] - 2026-11-05

### Added

- 应用内反馈通道（直达开发者飞书群）：设置页新增「反馈」入口，表单含反馈类型/内容描述/联系方式（选填），可选附带诊断日志（末尾 50 行）；webhook 未配置时入口自动隐藏；提交失败降级引导 GitHub Issues
