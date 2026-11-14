// Conservative bounds for the translator's uniform { vec4 data[N]; } blocks.
// Direct access chains with proven scalar index ranges are accepted. Unknown
// layouts, unbounded indexing, pointer aliases and pointer escapes retain the full
// binding. The SPIR-V itself is unchanged; this only limits CPU shadow copies.
#ifndef VK_CBUF_EXTENT_H
#define VK_CBUF_EXTENT_H
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

// Inclusive nonnegative scalar intervals. Float intervals are deliberately
// restricted to integral endpoints <= 2^24: these endpoints remain exact in
// float32. Unknown arithmetic, overflow, pointer escapes and multiply-written
// locals fail closed. Only defined SPIR-V executions are considered.
typedef struct { uint64_t lo, hi; int kind; } spv_range; // kind 1 integer, 2 float
static uint32_t spv_block(const uint32_t *w, uint32_t pos) {
    uint32_t b=0; for(uint32_t i=5;i<pos;i+=w[i]>>16) if((w[i]&65535)==248) b=w[i+1]; return b;
}
static uint32_t spv_term(const uint32_t *w,uint32_t nw,uint32_t label) {
    int inside=0;
    for(uint32_t i=5;i<nw;i+=w[i]>>16) { uint32_t op=w[i]&65535;
        if(op==248) { if(inside) return 0; inside=w[i+1]==label; }
        if(inside && op>=249 && op<=255) return i;
    } return 0;
}
// Recognize a strictly shaped do/countdown loop, with an optional early break:
// i=K; do { j=i; ...; if(unknown) break; i=j-1; } while(j>T).
// Check every incoming CFG edge; arbitrary loops retain the full binding.
static spv_range spv_countdown(const uint32_t *w,uint32_t nw,const uint32_t *at,uint32_t var) {
    spv_range no={0}; uint32_t stores[2],ns=0;
    for(uint32_t i=5;i<nw;i+=w[i]>>16) if((w[i]&65535)==62 && w[i+1]==var) { if(w[i]>>16!=3 || ns==2) return no; stores[ns++]=i; }
    if(ns!=2) return no;
    uint32_t c=w[stores[0]+2]<w[3]?at[w[stores[0]+2]]:0;
    uint32_t add=w[stores[1]+2]<w[3]?at[w[stores[1]+2]]:0;
    if(!c || w[c]>>16!=4 || (w[c]&65535)!=43 || !w[c+3] || w[c+3]>4096 || !add || (w[add]&65535)!=128 || w[add]>>16!=5) return no;
    uint32_t ty=w[c+1]<w[3]?at[w[c+1]]:0;
    if(!ty || (w[ty]&65535)!=21 || w[ty+2]!=32 || w[ty+3]!=1 || w[add+1]!=w[c+1]) return no;
    uint32_t ld=w[add+3]<w[3]?at[w[add+3]]:0, minus=w[add+4]<w[3]?at[w[add+4]]:0;
    if(!ld || (w[ld]&65535)!=61 || w[ld]>>16!=4 || !minus || (w[minus]&65535)!=43 || w[minus]>>16!=4 || w[minus+3]!=UINT32_MAX) return no;
    uint32_t alias=w[ld+3], ast=0;
    for(uint32_t i=5;i<nw;i+=w[i]>>16) if((w[i]&65535)==62 && w[i+1]==alias) { if(ast || w[i]>>16!=3) return no; ast=i; }
    uint32_t src=ast && w[ast+2]<w[3]?at[w[ast+2]]:0;
    if(!src || (w[src]&65535)!=61 || w[src]>>16!=4 || w[src+3]!=var || ast!=src+4) return no;
    uint32_t init=spv_block(w,stores[0]), body=spv_block(w,ast), update=spv_block(w,stores[1]);
    uint32_t it=spv_term(w,nw,init),ut=spv_term(w,nw,update),bt=spv_term(w,nw,body);
    if(!it || it!=stores[0]+3 || (w[it]&65535)!=249 || !ut || ut!=stores[1]+3 || (w[ut]&65535)!=249 || !bt || (w[bt]&65535)!=250) return no;
    uint32_t header=w[it+1],cont=w[ut+1],ht=spv_term(w,nw,header),ct=spv_term(w,nw,cont);
    if(!ht || (w[ht]&65535)!=249 || w[ht+1]!=body || !ct || (w[ct]&65535)!=250 || w[ct+2]!=header) return no;
    if(spv_block(w,src)!=body || spv_block(w,ld)!=update || spv_block(w,add)!=update) return no;
    uint32_t merge=w[ct+3],lm=0;
    for(uint32_t i=5;i<ht;i+=w[i]>>16) if((w[i]&65535)==246 && spv_block(w,i)==header) lm=i;
    if(!lm || w[lm]>>16!=4 || w[lm+1]!=merge || w[lm+2]!=cont) return no;
    uint32_t neg=w[ct+1]<w[3]?at[w[ct+1]]:0;
    if(!neg || (w[neg]&65535)!=168 || w[neg]>>16!=4) return no;
    uint32_t cmp=w[neg+3]<w[3]?at[w[neg+3]]:0;
    if(!cmp || (w[cmp]&65535)!=179 || w[cmp]>>16!=5) return no;
    uint32_t cl=w[cmp+3]<w[3]?at[w[cmp+3]]:0,threshold=w[cmp+4]<w[3]?at[w[cmp+4]]:0;
    if(!cl || (w[cl]&65535)!=61 || w[cl]>>16!=4 || w[cl+3]!=alias || !threshold || (w[threshold]&65535)!=43 || w[threshold]>>16!=4 || !w[threshold+3] || w[threshold+3]>w[c+3]) return no;
    if(spv_block(w,cl)!=cont || spv_block(w,cmp)!=cont || spv_block(w,neg)!=cont || cl>=cmp || cmp>=neg || neg>=ct) return no;
    if(w[cl+1]!=w[c+1] || w[threshold+1]!=w[c+1] || w[minus+1]!=w[c+1]) return no;
    uint32_t escape=w[bt+2],et=spv_term(w,nw,escape);
    if(w[bt+3]!=update || !et || (w[et]&65535)!=249 || w[et+1]!=merge) return no;
    // All seven blocks must be distinct; no hidden entries into the induction path.
    uint32_t blocks[]={init,header,body,update,cont,escape,merge};
    for(int i=0;i<7;i++) for(int j=0;j<i;j++) if(blocks[i]==blocks[j]) return no;
    for(uint32_t i=5,b=0;i<nw;i+=w[i]>>16) {
        uint32_t op=w[i]&65535,n=w[i]>>16;if(op==248)b=w[i+1];
        // Alias must be a plain function-local scalar with no pointer escapes.
        for(uint32_t j=1;j<n;j++) if(w[i+j]==alias && b) {
            if(op==59 && n==4 && j==2 && w[i+3]==7) continue;
            if(op==61 && n==4 && j==3) continue;
            if(op==62 && n==3 && i==ast && j==1) continue;
            return no;
        }
        if(op==251) return no; // switch edges are outside this recognizer
        if(op!=249 && op!=250) continue;
        for(uint32_t j=op==249?1:2;j<(op==249?2u:4u);j++) {
            uint32_t target=w[i+j];
            if(target==header && i!=it && i!=ct) return no;
            if(target==body && i!=ht) return no;
            if(target==update && i!=bt) return no;
            if(target==cont && i!=ut) return no;
        }
    }
    // The decremented value may also be loaded after the loop, so include T-1.
    return (spv_range){w[threshold+3]-1,w[c+3],1};
}

static spv_range spv_index_range(const uint32_t *w, uint32_t nw, const uint32_t *at, uint32_t id, unsigned depth) {
    spv_range no = {0};
    if (depth > 64 || id >= w[3] || !at[id]) return no;
    uint32_t p=at[id], op=w[p]&65535, n=w[p]>>16;
    if(n<3) return no;
    uint32_t ty=w[p+1]<w[3]?at[w[p+1]]:0;
    if(!ty || ((w[ty]&65535)!=21 && (w[ty]&65535)!=22) || w[ty+2]!=32) return no;
    int kind=(w[ty]&65535)==21?1:2;
    uint64_t limit=kind==1 ? (w[ty+3]?2147483647ull:4294967295ull) : 16777216ull;
    if(op==43 && n==4) {
        if(kind==1) return w[p+3]<=limit?(spv_range){w[p+3],w[p+3],1}:no;
        float f; memcpy(&f,&w[p+3],4);
        if(!(f>=0 && f<=16777216.f) || f!=(float)(uint32_t)f) return no;
        return (spv_range){(uint32_t)f,(uint32_t)f,2};
    }
    if(op==61 && n==4) {
        uint32_t v=w[p+3], vp=v<w[3]?at[v]:0, value=0;
        if(!vp || (w[vp]&65535)!=59 || w[vp]>>16!=4 || w[vp+3]!=7) return no;
        for(uint32_t i=5;i<nw;i+=w[i]>>16) {
            uint32_t c=w[i]>>16,o=w[i]&65535;
            if(o==62 && c==3 && w[i+1]==v) { if(value) value=UINT32_MAX; else value=w[i+2]; }
            // Function local pointers must not escape or be accessed indirectly.
            if(i>=vp) for(uint32_t j=1;j<c;j++) if(w[i+j]==v) {
                if(o==59 && j==2 && i==vp) continue;
                if(o==61 && c==4 && j==3) continue;
                if(o==62 && c==3 && j==1) continue;
                return no;
            }
        }
        return value==UINT32_MAX?spv_countdown(w,nw,at,v):value?spv_index_range(w,nw,at,value,depth+1):no;
    }
    if(op==12 && n>=6) {
        uint32_t imp=w[p+3]<w[3]?at[w[p+3]]:0;
        if(!imp || w[imp]>>16!=6 || memcmp(w+imp+2,"GLSL.std.450",13)) return no;
        if(w[p+4]==43 && n==8 && kind==2) { // FClamp, finite constant endpoints
            spv_range a=spv_index_range(w,nw,at,w[p+6],depth+1), b=spv_index_range(w,nw,at,w[p+7],depth+1);
            if(a.kind==2 && b.kind==2 && a.lo==a.hi && b.lo==b.hi && a.lo<=b.lo) return (spv_range){a.lo,b.hi,2};
        }
        if(w[p+4]==8 && n==6 && kind==2) { // Floor preserves integral bounds
            spv_range a=spv_index_range(w,nw,at,w[p+5],depth+1); if(a.kind==2) return a;
        }
        return no;
    }
    if(n<4) return no;
    spv_range a=spv_index_range(w,nw,at,w[p+3],depth+1);
    if((op==83 || op==124) && n==4 && a.kind==kind && a.hi<=limit) return a;
    if((op==109 || op==110) && n==4 && kind==1 && a.kind==2 && a.hi<=limit) return (spv_range){a.lo,a.hi,1};
    if(n!=5) return no;
    spv_range b=spv_index_range(w,nw,at,w[p+4],depth+1);
    if(op==199 && kind==1) { // AND with a nonnegative constant bounds unknown input too
        if(b.kind==1 && b.lo==b.hi && b.hi<=limit) return (spv_range){0,b.hi,1};
        if(a.kind==1 && a.lo==a.hi && a.hi<=limit) return (spv_range){0,a.hi,1};
    }
    if(a.kind!=kind || b.kind!=kind) return no;
    if(op==128 && kind==1 && a.hi<=limit-b.hi) return (spv_range){a.lo+b.lo,a.hi+b.hi,1};
    if((op==132 && kind==1) || (op==133 && kind==2)) {
        if(!b.hi || a.hi<=limit/b.hi) return (spv_range){a.lo*b.lo,a.hi*b.hi,kind};
    }
    if(kind==1 && b.lo==b.hi && b.hi<32) {
        if(op==194) return (spv_range){a.lo>>b.hi,a.hi>>b.hi,1};
        if(op==196 && a.hi<=(limit>>b.hi)) return (spv_range){a.lo<<b.hi,a.hi<<b.hi,1};
    }
    return no;
}

static uint32_t spv_cbuf_extent(const uint32_t *w, uint32_t nw, uint32_t binding) {
    if (nw < 5 || w[0] != 0x07230203 || !w[3] || w[3] > 1048576 || w[nw-1] != ((1u<<16)|56)) return 0;
    uint32_t bound = w[3], var = 0, fn = nw, extent = 0;
    uint32_t *at = calloc(bound, sizeof *at); uint8_t *ptr = calloc(bound, 1);
    if (!at || !ptr) { free(at); free(ptr); return 0; }
    int ok = 1;
    for (uint32_t i = 5; i < nw;) {
        uint32_t n = w[i] >> 16, op = w[i] & 65535;
        if (!n || n > nw - i) { ok = 0; break; }
        if (op == 54 && fn == nw) fn = i;
        if (op >= 19 && op <= 33 && n >= 2 && w[i+1] < bound) at[w[i+1]] = i;
        if (op==11 && n>=2 && w[i+1]<bound) at[w[i+1]]=i;
        if ((op == 12 || op == 43 || op == 59 || op == 61 || op == 83 || op == 109 || op == 110 || op == 124 || op == 128 || op == 132 || op == 133 || op == 168 || op == 179 || op == 194 || op == 196 || op == 199) && n >= 3 && w[i+2] < bound) at[w[i+2]] = i;
        if (op == 71 && n == 4 && w[i+2] == 33 && w[i+3] == binding) {
            if (var) ok = 0; else var = w[i+1];
        }
        i += n;
    }
    uint32_t p = var < bound ? at[var] : 0, st = 0, ar = 0, ve = 0, scalar = 0, count = 0;
    if (!p || (w[p] & 65535) != 59 || w[p] >> 16 != 4 || w[p+3] != 2) ok = 0;
    if (ok) { p = w[p+1] < bound ? at[w[p+1]] : 0;
        if (!p || (w[p]&65535) != 32 || w[p]>>16 != 4 || w[p+2] != 2) ok = 0; else st = w[p+3]; }
    if (ok) { p = st < bound ? at[st] : 0;
        if (!p || (w[p]&65535) != 30 || w[p]>>16 != 3) ok = 0; else ar = w[p+2]; }
    if (ok) { p = ar < bound ? at[ar] : 0;
        if (!p || (w[p]&65535) != 28 || w[p]>>16 != 4) ok = 0;
        else { ve = w[p+2]; uint32_t c = w[p+3] < bound ? at[w[p+3]] : 0;
            if (!c || (w[c]&65535) != 43 || w[c]>>16 != 4 || !w[c+3] || w[c+3]>4096) ok = 0; else count=w[c+3]; } }
    if (ok) { p = ve < bound ? at[ve] : 0;
        if (!p || (w[p]&65535) != 23 || w[p]>>16 != 4 || w[p+3] != 4) ok = 0; else scalar = w[p+2]; }
    if (ok) { p = scalar < bound ? at[scalar] : 0;
        if (!p || ((w[p]&65535) != 21 && (w[p]&65535) != 22) || w[p+2] != 32) ok = 0; }
    int stride = 0, offset = 0, block = 0;
    for (uint32_t i = 5; ok && i < fn; i += w[i] >> 16) {
        uint32_t n=w[i]>>16, op=w[i]&65535;
        if (op==71 && n>=3 && w[i+1]==st && w[i+2]==2) block=1;
        if (op==71 && n==4 && w[i+1]==ar && w[i+2]==6) { if(w[i+3]!=16) ok=0; stride=1; }
        if (op==72 && n==5 && w[i+1]==st && w[i+2]==0 && w[i+3]==35) { if(w[i+4]!=0) ok=0; offset=1; }
    }
    ok &= stride && offset && block;
    // Mark only the simple pointer results, then reject every other pointer use.
    for (uint32_t i=fn; ok && i<nw; i+=w[i]>>16) {
        uint32_t n=w[i]>>16, op=w[i]&65535;
        if ((op==65 || op==66) && n>=4 && w[i+3]==var) {
            if ((n!=6 && n!=7) || w[i+2]>=bound) { ok=0; break; }
            uint32_t ix[3]={0};
            for(uint32_t k=4;k<n;k++) {
                spv_range r=spv_index_range(w,nw,at,w[i+k],0);
                if(r.kind!=1 || r.hi>UINT32_MAX || (k==4 && r.lo!=r.hi)) {ok=0;break;}
                ix[k-4]=(uint32_t)r.hi;
            }
            if(!ok || ix[0] || ix[1]>=count || ix[2]>=4) {ok=0;break;}
            uint32_t ty=w[i+1]<bound?at[w[i+1]]:0;
            if(!ty || (w[ty]&65535)!=32 || w[ty]>>16!=4 || w[ty+2]!=2 || w[ty+3]!=(n==6?ve:scalar)) {ok=0;break;}
            ptr[w[i+2]]=1; uint32_t end=(ix[1]+1)*16; if(end>extent) extent=end;
        }
    }
    for(uint32_t i=fn;ok && i<nw;i+=w[i]>>16) {
        uint32_t n=w[i]>>16,op=w[i]&65535;
        for(uint32_t j=1;j<n;j++) if(w[i+j]==var || (w[i+j]<bound && ptr[w[i+j]])) {
            if((op==65 || op==66) && n>=6 && w[i+3]==var && (j==2 || j==3)) continue;
            if(op==61 && n>=4 && j==3 && w[i+j]!=var) continue;
            ok=0;break;
        }
    }
    free(at); free(ptr); return ok ? extent : 0;
}
#endif
