export type Severity = "critical" | "high" | "medium" | "low" | "info";

export type Finding = {
  id: string;
  section: SectionKey;
  check: string;
  severity: Severity;
  message: string;
  deduction: number;
  start?: number;
  end?: number;
  recommendation: string;
};

export type SectionKey =
  | "technical_specs"
  | "visual_quality"
  | "editing_rhythm"
  | "audio_quality"
  | "captions_packaging"
  | "model_review";

export type SectionScore = {
  key: SectionKey;
  label: string;
  weight: number;
  status: "pass" | "warn" | "fail" | "skipped";
  score: number | null;
  deductions: number;
  findingCount: number;
};

export type VideoReport = {
  version: "short_vertical_v1-web";
  fileName: string;
  generatedAt: string;
  score: number;
  coverage: number;
  level: "publish_ready" | "minor_fixes" | "needs_revision" | "blocked" | "partial_review";
  metadata: {
    durationSeconds: number;
    width: number;
    height: number;
    aspectRatio: string;
    estimatedFps: null;
    fileSizeBytes: number;
    fileType: string;
    hasAudio: boolean | null;
  };
  sections: SectionScore[];
  findings: Finding[];
  metrics: {
    sampledFrames: number;
    blackSegments: number;
    freezeSegments: number;
    sceneCount: number;
    cutsPerMinute: number;
    averageShotSeconds: number;
    meanVolumeDb: number | null;
    peakVolumeDb: number | null;
    silenceSeconds: number | null;
    captionCues: number | null;
  };
  notes: string[];
};

type Progress = (percent: number, label: string) => void;

type Sample = { time: number; brightness: number; difference: number };
type Segment = { start: number; end: number; duration: number };

const WEIGHTS: Record<SectionKey, number> = {
  technical_specs: 20,
  visual_quality: 25,
  editing_rhythm: 20,
  audio_quality: 20,
  captions_packaging: 10,
  model_review: 5,
};

const LABELS: Record<SectionKey, string> = {
  technical_specs: "技术规格",
  visual_quality: "画面质量",
  editing_rhythm: "剪辑节奏",
  audio_quality: "音频质量",
  captions_packaging: "字幕包装",
  model_review: "模型复核",
};

const DEDUCTIONS: Record<Severity, number> = {
  critical: 12,
  high: 8,
  medium: 5,
  low: 2,
  info: 0,
};

const nextFrame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

function waitFor(target: EventTarget, event: string, errorTarget?: EventTarget) {
  return new Promise<void>((resolve, reject) => {
    const done = () => {
      cleanup();
      resolve();
    };
    const failed = () => {
      cleanup();
      reject(new Error("无法读取视频，请尝试 MP4 / WebM / MOV 格式。"));
    };
    const cleanup = () => {
      target.removeEventListener(event, done);
      (errorTarget ?? target).removeEventListener("error", failed);
    };
    target.addEventListener(event, done, { once: true });
    (errorTarget ?? target).addEventListener("error", failed, { once: true });
  });
}

async function seek(video: HTMLVideoElement, time: number) {
  if (Math.abs(video.currentTime - time) < 0.015 && video.readyState >= 2) return;
  const ready = waitFor(video, "seeked");
  video.currentTime = Math.max(0, Math.min(time, video.duration - 0.03));
  await ready;
}

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

function aspectLabel(width: number, height: number) {
  const divisor = gcd(width, height);
  const simpleW = Math.round(width / divisor);
  const simpleH = Math.round(height / divisor);
  if (simpleW <= 24 && simpleH <= 24) return `${simpleW}:${simpleH}`;
  return `${(width / height).toFixed(2)}:1`;
}

function addFinding(
  findings: Finding[],
  input: Omit<Finding, "id" | "deduction"> & { deduction?: number },
) {
  findings.push({
    ...input,
    id: `${input.section}-${input.check}-${findings.length + 1}`,
    deduction: input.deduction ?? DEDUCTIONS[input.severity],
  });
}

function makeSegments(samples: Sample[], predicate: (sample: Sample) => boolean, interval: number) {
  const segments: Segment[] = [];
  let start: number | null = null;
  for (let index = 0; index < samples.length; index += 1) {
    const sample = samples[index];
    if (predicate(sample) && start === null) start = sample.time;
    const isLast = index === samples.length - 1;
    if (start !== null && (!predicate(sample) || isLast)) {
      const end = Math.min(sample.time + (isLast && predicate(sample) ? interval : 0), samples.at(-1)!.time + interval);
      segments.push({ start, end, duration: Math.max(0, end - start) });
      start = null;
    }
  }
  return segments;
}

async function sampleFrames(video: HTMLVideoElement, onProgress: Progress) {
  const duration = video.duration;
  const interval = Math.max(0.5, duration / 72);
  const count = Math.max(2, Math.min(73, Math.ceil(duration / interval) + 1));
  const canvas = document.createElement("canvas");
  canvas.width = 90;
  canvas.height = Math.max(90, Math.round((90 * video.videoHeight) / video.videoWidth));
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("当前浏览器无法创建画面分析器。");

  const samples: Sample[] = [];
  let previous: Uint8ClampedArray | null = null;

  for (let index = 0; index < count; index += 1) {
    const time = Math.min(duration - 0.04, index * interval);
    await seek(video, time);
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let brightnessTotal = 0;
    let differenceTotal = 0;
    const pixelCount = pixels.length / 4;
    for (let offset = 0; offset < pixels.length; offset += 4) {
      brightnessTotal += pixels[offset] * 0.2126 + pixels[offset + 1] * 0.7152 + pixels[offset + 2] * 0.0722;
      if (previous) {
        differenceTotal +=
          (Math.abs(pixels[offset] - previous[offset]) +
            Math.abs(pixels[offset + 1] - previous[offset + 1]) +
            Math.abs(pixels[offset + 2] - previous[offset + 2])) /
          3;
      }
    }
    samples.push({
      time,
      brightness: brightnessTotal / pixelCount,
      difference: previous ? differenceTotal / pixelCount : 255,
    });
    previous = new Uint8ClampedArray(pixels);
    onProgress(14 + Math.round(((index + 1) / count) * 48), `抽检画面 ${index + 1}/${count}`);
    if (index % 4 === 0) await nextFrame();
  }

  return { samples, interval };
}

async function analyzeAudio(file: File) {
  const AudioContextClass = window.AudioContext;
  if (!AudioContextClass) return null;
  const context = new AudioContextClass();
  try {
    const buffer = await file.arrayBuffer();
    const audio = await context.decodeAudioData(buffer.slice(0));
    const channelCount = audio.numberOfChannels;
    const channelLength = audio.length;
    let sumSquares = 0;
    let peak = 0;
    for (let channelIndex = 0; channelIndex < channelCount; channelIndex += 1) {
      const data = audio.getChannelData(channelIndex);
      for (let index = 0; index < channelLength; index += 1) {
        const value = data[index];
        sumSquares += value * value;
        const absolute = Math.abs(value);
        if (absolute > peak) peak = absolute;
      }
    }

    const chunkDuration = 0.25;
    const chunkSize = Math.max(1, Math.floor(audio.sampleRate * chunkDuration));
    const primary = audio.getChannelData(0);
    const silentChunks: { start: number; end: number }[] = [];
    for (let start = 0; start < channelLength; start += chunkSize) {
      const end = Math.min(channelLength, start + chunkSize);
      let localSquares = 0;
      for (let index = start; index < end; index += 1) localSquares += primary[index] * primary[index];
      const rms = Math.sqrt(localSquares / Math.max(1, end - start));
      const db = 20 * Math.log10(Math.max(rms, 1e-7));
      if (db < -35) silentChunks.push({ start: start / audio.sampleRate, end: end / audio.sampleRate });
    }

    const silenceSegments: Segment[] = [];
    for (const chunk of silentChunks) {
      const last = silenceSegments.at(-1);
      if (last && chunk.start - last.end < chunkDuration * 1.25) {
        last.end = chunk.end;
        last.duration = last.end - last.start;
      } else {
        silenceSegments.push({ start: chunk.start, end: chunk.end, duration: chunk.end - chunk.start });
      }
    }

    const rms = Math.sqrt(sumSquares / Math.max(1, channelCount * channelLength));
    return {
      meanVolumeDb: 20 * Math.log10(Math.max(rms, 1e-7)),
      peakVolumeDb: 20 * Math.log10(Math.max(peak, 1e-7)),
      silenceSegments: silenceSegments.filter((segment) => segment.duration >= 1),
    };
  } catch {
    return null;
  } finally {
    await context.close();
  }
}

type CaptionCue = { start: number; end: number; text: string };

function parseTimestamp(value: string) {
  const parts = value.trim().replace(",", ".").split(":").map(Number);
  if (parts.some(Number.isNaN)) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return null;
}

async function parseCaptions(file?: File | null): Promise<CaptionCue[] | null> {
  if (!file) return null;
  const text = await file.text();
  const blocks = text.replace(/\r/g, "").split(/\n{2,}/);
  const cues: CaptionCue[] = [];
  for (const block of blocks) {
    const lines = block.split("\n").filter(Boolean);
    const timingIndex = lines.findIndex((line) => line.includes("-->"));
    if (timingIndex < 0) continue;
    const [startText, endText] = lines[timingIndex].split("-->");
    const start = parseTimestamp(startText);
    const end = parseTimestamp(endText.split(/\s+/)[0]);
    if (start === null || end === null || end <= start) continue;
    cues.push({ start, end, text: lines.slice(timingIndex + 1).join(" ").replace(/<[^>]+>/g, "") });
  }
  return cues;
}

function buildSections(findings: Finding[], evaluated: Set<SectionKey>) {
  return (Object.keys(WEIGHTS) as SectionKey[]).map((key): SectionScore => {
    const weight = WEIGHTS[key];
    if (!evaluated.has(key)) {
      return { key, label: LABELS[key], weight, status: "skipped", score: null, deductions: 0, findingCount: 0 };
    }
    const sectionFindings = findings.filter((finding) => finding.section === key);
    const deductions = Math.min(weight, sectionFindings.reduce((total, finding) => total + finding.deduction, 0));
    const score = Math.max(0, weight - deductions);
    return {
      key,
      label: LABELS[key],
      weight,
      status: deductions === 0 ? "pass" : score === 0 ? "fail" : "warn",
      score,
      deductions,
      findingCount: sectionFindings.length,
    };
  });
}

export async function analyzeVideo(file: File, captionFile: File | null, onProgress: Progress): Promise<VideoReport> {
  if (!file.type.startsWith("video/")) throw new Error("请选择视频文件。支持 MP4、WebM、MOV 等浏览器可播放格式。");
  if (file.size > 1.5 * 1024 * 1024 * 1024) throw new Error("文件超过 1.5 GB。建议先压缩或截取后再分析。");

  onProgress(3, "读取视频信息");
  const objectUrl = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.preload = "metadata";
  video.muted = true;
  video.playsInline = true;
  video.src = objectUrl;
  const metadataReady = waitFor(video, "loadedmetadata");
  video.load();
  await metadataReady;

  try {
    if (!Number.isFinite(video.duration) || video.duration <= 0) throw new Error("没有读取到有效的视频时长。");
    onProgress(10, "建立画面时间轴");
    const [{ samples, interval }, captions] = await Promise.all([
      sampleFrames(video, onProgress),
      parseCaptions(captionFile),
    ]);

    onProgress(68, "分析音量与静音");
    const audio = await analyzeAudio(file);
    onProgress(84, "核对字幕与平台规格");

    const findings: Finding[] = [];
    const evaluated = new Set<SectionKey>(["technical_specs", "visual_quality", "editing_rhythm"]);
    const duration = video.duration;
    const width = video.videoWidth;
    const height = video.videoHeight;
    const ratio = width / height;

    if (duration < 5 || duration > 180) {
      addFinding(findings, {
        section: "technical_specs",
        check: "duration",
        severity: "medium",
        message: `片长 ${duration.toFixed(1)} 秒，不在短视频建议的 5–180 秒范围内。`,
        recommendation: "确认发布平台限制，或剪出更聚焦的短版。",
      });
    }
    if (width < 720 || height < 1280) {
      addFinding(findings, {
        section: "technical_specs",
        check: "resolution",
        severity: "high",
        message: `分辨率 ${width}×${height}，低于竖屏交付基线 720×1280。`,
        recommendation: "使用原始素材重新导出，至少保持 720×1280。",
      });
    }
    if (Math.abs(ratio - 9 / 16) > 0.04) {
      addFinding(findings, {
        section: "technical_specs",
        check: "aspect_ratio",
        severity: "medium",
        message: `画幅为 ${aspectLabel(width, height)}，不是标准 9:16 竖屏。`,
        recommendation: "按 9:16 重新构图，检查人物与字幕安全区。",
      });
    }

    const blackSegments = makeSegments(samples, (sample) => sample.brightness < 14, interval).filter(
      (segment) => segment.duration >= 0.5,
    );
    for (const segment of blackSegments.slice(0, 4)) {
      addFinding(findings, {
        section: "visual_quality",
        check: "black_segments",
        severity: "medium",
        message: `检测到 ${segment.duration.toFixed(1)} 秒连续暗场。`,
        start: segment.start,
        end: segment.end,
        recommendation: "检查是否为意外黑帧；若是转场，建议缩短停留。",
      });
    }

    const freezeSegments = makeSegments(
      samples,
      (sample) => sample.difference < 2.3 && sample.brightness >= 14,
      interval,
    ).filter((segment) => segment.duration >= 1);
    for (const segment of freezeSegments.slice(0, 4)) {
      addFinding(findings, {
        section: "visual_quality",
        check: "freeze_segments",
        severity: "medium",
        message: `画面约 ${segment.duration.toFixed(1)} 秒几乎没有变化。`,
        start: segment.start,
        end: segment.end,
        recommendation: "确认不是误停帧；静态讲解段可增加景别、动效或 B-roll。",
      });
    }

    const sceneTimes = samples.filter((sample, index) => index > 0 && sample.difference > 19).map((sample) => sample.time);
    const sceneCount = Math.max(1, sceneTimes.length + 1);
    const cutsPerMinute = (sceneTimes.length / duration) * 60;
    const averageShotSeconds = duration / sceneCount;
    if (cutsPerMinute < 4) {
      addFinding(findings, {
        section: "editing_rhythm",
        check: "scene_change_density",
        severity: "medium",
        message: `每分钟约 ${cutsPerMinute.toFixed(1)} 次画面变化，节奏偏慢。`,
        recommendation: "优先强化前 3 秒，并在信息节点加入景别或素材变化。",
      });
    } else if (cutsPerMinute > 90) {
      addFinding(findings, {
        section: "editing_rhythm",
        check: "scene_change_density",
        severity: "medium",
        message: `每分钟约 ${cutsPerMinute.toFixed(1)} 次画面变化，可能过密。`,
        recommendation: "给关键观点留出阅读时间，减少无信息增量的跳切。",
      });
    }
    if (averageShotSeconds > 12) {
      addFinding(findings, {
        section: "editing_rhythm",
        check: "average_shot_length",
        severity: "medium",
        message: `平均镜头约 ${averageShotSeconds.toFixed(1)} 秒，超过 12 秒参考线。`,
        recommendation: "在长镜头中加入构图、字幕层级或素材切换。",
      });
    }

    if (audio) {
      evaluated.add("audio_quality");
      if (audio.meanVolumeDb < -28 || audio.meanVolumeDb > -12) {
        addFinding(findings, {
          section: "audio_quality",
          check: "mean_volume",
          severity: "medium",
          message: `平均音量约 ${audio.meanVolumeDb.toFixed(1)} dB，超出 -28 至 -12 dB 参考区间。`,
          recommendation: audio.meanVolumeDb < -28 ? "提升对白响度，并检查背景音乐是否压住人声。" : "降低整体增益，保留动态余量。",
        });
      }
      if (audio.peakVolumeDb > -0.5) {
        addFinding(findings, {
          section: "audio_quality",
          check: "peak_volume",
          severity: "low",
          message: `峰值约 ${audio.peakVolumeDb.toFixed(1)} dB，存在削波风险。`,
          recommendation: "限制峰值到 -1 dB 左右，并复听爆破音与音乐重拍。",
        });
      }
      for (const segment of audio.silenceSegments.filter((item) => item.duration >= 3).slice(0, 4)) {
        addFinding(findings, {
          section: "audio_quality",
          check: "long_silence",
          severity: "medium",
          message: `检测到 ${segment.duration.toFixed(1)} 秒长静音。`,
          start: segment.start,
          end: segment.end,
          recommendation: "确认是否为有意留白；否则补齐对白、环境声或音乐。",
        });
      }
    }

    if (captions) {
      evaluated.add("captions_packaging");
      let fastCount = 0;
      let longLineCount = 0;
      let durationCount = 0;
      for (const cue of captions) {
        const cueDuration = cue.end - cue.start;
        const visibleText = cue.text.replace(/\s/g, "");
        if (visibleText.length / cueDuration > 18) fastCount += 1;
        if (cue.text.split(/\n|\\N/).some((line) => line.length > 28)) longLineCount += 1;
        if (cueDuration < 0.7 || cueDuration > 6) durationCount += 1;
      }
      if (fastCount > 0) {
        addFinding(findings, {
          section: "captions_packaging",
          check: "reading_speed",
          severity: "medium",
          message: `${fastCount} 条字幕阅读速度超过每秒 18 字。`,
          recommendation: "精简文案或延长字幕停留，优先保留关键词。",
        });
      }
      if (longLineCount > 0) {
        addFinding(findings, {
          section: "captions_packaging",
          check: "line_length",
          severity: "low",
          message: `${longLineCount} 条字幕单行超过 28 字。`,
          recommendation: "拆分长句，并保持移动端一眼可读。",
        });
      }
      if (durationCount > 0) {
        addFinding(findings, {
          section: "captions_packaging",
          check: "cue_duration",
          severity: "low",
          message: `${durationCount} 条字幕的停留时间过短或过长。`,
          recommendation: "将单条字幕控制在约 0.7–6 秒。",
        });
      }
    }

    const sections = buildSections(findings, evaluated);
    const scoredWeight = sections.reduce((total, section) => total + (section.score === null ? 0 : section.weight), 0);
    const earned = sections.reduce((total, section) => total + (section.score ?? 0), 0);
    const coverage = (scoredWeight / 100) * 100;
    const score = scoredWeight ? (earned / scoredWeight) * 100 : 0;
    const roundedScore = Math.round(score * 10) / 10;
    const level =
      coverage < 60
        ? "partial_review"
        : roundedScore >= 90
          ? "publish_ready"
          : roundedScore >= 75
            ? "minor_fixes"
            : roundedScore >= 60
              ? "needs_revision"
              : "blocked";

    onProgress(100, "报告已生成");
    return {
      version: "short_vertical_v1-web",
      fileName: file.name,
      generatedAt: new Date().toISOString(),
      score: roundedScore,
      coverage: Math.round(coverage * 10) / 10,
      level,
      metadata: {
        durationSeconds: Math.round(duration * 10) / 10,
        width,
        height,
        aspectRatio: aspectLabel(width, height),
        estimatedFps: null,
        fileSizeBytes: file.size,
        fileType: file.type,
        hasAudio: audio ? true : null,
      },
      sections,
      findings,
      metrics: {
        sampledFrames: samples.length,
        blackSegments: blackSegments.length,
        freezeSegments: freezeSegments.length,
        sceneCount,
        cutsPerMinute: Math.round(cutsPerMinute * 10) / 10,
        averageShotSeconds: Math.round(averageShotSeconds * 10) / 10,
        meanVolumeDb: audio ? Math.round(audio.meanVolumeDb * 10) / 10 : null,
        peakVolumeDb: audio ? Math.round(audio.peakVolumeDb * 10) / 10 : null,
        silenceSeconds: audio
          ? Math.round(audio.silenceSegments.reduce((total, segment) => total + segment.duration, 0) * 10) / 10
          : null,
        captionCues: captions?.length ?? null,
      },
      notes: [
        "视频在浏览器本地完成抽帧与音频解码，不会上传到服务器。",
        "浏览器无法稳定读取容器帧率，帧率检查保留为空；最终交付前建议用桌面版 FFprobe 复核。",
        captions ? `已检查 ${captions.length} 条字幕。` : "未提供 SRT/VTT，字幕包装与模型复核不计入本次得分。",
      ],
    };
  } finally {
    URL.revokeObjectURL(objectUrl);
    video.removeAttribute("src");
    video.load();
  }
}

export function formatTime(seconds?: number) {
  if (seconds === undefined) return "—";
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${remaining.toFixed(1).padStart(4, "0")}`;
}

export function levelLabel(level: VideoReport["level"]) {
  return {
    publish_ready: "可以发布",
    minor_fixes: "小修后发布",
    needs_revision: "建议返修",
    blocked: "暂缓发布",
    partial_review: "检查不完整",
  }[level];
}
