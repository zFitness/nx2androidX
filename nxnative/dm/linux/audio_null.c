// Linux port: real audio through SDL3 (the container's own pipewire/pulse/alsa), the movie's
// AAC decoded by FFmpeg's libavcodec when the build has it (HAVE_LIBAV, set by build.py the
// same way movie_ffmpeg.c is picked) — the same trade as the movie decoder: the container's
// own libraries, nothing added to the payload.
//
// hle_audio.c (the host) speaks AudioUnit — an output unit with a render callback — and
// hle_movie.c speaks AudioConverter (AAC in, interleaved PCM out); the Android port maps both
// onto AAudio / MediaCodec in dm/android/compat/. This file keeps the same surface: the
// render callback fills a buffer that goes to the SDL audio device's queue (pipewire here),
// paced to the device, with an underrun count in a health line every ~10 s; the AAC converter
// decodes packets handed over by hle_movie.c's aac_feed into interleaved s16, keeping what
// does not fit for the next fill (the audioconverter_mediacodec.c shape). Without a device or
// without libavcodec the old stand-ins answer as before (the game's audio clock advances,
// movies stay silent), with [RED] lines on record.
#include <AudioToolbox/AudioToolbox.h>
#include <SDL3/SDL.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#ifdef HAVE_LIBAV
#include <libavcodec/avcodec.h>
#include <libavutil/channel_layout.h>
#include <libavutil/mem.h>
#include <libavutil/opt.h>
#endif

struct dm_audio_component { int dummy; };
struct dm_audio_unit {
    AURenderCallback cb; void *ref;
    AudioStreamBasicDescription fmt;
    atomic_bool run; pthread_t th; int threaded;
    SDL_AudioStream *astr;
    unsigned char *pull; UInt32 pull_bytes;   // one render callback's mix, handed to the SDL stream
    unsigned long long cb_n, underruns;
};
#ifdef HAVE_LIBAV
struct dm_audio_converter {
    AudioStreamBasicDescription in, out;
    uint8_t asc[64]; int nasc;              // the AudioSpecificConfig (the magic cookie's DecoderSpecificInfo)
    int failed;                             // libavcodec refused: stay silent, no retries
    uint8_t *pend; size_t npend, cappend;   // decoded interleaved s16 not handed out yet
    AVCodecContext *ctx; AVPacket *pkt; AVFrame *frm;
};
#else
struct dm_audio_converter { int dummy; };
#endif

static struct dm_audio_component g_component;

AudioComponent AudioComponentFindNext(AudioComponent after, const AudioComponentDescription *d) {
    (void)d;
    return after ? NULL : &g_component;   // one (make-believe) output device
}

OSStatus AudioComponentInstanceNew(AudioComponent c, AudioComponentInstance *out) {
    if (!c || !out) return kAudio_UnimplementedError;
    *out = calloc(1, sizeof(struct dm_audio_unit));
    return *out ? noErr : kAudio_UnimplementedError;
}

OSStatus AudioComponentInstanceDispose(AudioComponentInstance u) {
    free(u);
    return noErr;
}

OSStatus AudioUnitSetProperty(AudioUnit u, AudioUnitPropertyID id, AudioUnitScope scope,
                              AudioUnitElement el, const void *data, UInt32 size) {
    (void)scope; (void)el;
    if (!u) return kAudio_UnimplementedError;
    if (id == kAudioUnitProperty_SetRenderCallback && size >= sizeof(AURenderCallbackStruct)) {
        const AURenderCallbackStruct *cb = data;
        u->cb = cb->inputProc; u->ref = cb->inputProcRefCon;
    } else if (id == kAudioUnitProperty_StreamFormat && size >= sizeof(AudioStreamBasicDescription)) {
        u->fmt = *(const AudioStreamBasicDescription *)data;
    }
    return noErr;
}

OSStatus AudioUnitInitialize(AudioUnit u) { (void)u; return noErr; }
OSStatus AudioUnitUninitialize(AudioUnit u) { (void)u; return noErr; }

// The device drives: when its stream wants more data, one render callback mixes ~10 ms and the
// mix goes into the stream (SDL converts 6 → 2 channels and resamples to the device on the way
// to pipewire). hle_audio.c's callback releases the game's buffers here, so the game's audio
// clock is the device's clock — no timer thread, no drift. The health line (every ~10 s) counts
// how often the stream was already empty when asked: a real underrun is the game mixing too slow.
static void sdl_pull(void *ud, SDL_AudioStream *st, int additional, int total) {
    AudioUnit u = ud;
    while (SDL_GetAudioStreamAvailable(st) < total) {
        if (!atomic_load(&u->run)) return;
        UInt32 frames = (UInt32)(u->fmt.mSampleRate / 100.0) + 1;   // ~10 ms per callback
        UInt32 bytes = u->fmt.mBytesPerFrame ? u->fmt.mBytesPerFrame * frames : 0;
        if (!bytes || bytes > u->pull_bytes) return;   // the unit is not set up yet
        if (u->cb) {
            AudioUnitRenderActionFlags flags = 0;
            AudioBufferList out = { .mNumberBuffers = 1,
                                    .mBuffers = { { u->fmt.mChannelsPerFrame, bytes, u->pull } } };
            u->cb(u->ref, &flags, NULL, 0, frames, &out);
        } else memset(u->pull, 0, bytes);
        SDL_PutAudioStreamData(st, u->pull, (int)bytes);
        u->cb_n++;
        for (int r = 0; r < 5 && SDL_GetAudioStreamAvailable(st) < total; r++) {   // audren renders one block per release (~5 ms lag)
            struct timespec wt = { 0, 3000000 }; nanosleep(&wt, NULL);
            if (u->cb) {
                AudioUnitRenderActionFlags flags = 0;
                AudioBufferList out2 = { .mNumberBuffers = 1,
                                         .mBuffers = { { u->fmt.mChannelsPerFrame, bytes, u->pull } } };
                u->cb(u->ref, &flags, NULL, 0, frames, &out2);
            } else memset(u->pull, 0, bytes);
            SDL_PutAudioStreamData(st, u->pull, (int)bytes);
        }
        if (SDL_GetAudioStreamAvailable(st) == 0) u->underruns++;   // still nothing: the game's mix was genuinely late
        if (u->cb_n % 1000 == 0)   // ~10 s at 10 ms calls: the health line (no underrun pile-up is the acceptance)
            fprintf(stderr, "[audio] callbacks %llu, underruns %llu\n", (unsigned long long)u->cb_n, (unsigned long long)u->underruns);
    }
}

OSStatus AudioOutputUnitStart(AudioUnit u) {
    if (!u) return kAudio_UnimplementedError;
    if (u->astr) return noErr;
    if (!SDL_WasInit(SDL_INIT_AUDIO) && !SDL_InitSubSystem(SDL_INIT_AUDIO))
        fprintf(stderr, "[RED] [audio] SDL audio init failed: %s (staying silent)\n", SDL_GetError());
    else {
        SDL_AudioSpec spec = { SDL_AUDIO_S16, u->fmt.mChannelsPerFrame ? u->fmt.mChannelsPerFrame : 2,
                               (int)(u->fmt.mSampleRate ? u->fmt.mSampleRate : 48000) };
        u->pull_bytes = u->fmt.mBytesPerFrame ? u->fmt.mBytesPerFrame * ((UInt32)(spec.freq / 100) + 1) : 0;
        if (u->pull_bytes) u->pull = malloc(u->pull_bytes);
        // the device drives: sdl_pull mixes when the stream wants data (SDL converts the unit's
        // 6 ch s16 48 kHz to whatever the endpoint is — 2 ch stereo here — on the way through)
        u->astr = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, sdl_pull, u);
        if (!u->astr) fprintf(stderr, "[RED] [audio] no playback device: %s (staying silent)\n", SDL_GetError());
        else { SDL_ResumeAudioStreamDevice(u->astr);
               fprintf(stderr, "[audio] playback via SDL3 on %s (unit %d Hz %u ch s16, endpoint %d Hz %d ch)\n",
                       SDL_GetAudioDeviceName(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK), (int)u->fmt.mSampleRate,
                       u->fmt.mChannelsPerFrame, spec.freq, spec.channels); }
    }
    atomic_store(&u->run, 1);
    return noErr;
}

OSStatus AudioOutputUnitStop(AudioUnit u) {
    if (!u) return kAudio_UnimplementedError;
    atomic_store(&u->run, 0);
    if (u->astr) { SDL_DestroyAudioStream(u->astr); u->astr = NULL; }
    free(u->pull); u->pull = NULL; u->pull_bytes = 0;
    return noErr;
}

#ifdef HAVE_LIBAV
// The AAC decoder's real body: packets handed over by hle_movie.c's aac_feed (one per fill,
// AudioSpecificConfig as the magic cookie's DecoderSpecificInfo) decoded by libavcodec into
// interleaved s16, what does not fit kept for the next fill (the audioconverter_mediacodec.c
// shape and the same dm_aac_tail flush contract).

static const uint8_t *descr(const uint8_t *p, const uint8_t *e, int *tag, size_t *n) {   // one ES-descriptor level
    if (p >= e) return NULL;
    *tag = *p++; size_t len = 0;
    for (int i = 0; i < 4 && p < e; i++) { uint8_t b = *p++; len = len << 7 | (b & 0x7f); if (!(b & 0x80)) break; }
    if (len > (size_t)(e - p)) return NULL;
    *n = len; return p;
}

OSStatus AudioConverterNew(const AudioStreamBasicDescription *in, const AudioStreamBasicDescription *out,
                           AudioConverterRef *c) {
    *c = NULL;
    if (in->mFormatID != kAudioFormatMPEG4AAC || out->mFormatID != kAudioFormatLinearPCM || out->mBitsPerChannel != 16 ||
        in->mChannelsPerFrame != out->mChannelsPerFrame || !in->mChannelsPerFrame || in->mChannelsPerFrame > 8)
        return kAudio_UnimplementedError;
    AudioConverterRef a = calloc(1, sizeof *a); if (!a) return -1;
    a->in = *in; a->out = *out; *c = a; return noErr;
}

OSStatus AudioConverterSetProperty(AudioConverterRef c, AudioConverterPropertyID id, UInt32 size, const void *data) {
    if (id != kAudioConverterDecompressionMagicCookie) return kAudio_UnimplementedError;
    const uint8_t *p = data, *e = p + size; int tag; size_t n;
    // ES descriptor (3): ES ID (2 bytes) and flags (1) before its decoder configuration (4): 13 bytes before its
    // DecoderSpecificInfo (5) = the AudioSpecificConfig
    if (!(p = descr(p, e, &tag, &n)) || tag != 3 || n < 3) return -50;
    e = p + n; p += 3;
    if (!(p = descr(p, e, &tag, &n)) || tag != 4 || n < 13) return -50;
    e = p + n; p += 13;
    if (!(p = descr(p, e, &tag, &n)) || tag != 5 || !n || n > sizeof c->asc) return -50;
    memcpy(c->asc, p, n); c->nasc = (int)n; return noErr;
}

static int open_codec(AudioConverterRef c) {   // once; a failure is final (silence, no retries)
    if (c->ctx) return 1;
    if (c->failed) return 0;
    c->failed = 1;
    const AVCodec *dec = avcodec_find_decoder(AV_CODEC_ID_AAC);
    if (!dec) { fprintf(stderr, "[RED] [audio] libavcodec has no AAC decoder\n"); return 0; }
    c->ctx = avcodec_alloc_context3(dec);
    if (!c->ctx) return 0;
    int rate = (int)c->in.mSampleRate, ch = (int)c->in.mChannelsPerFrame;
    uint8_t asc[64]; int an = c->nasc;
    if (!an) {   // no cookie: an AAC-LC configuration from the sample rate and channel count
        static const int rates[] = {96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350};
        int fi = 3; for (int i = 0; i < 13; i++) if (rates[i] == rate) fi = i;
        asc[0] = (uint8_t)(2 << 3 | fi >> 1); asc[1] = (uint8_t)((fi & 1) << 7 | (ch & 15) << 3); an = 2;
    } else memcpy(asc, c->asc, (size_t)an);
    c->ctx->extradata = av_mallocz((size_t)an + AV_INPUT_BUFFER_PADDING_SIZE);
    if (!c->ctx->extradata) return 0;
    memcpy(c->ctx->extradata, asc, (size_t)an); c->ctx->extradata_size = an;
    c->ctx->sample_rate = rate;
    av_channel_layout_default(&c->ctx->ch_layout, ch);
    if (avcodec_open2(c->ctx, dec, NULL) < 0) { fprintf(stderr, "[RED] [audio] avcodec_open2(aac) failed\n"); return 0; }
    c->pkt = av_packet_alloc(); c->frm = av_frame_alloc();
    if (!c->pkt || !c->frm) return 0;
    c->failed = 0; return 1;
}

static void pend_put(AudioConverterRef c, const uint8_t *s16, size_t bytes) {   // interleaved s16 into the pending buffer
    if (c->npend + bytes > c->cappend) {
        size_t want = c->cappend ? c->cappend : 16384;
        while (want < c->npend + bytes) want *= 2;
        uint8_t *r = realloc(c->pend, want); if (!r) return;
        c->pend = r; c->cappend = want;
    }
    memcpy(c->pend + c->npend, s16, bytes); c->npend += bytes;
}

static int pend_frames(AudioConverterRef c) {   // decoded s16 bytes → frames (of the output)
    return (int)(c->npend / (2u * c->out.mChannelsPerFrame));
}

// one AAC packet (the proc's buffer) → decoded interleaved s16 into the pending buffer
static void decode_packet(AudioConverterRef c, const uint8_t *data, UInt32 len) {
    if (av_new_packet(c->pkt, len) < 0) return;   // av_malloc'd with padding; av_packet_from_data would take
    memcpy(c->pkt->data, data, len);              // ownership of hle_movie's plain malloc pointer and av_free it
    if (avcodec_send_packet(c->ctx, c->pkt) < 0) return;
    av_packet_unref(c->pkt);
    while (avcodec_receive_frame(c->ctx, c->frm) >= 0) {
        int n = c->frm->nb_samples, ch = c->frm->ch_layout.nb_channels;
        if (n <= 0 || ch <= 0) { av_frame_unref(c->frm); continue; }
        size_t fb = (size_t)(2 * c->out.mChannelsPerFrame);
        uint8_t *row = malloc((size_t)n * fb);
        if (!row) { av_frame_unref(c->frm); continue; }
        if (c->frm->format == AV_SAMPLE_FMT_S16) {
            memcpy(row, c->frm->data[0], (size_t)n * fb);
        } else {   // fltp (the AAC decoder's native): planar f32 → interleaved s16
            for (int i = 0; i < n; i++) for (int k = 0; k < c->out.mChannelsPerFrame; k++) {
                const float *pl = (const float *)c->frm->data[k < ch ? k : ch - 1];
                float v = pl[i] * 32768.0f;
                int s = v > 32767.f ? 32767 : v < -32768.f ? -32768 : (int)v;
                ((uint16_t *)row)[i * c->out.mChannelsPerFrame + k] = (uint16_t)s;
            }
        }
        pend_put(c, row, (size_t)n * fb);
        free(row);
        av_frame_unref(c->frm);
    }
}

OSStatus AudioConverterFillComplexBuffer(AudioConverterRef c, AudioConverterComplexInputDataProc proc,
                                         void *ref, UInt32 *packets, AudioBufferList *out,
                                         AudioStreamPacketDescription *desc) {
    (void)desc;
    if (!open_codec(c)) { if (packets) *packets = 0; return kAudio_UnimplementedError; }
    UInt32 want = *packets; *packets = 0;
    size_t fb = 2u * c->out.mChannelsPerFrame, cap = out->mBuffers[0].mDataByteSize / fb;
    if (want > cap) want = (UInt32)cap;
    OSStatus st = noErr;
    // packets in while the pending output is short of the request, and always the first one offered:
    // hle_movie.c hands one packet per fill and asks for one packet's frames (1024), so a packet left
    // untaken would be lost
    for (int first = 1; first || pend_frames(c) < (int)want; first = 0) {
        UInt32 np = 1; AudioBufferList bl = {1, {{c->in.mChannelsPerFrame, 0, NULL}}}; AudioStreamPacketDescription *pd = NULL;
        st = proc(c, &np, &bl, &pd, ref);
        if (st || !np || !bl.mBuffers[0].mData || !bl.mBuffers[0].mDataByteSize) break;
        decode_packet(c, bl.mBuffers[0].mData, bl.mBuffers[0].mDataByteSize);
    }
    size_t frames = c->npend / fb; if (frames > want) frames = want;
    memcpy(out->mBuffers[0].mData, c->pend, frames * fb);
    memmove(c->pend, c->pend + frames * fb, c->npend - frames * fb); c->npend -= frames * fb;
    out->mBuffers[0].mDataByteSize = (UInt32)(frames * fb);
    *packets = (UInt32)frames;
    return frames ? noErr : st;
}

// The PCM still in the decoder once no packet comes (hle_movie.c's md_aac_tail): an
// end-of-stream input drains it, the codec is closed (the next fill opens a fresh one, so a
// looped movie's stream goes on), and up to cap bytes of what is decoded go out per call
size_t dm_aac_tail(AudioConverterRef c, void *dst, size_t cap) {
    if (c->ctx) {
        avcodec_send_packet(c->ctx, NULL);   // end of stream: flush
        while (avcodec_receive_frame(c->ctx, c->frm) >= 0) {
            int n = c->frm->nb_samples, ch = c->frm->ch_layout.nb_channels;
            if (n > 0 && ch > 0) {
                size_t fb = (size_t)(2 * c->out.mChannelsPerFrame);
                uint8_t *row = malloc((size_t)n * fb);
                if (row) {
                    if (c->frm->format == AV_SAMPLE_FMT_S16) memcpy(row, c->frm->data[0], (size_t)n * fb);
                    else for (int i = 0; i < n; i++) for (int k = 0; k < c->out.mChannelsPerFrame; k++) {
                        const float *pl = (const float *)c->frm->data[k < ch ? k : ch - 1];
                        float v = pl[i] * 32768.0f;
                        int s = v > 32767.f ? 32767 : v < -32768.f ? -32768 : (int)v;
                        ((uint16_t *)row)[i * c->out.mChannelsPerFrame + k] = (uint16_t)s;
                    }
                    pend_put(c, row, (size_t)n * fb);
                    free(row);
                }
            }
            av_frame_unref(c->frm);
        }
        avcodec_free_context(&c->ctx); c->ctx = NULL;
        av_packet_free(&c->pkt); av_frame_free(&c->frm);
    }
    size_t fb = 2u * c->out.mChannelsPerFrame, n = c->npend < cap ? c->npend : cap; n -= n % fb;
    memcpy(dst, c->pend, n); memmove(c->pend, c->pend + n, c->npend - n); c->npend -= n;
    return n;
}

OSStatus AudioConverterDispose(AudioConverterRef c) {
#ifdef HAVE_LIBAV
    avcodec_free_context(&c->ctx); av_packet_free(&c->pkt); av_frame_free(&c->frm);
    free(c->pend);
#endif
    free(c);
    return noErr;
}
#else   // !HAVE_LIBAV
// The AAC decoder's stand-in: every pull answers "no data", so a movie plays without its own
// sound (the same shape as movie_null.c on the video side; build.py defines HAVE_LIBAV when
// libavcodec is there, the same switch that picks movie_ffmpeg.c)
OSStatus AudioConverterNew(const AudioStreamBasicDescription *in, const AudioStreamBasicDescription *out,
                           AudioConverterRef *c) {
    (void)in; (void)out;
    if (!c) return kAudio_UnimplementedError;
    *c = calloc(1, sizeof(struct dm_audio_converter));
    return *c ? noErr : kAudio_UnimplementedError;
}

OSStatus AudioConverterSetProperty(AudioConverterRef c, AudioConverterPropertyID id, UInt32 size, const void *data) {
    (void)c; (void)id; (void)size; (void)data;
    return noErr;
}

OSStatus AudioConverterFillComplexBuffer(AudioConverterRef c, AudioConverterComplexInputDataProc proc,
                                         void *ref, UInt32 *packets, AudioBufferList *out,
                                         AudioStreamPacketDescription *desc) {
    (void)c; (void)proc; (void)ref; (void)out; (void)desc;
    if (packets) *packets = 0;   // end of stream: no decoded audio, ever
    return noErr;
}

size_t dm_aac_tail(AudioConverterRef c, void *dst, size_t cap) { (void)c; (void)dst; (void)cap; return 0; }

OSStatus AudioConverterDispose(AudioConverterRef c) {
    free(c);
    return noErr;
}
#endif
