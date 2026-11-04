# Changelog

更早的版本说明见 [GitHub Releases](https://github.com/luolin1024/chalkpress/releases)。

## [0.5.2] - 2026-11-05

### Changed

- 反馈通道切换为直连飞书开放 API 写多维表格（方案 B）：tenant_access_token 内存缓存（expire-300s），提交失败重试 2 次（其间刷新 token 一次），仍失败降级引导 GitHub Issues
- 凭据改为 env 文件（`CHALKPRESS_FEEDBACK_ENV` 指向，默认 `~/.config/chalkpress-feedback.env`，600）或环境变量直接注入（`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_BITABLE_APP_TOKEN` / `FEISHU_BITABLE_TABLE_ID`），不再读取 webhook；凭据永不写入仓库/config.toml；缺失或不完整时设置页反馈入口隐藏并 log 一行 warn

## [0.5.1] - 2026-11-05

### Added

- 应用内反馈通道（直达开发者飞书群）：设置页新增「反馈」入口，表单含反馈类型/内容描述/联系方式（选填），可选附带诊断日志（末尾 50 行）；webhook 未配置时入口自动隐藏；提交失败降级引导 GitHub Issues
