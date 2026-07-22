"use client";

import { useEffect, useRef, useState } from "react";
import {
  analyzeVideo,
  formatTime,
  levelLabel,
  type Finding,
  type VideoReport,
} from "./video-analyzer";

const sectionDescriptions = [
  ["01", "技术规格", "片长 · 分辨率 · 画幅 · 音轨"],
  ["02", "画面质量", "黑屏 · 冻帧 · 连续暗场"],
  ["03", "剪辑节奏", "切换密度 · 平均镜头时长"],
  ["04", "音频质量", "静音 · 平均响度 · 峰值"],
  ["05", "字幕包装", "阅读速度 · 行长 · 停留时长"],
];

const severityLabel: Record<Finding["severity"], string> = {
  critical: "致命",
  high: "高",
  medium: "中",
  low: "低",
  info: "提示",
};

function fileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function SectionBar({ section }: { section: VideoReport["sections"][number] }) {
  const percent = section.score === null ? 0 : (section.score / section.weight) * 100;
  return (
    <div className="section-row">
      <div className="section-row__meta">
        <span>{section.label}</span>
        <span className={`status status--${section.status}`}>
          {section.status === "skipped" ? "未覆盖" : `${section.score}/${section.weight}`}
        </span>
      </div>
      <div className="bar" aria-label={`${section.label}得分`}>
        <span className={`bar__fill bar__fill--${section.status}`} style={{ width: `${percent}%` }} />
      </div>
      <div className="section-row__foot">
        <span>{section.findingCount ? `${section.findingCount} 个问题` : section.status === "skipped" ? "本次未检查" : "通过"}</span>
        <span>{section.deductions ? `-${section.deductions}` : ""}</span>
      </div>
    </div>
  );
}

function FindingCard({ finding, index }: { finding: Finding; index: number }) {
  return (
    <article className="finding-card">
      <div className="finding-card__index">{String(index + 1).padStart(2, "0")}</div>
      <div className="finding-card__content">
        <div className="finding-card__topline">
          <span className={`severity severity--${finding.severity}`}>{severityLabel[finding.severity]}风险</span>
          {finding.start !== undefined ? (
            <span className="timecode">
              {formatTime(finding.start)}–{formatTime(finding.end)}
            </span>
          ) : null}
        </div>
        <h4>{finding.message}</h4>
        <p><span>建议</span>{finding.recommendation}</p>
      </div>
      <div className="finding-card__deduction">-{finding.deduction}</div>
    </article>
  );
}

export default function Home() {
  const videoInputRef = useRef<HTMLInputElement>(null);
  const captionInputRef = useRef<HTMLInputElement>(null);
  const previewUrlRef = useRef<string | null>(null);
  const resultRef = useRef<HTMLElement>(null);
  const lastProgressRef = useRef(0);
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [captionFile, setCaptionFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState({ percent: 0, label: "等待视频" });
  const [report, setReport] = useState<VideoReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  function chooseVideo(file?: File) {
    if (!file) return;
    if (!file.type.startsWith("video/")) {
      setError("这不是视频文件。请选择 MP4、WebM 或 MOV。 ");
      return;
    }
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    const url = URL.createObjectURL(file);
    previewUrlRef.current = url;
    setPreviewUrl(url);
    setVideoFile(file);
    setReport(null);
    setError(null);
    setProgress({ percent: 0, label: "准备就绪" });
  }

  async function runAnalysis() {
    if (!videoFile || analyzing) return;
    setAnalyzing(true);
    setError(null);
    setReport(null);
    lastProgressRef.current = 0;
    try {
      const nextReport = await analyzeVideo(videoFile, captionFile, (percent, label) => {
        if (percent === 100 || percent - lastProgressRef.current >= 2) {
          lastProgressRef.current = percent;
          setProgress({ percent, label });
        }
      });
      setReport(nextReport);
      requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分析失败，请换一个视频重试。");
      setProgress({ percent: 0, label: "分析中断" });
    } finally {
      setAnalyzing(false);
    }
  }

  function downloadReport() {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${report.fileName.replace(/\.[^.]+$/, "")}.framecheck.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function copySummary() {
    if (!report) return;
    const summary = [
      `《${report.fileName}》视频质检：${report.score}/100（${levelLabel(report.level)}）`,
      `检查覆盖率：${report.coverage}%`,
      ...report.findings.slice(0, 5).map((finding, index) => `${index + 1}. ${finding.message} 建议：${finding.recommendation}`),
    ].join("\n");
    await navigator.clipboard.writeText(summary);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="帧检首页">
          <span className="brand__mark" aria-hidden="true"><i /><i /></span>
          <span>帧检 <b>FRAMECHECK</b></span>
        </a>
        <nav aria-label="主导航">
          <a href="#analyzer">开始质检</a>
          <a href="#standard">检查标准</a>
          <span className="privacy-pill"><i /> 本地处理</span>
        </nav>
      </header>

      <section className="hero" id="top">
        <div className="hero__eyebrow"><span>POST-PRODUCTION QA</span><span>短视频交付质检</span></div>
        <h1>发出去之前，<br /><em>先把问题找出来。</em></h1>
        <p className="hero__copy">上传成片，自动抽检画面、节奏、音频和字幕。几分钟内得到一份带时间码的返修清单。</p>
        <div className="hero__proof">
          <span><b>05</b> 检查维度</span>
          <span><b>100</b> 分制评分</span>
          <span><b>0</b> 云端上传</span>
        </div>
      </section>

      <section className="analyzer-shell" id="analyzer" aria-labelledby="analyzer-title">
        <div className="analyzer-shell__header">
          <div>
            <span className="kicker">NEW REVIEW</span>
            <h2 id="analyzer-title">新建质检</h2>
          </div>
          <p>默认规则 <b>竖屏短视频 V1</b><br />建议文件小于 500 MB</p>
        </div>

        <div className="workspace">
          <div className="upload-column">
            <input
              ref={videoInputRef}
              className="sr-only"
              type="file"
              accept="video/*,.mov,.m4v"
              onChange={(event) => chooseVideo(event.target.files?.[0])}
            />
            <div
              className={`dropzone ${dragging ? "dropzone--dragging" : ""} ${videoFile ? "dropzone--has-file" : ""}`}
              role="button"
              tabIndex={0}
              aria-label="选择要质检的视频"
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") videoInputRef.current?.click();
              }}
              onClick={() => videoInputRef.current?.click()}
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                chooseVideo(event.dataTransfer.files[0]);
              }}
            >
              {previewUrl && videoFile ? (
                <div className="video-preview">
                  <video src={previewUrl} muted playsInline preload="metadata" />
                  <span className="video-preview__veil" />
                  <div className="video-preview__file">
                    <span className="file-badge">VIDEO</span>
                    <div><strong>{videoFile.name}</strong><small>{fileSize(videoFile.size)} · 点击更换</small></div>
                  </div>
                </div>
              ) : (
                <div className="dropzone__empty">
                  <span className="upload-glyph" aria-hidden="true">↗</span>
                  <h3>把成片拖到这里</h3>
                  <p>或点击选择 MP4 / MOV / WebM</p>
                  <small>视频仅在当前浏览器中解码，不会离开你的设备</small>
                </div>
              )}
            </div>

            <div className="caption-row">
              <div>
                <span className="caption-icon">CC</span>
                <div><strong>字幕文件 <i>可选</i></strong><small>加入 SRT / VTT 后可检查阅读速度与断句</small></div>
              </div>
              <input
                ref={captionInputRef}
                className="sr-only"
                type="file"
                accept=".srt,.vtt,text/vtt"
                onChange={(event) => setCaptionFile(event.target.files?.[0] ?? null)}
              />
              <button type="button" className="text-button" onClick={() => captionInputRef.current?.click()}>
                {captionFile ? captionFile.name : "+ 添加字幕"}
              </button>
            </div>
          </div>

          <aside className="checklist-panel">
            <div className="checklist-panel__title"><span>质检清单</span><span>权重</span></div>
            {sectionDescriptions.map(([number, title, detail], index) => (
              <div className="check-item" key={number}>
                <span className="check-item__number">{number}</span>
                <div><strong>{title}</strong><small>{detail}</small></div>
                <span className="check-item__weight">{[20, 25, 20, 20, 10][index]}%</span>
              </div>
            ))}
            <div className="checklist-panel__note"><span>+</span><p><b>5% 模型复核接口已预留</b><br />浏览器版不纳入本次得分</p></div>
          </aside>
        </div>

        <div className="action-row">
          <div className="progress-copy" aria-live="polite">
            <span>{analyzing ? `${progress.percent}%` : videoFile ? "READY" : "—"}</span>
            <div><b>{progress.label}</b><i>{analyzing ? "正在逐帧抽检，请保持页面打开" : "一段 60 秒视频通常需要约 1–3 分钟"}</i></div>
          </div>
          <button className="primary-button" type="button" disabled={!videoFile || analyzing} onClick={runAnalysis}>
            {analyzing ? "正在质检" : "开始质检"}<span>{analyzing ? "···" : "↗"}</span>
          </button>
        </div>
        {analyzing ? <div className="progress-track"><span style={{ width: `${progress.percent}%` }} /></div> : null}
        {error ? <p className="error-message" role="alert">{error}</p> : null}
      </section>

      {report ? (
        <section className="report" ref={resultRef} aria-labelledby="report-title">
          <div className="report__heading">
            <div><span className="kicker">REVIEW COMPLETE</span><h2 id="report-title">质检报告</h2></div>
            <div className="report__actions">
              <button type="button" onClick={copySummary}>{copied ? "已复制" : "复制摘要"}</button>
              <button type="button" className="button-dark" onClick={downloadReport}>导出 JSON ↗</button>
            </div>
          </div>

          <div className="score-grid">
            <article className={`score-card score-card--${report.level}`}>
              <div className="score-card__top"><span>综合得分</span><span>{report.coverage}% 覆盖</span></div>
              <div className="score-number"><strong>{report.score}</strong><span>/100</span></div>
              <div className="score-verdict"><i /> {levelLabel(report.level)}</div>
              <p>{report.findings.length ? `共发现 ${report.findings.length} 个需要确认的问题，建议按扣分优先级返修。` : "本次自动检查未发现明确问题，可以进入人工终审。"}</p>
            </article>

            <article className="spec-card">
              <div className="spec-card__title"><span>成片信息</span><small>{report.fileName}</small></div>
              <dl>
                <div><dt>画幅</dt><dd>{report.metadata.aspectRatio}</dd></div>
                <div><dt>分辨率</dt><dd>{report.metadata.width}×{report.metadata.height}</dd></div>
                <div><dt>片长</dt><dd>{formatTime(report.metadata.durationSeconds)}</dd></div>
                <div><dt>文件</dt><dd>{fileSize(report.metadata.fileSizeBytes)}</dd></div>
              </dl>
              <div className="metric-strip">
                <span><b>{report.metrics.sceneCount}</b> 画面段</span>
                <span><b>{report.metrics.cutsPerMinute}</b> 变化/分钟</span>
                <span><b>{report.metrics.sampledFrames}</b> 抽检帧</span>
              </div>
            </article>

            <article className="sections-card">
              <div className="spec-card__title"><span>分项得分</span><small>按有效权重归一化</small></div>
              {report.sections.map((section) => <SectionBar section={section} key={section.key} />)}
            </article>
          </div>

          <div className="findings-section">
            <div className="findings-section__head">
              <div><span className="kicker">ACTION LIST</span><h3>返修清单</h3></div>
              <p>按风险与扣分排序 · 时间码来自均匀抽帧近似定位</p>
            </div>
            <div className="finding-list">
              {report.findings.length ? report.findings
                .toSorted((a, b) => b.deduction - a.deduction)
                .map((finding, index) => <FindingCard key={finding.id} finding={finding} index={index} />) : (
                  <div className="empty-findings"><span>✓</span><h4>自动检查全部通过</h4><p>仍建议在发布前进行一次完整人工复看。</p></div>
                )}
            </div>
          </div>

          <div className="report-note">
            <strong>关于本次结果</strong>
            <ul>{report.notes.map((note) => <li key={note}>{note}</li>)}</ul>
          </div>
        </section>
      ) : null}

      <section className="standard-section" id="standard">
        <div className="standard-section__head">
          <span className="kicker">WHY FRAMECHECK</span>
          <h2>不是“感觉还行”，<br />是每一项都有依据。</h2>
        </div>
        <div className="principles">
          <article><span>01</span><h3>问题带时间码</h3><p>直接定位黑屏、静帧与长静音，不用从头拖进度条。</p></article>
          <article><span>02</span><h3>覆盖率单独展示</h3><p>没检查的项目不伪装成通过，分数始终标明有效权重。</p></article>
          <article><span>03</span><h3>规则可以复核</h3><p>沿用本地 Video Scorecard 的短竖屏阈值，结果可导出留档。</p></article>
        </div>
      </section>

      <footer>
        <a className="brand brand--footer" href="#top"><span className="brand__mark"><i /><i /></span><span>帧检 <b>FRAMECHECK</b></span></a>
        <p>Browser-local video QA · 你的素材不会上传</p>
        <a href="#analyzer">开始新质检 ↑</a>
      </footer>
    </main>
  );
}
