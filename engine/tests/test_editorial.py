import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from postscore.editorial import AXES, CHECKS, blank_notes, evaluate, read_metrics


def decision(tmp_path, *, goal="购买", bottleneck="前3秒"):
    video = tmp_path / "media"
    video.write_bytes(b"unique cut")
    d = blank_notes(video)
    d.update(audience="首次观看者", goal=goal, entry="信息流", bottleneck=bottleneck,
             checks={key: {"status":"已核","evidence":"可核对的素材依据"} for key in CHECKS})
    return video, d


def read(tmp_path, video, d):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return evaluate(path, video)


def finding(topic, stage, level):
    return dict(topic=topic, stage=stage, level=level, evidence="1.0 秒，说明书核对", action="调整声画",
                acceptance="逐帧核对功能表述", confidence="编辑判断", cost="现有素材剪辑")


@pytest.mark.parametrize("goal,stage,extra,expected", [
    ("成交","前3秒",("错误功能","事实依据","发布前须改"),"错误功能"),
    ("成交","中段兑现",("证据太晚","中段兑现","影响目标"),"证据太晚"),
    ("涨粉","结尾行动",("追看收益不清","结尾行动","影响目标"),"追看收益不清"),
    ("转发","收藏分享与品牌",("缺转发理由","收藏分享与品牌","影响目标"),"缺转发理由"),
    ("收藏","入口承诺",("列表看不懂主题","入口承诺","影响目标"),"列表看不懂主题"),
    ("成交","中段兑现",("商品入口失效","行动承接","发布前须改"),"商品入口失效"),
    ("品牌回想","画面与包装",("品牌名被挡","画面与包装","影响目标"),"品牌名被挡"),
])
def test_goal_driven_priority(tmp_path,goal,stage,extra,expected):
    video,d=decision(tmp_path,goal=goal,bottleneck=stage)
    d["findings"]=[finding("色调精修","画面与包装","精修"),finding(*extra)]
    assert read(tmp_path, video, d)["priorities"][0]["topic"] == expected


@pytest.mark.parametrize("role,integrity,delivery,expected",[
    ("候选","已核",10,"传播待核"),("首帧","已核",10,"传播待核"),
    ("发布封面","须修",10,"发布前须改"),("发布封面","已核",0,"发布前须改"),
    ("发布封面","待核",10,"传播待核"),("发布封面","已核",10,"已完成传播审片"),
])
def test_cover_gate(tmp_path,role,integrity,delivery,expected):
    video,d=decision(tmp_path)
    cv2.imencode(".png",np.ones((12,12,3),dtype=np.uint8))[1].tofile(str(tmp_path/"cover.png"))
    marks={key:dict(score=10,evidence="在缩略预览核对") for axis in AXES.values() for key in axis}
    marks["正文兑现"]["score"]=delivery
    d.update(cover_required=True,covers=[dict(name="demo",role=role,image="cover.png",marks=marks,
        integrity=dict(status=integrity,evidence="对照正文"),correction="缩小承诺范围")])
    assert read(tmp_path,video,d)["status"]==expected


def test_incomplete_provenance_and_counts(tmp_path):
    video,d=decision(tmp_path)
    d["checks"]["行动承接"]={"status":"待核","evidence":"缺后台"}
    assert read(tmp_path,video,d)["status"]=="传播待核"
    d["checks"]["行动承接"]["status"]="须修"
    with pytest.raises(ValueError, match="修改项"):
        read(tmp_path,video,d)
    video.write_bytes(b"new cut")
    with pytest.raises(ValueError, match="指纹"):
        read(tmp_path,video,d)
    path=tmp_path/"metrics.csv"
    fields="source_sha256 variant traffic window metric numerator denominator kind".split()
    def rows(n,k):
        with path.open("w",newline="") as f:
            w=csv.writer(f);w.writerow(fields);w.writerow(["abc","A","搜索","7日","点击",n,100,k])
    rows(105,"proportion")
    with pytest.raises(ValueError):
        read_metrics(path,"abc")
    rows(105,"per_view")
    assert read_metrics(path,"abc")[0]["rate"]==1.05


def test_content_floor_and_calibration(tmp_path):
    from postscore.editorial import CREATIVE_WEIGHTS, calibration
    video,d=decision(tmp_path)
    marks={k:dict(score=v,evidence="已看当前视频") for k,v in CREATIVE_WEIGHTS.items()}
    d["content"]=dict(version="creative-100-v1",marks=marks)
    assert read(tmp_path,video,d)["content"]["total"]=="100"
    first=next(iter(marks))
    for score,expected in [("1.99","低于目标"),("2","达到目标")]:
        marks[first]["score"]=score
        assert read(tmp_path,video,d)["content"]["status"]==expected
    d["findings"]=[finding("真实承诺","事实依据","发布前须改")]
    review=read(tmp_path,video,d)
    (tmp_path/"report.json").write_text(json.dumps({"editorial":review}), encoding="utf-8")
    manifest=tmp_path/"cases.csv"
    manifest.write_text("case,type,report,first_a,first_b,score_a,score_b\n1,品牌,report.json,真实承诺,真实承诺,85,84\n2,品牌,report.json,节奏,事实,75,80",encoding="utf-8")
    a,b=calibration(manifest)
    assert a["consensus_in_top3"] and a["editor_gap"]=="1"
    assert b["consensus_in_top3"] is None
