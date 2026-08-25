plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.smarthome.livingroom_v2"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.smarthome.livingroom_v2"
        minSdk = 24
        targetSdk = 35
        versionCode = 3
        versionName = "0.5.0"
        buildConfigField("String", "DEFAULT_EDGE_CLIENT_HINT", "\"living-room-chromecast\"")
        buildConfigField("String", "DEFAULT_BRAIN_BASE_URL", "\"http://192.168.3.73:9527\"")
        buildConfigField(
            "String",
            "DEFAULT_COMMANDS_PULL_URL",
            "\"http://192.168.3.73:9527/api/v1/devices/living-room/intents\"",
        )
        buildConfigField(
            "String",
            "DEFAULT_INTENT_URL",
            "\"http://192.168.3.73:9527/api/v1/intent\"",
        )
        buildConfigField("long", "HEARTBEAT_INTERVAL_MS", "15000L")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
    }

    // Plugin sources live under repo plugins/ (same idea as iOS Xcode group).
    sourceSets {
        getByName("main") {
            java.srcDir("${rootProject.projectDir}/../plugins/netease-music/android")
            java.srcDir("${rootProject.projectDir}/../plugins/chromecast-display/android")
        }
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.leanback:leanback:1.0.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
