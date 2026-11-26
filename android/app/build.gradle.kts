// The phone app: nx2android's porter, running on the phone itself.
//
// The app is a shell: it unpacks the environment (the rootfs from the nixport payload, the toolchain and the
// tool's own tree) into its files folder, and runs the porter inside it. The UI is Android's own.
plugins {
    id("com.android.application")
    // The Compose compiler: from Kotlin 2.0 it is a plugin of its own
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
    id("com.google.dagger.hilt.android")
}

// The payload (the environment in one archive, the driver) is built by packaging/android-apk/build_assets.py and
// staged outside the source tree: it is a few hundred megabytes and not committed. The working tree the build
// stages the tool's tree in is .cache/assets; what goes into the APK is .cache/apk-assets.
val assetsDir = rootProject.layout.projectDirectory.dir("../packaging/android-apk/.cache/apk-assets")

// The Vulkan driver loader (libadrenotools.so), built by packaging/android-apk/build_adrenotools.py and staged
// outside the source tree as well. It is the app's own native library: the host dlopens it by name, and the
// Android linker looks a bare name up in LD_LIBRARY_PATH, in the caller's DT_RUNPATH and in the namespace's
// default library paths — the app's native library folder is the only one of those the app controls.
val jniLibsDir = rootProject.layout.projectDirectory.dir("../packaging/android-apk/.cache/jniLibs")

// The app's own signing key: a keystore of the project's, so that every build of the app (this machine, CI, the
// release) carries the same signature and installs over the one before it. Android refuses an update whose
// signature differs (INSTALL_FAILED_UPDATE_INCOMPATIBLE), and the debug keystore of a machine is that machine's:
// two builds from two machines can never replace each other. The keystore is not in the repository: it lives in
// ~/.android/nx2android.keystore (or wherever NX2A_KEYSTORE points), and CI gets it from the secret
// NX2A_KEYSTORE_B64. Without it the build falls back to the machine's debug key, which is good enough for a
// build nobody installs over another.
fun envOf(name: String) = System.getenv(name)?.takeIf { it.isNotBlank() }
val nx2aKeystore = File(envOf("NX2A_KEYSTORE") ?: "${System.getProperty("user.home")}/.android/nx2android.keystore")


// One revision source for the APK and its bundled porter.
val playerApiRevision = Regex("(?m)^PLAYER_API_REVISION = ([1-9][0-9]*)$")
    .find(rootProject.file("../porter/revision.py").readText())!!.groupValues[1].toInt()
val revisionSources = layout.buildDirectory.dir("generated/playerApiRevision")
val generatePlayerApiRevision by tasks.registering {
    inputs.file(rootProject.file("../porter/revision.py"))
    outputs.dir(revisionSources)
    doLast {
        val target = revisionSources.get().file("com/nx/android/domain/PlayerApiRevision.java").asFile
        target.parentFile.mkdirs()
        target.writeText("package com.nx.android.domain;\n\npublic final class PlayerApiRevision { public static final int CURRENT = $playerApiRevision; private PlayerApiRevision() {} }\n")
    }
}
// The list of the games the porter knows (docs/PORT_CHECKLIST.md): the build page shows it, so the
// doc goes into the app's assets. The doc is made from the profiles (docs/gen_tables.py) and copied
// here at build time: the app shows the list of the commit it was built from, and the repo keeps one
// copy of the list, not two.
val gameListAssets = layout.buildDirectory.dir("generated/gameList")
val copyGameList by tasks.registering(Copy::class) {
    from(rootProject.file("../docs/PORT_CHECKLIST.md"))
    into(gameListAssets.get().asFile.resolve("docs"))
    rename { "port_checklist.md" }
}

tasks.named("preBuild").configure { dependsOn(generatePlayerApiRevision, copyGameList) }

android {
    namespace = "com.nx.android"
    compileSdk = 37

    signingConfigs {
        if (nx2aKeystore.isFile) {
            create("nx2android") {
                storeFile = nx2aKeystore
                storePassword = envOf("NX2A_KEYSTORE_PASSWORD") ?: "nx2android"
                keyAlias = envOf("NX2A_KEYSTORE_ALIAS") ?: "nx2android"
                keyPassword = envOf("NX2A_KEY_PASSWORD") ?: envOf("NX2A_KEYSTORE_PASSWORD") ?: "nx2android"
            }
        }
    }

    defaultConfig {
        applicationId = "com.nx.android"
        minSdk = 26
        // SDK 29 from the platform enforces W^X for app data: the guest programs under files/rootfs could not
        // be exec'd at all. The app is not on Google Play (it ships as an APK from the project's releases).
        targetSdk = 28
        // The version the release's tag carries, without the "v": v0.3.0-alpha02 -> 0.3.0-alpha02. The update
        // check compares the two, so the app can tell which release is newer than the one running.
        versionCode = 22
        versionName = "0.4.1-alpha02"
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    sourceSets {
        getByName("main") {
            java.srcDir(revisionSources.get().asFile)
            // The list of the games the porter knows: copied into the assets by the task above
            assets.srcDir(gameListAssets.get().asFile)
            // The payload (the environment in one archive, the driver): built by packaging/android-apk/build_assets.py.
            // -PnoPayload leaves it out: a quick build of the app itself, for a phone that already has the
            // environment unpacked (the unpacked tree is in the app's own folder, so it survives the update).
            if (!project.hasProperty("noPayload") && assetsDir.asFile.exists()) {
                assets.directories.add(assetsDir.asFile.absolutePath)
            }
            // The Vulkan driver loader, in the app's own native library folder: the host dlopens it by name and
            // that folder is where the linker looks (jniLibs.useLegacyPackaging keeps it extracted there).
            if (jniLibsDir.asFile.exists()) {
                jniLibs.srcDir(jniLibsDir.asFile.absolutePath)
            }
        }
    }

    // The payload is big: no compression of the assets that are already compressed (the environment's archive),
    // and the whole thing is a single big blob the app unpacks on the first start.
    androidResources {
        noCompress += listOf("gz", "so", "zip", "pkg")
    }
    packaging {
        jniLibs.useLegacyPackaging = true
    }

    lint {
        // targetSdk = 28 is deliberate: SDK 29 and later enforce W^X for app data, and the guest programs
        // under files/rootfs could not be exec'd at all. This check only says the target is old - it is
        // not an error here, and it is the one check that stands between the tree and a release build.
        disable += "ExpiredTargetSdkVersion"
    }

    // The screen is Jetpack Compose (Material 3).
    buildFeatures {
        compose = true
        buildConfig = true
    }

    buildTypes {
        // The project's own key when it is there (the machine's, or the one CI restores from the secret), the
        // machine's debug key otherwise: the app is not on Google Play, and a build nobody installs over another
        // needs no key of its own.
        getByName("debug") { signingConfig = signingConfigs.findByName("nx2android") ?: signingConfigs.getByName("debug") }
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("nx2android") ?: signingConfigs.getByName("debug")
        }
    }

    // the app's own network stack is the platform's (HttpURLConnection): the agent's engine runs in
    // the guest, not in this process, so there is no HTTP client here
    configurations.all {
        // The MCP SDK 0.17.x ships the io.modelcontextprotocol.json package in both mcp-core and mcp-json;
        // the assistant never speaks MCP on the phone, so one of the twins simply goes.
        exclude(group = "io.modelcontextprotocol.sdk", module = "mcp-json")
    }

    dependencies {
        implementation(platform("androidx.compose:compose-bom:2026.09.00"))
        implementation("androidx.compose.ui:ui")
        implementation("androidx.compose.ui:ui-tooling-preview")
        // The preview runtime: the IDE's Compose Preview renders the @Preview functions with it (debug only,
        // it never goes into the APK)
        debugImplementation("androidx.compose.ui:ui-tooling")
        implementation("androidx.compose.material3:material3")
        implementation("androidx.compose.material:material-icons-extended")
        // the assistant's answers are markdown (ADR-009): full renderer — tables, links, nested lists
        implementation("com.mikepenz:multiplatform-markdown-renderer-m3:0.46.0")
        implementation("com.mikepenz:multiplatform-markdown-renderer-coil3:0.46.0")
        // the agent drawer's frosted glass (磨砂): the page behind is captured and blurred (API 31+,
        // older devices fall back to the solid tint)
        implementation("dev.chrisbanes.haze:haze:2.1.0")
        implementation("dev.chrisbanes.haze:haze-blur:2.1.0")
        implementation("androidx.activity:activity-compose:1.13.0")
        // keep these at the version the runtime graph resolves anyway: androidx.core 1.19 brings
        // lifecycle 2.11 in through the family's atomic group constraint, and the compile classpath
        // has to follow. It has to: 2.11 turned ViewModelStore.put's key from String into Object, so
        // a test compiled against 2.9 died with NoSuchMethodError against the 2.11 runtime
        implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
        implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.11.0")
        implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")
        implementation("androidx.hilt:hilt-lifecycle-viewmodel-compose:1.3.0")
        implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
        implementation("com.google.dagger:hilt-android:2.60.1")
        ksp("com.google.dagger:hilt-compiler:2.60.1")
        // adb's wireless debugging pairing needs the TLS session's keying material, which the
        // platform's Conscrypt does not export: the app pairs with itself to switch off Android's
        // child-process limit (data/PhantomFix.kt)
        implementation("org.conscrypt:conscrypt-android:2.7.0")
        testImplementation("junit:junit:4.13.2")
        testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
        // the porter's progress events and the data pack's manifest are JSON: the JVM tests parse them with
        // the real org.json (the android.jar the tests run against only has the stubs)
        testImplementation("org.json:json:20240303")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        // AgentScope rides on OkHttp 5, whose -jvm and -android modules both carry the same native-image
        // descriptors (and the framework's server-side jars carry more desktop-only metadata): none of it
        // belongs in an APK.
        resources {
            excludes += "META-INF/native-image/**"
            excludes += "META-INF/versions/9/OSGI-INF/MANIFEST.MF"
            excludes += "META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

// The one boundary the build enforces: the ":play" process's liveness is the ledger's own fact
// (appstate/PlayerState.kt). The launch gate, the busy checks and the crash detection all ask the ledger,
// and no other file scans the process itself. data/Player.kt holds the scan; appstate/PlayerState.kt is the
// one consumer.
//
// The package directions in docs/ARCHITECTURE.md (domain/ stays free of Android, Compose, data/ and
// feature/; feature/ reaches for data/ through domain contracts) are design rules kept by review, not by
// the build.
val checkArchitectureBoundaries by tasks.registering {
    group = "verification"
    description = "Checks that only the player ledger asks whether the :play process is alive."
    doLast {
        val sourceRoot = file("src/main/java/com/nx/android")
        val processAliveAllowed = setOf("data/Player.kt", "appstate/PlayerState.kt")
        val processAliveViolations = sourceRoot.walkTopDown().filter { it.isFile && it.extension == "kt" }
            .filterNot { it.relativeTo(sourceRoot).path in processAliveAllowed }
            .flatMap { source ->
                source.readLines().mapIndexedNotNull { index, line ->
                    if ("playProcessAlive" in line) "${source.relativeTo(sourceRoot)}:${index + 1}: $line" else null
                }
            }.toList()

        check(processAliveViolations.isEmpty()) {
            "Only the ledger (appstate/PlayerState.kt) may ask whether the :play process is alive:\n${processAliveViolations.joinToString("\n")}"
        }
    }
}

tasks.named("check") { dependsOn(checkArchitectureBoundaries) }

// The assets are merged before the preBuild runs when the build is only asked for the assets: the
// merge task waits for the copy itself, so the list is in the APK whatever the task graph looks like.
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }.configureEach {
    dependsOn(copyGameList)
}
