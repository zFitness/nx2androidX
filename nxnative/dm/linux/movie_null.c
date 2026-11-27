// Linux port: the movie decoder's stand-in where no H.264 decoder exists yet.
//
// hle_movie.c drives every platform's decoder through the mavc_* surface of
// dm/host/hle_movie_avc.h: VideoToolbox there (hle_movie_avc.c), MediaCodec on Android
// (dm/android/movie_avc.c), and here nothing yet — every access unit is dropped and no
// picture ever comes out, so a game's cutscenes show the player whatever the surface
// held before them and the movie's own audio (AAC) stays silent too (audio_null.c's
// AudioConverter answers "no data"). The real Linux decoder (ffmpeg) lands in this
// folder later, one file beside these two like the other platforms'.
#include "hle_movie_avc.h"
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

struct mavc { int dummy; };

mavc *mavc_new(void) { return calloc(1, sizeof(struct mavc)); }
void mavc_free(mavc *a) { free(a); }
void mavc_param_sets(mavc *a, const uint8_t *p, size_t n) { (void)a; (void)p; (void)n; }
void mavc_avcc(mavc *a, const uint8_t *p, size_t n) { (void)a; (void)p; (void)n; }
int mavc_decode(mavc *a, const uint8_t *p, int n, int64_t pts_us) {
    (void)a; (void)p; (void)n; (void)pts_us;
    return 0;   // 0 = "decoded (or nothing to decode)": the movie plays on without pictures
}
int mavc_take(mavc *a, int flush, uint8_t *nv12, int w, int h, int64_t *pts_us) {
    (void)a; (void)flush; (void)nv12; (void)w; (void)h; (void)pts_us;
    return 0;   // no picture in presentation order
}
int mavc_queued(const mavc *a) { (void)a; return 0; }
int mavc_held(const mavc *a) { (void)a; return 0; }   // the strong form of hle_movie.c's weak default
void mavc_set_rgba(mavc *a) { (void)a; }
void mavc_drop(mavc *a) { (void)a; }
