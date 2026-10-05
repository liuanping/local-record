plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.localrecord.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.localrecord.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 312
        versionName = "3.1.2"
        ndk {
            // ABI 由下面的 splits 决定（这里不能再写 abiFilters，否则和 splits 冲突）
        }
        externalNativeBuild {
            cmake {
                // 只编我们需要的后端，别把全部示例都编进来
                arguments += listOf(
                    "-DANDROID_STL=c++_shared",
                    "-DCMAKE_BUILD_TYPE=Release"
                )
                cppFlags += "-O3"
            }
        }
    }

    // 正式包只出 arm64（手机的 onnxruntime 就有 26MB，x86_64 那份 31MB 只给模拟器用，
    // 切掉后包体少一半）。需要模拟器验证时：gradlew -Pemu assembleDebug
    splits {
        abi {
            isEnable = true
            reset()
            if (project.hasProperty("emu")) {
                include("arm64-v8a", "x86_64")
            } else {
                include("arm64-v8a")
            }
            isUniversalApk = false
        }
    }

    buildTypes {
        release {
            // 正式包：打开代码/资源瘦身，尽量压体积（ABI 由上面的 splits 决定）
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }
    ndkVersion = "27.0.12077973"
    packaging {
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}")
        // AAR 里的 .so 不要压缩，装到设备后可直接 dlopen
        jniLibs.useLegacyPackaging = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation(platform("androidx.compose:compose-bom:2024.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    // sherpa-onnx Android（离线 ASR + 标点），本地 AAR
    implementation(files("libs/sherpa-onnx.aar"))

    // VAD 这类纯逻辑用 JVM 单元测试验证（不用开模拟器、省内存）
    testImplementation("junit:junit:4.13.2")
}

// 单元测试把 println 打出来（VAD 切段证据）
tasks.withType<Test>().configureEach {
    testLogging { showStandardStreams = true }
}
