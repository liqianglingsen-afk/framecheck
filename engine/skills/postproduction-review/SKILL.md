---
name: postproduction-review
description: Use when the user asks for local video post-production scoring, batch video QC, folder/link review, editing/color grading checks, or Chinese HTML/JSON reports; supports 后期评分, 批量视频质检, 文件夹评分, 多链接评分.
---

# Postproduction Review Skill

这个 Skill 用于调用 `postscore-ai` 本地 Python CLI，对视频后期处理品质进行评分，并生成中文 HTML/JSON 报告。

## 触发词

- 后期评分
- 视频评分
- 后期检测
- 视频质检
- 剪辑评分
- 调色评分
- Amazon后期评分
- 抖音后期评分
- 小红书后期评分
- TikTok后期评分
- 深度后期评分
- 批量后期评分
- 多视频评分
- 文件夹评分
- 多链接评分

## 执行流程

1. 从用户消息中提取所有本地视频路径、文件夹路径和公开视频链接。
2. 如果只有 1 个视频源，使用 `review`；如果有多个源、包含文件夹，或用户说“批量/多个/文件夹”，使用 `batch`。
3. 根据关键词选择 preset。
4. 固定使用 `deep` 模式；项目已取消 `fast` 快检。
5. 运行环境检查；如果 FFmpeg、ffprobe 或 Python 依赖缺失，先提示修复。
6. 调用本地命令生成报告。
7. 返回总分、等级、Top 5 问题、HTML 报告路径、JSON 报告路径；批量任务还要返回批量总览 HTML 和 CSV。

## 默认命令

```bash
python -m postscore review "video.mp4" --mode deep --preset default --html --json
```

`--mode deep` 可以省略：

```bash
python -m postscore review "video.mp4" --preset default --html --json
```

批量评分：

```bash
python -m postscore batch "D:\path\to\videos" "https://example.com/video" "D:\path\to\a.mp4" --preset short_social
```

## 深度检测策略

- 默认抽帧目标为 3 fps。
- 默认最多抽取约 360 张关键帧，避免 3 分钟视频无上限抽 500+ 张导致速度不稳定。
- 默认关键帧宽度上限为 720 像素。
- 默认最多 48 张代表帧进入可选 AI 接口；MVP 不默认调用云端 AI。
- 如果用户明确要更细，可以设置 `--max-sampled-frames 0` 取消关键帧上限。

## preset 选择逻辑

- `default`：普通视频。
- `amazon_product`：用户提到 Amazon、电商产品、产品视频。
- `short_social`：用户提到抖音、小红书、TikTok、短视频、Reels。
- `brand_commercial`：用户提到品牌片、广告片、宣传片。

## 报告体验规则

- 结论先行：`最终建议` 必须放在总评分下方、分项评分前方。
- 主结论醒目：`是否可发布` 是第一优先信息，应作为主卡突出展示。
- 指标中文化：关键帧指标不能直接暴露 Python 字典或英文键。
- 时间轴不能叠字：时间轴点只放 marker 和 title，文字说明放到独立事件卡。
- Top 问题和关键帧证据使用自适应网格，浏览器宽度变化时每行约 1-5 个问题。
- 横屏和竖屏证据图都必须完整展示，图片使用 `object-fit: contain`，不要裁切主体。
- 批量总览只做导航和摘要；每个视频都必须生成单独完整 HTML/JSON 评分报告。

## 输出格式

单视频只返回：

- 总分
- 等级
- Top 5 问题
- HTML 报告路径
- JSON 报告路径

批量任务返回：

- 成功数量 / 失败数量
- 批量总览 HTML
- 批量汇总 CSV
- 每条视频的短名称、来源位置或原始链接、单独 HTML/JSON 报告路径

## 重要限制

不能编造视觉问题。所有扣分理由必须基于指标、时间点或关键帧证据。如果没有真实视频，只能明确说明是 mock 示例报告。

公开视频链接下载依赖平台策略和登录状态，可能失效。只有在用户明确授权时，才可使用当前任务所需 cookie；不要在报告、日志或回复中泄露 cookie/token。下载失败时优先让用户提供本地视频。
