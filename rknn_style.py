#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import ctypes
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_PATH = os.path.join(HERE, "librknn_style.so")
MODEL_DIR = os.path.join(HERE, "models", "rknn")

STYLES = ("udnie",)


def find_model(name, precision):
    suffix = {
        "int8": "_int8_rk3576.rknn",
        "fp16": "_rk3576.rknn",
    }[precision]
    if os.path.isdir(MODEL_DIR):
        hits = [f for f in sorted(os.listdir(MODEL_DIR))
                if f.endswith(suffix) and f.startswith(name)]
        if hits:
            return os.path.join(MODEL_DIR, hits[0])
    return None


class RknnStyle:
    def __init__(self, model_path):
        if not os.path.isfile(LIB_PATH):
            raise RuntimeError("%s not found; run ./build.sh first" % LIB_PATH)
        self.lib = ctypes.CDLL(LIB_PATH)

        self.lib.ql_rknn_init.restype = ctypes.c_void_p
        self.lib.ql_rknn_init.argtypes = [ctypes.c_char_p]
        self.lib.ql_rknn_last_error.restype = ctypes.c_char_p
        self.lib.ql_rknn_input_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int)]
        self.lib.ql_rknn_run.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.lib.ql_rknn_release.argtypes = [ctypes.c_void_p]

        self.handle = self.lib.ql_rknn_init(model_path.encode())
        if not self.handle:
            raise RuntimeError("rknn_init failed: %s"
                               % self.lib.ql_rknn_last_error().decode())

        w = ctypes.c_int(); h = ctypes.c_int(); c = ctypes.c_int()
        if self.lib.ql_rknn_input_info(self.handle,
                                       ctypes.byref(w), ctypes.byref(h),
                                       ctypes.byref(c)) != 0:
            raise RuntimeError("querying input shape failed: %s"
                               % self.lib.ql_rknn_last_error().decode())
        self.w, self.h, self.c = w.value, h.value, c.value
        if self.c != 3:
            print("warning: model expects %d channels, 3 expected" % self.c)

        self.in_buf = np.zeros(self.w * self.h * self.c, dtype=np.float32)
        self.out_buf = np.zeros(self.w * self.h * self.c * 4, dtype=np.float32)
        self.out_n = 0

    def run(self, rgb):
        np.copyto(self.in_buf, rgb.astype(np.float32).reshape(-1))
        out_bytes = ctypes.c_int(0)
        ret = self.lib.ql_rknn_run(
            self.handle,
            self.in_buf.ctypes.data_as(ctypes.c_void_p),
            self.in_buf.nbytes,
            self.out_buf.ctypes.data_as(ctypes.c_void_p),
            self.out_buf.nbytes,
            ctypes.byref(out_bytes))
        if ret != 0:
            raise RuntimeError("rknn_run failed: %s"
                               % self.lib.ql_rknn_last_error().decode())
        self.out_n = out_bytes.value
        n = self.out_n // 4
        img = self.out_buf[:n].reshape(self.c, self.h, self.w)
        return np.transpose(img, (1, 2, 0))

    def release(self):
        if getattr(self, "handle", None):
            self.lib.ql_rknn_release(self.handle)
            self.handle = None
