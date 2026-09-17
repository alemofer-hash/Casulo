
#pragma once
#include <cstdint>
struct whisper_context {};
struct whisper_context_params { bool use_gpu; };
enum whisper_sampling_strategy { WHISPER_SAMPLING_GREEDY };
struct whisper_full_params {
    int n_threads; const char * language;
    bool detect_language, translate, no_context, no_timestamps;
    bool single_segment, print_special, print_progress;
    bool print_realtime, print_timestamps;
};
extern "C" {
whisper_context_params whisper_context_default_params();
whisper_context * whisper_init_from_file_with_params(const char *, whisper_context_params);
int whisper_is_multilingual(whisper_context *);
void whisper_free(whisper_context *);
const char * whisper_version();
whisper_full_params whisper_full_default_params(whisper_sampling_strategy);
int whisper_full(whisper_context *, whisper_full_params, const float *, int);
int whisper_full_n_segments(whisper_context *);
const char * whisper_full_get_segment_text(whisper_context *, int);
}
