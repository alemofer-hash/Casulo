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
    return "sha256:bc49962fed74c9a265d3fa3b325a428a05ed15f0dea7b397c74a784f9d225b00";
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
