#!/usr/bin/env bash
# Build the phone app: the payload (the rootfs, the build tools, the tool's tree) and the APK.
#
#   bash packaging/android-apk/build_apk.sh [debug|release]
#
# The steps:
#   1. the rootfs from the nixport payload release (the patched glibc, Python and the rest of the runtime)
#   2. the build tools: Google's NDK (its sysroot and compiler-rt) + an ARM64 LLVM + glslc from Debian
#   3. the tool's own tree and the Python modules, staged as the app's assets
#   4. the APK (Gradle)
#
# The downloads are kept in packaging/android-apk/.cache (not committed). The payload release is public: the
# download needs the gh CLI signed in (any account), not a token with access to NixPort/nixport-rootfs.
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
root=$PWD
here=$root/packaging/android-apk
cache=$here/.cache
variant=${1:-debug}
# --no-payload: only the app, without the rootfs and the build tools (the phone already has them unpacked)
payload_flag=""
for a in "$@"; do
    [[ $a == --no-payload ]] && payload_flag="-PnoPayload"
done

die() { echo "android-apk: $*" >&2; exit 1; }

command -v gh >/dev/null || die "the gh CLI is needed (the rootfs comes from the nixport payload release)"
# The scripts need Python 3.11+: macOS's /usr/bin/python3 is 3.9, whose TLS stack stalls on the Debian index.
# The first interpreter that is new enough wins: the Homebrew names, then whatever python3 is.
py=
for c in python3.12 python3.11 python3.13 python3.14 python3; do
    command -v "$c" >/dev/null || continue
    if "$c" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then py=$c; break; fi
done
[[ -n $py ]] || die "Python 3.11+ is needed (macOS's own python3 is 3.9): install one or put it first on PATH"
echo ">> python: $py ($("$py" -c 'import platform; print(platform.python_version())'))"

# The Gradle build needs a JDK the Android plugin can make its image with (jlink): a GraalVM fails
# there ("Failed to transform core-for-system-modules.jar"). Android Studio's own runtime is the one
# that is known to work, so it is the default when it is there; a machine without it (CI) keeps the
# JAVA_HOME it was given. NX2A_JDK overrides both.
if [[ -n ${NX2A_JDK:-} ]]; then
    export JAVA_HOME=$NX2A_JDK
else
    for jbr in "/Applications/Android Studio.app/Contents/jbr/Contents/Home" "$HOME/Library/Java/JavaVirtualMachines"; do
        if [[ -x $jbr/bin/jlink ]]; then export JAVA_HOME=$jbr; break; fi
    done
fi
[[ -n ${JAVA_HOME:-} ]] || die "no JDK was found (set JAVA_HOME or NX2A_JDK to one)"

mkdir -p "$cache"

# 1. the rootfs (the supply channel's release)
if [[ ! -s $cache/payload-arm64.tar.gz ]]; then
    echo ">> the payload (nixport-rootfs@payload-latest)"
    gh release download payload-latest -R NixPort/nixport-rootfs -p payload-arm64.tar.gz -D "$cache" \
        || die "the payload is not reachable (gh release download payload-latest -R NixPort/nixport-rootfs)"
fi

# 2. the build tools
echo ">> the build tools"
"$py" "$here/fetch_debs.py" --out "$cache/debs" --cache "$cache/.deb-cache" glslc >/dev/null
"$py" "$here/build_toolchain.py" --out "$cache/toolchain" --cache "$cache" --debs "$cache/debs"

# 3. the payload the app ships
echo ">> the app's assets"
if [[ -n $payload_flag ]]; then
    echo "   skipped (--no-payload): the phone must already have the environment"
else
    "$py" "$here/build_assets.py" --out "$cache/assets" --apk-out "$cache/apk-assets" \
        --payload "$cache/payload-arm64.tar.gz" --toolchain "$cache/toolchain"
    # nx_extract for the phone, built here (the phone's .NET SDK cannot): after the assets, which it joins
    "$py" "$here/build_nx_extract.py" || echo "   (no nx_extract for the phone: the .NET SDK is missing)"
    # The phone runs the C# tools but cannot build them: without them it would try to build the shader
    # translator itself and wait for a network that is not there.
    for t in "$cache/assets/tool/tools/nx_extract/nx_extract" "$cache/assets/tool/tools/dmsh_xlate/dmsh_xlate.dll"; do
        [[ -f $t ]] || die "the app's C# tools are missing: $t (build_nx_extract.py needs the .NET SDK: install it or set DOTNET=/path/to/dotnet)"
    done
fi

# The Vulkan driver loader: the host dlopens it by name, so it goes into the app's own native library folder
# (the one the Android linker searches). Its four hooks go into the app's assets, where the porter takes them
# for the data pack (the host hands the loader the folder it sits in, and the loader looks the hooks up there).
# The phone has no C++ compiler, so it is built here. Not part of the payload: the app needs it either way.
echo ">> the Vulkan driver loader"
"$py" "$here/build_adrenotools.py" --out "$cache/assets/tool/tools/adrenotools" --jni-out "$cache/jniLibs/arm64-v8a" \
    || die "the driver loader did not build: a Vulkan driver the player picks would not load"
[[ -f "$cache/jniLibs/arm64-v8a/libadrenotools.so" ]] || die "the driver loader is not in the app's native library folder"

# Finalize after the C# tools and hooks have joined the tree: the archive is packed again, so it holds them.
if [[ -z $payload_flag ]]; then
    "$py" "$here/build_assets.py" --out "$cache/assets" --apk-out "$cache/apk-assets" --finalize
fi

# 4. the APK
echo ">> the APK"
# The old APK goes first: the packaging task writes the new zip over the old file, and a smaller build
# would leave the old bytes in it (a 380 MB APK that holds 215 MB of content).
rm -f "$root/android/app/build/outputs/apk/$variant/"*.apk
cd "$root/android"
./gradlew ":app:assemble$("$py" -c "print('Debug' if '$variant' == 'debug' else 'Release')")" $payload_flag --console=plain
apk=$(ls -t "$root/android/app/build/outputs/apk/$variant"/*.apk | head -1)
echo
echo "APK: $apk ($(du -m "$apk" | cut -f1) MB)"
