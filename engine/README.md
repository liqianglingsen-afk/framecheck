# postscore-ai

中文名称：视频后期评分系统 / 后期质检系统

`postscore-ai` 是一个本地运行的 Python CLI 工具，用于分析视频后期处理品质，输出 100 分制评分、问题清单、修改建议、JSON 数据和可直接打开的中文 HTML 图文报告。

第一版以稳定跑通和证据可追溯为优先目标：真实视频分析依赖 FFmpeg、ffprobe、OpenCV、NumPy 等本地工具；AI 审美判断只是预留接口，不会默认调用云端 API。

## 当前策略

- 已取消 `fast` 快检选项。
- 所有视频评分统一使用 `deep` 深度检测。
- 默认深度抽帧目标为 3 fps。
- 默认最多抽取约 360 张关键帧，避免 3 分钟视频无上限抽帧导致速度不稳定。
- 默认关键帧宽度上限为 720 像素。
- 如果需要更细检测，可设置 `--max-sampled-frames 0` 取消关键帧上限。
- 报告采用结论先行：总评分下方优先展示最终建议，再展示分项评分。
- 批量评分会为每个视频生成独立完整报告，并额外生成总览页和 CSV。

## 安装方法

需要 Python 3.10+。

Windows：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

macOS / Linux：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install -e .
```

## Windows 安装方法

在 PowerShell 中运行：

```powershell
.\scripts\install_windows.ps1
```

如果没有 FFmpeg，可使用：

```powershell
winget install Gyan.FFmpeg
```

也可以使用 `choco install ffmpeg` 或 `scoop install ffmpeg`。

## macOS / Linux 安装方法

```bash
chmod +x scripts/install_mac_linux.sh
./scripts/install_mac_linux.sh
```

macOS 安装 FFmpeg：

```bash
brew install ffmpeg
```

Ubuntu / Debian 安装 FFmpeg：

```bash
sudo apt update
sudo apt install ffmpeg
```

## 环境检查

```bash
python scripts/check_environment.py
```

检查内容包括 Python 版本、FFmpeg、ffprobe、yt-dlp、OpenCV、Jinja2、Plotly、PyYAML、Pydantic、Rich、报告目录和 HTML 模板。

## 基础使用命令

```bash
python -m postscore review "video.mp4" --html --json
python -m postscore review "video.mp4" --mode deep --html
python -m postscore review "https://example.com/video.mp4" --preset short_social --html
python -m postscore review "video.mp4" --preset amazon_product --html
python -m postscore review "video.mp4" --preset brand_commercial --html
```

默认会生成 JSON；传入 `--html` 会同时生成 HTML。传入 `--open` 会在生成后自动打开 HTML 报告。

## 批量评分

一次给多个链接、文件或文件夹时，使用 `batch`：

```bash
python -m postscore batch "D:\Videos\待评分" "D:\Videos\a.mp4" "https://example.com/video" --preset short_social
```

批量模式会逐个深度检测：

- 本地文件：总览中显示文件名和文件位置。
- 文件夹：默认扫描当前文件夹第一层的视频文件；加 `--recursive` 可递归扫描子文件夹。
- 在线链接：总览中显示短名称、原始链接和下载后的本地分析源。
- 每条视频都会生成一份独立完整的 HTML 评分报告和 JSON 数据报告，内容与单视频 `review` 报告一致。
- 额外生成 `batch_index_*.html` 总览页和 `batch_summary_*.csv` 汇总表；总览页只做导航和汇总，会链接到每条完整报告。
- 单条失败不会中断后续视频，会在总览中标记为 failed 并记录错误。

示例：

```bash
python -m postscore batch "D:\Videos\待评分" --preset short_social --recursive --open
python -m postscore batch "https://example.com/a.mp4" "https://example.com/b.mp4" --preset short_social
```

推荐工作流：

1. 把本地视频放到一个文件夹，或一次粘贴多个链接/文件路径。
2. 统一执行 `postscore batch ... --preset short_social`。
3. 先打开 `batch_index_*.html` 看总览和失败项。
4. 再进入每条视频的独立 HTML 报告查看完整评分、问题证据和修改建议。
5. 对失败的在线链接，优先下载成本地视频后重新跑；平台链接能力依赖 `yt-dlp` 和平台当前策略。

## 深度模式说明

- `deep` 是唯一检测模式。
- 默认 3 fps 抽帧，但最多约 360 张关键帧。
- 3 分钟视频的默认有效抽帧率约为 2 fps。
- 默认关键帧宽度上限 720 像素，用于加快 OpenCV 指标计算。
- 音频用 FFmpeg 快速检测。
- 可选 AI 接口最多 48 张代表帧，MVP 默认不调用云端 AI。

## preset 说明

- `default`：通用视频。
- `amazon_product`：Amazon 产品视频，重点关注产品清晰度、颜色准确性、背景干净度和转化表现。
- `short_social`：抖音、TikTok、小红书、Reels，重点关注前 3 秒、节奏、字幕和手机端安全区。
- `brand_commercial`：品牌宣传片，重点关注调色统一性、高级感、声音质感和品牌视觉一致性。

## HTML 报告示例

没有真实视频时可以生成 mock 示例报告：

```bash
python -m postscore review --mock --html --json
```

报告会输出到 `reports/`，包含总览、分项评分、雷达图、时间轴问题分布、Top 问题、关键帧证据、音频分析、导出规范和修改优先级清单。

报告布局验收标准：

- `最终建议` 位于总评分下方、分项评分前方。
- `是否可发布` 作为主结论醒目展示。
- 所有关键帧指标使用中文标签和百分比/数值格式。
- 时间轴 marker 不承载长文本，问题说明放在独立事件卡中，避免叠字。
- Top 问题和关键帧证据使用自适应网格，浏览器宽度变化时每行约 1-5 个条目。
- 证据图片横屏、竖屏都完整展示，不裁切主体。

## 常见问题

### 链接无法下载怎么办？

先确认链接可公开访问。如果没有安装 `yt-dlp`，链接下载会受影响，但本地视频路径仍可分析。建议改用本地视频文件。

### 没有 FFmpeg 怎么办？

安装 FFmpeg 并确认 `ffmpeg` 和 `ffprobe` 在 PATH 中。安装后重新运行 `python scripts/check_environment.py`。

### 深度检测能否 40 秒内完成？

可以作为默认目标，但不是硬保证。当前策略通过关键帧上限和 720 像素分析帧控制速度；3 分钟左右的视频在普通 Windows 本机上通常可以接近或低于 40 秒。耗时仍受视频编码、磁盘速度、CPU、链接下载速度和是否取消抽帧上限影响。

### 如何提高检测准确度？

可以提高 `--sample-fps`，或设置 `--max-sampled-frames 0` 取消关键帧上限。代价是速度会变慢。

### 如何添加品牌专属评分标准？

新增 `configs/scoring_<brand>.yaml`，定义品牌关注项和阈值，然后在 `scoring.py` 中接入对应 preset 或扩展配置加载逻辑。

## 实测经验

本项目已经根据本机实测修正了几个问题：

- Windows 子进程输出可能不是 GBK，命令执行统一改为 UTF-8 容错解码。
- OpenCV `imread` 不能稳定读取中文路径，改用 `np.fromfile + cv2.imdecode`。
- 报告中的关键帧指标必须用中文展示，避免直接暴露 Python 字典和英文键。
- 公开视频链接可用 `yt-dlp` 下载，但平台风控可能变化，失败时应改用本地视频。
- 深度检测比快检更稳定，项目已取消 fast。
- 结论区必须足够醒目，最终发布建议应早于分项评分出现。
- 多视频评分应使用 `batch`，总览页负责导航，每条视频仍保留独立完整报告。
- 中文仓库或中文路径下的工具脚本要显式使用 UTF-8 容错读取，避免 Windows 默认编码导致失败。

## 后续扩展建议

- OCR 字幕识别和字幕可读性评分。
- 人脸肤色检测。
- 产品主体识别和背景杂乱度模型。
- 平台专属导出规范库。
- 可选本地 VLM 或云端 AI 审美判断。
- 历史评分对比。

## 短视频优化目标

`postscore review clip.mp4 --preset short_social --html --json` 默认以 85/100 验收当前文件的后期技术质量。单条与批量均可用 `--optimization-target 90` 提高目标，或在电商、品牌预设上启用短视频验收。HTML、JSON 和命令行会区分达标、未达标、示例与待核。用相同预设和抽样参数复评导出文件；配套 Skill 提供剪辑清单和条件性补拍方案。

## 传播、创意和封面复核（0.3.0）

`postscore brief source.mp4 --output notes.json` 创建绑定成片指纹的审片底稿。Codex 或编辑依据真实素材填写后，运行 `postscore review source.mp4 --preset short_social --editorial notes.json --html --json`。技术分继续沿用旧预设，内容分采用十项直接相加的新百分制，封面按传播与美学各 50 分单列。只运行技术检测时传播状态为待核。批量使用 `--editorial-dir`，按每份导出 SHA256.json 匹配。指标导入、字段格式和编辑规则见[完整审片操作约定](https://github.com/liqianglingsen-afk/creator-video-ops/blob/main/skills/short-video-forensic-teardown/references/editorial-review.md)。

`postscore calibrate cases.csv --output comparison.json` 对照两位独立评审与实际报告前三项。清单列为 case,type,report,first_a,first_b,score_a,score_b；报告路径相对清单，首项用复核后对齐的同义问题名称。输出逐片记录首选是否一致、共识是否进入前三及评分分差。建议用带货、教程、品牌、剧情的独立样本，保留分歧和留出样本，发布后台数据另判。

## 0.4.0 全片剪辑与成对复评

`revision-init` 从绑定原片的内容报告创建底稿；填写逐项预测、完整时间线和保护项后，用 `revision-plan` 封存并导出 HTML/JSON。`revision-render` 调用项目的剪辑命令，生成可解码视频和绑定快照的导出凭据。`revision-audit` 创建验收底稿，`revision-blind` 提供仅含成片、目标与量表的独立评审表。原改两次 `review` 使用相同设置，最后用 `revision-compare` 生成原改十维表、关键帧、包装及逐版位 UI 校样。无预测快照的旧案例按历史回放处理。

[命令、字段及版位示例](https://github.com/liqianglingsen-afk/creator-video-ops/blob/main/skills/short-video-forensic-teardown/references/full-revision.md)。每个命令均支持 `--help`。单片、批量与历史数据入口继续可用。
