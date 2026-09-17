#include "whisper.h"

#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <exception>
#include <new>
#include <string>

#if defined(_WIN32)
#  if defined(CASULO_WHISPER_BUILD)
#    define CASULO_API extern "C" __declspec(dllexport)
#  else
#    define CASULO_API extern "C" __declspec(dllimport)
#  endif
#else
#  define CASULO_API extern "C" __attribute__((visibility("default")))
#endif

namespace {

constexpr std::size_t kMaximumTranscriptBytes = 1024 * 1024;

struct CasuloWhisperHandle {
    whisper_context * context = nullptr;
    int threads = 1;
    std::string last_error;
};

void set_error(CasuloWhisperHandle * handle, const char * message) {
    if (handle != nullptr) {
        handle->last_error = message == nullptr ? "unknown" : message;
    }
}

}  // namespace

CASULO_API CasuloWhisperHandle * casulo_whisper_create(
    const char * model_path,
    int threads,
    int use_gpu) {
    if (model_path == nullptr || model_path[0] == '\0' || threads <= 0) {
        return nullptr;
    }
    auto * handle = new (std::nothrow) CasuloWhisperHandle();
    if (handle == nullptr) {
        return nullptr;
    }
    auto parameters = whisper_context_default_params();
    parameters.use_gpu = use_gpu != 0;
    handle->context = whisper_init_from_file_with_params(model_path, parameters);
    handle->threads = threads;
    if (handle->context == nullptr) {
        delete handle;
        return nullptr;
    }
    if (whisper_is_multilingual(handle->context) == 0) {
        whisper_free(handle->context);
        delete handle;
        return nullptr;
    }
    return handle;
}

CASULO_API void casulo_whisper_destroy(CasuloWhisperHandle * handle) {
    if (handle == nullptr) {
        return;
    }
    if (handle->context != nullptr) {
        whisper_free(handle->context);
    }
    delete handle;
}

CASULO_API const char * casulo_whisper_last_error(CasuloWhisperHandle * handle) {
    return handle == nullptr ? "invalid handle" : handle->last_error.c_str();
}

CASULO_API const char * casulo_whisper_upstream_version() {
    return whisper_version();
}

// 0 = success, 1 = invalid input, 2 = output too small, 3 = inference failed.
CASULO_API int casulo_whisper_transcribe_pt_br(
    CasuloWhisperHandle * handle,
    const float * samples,
    std::size_t sample_count,
    char * output,
    std::size_t output_capacity,
    std::size_t * output_size) {
    if (output_size != nullptr) {
        *output_size = 0;
    }
    if (handle == nullptr || handle->context == nullptr || samples == nullptr ||
        sample_count == 0 || sample_count > static_cast<std::size_t>(INT_MAX) ||
        output == nullptr || output_capacity == 0 || output_size == nullptr) {
        set_error(handle, "invalid transcription arguments");
        return 1;
    }
    try {
        auto parameters = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
        parameters.n_threads = handle->threads;
        parameters.language = "pt";
        parameters.detect_language = false;
        parameters.translate = false;
        parameters.no_context = true;
        parameters.no_timestamps = true;
        parameters.single_segment = false;
        parameters.print_special = false;
        parameters.print_progress = false;
        parameters.print_realtime = false;
        parameters.print_timestamps = false;
        if (whisper_full(
                handle->context,
                parameters,
                samples,
                static_cast<int>(sample_count)) != 0) {
            set_error(handle, "whisper_full failed");
            return 3;
        }
        std::string transcript;
        const int segment_count = whisper_full_n_segments(handle->context);
        for (int index = 0; index < segment_count; ++index) {
            const char * segment = whisper_full_get_segment_text(handle->context, index);
            if (segment != nullptr) {
                transcript.append(segment);
            }
        }
        if (transcript.size() + 1 > kMaximumTranscriptBytes) {
            set_error(handle, "transcript exceeds first-party limit");
            return 3;
        }
        *output_size = transcript.size();
        if (transcript.size() + 1 > output_capacity) {
            set_error(handle, "output buffer too small");
            return 2;
        }
        std::memcpy(output, transcript.data(), transcript.size());
        output[transcript.size()] = '\0';
        handle->last_error.clear();
        return 0;
    } catch (const std::exception & error) {
        set_error(handle, error.what());
        return 3;
    } catch (...) {
        set_error(handle, "unknown inference exception");
        return 3;
    }
}
