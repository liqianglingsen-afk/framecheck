---
name: postproduction-review
description: Use when the user asks for local video post-production scoring, batch video QC, folder/link review, editing/color grading checks, or Chinese HTML/JSON reports; supports 后期评分, 批量视频质检, 文件夹评分, 多链接评分.
---

# Postproduction Review Skill

这个 Skill 用于调用 `postscore-ai` 本地 Python CLI，对视频后期处理品质进行评分，并生成中文 HTML/JSON 报告。

## 综合审片 · 0.5.0

从 brief 建 editorial-0.5。主任务与辅助切口分别写清；核对独立封面、已证实平台实显、首帧及设计候选，按传播和美学各 50 分；弱封面给两个观看动机。前三秒按主体 4、受众 4、观看理由 5、可信线索 4 逐项给源时码。弱钩子给两个三拍开场。登记亮相、质感、功能及尾镜，逐一注明画面／屏显／字幕／声音的去向。按同机连续实录核复位时间和真实零值。正常播放与静音核对主体关系，错误、擦空或主体误认须在发布前修改。见[填写示例与字段说明](https://github.com/liqianglingsen-afk/creator-video-ops/blob/main/skills/short-video-forensic-teardown/references/creative-evidence.md)。

## 全片修改与原改复评

有修改方案或改片时执行[全片修改与对照约定](https://github.com/liqianglingsen-afk/creator-video-ops/blob/main/skills/short-video-forensic-teardown/references/full-revision.md)。用 revision-plan 记录剪前十维预测及保留资产；revision-render 绑定快照和实际导出；review 对两版评分；revision-compare 是“按方案修改”及原改对照的最终入口。输出成对标准报告、视频及未验项。缺历史预测如实标注。仅单片技术或批量评分仍用原入口。

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

## 短视频优化验收

短视频优化目标至少 **85/100**。使用 `short_social` 时单条和批量报告自动给出目标、差距与后期验收状态。电商短视频、品牌短片需要专用评分预设时，保留预设并加 `--optimization-target 85`；更高目标用指定分数。仅评分时保留原件，给出当前文件的分数和按优先级排列的修改清单。

要求优化时，先核对扣分处与现有素材，按“源文件＋入出点 → 成片位置 → 轨道、操作与参数 → 扣分证据 → 验收”给剪辑单及可运行的 FFmpeg 命令、脚本或工程。优先用现成镜头、原声、字幕和图卡；例如删除停顿时同步裁剪音画，给出两轨切点。Codex 能做的直接导出新版本，检查成片的画面、声音、字幕和关键信息，再用原预设与相同抽样设置复评。预测、示例和未导出的方案标注待验。技术评分与内容拆解分别报告。

只有确认现有素材不足，或试剪反馈说明剩余差距靠剪辑无法解决时，才提出新增、重做或重拍。列出剩余扣分、已查素材和尝试、缺失证据、最少补几镜、每镜动作/台词/景别/秒数、接在哪个切点以及怎样验收。原片已过线时优先保留有效镜头。

## 传播评分与修改排序 · v0.3.0

短视频评分、拆解及优化共用[传播与美学审片约定](https://github.com/liqianglingsen-afk/creator-video-ops/blob/main/skills/short-video-forensic-teardown/references/editorial-review.md)。先核目标受众、入口、前三秒承诺及兑现、结尾收益与真实承接，检查哪些镜头必须保留。按事实问题、目标瓶颈、证据和成本选 1–3 项。前台分别显示十维内容分、后期技术分、封面双轴分和发布前问题。按委托制作首选与挑战剪法或封面，复核手机预览与实际导出。单纯评分保留原片。

使用 Framecheck 0.3+ 的 `postscore brief` 创建底稿并由 Codex 依据实际审片填写，再用 `review --editorial` 或 `batch --editorial-dir` 生成报告。初次裸跑技术检查时传播判断待核。纯技术任务可直接交付；用户问传播/转化或综合评分时继续完成可验证的创意审片，包含内容百分制及封面证据。缺真实发布封面或转化组件时写待核，按当前素材提出候选。需要成交、关注或回访数据时用可选的 metrics_csv 导入。

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

单视频返回以下结果；短视频另附目标、差距及对应版本，优化任务附剪辑单、成片或待补素材项。

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
