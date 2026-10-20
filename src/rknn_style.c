#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>

#include "rknn_api.h"

#define QL_ERR_MAX 512
static char g_err[QL_ERR_MAX];

static void set_err(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_err, QL_ERR_MAX, fmt, ap);
    va_end(ap);
}

const char *ql_rknn_last_error(void)
{
    return g_err;
}

static void *read_file(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        set_err("无法打开模型: %s", path);
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0) {
        set_err("模型为空: %s", path);
        fclose(f);
        return NULL;
    }
    void *buf = malloc((size_t)n);
    if (!buf) {
        set_err("内存不足(%ld 字节)", n);
        fclose(f);
        return NULL;
    }
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) {
        set_err("读取模型失败: %s", path);
        free(buf);
        fclose(f);
        return NULL;
    }
    fclose(f);
    *size = (size_t)n;
    return buf;
}

typedef struct {
    rknn_context ctx;
    rknn_input_output_num io_num;
    rknn_tensor_attr     in_attr;
    rknn_tensor_attr     out_attr;
    int                  w, h, c;
    size_t               out_bytes;
} ql_ctx_t;

void *ql_rknn_init(const char *model_path)
{
    size_t model_size = 0;
    void  *model_data = read_file(model_path, &model_size);
    if (!model_data)
        return NULL;

    ql_ctx_t *q = (ql_ctx_t *)calloc(1, sizeof(ql_ctx_t));
    if (!q) {
        set_err("calloc 失败");
        free(model_data);
        return NULL;
    }

    int ret = rknn_init(&q->ctx, model_data, (uint32_t)model_size, 0, NULL);
    free(model_data);
    if (ret != RKNN_SUCC) {
        set_err("rknn_init 失败 ret=%d", ret);
        free(q);
        return NULL;
    }

    rknn_sdk_version ver;
    memset(&ver, 0, sizeof(ver));
    if (rknn_query(q->ctx, RKNN_QUERY_SDK_VERSION, &ver, sizeof(ver)) == RKNN_SUCC)
        fprintf(stderr, "[rknn] api=%s driver=%s\n", ver.api_version, ver.drv_version);

    ret = rknn_query(q->ctx, RKNN_QUERY_IN_OUT_NUM, &q->io_num, sizeof(q->io_num));
    if (ret != RKNN_SUCC) {
        set_err("查询 IN_OUT_NUM 失败 ret=%d", ret);
        rknn_destroy(q->ctx);
        free(q);
        return NULL;
    }

    memset(&q->in_attr, 0, sizeof(q->in_attr));
    q->in_attr.index = 0;
    ret = rknn_query(q->ctx, RKNN_QUERY_INPUT_ATTR, &q->in_attr, sizeof(q->in_attr));
    if (ret != RKNN_SUCC) {
        set_err("查询 INPUT_ATTR 失败 ret=%d", ret);
        rknn_destroy(q->ctx);
        free(q);
        return NULL;
    }

    memset(&q->out_attr, 0, sizeof(q->out_attr));
    q->out_attr.index = 0;
    ret = rknn_query(q->ctx, RKNN_QUERY_OUTPUT_ATTR, &q->out_attr, sizeof(q->out_attr));
    if (ret != RKNN_SUCC) {
        set_err("查询 OUTPUT_ATTR 失败 ret=%d", ret);
        rknn_destroy(q->ctx);
        free(q);
        return NULL;
    }

    if (q->in_attr.fmt == RKNN_TENSOR_NCHW) {
        // NCHW: dims = [1,C,H,W]
        q->c = q->in_attr.dims[1];
        q->h = q->in_attr.dims[2];
        q->w = q->in_attr.dims[3];
    } else {
        // NHWC: dims = [1,H,W,C]
        q->h = q->in_attr.dims[1];
        q->w = q->in_attr.dims[2];
        q->c = q->in_attr.dims[3];
    }
    q->out_bytes = q->out_attr.n_elems * (q->out_attr.type == RKNN_TENSOR_FLOAT32 ? 4 : 2);

    fprintf(stderr, "[rknn] 输入 %dx%d C%d (fmt=%d type=%d) 输出 n_elems=%d type=%d\n",
            q->w, q->h, q->c, q->in_attr.fmt, q->in_attr.type,
            q->out_attr.n_elems, q->out_attr.type);

    return q;
}

int ql_rknn_input_info(void *handle, int *w, int *h, int *c)
{
    ql_ctx_t *q = (ql_ctx_t *)handle;
    if (!q) { set_err("句柄为空"); return -1; }
    if (w) *w = q->w;
    if (h) *h = q->h;
    if (c) *c = q->c;
    return 0;
}

int ql_rknn_run(void *handle, const void *in_ptr, int in_bytes,
                void *out_ptr, int out_cap, int *out_bytes)
{
    ql_ctx_t *q = (ql_ctx_t *)handle;
    if (!q) { set_err("句柄为空"); return -1; }

    rknn_input inputs[1];
    memset(inputs, 0, sizeof(inputs));
    inputs[0].index        = 0;
    inputs[0].type         = RKNN_TENSOR_FLOAT32;
    inputs[0].fmt          = RKNN_TENSOR_NHWC;
    inputs[0].size         = (uint32_t)in_bytes;
    inputs[0].buf          = (void *)in_ptr;
    inputs[0].pass_through = 0;

    int ret = rknn_inputs_set(q->ctx, 1, inputs);
    if (ret != RKNN_SUCC) { set_err("rknn_inputs_set 失败 ret=%d", ret); return -1; }

    ret = rknn_run(q->ctx, NULL);
    if (ret != RKNN_SUCC) { set_err("rknn_run 失败 ret=%d", ret); return -1; }

    rknn_output outputs[1];
    memset(outputs, 0, sizeof(outputs));
    outputs[0].index        = 0;
    outputs[0].want_float   = 1;
    outputs[0].is_prealloc  = 1;
    outputs[0].buf          = out_ptr;
    outputs[0].size         = (uint32_t)out_cap;

    ret = rknn_outputs_get(q->ctx, 1, outputs, NULL);
    if (ret != RKNN_SUCC) { set_err("rknn_outputs_get 失败 ret=%d", ret); return -1; }

    if (out_bytes)
        *out_bytes = (int)(q->out_attr.n_elems * sizeof(float));

    ret = rknn_outputs_release(q->ctx, 1, outputs);
    if (ret != RKNN_SUCC) { set_err("rknn_outputs_release 失败 ret=%d", ret); return -1; }

    return 0;
}

void ql_rknn_release(void *handle)
{
    ql_ctx_t *q = (ql_ctx_t *)handle;
    if (!q) return;
    rknn_destroy(q->ctx);
    free(q);
}
