
#include "whisper.h"
whisper_context_params whisper_context_default_params(){ return {false}; }
whisper_context * whisper_init_from_file_with_params(const char *, whisper_context_params){ static whisper_context c; return &c; }
int whisper_is_multilingual(whisper_context *){ return 1; }
void whisper_free(whisper_context *){}
const char * whisper_version(){ return "stub"; }
whisper_full_params whisper_full_default_params(whisper_sampling_strategy){ return {}; }
int whisper_full(whisper_context *, whisper_full_params, const float *, int){ return 0; }
int whisper_full_n_segments(whisper_context *){ return 0; }
const char * whisper_full_get_segment_text(whisper_context *, int){ return ""; }
