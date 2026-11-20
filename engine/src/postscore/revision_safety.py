"""Frame-timed collision checks for annotated content and a specific platform UI."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import cv2
import numpy as np
from pydantic import Field, model_validator

from .editorial import Record, Text, digest
from .image_io import read_image

Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Box(Record):
    x: Unit
    y: Unit
    w: Unit
    h: Unit

    @model_validator(mode="after")
    def bounds(self):
        if min(self.w, self.h) <= 0 or self.x + self.w > 1.000001 or self.y + self.h > 1.000001:
            raise ValueError("边框必须完整位于画布内")
        return self

    def vector(self):
        return np.array([self.x, self.y, self.w, self.h])


class Key(Box):
    time: Seconds


class Track(Record):
    name: Text
    keys: Annotated[list[Key], Field(min_length=1)]
    end: Seconds
    interpolation: Literal["linear", "hold"] = "linear"

    @model_validator(mode="after")
    def times(self):
        times = [k.time for k in self.keys]
        if times != sorted(set(times)) or self.end <= times[-1]:
            raise ValueError("元素关键帧必须递增，结束须晚于最后关键帧")
        return self


class Placement(Record):
    platform: Text
    placement: Text
    ui_state: Text
    source: Literal["版位实证", "示意"]
    reference: Text
    reference_date: date
    coverage_checked: bool
    zones: Annotated[dict[Text, Box], Field(min_length=1)]
    tracks: Annotated[list[Track], Field(min_length=1)]


def collision(first, second):
    x, y, w, h = first
    a, b, c, d = second
    return min(x + w, a + c) > max(x, a) and min(y + h, b + d) > max(y, b)


def correction(box, zones):
    x, y, width, height = box
    xs = {x, 0.0, 1.0 - width}
    ys = {y, 0.0, 1.0 - height}
    for zone in zones.values():
        xs.update((zone.x - width - 0.005, zone.x + zone.w + 0.005))
        ys.update((zone.y - height - 0.005, zone.y + zone.h + 0.005))
    candidates = [
        (px, py)
        for px in xs
        for py in ys
        if 0 <= px <= 1 - width
        and 0 <= py <= 1 - height
        and not any(collision((px, py, width, height), z.vector()) for z in zones.values())
    ]
    if not candidates:
        return "按该帧可用空间重排或缩短文字，保留主体边界后重验"
    px, py = min(candidates, key=lambda xy: (xy[0] - x) ** 2 + (xy[1] - y) ** 2)
    return f"在该帧试移到左上角 ({px:.3f}, {py:.3f})，单位为画幅比例；回看完整动画与产品边界"


def scan_track(track, zones, timestamps):
    times = np.array([k.time for k in track.keys])
    values = np.array([k.vector() for k in track.keys])
    active = timestamps[(timestamps >= times[0]) & (timestamps < track.end)]
    if track.interpolation == "linear":
        boxes = np.stack([np.interp(active, times, column) for column in values.T], axis=1)
    else:
        boxes = values[np.searchsorted(times, active, side="right") - 1]
    hits = []
    for name, zone in zones.items():
        for moment, box in zip(active, boxes):
            if collision(box, zone.vector()):
                x, y, w, h = box
                ox, oy = max(x, zone.x), max(y, zone.y)
                overlap = [ox, oy, min(x + w, zone.x + zone.w) - ox, min(y + h, zone.y + zone.h) - oy]
                hits.append(
                    dict(
                        element=track.name,
                        zone=name,
                        time=float(moment),
                        box=box.tolist(),
                        overlap=overlap,
                        fix=correction(box, zones),
                    )
                )
                break
    return hits


def frame_at(cap, time, width=440):
    cap.set(cv2.CAP_PROP_POS_MSEC, time * 1000)
    ok, image = cap.read()
    if not ok:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) - 1))
        ok, image = cap.read()
        if not ok:
            raise ValueError(f"无法读取 {time:g} 秒证据帧")
    h, w = image.shape[:2]
    return cv2.resize(image, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)


def save_image(path, image):
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("无法编码证据帧")
    data.tofile(str(path))


def draw_box(frame, box, color):
    h, w = frame.shape[:2]
    x, y, bw, bh = box
    cv2.rectangle(
        frame, (round(x * w), round(y * h)), (round((x + bw) * w) - 1, round((y + bh) * h) - 1), color, 2
    )


def placement_review(spec, directory, cap, timestamps, duration, out, index, required=None):
    reference = (directory / spec.reference).resolve()
    ref = read_image(reference, cv2, np) if reference.is_file() else None
    if ref is None:
        raise ValueError("UI 校样需要当前视频显示画布对应的版位参考图")
    viewport = frame_at(cap, 0)
    h, w = viewport.shape[:2]
    rh, rw = ref.shape[:2]
    if abs(rw / rh - w / h) > 0.015:
        raise ValueError("请把版位截图裁到实际视频显示画布，并对齐画幅")
    ref_layer = cv2.resize(ref, (w, h))
    if len({track.name for track in spec.tracks}) != len(spec.tracks):
        raise ValueError("同一版位每条元素轨迹需有唯一名称")
    hits = []
    previews = []
    for i, track in enumerate(spec.tracks):
        if track.end > duration + 0.001 or not np.any(
            (timestamps >= track.keys[0].time) & (timestamps < track.end)
        ):
            raise ValueError("元素在该成片中没有对应帧")
        found = scan_track(track, spec.zones, timestamps)
        hits.extend(found)
        for j, hit in enumerate(found or [None]):
            t = hit["time"] if hit else track.keys[0].time
            frame = frame_at(cap, t)
            clean = f"clean-{index}-{i}-{j}.jpg"
            save_image(out / clean, frame)
            for zone in spec.zones.values():
                x, y, bw, bh = zone.vector()
                x0, x1 = round(x * w), round((x + bw) * w)
                y0, y1 = round(y * h), round((y + bh) * h)
                frame[y0:y1, x0:x1] = ref_layer[y0:y1, x0:x1]
                draw_box(frame, zone.vector(), (0, 65, 235))
            draw_box(frame, hit["box"] if hit else track.keys[0].vector(), (30, 225, 255))
            name = f"ui-{index}-{i}-{j}.jpg"
            save_image(out / name, frame)
            previews.append(dict(image=name, clean=clean, element=track.name, time=t))
    ref_name = f"ui-reference-{index}.jpg"
    save_image(out / ref_name, ref)
    coverage = spec.coverage_checked
    if required is not None:
        coverage = coverage and bool(required)
        for name,spans in required.items():
            tracks = [t for t in spec.tracks if t.name == name]
            for span in spans:
                active = timestamps[(timestamps >= span.start) & (timestamps < span.end)]
                observed = np.zeros(len(active), dtype=bool)
                for t in tracks:
                    observed |= (active >= t.keys[0].time) & (active < t.end)
                coverage = coverage and bool(len(active)) and bool(np.all(observed))
    verified = spec.source == "版位实证" and coverage
    status = (
        ("须修" if hits else "通过")
        if verified
        else ("须修" if hits and spec.source == "版位实证" else "待核")
    )
    return dict(
        platform=spec.platform,
        placement=spec.placement,
        ui_state=spec.ui_state,
        source=spec.source,
        reference_date=spec.reference_date.isoformat(),
        reference_sha256=digest(reference),
        reference_image=ref_name,
        coverage_checked=coverage,
        status=status,
        hits=hits,
        previews=previews,
    )
