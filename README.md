# Framecheck / Postscore AI

本地优先的视频后期质检项目，包含两个互补产品：

- [`engine/`](engine)：`postscore-ai` Python CLI。支持单视频和批量检测、100 分制评分、时间码问题清单、HTML/JSON 报告与 CSV 总览。
- [`web/`](web)：Framecheck 浏览器版。视频只在当前浏览器内解码，核心质检流程免登录、免上传。

## 为什么放在同一个仓库

两者服务同一份视频质检标准，但面向不同使用场景：CLI 适合深度检测、批量任务和团队报告；浏览器版适合快速自助检查。它们保留独立依赖和运行方式，后续可以逐步共享报告 schema 与评分阈值。

## Python 深度质检

需要 Python 3.10+、FFmpeg 和 ffprobe。

```bash
cd engine
python -m venv .venv
python -m pip install -e ".[dev]"
pytest
python -m postscore review --mock --html --json
```

详细命令与批量模式见 [`engine/README.md`](engine/README.md)。

## Framecheck 浏览器版

需要 Node.js 22.13+。

```bash
cd web
npm ci
npm run dev
npm run build
npm test
```

脚本通过 `cross-env` 兼容 Windows、macOS 与 Linux，无需额外修改 npm shell。

浏览器版不会把选择的视频上传到服务器。当前核心流程不依赖账号、会话或登录守卫。

## 隐私和发布边界

- 不提交视频、关键帧、历史报告、`.venv`、`node_modules`、cookies、tokens 或浏览器状态。
- 在线链接能力受平台策略影响；公开仓库不包含任何登录凭据。
- 浏览器版的 FPS 仍属于未完全覆盖项，需要在严格交付时用 FFprobe 复核。
