use std::path::Path;

fn main() {
    let image = Path::new(env!("CASULO_UEFI_IMAGE"));
    println!("{}", image.display());
}
