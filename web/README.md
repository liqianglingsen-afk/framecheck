# Framecheck Web

Framecheck 的浏览器本地视频质检界面。用户选择视频后，画面、节奏、音频与可选字幕分析都在当前浏览器中执行；素材不会上传。

## 开发

需要 Node.js 22.13+。

```bash
npm ci
npm run dev
npm run build
npm test
```

脚本通过 `cross-env` 兼容 Windows、macOS 与 Linux，无需额外修改 npm shell。正式部署以 `npm run build` 为门槛，本地交互验收使用 `npm run dev`。

## 产品边界

- 核心上传、分析与报告流程不要求登录。
- 视频只在浏览器中解码，不发送到服务端。
- 浏览器版无法可靠读取所有容器 FPS；严格交付请用仓库 `engine/` 中的 FFprobe 流程复核。
- 可选 SRT/VTT 能增强字幕速度和断句检查。

部署配置位于 `.openai/hosting.json`，用于继续更新现有 Framecheck Sites 项目。
