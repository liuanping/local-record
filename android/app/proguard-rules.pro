# sherpa-onnx 的 Kotlin 类会被 native 代码按名字构造/调用，必须保留
-keep class com.k2fsa.sherpa.onnx.** { *; }

# 自己写的 native 方法与 JNI 入口
-keepclasseswithmembernames class * {
    native <methods>;
}
-keep class com.localrecord.app.OcrEngine { *; }

# 保留行号，便于看崩溃栈
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
