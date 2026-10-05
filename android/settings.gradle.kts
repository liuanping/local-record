pluginManagement {
    repositories {
        // 国内镜像优先（Google Maven 直连也通，作为兜底）
        maven("https://maven.aliyun.com/repository/gradle-plugin")
        maven("https://maven.aliyun.com/repository/google")
        maven("https://maven.aliyun.com/repository/public")
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.PREFER_SETTINGS)
    repositories {
        maven("https://maven.aliyun.com/repository/google")
        maven("https://maven.aliyun.com/repository/public")
        google()
        mavenCentral()
        flatDir { dirs("libs") }        // 本地 sherpa-onnx AAR
    }
}

rootProject.name = "LocalRecord"
include(":app")
