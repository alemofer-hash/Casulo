use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=src/ap_trampoline.asm");
    println!("cargo:rerun-if-env-changed=CASULO_GENERATIVE_BRIDGE");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_INTERACTIVE");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_PROBE");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_PAGED_IO");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_TOKENIZER_EMBEDDING");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_BLOCK0");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_DECODER");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_SAMPLING");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_MODEL_RESIDENT");
    println!("cargo:rerun-if-env-changed=CASULO_NATIVE_CREATION");
    println!("cargo:rustc-check-cfg=cfg(casulo_native_model_decoder)");
    println!("cargo:rustc-check-cfg=cfg(casulo_native_model_resident)");
    println!("cargo:rustc-check-cfg=cfg(casulo_native_creation)");
    println!(
        "cargo:rustc-env=CASULO_NATIVE_INTERACTIVE={}",
        env::var("CASULO_NATIVE_INTERACTIVE").unwrap_or_else(|_| "0".to_owned())
    );
    println!(
        "cargo:rustc-env=CASULO_NATIVE_MODEL_PROBE={}",
        env::var("CASULO_NATIVE_MODEL_PROBE").unwrap_or_else(|_| "0".to_owned())
    );
    println!(
        "cargo:rustc-env=CASULO_NATIVE_MODEL_PAGED_IO={}",
        env::var("CASULO_NATIVE_MODEL_PAGED_IO").unwrap_or_else(|_| "0".to_owned())
    );
    println!(
        "cargo:rustc-env=CASULO_NATIVE_TOKENIZER_EMBEDDING={}",
        env::var("CASULO_NATIVE_TOKENIZER_EMBEDDING").unwrap_or_else(|_| "0".to_owned())
    );
    println!(
        "cargo:rustc-env=CASULO_NATIVE_MODEL_BLOCK0={}",
        env::var("CASULO_NATIVE_MODEL_BLOCK0").unwrap_or_else(|_| "0".to_owned())
    );
    let decoder = env::var("CASULO_NATIVE_MODEL_DECODER").unwrap_or_else(|_| "0".to_owned());
    println!("cargo:rustc-env=CASULO_NATIVE_MODEL_DECODER={decoder}");
    if decoder == "1" {
        println!("cargo:rustc-cfg=casulo_native_model_decoder");
    }
    let resident = env::var("CASULO_NATIVE_MODEL_RESIDENT").unwrap_or_else(|_| "0".to_owned());
    println!("cargo:rustc-env=CASULO_NATIVE_MODEL_RESIDENT={resident}");
    if resident == "1" {
        assert_eq!(decoder, "1", "resident model profile requires the decoder");
        println!("cargo:rustc-cfg=casulo_native_model_resident");
    }
    let creation = env::var("CASULO_NATIVE_CREATION").unwrap_or_else(|_| "0".to_owned());
    println!("cargo:rustc-env=CASULO_NATIVE_CREATION={creation}");
    if creation == "1" {
        assert_eq!(
            decoder, "1",
            "Native creation requires the complete decoder"
        );
        assert_eq!(resident, "1", "Native creation requires a resident model");
        println!("cargo:rustc-cfg=casulo_native_creation");
    }
    println!(
        "cargo:rustc-env=CASULO_NATIVE_MODEL_SAMPLING={}",
        env::var("CASULO_NATIVE_MODEL_SAMPLING").unwrap_or_else(|_| "0".to_owned())
    );
    let out = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR missing"));
    let output = out.join("ap_trampoline.bin");
    let status = Command::new("nasm")
        .args(["-f", "bin", "src/ap_trampoline.asm", "-o"])
        .arg(&output)
        .status()
        .expect("nasm is required to build the bounded x86 AP trampoline");
    assert!(status.success(), "nasm failed to assemble AP trampoline");
}
