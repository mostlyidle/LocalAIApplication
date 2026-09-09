fn main() {
    #[cfg(target_os = "macos")]
    cc::Build::new()
        .file("native/macos_audio_bridge.m")
        .include("native")
        .flag("-fobjc-arc")
        .compile("localai_audio_bridge");

    #[cfg(target_os = "macos")]
    for framework in [
        "AVFAudio",
        "AVFoundation",
        "CoreMedia",
        "CoreAudio",
        "CoreGraphics",
        "ScreenCaptureKit",
    ] {
        println!("cargo:rustc-link-lib=framework={framework}");
    }
    tauri_build::build()
}
