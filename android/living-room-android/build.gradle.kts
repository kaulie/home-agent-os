plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.smarthome.livingroom_android"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.smarthome.livingroom_android"
        minSdk = 26
        targetSdk = 35
        versionCode = 6
        versionName = "0.6.0-console"
        buildConfigField("String", "DEFAULT_EDGE_CLIENT_HINT", "\"living-room-android\"")
        buildConfigField("String", "DEFAULT_BRAIN_BASE_URL", "\"http://192.168.3.73:9527\"")
        buildConfigField("String", "DEFAULT_CLOUD_BRAIN_BASE_URL", "\"http://115.190.153.53:9527\"")
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
        buildConfigField("long", "HEARTBEAT_INTERVAL_MS", "30000L")
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
        compose = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation(platform("androidx.compose:compose-bom:2024.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.android.gms:play-services-mlkit-document-scanner:16.0.0")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")
}
