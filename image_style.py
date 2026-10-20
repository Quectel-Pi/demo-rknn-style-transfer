#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import os
import sys
import time

import numpy as np
import cv2

from rknn_style import MODEL_DIR, STYLES, RknnStyle, find_model

INTERP = {
    "nearest": cv2.INTER_NEAREST,
    "linear": cv2.INTER_LINEAR,
    "cubic": cv2.INTER_CUBIC,
    "lanczos": cv2.INTER_LANCZOS4,
}

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")


def read_image(path):
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        raise RuntimeError("cannot read %s" % path)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("unsupported or corrupt image: %s" % path)
    return img


def write_image(path, bgr):
    ext = os.path.splitext(path)[1].lower()
    if not ext:
        ext = ".png"
        path += ext
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    params = []
    if ext in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, 95]
    elif ext == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
    ok, buf = cv2.imencode(ext, bgr, params)
    if not ok:
        raise RuntimeError("cannot encode %s" % ext)
    buf.tofile(path)
    return path


def _source_ext(src):
    ext = os.path.splitext(src)[1].lower()
    return ext if ext in IMAGE_EXTS else ".png"


def is_dir_like(path):
    return path.endswith(os.sep) or os.path.isdir(path)


def resolve_output(output, outdir, src, model):
    stem = os.path.splitext(os.path.basename(src))[0]
    ext = _source_ext(src)

    name = None
    if outdir:
        folder = outdir
    elif output:
        if is_dir_like(output):
            folder, name = output, None
        else:
            folder, name = os.path.split(output)
    else:
        folder = os.path.dirname(src)

    if not name:
        name = "%s_%s%s" % (stem, model, ext)
    else:
        name = name.replace("{stem}", stem).replace("{model}", model)
        if os.path.splitext(name)[1].lower() not in IMAGE_EXTS:
            name += ext

    return os.path.join(folder or ".", name)


def style_image(rknn, bgr, interp, keep_size):
    orig_h, orig_w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    shrink = (rknn.w * rknn.h) < (orig_w * orig_h)
    small = cv2.resize(rgb, (rknn.w, rknn.h),
                       interpolation=cv2.INTER_AREA if shrink else interp)

    out = np.clip(rknn.run(small), 0, 255).astype(np.uint8)

    if keep_size:
        return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
    big = cv2.resize(out, (orig_w, orig_h), interpolation=interp)
    return cv2.cvtColor(big, cv2.COLOR_RGB2BGR)


def build_parser():
    ap = argparse.ArgumentParser(
        description="Apply RKNN style transfer to images")
    ap.add_argument("inputs", nargs="+", metavar="INPUT",
                    help="input image(s)")
    ap.add_argument("-o", "--output", metavar="PATH",
                    help="output file, or a directory (ending with /) to put "
                         "generated names in; supports {stem} and {model}")
    ap.add_argument("-d", "--outdir", metavar="DIR",
                    help="write results into DIR using generated file names")
    ap.add_argument("-m", "--model", default="udnie", choices=STYLES,
                    help="style name (default: udnie)")
    ap.add_argument("--precision", choices=("int8", "fp16"), default="int8",
                    help="model precision (default: int8)")
    ap.add_argument("--keep-size", action="store_true",
                    help="keep the model output size instead of scaling back")
    ap.add_argument("--interp", choices=tuple(INTERP), default="lanczos",
                    help="rescaling interpolation (default: lanczos)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="only print errors")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    say = (lambda *a: None) if args.quiet else (lambda *a: print(*a, flush=True))

    if args.output and args.outdir:
        print("error: -o and -d are mutually exclusive", file=sys.stderr)
        return 2
    if args.output and len(args.inputs) > 1 and not is_dir_like(args.output):
        print("error: -o needs a directory when given multiple inputs",
              file=sys.stderr)
        return 2
    for path in args.inputs:
        if not os.path.isfile(path):
            print("error: no such file: %s" % path, file=sys.stderr)
            return 2

    model_path = find_model(args.model, args.precision)
    if not model_path:
        print("error: no '%s' %s model under %s"
              % (args.model, args.precision, MODEL_DIR), file=sys.stderr)
        return 1

    say("model:  %s" % model_path)
    try:
        rknn = RknnStyle(model_path)
    except Exception as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    say("size:   model input %dx%d, %d channel(s)" % (rknn.w, rknn.h, rknn.c))

    interp = INTERP[args.interp]
    failed = 0
    try:
        for src in args.inputs:
            dst = resolve_output(args.output, args.outdir, src, args.model)
            try:
                bgr = read_image(src)
                t0 = time.time()
                styled = style_image(rknn, bgr, interp, args.keep_size)
                ms = (time.time() - t0) * 1000.0
                dst = write_image(dst, styled)
            except Exception as exc:
                print("error: %s: %s" % (src, exc), file=sys.stderr)
                failed += 1
                continue
            say("[%dx%d] -> [%dx%d]  %.0f ms  %s"
                % (bgr.shape[1], bgr.shape[0],
                   styled.shape[1], styled.shape[0], ms, dst))
    finally:
        rknn.release()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
