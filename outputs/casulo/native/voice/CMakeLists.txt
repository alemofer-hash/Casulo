cmake_minimum_required(VERSION 3.20)
project(casulo_whisper_bridge LANGUAGES C CXX)

if(NOT DEFINED WHISPER_CPP_DIR)
  message(FATAL_ERROR "WHISPER_CPP_DIR is required")
endif()

if(NOT DEFINED CASULO_VOICE_OUTPUT_DIR)
  message(FATAL_ERROR "CASULO_VOICE_OUTPUT_DIR is required")
endif()

if(NOT EXISTS "${WHISPER_CPP_DIR}/include/whisper.h")
  message(FATAL_ERROR "Pinned whisper.cpp source is missing include/whisper.h")
endif()

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(WHISPER_CURL OFF CACHE BOOL "" FORCE)
set(WHISPER_SDL2 OFF CACHE BOOL "" FORCE)
set(WHISPER_OPENVINO OFF CACHE BOOL "" FORCE)
set(WHISPER_COREML OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)

add_subdirectory("${WHISPER_CPP_DIR}" whisper-upstream EXCLUDE_FROM_ALL)

add_library(casulo_whisper_bridge SHARED casulo_whisper_bridge.cpp)
target_compile_features(casulo_whisper_bridge PRIVATE cxx_std_17)
target_include_directories(casulo_whisper_bridge PRIVATE "${WHISPER_CPP_DIR}/include")
target_link_libraries(casulo_whisper_bridge PRIVATE whisper)
target_compile_definitions(casulo_whisper_bridge PRIVATE CASULO_WHISPER_BUILD=1)

# The Windows product must not depend on an undeclared MinGW runtime search path.
# Keep the first-party bridge self-contained while Windows system DLLs remain dynamic.
if(MINGW)
  target_link_options(casulo_whisper_bridge PRIVATE
    -static
    -static-libgcc
    -static-libstdc++
  )
endif()

set_target_properties(casulo_whisper_bridge PROPERTIES
  PREFIX ""
  OUTPUT_NAME "casulo_whisper_bridge"
  RUNTIME_OUTPUT_DIRECTORY "${CASULO_VOICE_OUTPUT_DIR}"
  LIBRARY_OUTPUT_DIRECTORY "${CASULO_VOICE_OUTPUT_DIR}"
)
