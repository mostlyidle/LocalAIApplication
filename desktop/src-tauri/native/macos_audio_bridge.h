#pragma once

#include <stdint.h>

typedef void (*la_pcm_callback)(const float *samples, uint32_t sample_count,
                                uint32_t sample_rate, uint16_t channels,
                                void *context);
typedef void (*la_error_callback)(const char *message, void *context);

void *la_start_system_audio(la_pcm_callback callback, la_error_callback error_callback,
                            void *context);
void *la_start_microphone(la_pcm_callback callback, void *context,
                           uint32_t *sample_rate, uint16_t *channels);
int32_t la_stop_capture(void *handle);
int32_t la_screen_recording_permission(void);
int32_t la_microphone_permission(void);
int32_t la_request_screen_recording_permission(void);
int32_t la_request_microphone_permission(void);
