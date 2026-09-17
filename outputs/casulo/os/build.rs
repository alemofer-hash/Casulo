use std::path::PathBuf;

fn main() {
    let out_dir = PathBuf::from(std::env::var_os("OUT_DIR").expect("OUT_DIR missing"));
    let kernel = std::env::var_os("CASULO_PREBUILT_KERNEL")
        .or_else(|| std::env::var_os("CARGO_BIN_FILE_CASULO_KERNEL_casulo-kernel"))
        .map(PathBuf::from)
        .expect("kernel artifact missing");
    let uefi_path = out_dir.join("casulo-native-x86_64.img");
    let ramdisk = std::env::var_os("CASULO_TCAP_RAMDISK")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("..")
                .join("release")
                .join("FloodSurrogate.tcap")
        });
    assert!(
        ramdisk.is_file(),
        "TCAP ramdisk missing: {}",
        ramdisk.display()
    );
    let mut boot = bootloader::UefiBoot::new(&kernel);
    boot.set_ramdisk(&ramdisk)
        .create_disk_image(&uefi_path)
        .expect("failed to create UEFI disk image");
    println!("cargo:rustc-env=CASULO_UEFI_IMAGE={}", uefi_path.display());
    println!("cargo:rerun-if-changed=kernel/src");
    println!("cargo:rerun-if-env-changed=CASULO_GENERATIVE_BRIDGE");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_PROBE");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_PAGED_IO");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_TOKENIZER_EMBEDDING");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_BLOCK0");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_DECODER");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_SAMPLING");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_RESIDENT");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_CREATION");
    println!("cargo:rerun-if-env-changed=CASULO_PREBUILT_KERNEL");
    println!("cargo:rerun-if-env-changed=CASULO_TCAP_RAMDISK");
    println!("cargo:rerun-if-changed={}", ramdisk.display());
}
