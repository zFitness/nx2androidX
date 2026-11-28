// Linux port: the movie decoder over FFmpeg's software H.264 (libavcodec), in the mavc_* surface of dm/host/hle_movie_avc.h —
// VideoToolbox there (hle_movie_avc.c), MediaCodec on Android (movie_avc.c). Software decode only: no hwaccel, no threads of ours
// (hle_movie.c calls from its own worker; one decode thread here keeps the picture out without frame-threading's reorder delay).
// build.py takes this file when pkg-config finds libavcodec, movie_null.c (no pictures) otherwise; it says which one went in.
//
// What the game hands over (hle_movie.c → Configure / AcquireInputBufferIndex): SPS/PPS through mavc_param_sets or mavc_avcc, one access
// unit per mavc_decode, pictures taken with mavc_take into NV12 (or RGBA through mavc_set_rgba, the native texture mode), padded with
// black / cropped to the texture's size. Access units may be Annex B already or length-prefixed (the AVCC layout VideoToolbox eats);
// both are turned into Annex B here, and the parameter sets become the decoder's extradata.
#include "hle_movie_avc.h"
#include <libavcodec/avcodec.h>
#include <libavutil/mem.h>
#include <libavutil/pixfmt.h>
#include <libswscale/swscale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FIFO_MAX 16
#define SAY_ONCE(...) do { if (!a->said) { fprintf(stderr, "[movie-ffmpeg] " __VA_ARGS__); a->said = 1; } } while (0)

struct mavc {
    AVCodecContext *ctx;      // opened at the first decode, with the parameter sets as extradata
    AVFrame *frm; AVPacket *pkt;
    AVFrame *fifo[FIFO_MAX]; int nfifo;   // decoded pictures, oldest (presentation order) first
    uint8_t *csd; size_t csd_n;           // SPS/PPS as Annex B (from param_sets or avcc)
    int rgba;                             // mavc_set_rgba: pictures as RGBA instead of NV12
    int eos;                              // the decoder was flushed: no more pictures after the fifo
    int64_t prev_pts;                     // the last picture's time, for frames the stream gave no time for
    struct SwsContext *sws;               // NV12/whatever → RGBA, for the native texture mode
    uint8_t *rgba_scratch; size_t rgba_cap; int said;
};

// ---- AVCC → Annex B ----------------------------------------------------------------------------------
static void csd_append(uint8_t **b, size_t *n, size_t *cap, const uint8_t *nal, size_t len) {
    if (*n + 4 + len > *cap) { *cap = (*n + 4 + len) * 2; *b = realloc(*b, *cap); }
    memcpy(*b + *n, "\x00\x00\x00\x01", 4); *n += 4;
    memcpy(*b + *n, nal, len); *n += len;
}

static void annexb_from_avcc(const uint8_t *p, size_t n, uint8_t **b, size_t *bn) {
    *b = malloc(64); *bn = 0; size_t cap = 64;
    if (n >= 7) {   // AVCDecoderConfigurationRecord: 5 header bytes, then NALU length + NALU twice over
        size_t o = 6;
        int sps = p[5] & 0x1f;
        for (int s = 0; s < sps && o + 2 <= n; s++) { size_t l = (size_t)p[o] << 8 | p[o + 1]; o += 2; if (o + l > n) goto loose; csd_append(b, bn, &cap, p + o, l); o += l; }
        if (o < n) { int pps = p[o]; o++; for (int s = 0; s < pps && o + 2 <= n; s++) { size_t l = (size_t)p[o] << 8 | p[o + 1]; o += 2; if (o + l > n) goto loose; csd_append(b, bn, &cap, p + o, l); o += l; } }
        if (*bn) return;
    }
loose:
    *bn = 0; csd_append(b, bn, &cap, p, n);   // not an avcC record after all: one NAL, start code in front
}

static void csd_set(struct mavc *a, const uint8_t *p, size_t n) {
    free(a->csd); a->csd = NULL;
    if (n >= 4 && p[0] == 0 && p[1] == 0 && (p[2] == 1 || (p[2] == 0 && p[3] == 1))) {   // Annex B already
        a->csd = malloc(n); memcpy(a->csd, p, n); a->csd_n = n; return;
    }
    annexb_from_avcc(p, n, &a->csd, &a->csd_n);
}

// One access unit as Annex B: pass-through when it carries start codes, else walked as [u32 length][NALU]
static uint8_t *au_annexb(const uint8_t *p, int n, int *out_n) {
    uint8_t *b; size_t bn = 0, cap = 0;
    if (n >= 4 && p[0] == 0 && p[1] == 0 && (p[2] == 1 || (p[2] == 0 && p[3] == 1))) {
        b = malloc((size_t)n); memcpy(b, p, (size_t)n); *out_n = n; return b;
    }
    if (n >= 4) {
        b = NULL; size_t o = 0, ok = 1;
        while (o + 4 <= (size_t)n) {
            size_t l = (size_t)p[o] << 24 | (size_t)p[o + 1] << 16 | (size_t)p[o + 2] << 8 | p[o + 3];
            o += 4;
            if (l == 0 || l > (size_t)n - o) { ok = 0; break; }
            csd_append(&b, &bn, &cap, p + o, l); o += l;
        }
        if (ok && bn && o == (size_t)n) { *out_n = (int)bn; return b; }
        free(b);
    }
    b = malloc((size_t)n + 4); memcpy(b, "\x00\x00\x00\x01", 4); memcpy(b + 4, p, (size_t)n); *out_n = n + 4; return b;
}

// ---- the decoder -------------------------------------------------------------------------------------
static enum AVPixelFormat get_fmt(struct AVCodecContext *c, const enum AVPixelFormat *f) {
    (void)c;
    for (const enum AVPixelFormat *p = f; *p != AV_PIX_FMT_NONE; p++)
        if (*p == AV_PIX_FMT_NV12) return *p;   // take() copies NV12 planes straight into the texture's buffer
    return f[0];
}

static int open_decoder(struct mavc *a) {
    if (a->ctx) return 1;
    const AVCodec *c = avcodec_find_decoder(AV_CODEC_ID_H264);
    if (!c) { fprintf(stderr, "[RED] [movie-ffmpeg] libavcodec has no H.264 decoder\n"); return 0; }
    a->ctx = avcodec_alloc_context3(c);
    a->frm = av_frame_alloc(); a->pkt = av_packet_alloc();
    if (!a->ctx || !a->frm || !a->pkt) { fprintf(stderr, "[RED] [movie-ffmpeg] out of memory\n"); return 0; }
    if (a->csd_n) { a->ctx->extradata = av_mallocz(a->csd_n + AV_INPUT_BUFFER_PADDING_SIZE); memcpy(a->ctx->extradata, a->csd, a->csd_n); a->ctx->extradata_size = (int)a->csd_n; }
    a->ctx->thread_count = 1;      // one thread: no frame-threading reorder delay; the movies decode in hle_movie's own worker
    a->ctx->get_format = get_fmt;
    if (avcodec_open2(a->ctx, c, NULL) < 0) { fprintf(stderr, "[RED] [movie-ffmpeg] avcodec_open2 failed\n"); return 0; }
    return 1;
}

static void drain(struct mavc *a) {
    while (a->nfifo < FIFO_MAX && avcodec_receive_frame(a->ctx, a->frm) >= 0) {
        AVFrame *hold = av_frame_alloc();
        av_frame_move_ref(hold, a->frm);
        a->fifo[a->nfifo++] = hold;
    }
}

// ---- the surface -------------------------------------------------------------------------------------
mavc *mavc_new(void) { struct mavc *a = calloc(1, sizeof *a); return a; }
void mavc_free(mavc *a) {
    if (!a) return;
    for (int i = 0; i < a->nfifo; i++) av_frame_free(&a->fifo[i]);
    sws_freeContext(a->sws); av_frame_free(&a->frm); av_packet_free(&a->pkt); avcodec_free_context(&a->ctx);
    free(a->csd); free(a->rgba_scratch); free(a);
}
void mavc_param_sets(mavc *a, const uint8_t *p, size_t n) { csd_set(a, p, n); }
void mavc_avcc(mavc *a, const uint8_t *p, size_t n) { free(a->csd); a->csd = malloc(n); memcpy(a->csd, p, n); a->csd_n = n; }
void mavc_set_rgba(mavc *a) { a->rgba = 1; }
void mavc_drop(mavc *a) { for (int i = 0; i < a->nfifo; i++) av_frame_free(&a->fifo[i]); a->nfifo = 0; if (a->ctx) avcodec_flush_buffers(a->ctx); a->eos = 0; }
int mavc_queued(const mavc *a) { return a->nfifo; }
int mavc_held(const mavc *a) { return a->nfifo; }

int mavc_decode(mavc *a, const uint8_t *p, int n, int64_t pts_us) {
    if (!a || n <= 0) return 0;
    if (!open_decoder(a)) return -1;
    int an = 0; uint8_t *au = au_annexb(p, n, &an);
    av_new_packet(a->pkt, an);               // its own padded buffer; the bytes copied in
    memcpy(a->pkt->data, au, (size_t)an);
    free(au);
    a->pkt->pts = a->pkt->dts = pts_us;
    int r = avcodec_send_packet(a->ctx, a->pkt);
    if (r == AVERROR(EAGAIN)) { drain(a); r = avcodec_send_packet(a->ctx, a->pkt); }
    if (r < 0 && r != AVERROR_INVALIDDATA) SAY_ONCE("avcodec_send_packet %d (%s)\n", r, av_err2str(r));
    drain(a);
    return 0;   // decoded (or the packet was dropped): the movie plays on
}

int mavc_take(mavc *a, int flush, uint8_t *dst, int w, int h, int64_t *pts_us) {
    if (!a || !a->ctx) return 0;
    if (flush) drain(a);
    if (!a->nfifo) return 0;
    AVFrame *f = a->fifo[0];
    for (int i = 1; i < a->nfifo; i++) a->fifo[i - 1] = a->fifo[i];
    a->nfifo--;
    const size_t dst_bytes = a->rgba ? (size_t)w * h * 4 : (size_t)w * h * 3 / 2;   // NV12: Y at w*h, interleaved UV at w*h/2
    memset(dst, 0, dst_bytes);   // black: the parts the picture does not cover are padded, the parts past it are cropped away
    if (!a->rgba && f->format == AV_PIX_FMT_NV12) {   // planes straight in (Y at stride w, then interleaved UV at w*h)
        int cw = w < f->width ? w : f->width, ch = (h < f->height ? h : f->height) / 2;
        for (int y = 0; y < (h < f->height ? h : f->height); y++) memcpy(dst + (size_t)y * w, f->data[0] + (size_t)y * f->linesize[0], (size_t)cw);
        for (int y = 0; y < ch; y++) memcpy(dst + (size_t)w * h + (size_t)y * w, f->data[1] + (size_t)y * f->linesize[1], (size_t)cw);
        if (f->pts != AV_NOPTS_VALUE && f->pts > 0) a->prev_pts = f->pts;
        *pts_us = a->prev_pts;
        av_frame_free(&f);
        return 1;
    } else {          // anything else (yuv420p, or RGBA mode): through sws, then padded/cropped row by row
        int same = f->width == w && f->height == h;
        enum AVPixelFormat to = a->rgba ? AV_PIX_FMT_RGBA : AV_PIX_FMT_NV12;
        int dw = same ? w : f->width, dh = same ? h : f->height;
        size_t out_bytes = a->rgba ? (size_t)dw * dh * 4 : (size_t)dw * dh * 3 / 2;
        uint8_t *out = dst;
        if (!same) { if (a->rgba_cap < out_bytes) { a->rgba_scratch = realloc(a->rgba_scratch, out_bytes); a->rgba_cap = out_bytes; } out = a->rgba_scratch; }
        sws_freeContext(a->sws);
        a->sws = sws_getContext(f->width, f->height, (enum AVPixelFormat)f->format, dw, dh, to, SWS_BILINEAR, NULL, NULL, NULL);
        if (!a->sws) { SAY_ONCE("no sws context (%dx%d %d → %dx%d %d)\n", f->width, f->height, f->format, dw, dh, to); av_frame_free(&f); return 1; }
        const uint8_t *src[4] = {f->data[0], f->data[1], f->data[2], NULL};
        int ss[4] = {f->linesize[0], f->linesize[1], f->linesize[2], 0}, ds[4] = {dw, dw, 0, 0};
        uint8_t *dd[4] = {out, out + (size_t)dw * dh, NULL, NULL};
        if (a->rgba) { dd[1] = NULL; ds[0] = dw * 4; ds[1] = 0; }
        sws_scale(a->sws, src, ss, 0, f->height, dd, ds);
        if (!same) {   // smaller picture: padded with black (the memset); larger: cropped
            int cw = w < f->width ? w : f->width, ch = h < f->height ? h : f->height;
            if (a->rgba) for (int y = 0; y < ch; y++) memcpy(dst + (size_t)y * w * 4, out + (size_t)y * dw * 4, (size_t)cw * 4);
            else { for (int y = 0; y < ch; y++) memcpy(dst + (size_t)y * w, out + (size_t)y * dw, (size_t)cw);
                   for (int y = 0; y < ch / 2; y++) memcpy(dst + (size_t)w * h + (size_t)y * w, out + (size_t)dw * dh + (size_t)y * dw, (size_t)cw); }
        }
        av_frame_free(&f);
        return 1;
    }
}
