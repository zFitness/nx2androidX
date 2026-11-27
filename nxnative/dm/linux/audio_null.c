// Linux port: the AudioToolbox subset's stand-in until the ALSA output lands here.
//
// hle_audio.c (the host) speaks AudioUnit — an output unit with a render callback — and
// hle_movie.c speaks AudioConverter (AAC in, interleaved PCM out); the Android port maps
// both onto AAudio / MediaCodec in dm/android/compat/. This file keeps the same surface
// alive with no device: the render callback runs on a thread of its own at the stream's
// pace and its samples go nowhere, so the game's audio clock advances and nothing hangs,
// while everything stays silent. The real output (ALSA, directly or through SDL3's audio)
// replaces only the thread body and the device setup; the surface stays.
#include <AudioToolbox/AudioToolbox.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct dm_audio_component { int dummy; };
struct dm_audio_unit {
    AURenderCallback cb; void *ref;
    AudioStreamBasicDescription fmt;
    atomic_bool run; pthread_t th; int threaded;
};
struct dm_audio_converter { int dummy; };

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

// The render callback at the stream's pace: hle_audio.c's callback refills the mix from
// the game's audio buffers, which is what releases them and moves the audio clock on.
static void *render_thread(void *arg) {
    AudioUnit u = arg;
    UInt32 frames = (UInt32)(u->fmt.mSampleRate / 100.0) + 1;   // ~10 ms per callback
    unsigned char silence[16 * 1024];
    UInt32 bytes = u->fmt.mBytesPerFrame ? u->fmt.mBytesPerFrame * frames : 0;
    if (!bytes || bytes > sizeof(silence)) bytes = sizeof(silence);
    memset(silence, 0, sizeof(silence));
    long tick_ns = u->fmt.mSampleRate > 0 ? (long)(1e9 / (u->fmt.mSampleRate / (double)frames)) : 10000000L;
    while (atomic_load(&u->run)) {
        if (u->cb) {
            AudioUnitRenderActionFlags flags = 0;
            AudioBufferList out = { .mNumberBuffers = 1,
                                    .mBuffers = { { u->fmt.mChannelsPerFrame, bytes, silence } } };
            u->cb(u->ref, &flags, NULL, 0, frames, &out);
        }
        struct timespec t = { 0, tick_ns };
        nanosleep(&t, NULL);
    }
    return NULL;
}

OSStatus AudioOutputUnitStart(AudioUnit u) {
    if (!u) return kAudio_UnimplementedError;
    if (u->threaded) return noErr;
    atomic_store(&u->run, 1);
    if (pthread_create(&u->th, NULL, render_thread, u)) { atomic_store(&u->run, 0); return kAudio_UnimplementedError; }
    u->threaded = 1;
    return noErr;
}

OSStatus AudioOutputUnitStop(AudioUnit u) {
    if (!u) return kAudio_UnimplementedError;
    if (u->threaded) {
        atomic_store(&u->run, 0);
        pthread_join(u->th, NULL);
        u->threaded = 0;
    }
    return noErr;
}

// The AAC decoder's stand-in: every pull answers "no data", so a movie plays without its
// own sound (the same shape as movie_null.c on the video side).
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

OSStatus AudioConverterDispose(AudioConverterRef c) {
    free(c);
    return noErr;
}
