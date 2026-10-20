#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import sys
import time

import numpy as np
import cv2

from rknn_style import MODEL_DIR, STYLES, RknnStyle, find_model

try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst, GLib
except Exception as e:                                    # pragma: no cover
    print("无法导入 GStreamer Python 绑定 (python3-gi / gir1.2-gstreamer-1.0): %s" % e)
    sys.exit(1)


def build_capture(camera):
    desc = (
        "v4l2src device=%s io-mode=4 ! "
        "video/x-raw,format=NV12,width=%d,height=%d ! "
        "videoconvert ! video/x-raw,format=RGB ! "
        "appsink name=sink emit-signals=true max-buffers=2 drop=true sync=false"
        % (camera, CAM_W, CAM_H)
    )
    print("[gst] 采集: %s" % desc)
    return Gst.parse_launch(desc)


def build_display(w, h, fullscreen=False):
    desc = (
        "appsrc name=src is-live=true format=time do-timestamp=true "
        "caps=video/x-raw,format=RGBA,width=%d,height=%d,framerate=%d/1 ! "
        "queue max-size-buffers=2 leaky=downstream ! "
        "waylandsink sync=false fullscreen=%s"
        % (w, h, FPS, str(fullscreen).lower())
    )
    print("[gst] 显示: %s" % desc)
    return Gst.parse_launch(desc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--model", default="udnie", choices=STYLES,
                    help="风格: %s" % "/".join(STYLES))
    ap.add_argument("--precision", choices=("int8", "fp16"), default="int8",
                    help="推理精度, 默认 int8")
    fullscreen = ap.add_mutually_exclusive_group()
    fullscreen.add_argument("--fullscreen", dest="fullscreen", action="store_true",
                            help="全屏显示")
    fullscreen.add_argument("--windowed", dest="fullscreen", action="store_false",
                            help="源尺寸窗口显示(默认)")
    ap.set_defaults(fullscreen=False)
    ap.add_argument("--camera", default="/dev/video33",
                    help="camera0=/dev/video33, camera1=/dev/video51")
    ap.add_argument("--frames", type=int, default=0,
                    help="跑多少帧后退出(0=一直跑)")
    args = ap.parse_args()

    model = find_model(args.model, args.precision)
    if not model:
        print("找不到风格 '%s' 的 %s 模型, 预期在 %s" %
              (args.model, args.precision, MODEL_DIR))
        print("本部署分支仅附带 udnie 的 INT8 模型")
        return 1

    Gst.init(None)

    print("[rknn] 模型 %s" % model)
    rknn = RknnStyle(model)
    print("[rknn] 模型输入 %dx%d C%d" % (rknn.w, rknn.h, rknn.c))

    cap = build_capture(args.camera)
    disp = build_display(CAM_W, CAM_H, args.fullscreen)
    sink = cap.get_by_name("sink")
    src = disp.get_by_name("src")

    loop = GLib.MainLoop()
    state = {"n": 0, "t0": time.time(), "last": time.time()}

    def on_sample(appsink):
        sample = appsink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, mi = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            frame = np.frombuffer(mi.data, dtype=np.uint8)
            frame = frame[:CAM_W * CAM_H * 3].reshape(CAM_H, CAM_W, 3)
        finally:
            buf.unmap(mi)

        small = cv2.resize(frame, (rknn.w, rknn.h),
                           interpolation=cv2.INTER_AREA)
        styled = rknn.run(small)

        img = np.clip(styled, 0, 255).astype(np.uint8)

        show = cv2.resize(img, (CAM_W, CAM_H), interpolation=cv2.INTER_LINEAR)
        show = cv2.cvtColor(show, cv2.COLOR_RGB2RGBA)
        data = np.ascontiguousarray(show).tobytes()
        gbuf = Gst.Buffer.new_allocate(None, len(data), None)
        gbuf.fill(0, data)
        gbuf.pts = state["n"] * Gst.SECOND // FPS
        gbuf.duration = Gst.SECOND // FPS
        src.emit("push-buffer", gbuf)

        state["n"] += 1
        state["last"] = time.time()
        if state["n"] % 5 == 0:
            dt = time.time() - state["t0"]
            print("[info] %d 帧, %.2f FPS" % (state["n"], state["n"] / dt), flush=True)
        if args.frames and state["n"] >= args.frames:
            loop.quit()
        return Gst.FlowReturn.OK

    sink.connect("new-sample", on_sample)

    def on_watchdog():
        idle = time.time() - state["last"]
        if state["n"] == 0 and idle > 15:
            print("[错误] 15 秒未收到任何帧 —— 检查相机 %s 是否可用" % args.camera,
                  flush=True)
            loop.quit()
            return False
        return True

    GLib.timeout_add(1000, on_watchdog)

    for p in (cap, disp):
        p.set_state(Gst.State.PLAYING)

    print("[info] 开始, 按 Ctrl+C 退出", flush=True)
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n[info] 中断, 清理中...", flush=True)
    finally:
        for p in (cap, disp):
            p.set_state(Gst.State.NULL)
        rknn.release()
    print("[info] 结束, 共处理 %d 帧" % state["n"], flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
