/* Gerado pelo compilador T da Teloscorp / Casulo. */
#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  define CASULO_EXPORT __declspec(dllexport)
#else
#  define CASULO_EXPORT __attribute__((visibility("default")))
#endif

#if defined(_MSC_VER)
#  define CASULO_RESTRICT __restrict
#else
#  define CASULO_RESTRICT restrict
#endif

#define CASULO_NATIVE_ABI_VERSION 1u

CASULO_EXPORT uint32_t casulo_abi_version(void) {
    return CASULO_NATIVE_ABI_VERSION;
}

CASULO_EXPORT const char *casulo_artifact_id(void) {
    return "sha256:e36f1c265a4dd9425f49e6d4af4d36f5df9a22f0148c097aea54304cf9e22963";
}

CASULO_EXPORT int32_t casulo_execute_f64(
    uint32_t operation,
    size_t records,
    const double * CASULO_RESTRICT casulo_input,
    size_t column_stride,
    double * CASULO_RESTRICT results,
    double * CASULO_RESTRICT stabilized,
    uint8_t * CASULO_RESTRICT states,
    uint8_t * CASULO_RESTRICT judgements,
    uint8_t * CASULO_RESTRICT restrictions,
    size_t *failed_record,
    uint32_t *failed_instruction
) {
    size_t record;
    if (casulo_input == NULL || results == NULL ||
        states == NULL || failed_record == NULL ||
        failed_instruction == NULL || column_stride < records) {
        return -1;
    }
    switch (operation) {
    default:
        return -2;
    }
}
