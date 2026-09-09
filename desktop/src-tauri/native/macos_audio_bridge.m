#import <AVFAudio/AVFAudio.h>
#import <AVFoundation/AVFoundation.h>
#import <CoreMedia/CoreMedia.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <pthread.h>
#import "macos_audio_bridge.h"

typedef NS_ENUM(int32_t, LAHandleKind) { LAHandleSystem = 1, LAHandleMicrophone = 2 };

typedef struct {
  pthread_mutex_t lock;
  dispatch_group_t callbacks;
  BOOL stopping;
  la_pcm_callback callback;
  la_error_callback errorCallback;
  void *context;
} LACallbackLifetime;

static BOOL la_callback_begin(LACallbackLifetime *lifetime) {
  pthread_mutex_lock(&lifetime->lock);
  if (lifetime->stopping) { pthread_mutex_unlock(&lifetime->lock); return NO; }
  dispatch_group_enter(lifetime->callbacks);
  pthread_mutex_unlock(&lifetime->lock);
  return YES;
}

static void la_callback_end(LACallbackLifetime *lifetime) {
  dispatch_group_leave(lifetime->callbacks);
}

static void la_callback_stop(LACallbackLifetime *lifetime) {
  pthread_mutex_lock(&lifetime->lock);
  lifetime->stopping = YES;
  pthread_mutex_unlock(&lifetime->lock);
  dispatch_group_wait(lifetime->callbacks, DISPATCH_TIME_FOREVER);
}

static LACallbackLifetime *la_callback_create(la_pcm_callback callback,
                                               la_error_callback errorCallback,
                                               void *context) {
  LACallbackLifetime *lifetime = calloc(1, sizeof(LACallbackLifetime));
  if (lifetime == NULL) return NULL;
  pthread_mutex_init(&lifetime->lock, NULL);
  lifetime->callbacks = dispatch_group_create();
  lifetime->callback = callback;
  lifetime->errorCallback = errorCallback;
  lifetime->context = context;
  return lifetime;
}

static void la_callback_destroy(LACallbackLifetime *lifetime) {
  if (lifetime == NULL) return;
#if !OS_OBJECT_USE_OBJC
  dispatch_release(lifetime->callbacks);
#else
  lifetime->callbacks = nil;
#endif
  pthread_mutex_destroy(&lifetime->lock);
  free(lifetime);
}

@interface LAStreamOutput : NSObject <SCStreamOutput>
@property(nonatomic, assign) LACallbackLifetime *lifetime;
@end

@interface LAStreamDelegate : NSObject <SCStreamDelegate>
@property(nonatomic, assign) LACallbackLifetime *lifetime;
@end

@implementation LAStreamDelegate
- (void)stream:(SCStream *)stream didStopWithError:(NSError *)error {
  if (error != nil && self.lifetime != NULL && la_callback_begin(self.lifetime)) {
    if (self.lifetime->errorCallback != NULL)
      self.lifetime->errorCallback(error.localizedDescription.UTF8String, self.lifetime->context);
    la_callback_end(self.lifetime);
  }
}
@end

@implementation LAStreamOutput
- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
         ofType:(SCStreamOutputType)type {
  if (type != SCStreamOutputTypeAudio || !CMSampleBufferDataIsReady(sampleBuffer) ||
      self.lifetime == NULL || self.lifetime->callback == NULL) return;
  if (!la_callback_begin(self.lifetime)) return;

  CMAudioFormatDescriptionRef desc = CMSampleBufferGetFormatDescription(sampleBuffer);
  const AudioStreamBasicDescription *asbd =
      CMAudioFormatDescriptionGetStreamBasicDescription(desc);
  if (asbd == NULL || asbd->mChannelsPerFrame == 0) { la_callback_end(self.lifetime); return; }

  size_t listSize = 0;
  CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
      sampleBuffer, &listSize, NULL, 0, NULL, NULL, 0, NULL);
  AudioBufferList *list = calloc(1, listSize);
  if (list == NULL) { la_callback_end(self.lifetime); return; }
  if (CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
          sampleBuffer, &listSize, list, listSize, NULL, NULL, 0, NULL) != noErr) {
    free(list);
    la_callback_end(self.lifetime);
    return;
  }

  uint32_t frames = (uint32_t)CMSampleBufferGetNumSamples(sampleBuffer);
  uint16_t channels = (uint16_t)asbd->mChannelsPerFrame;
  float *interleaved = calloc((size_t)frames * channels, sizeof(float));
  if (interleaved == NULL) { free(list); la_callback_end(self.lifetime); return; }
  const BOOL isFloat = (asbd->mFormatFlags & kAudioFormatFlagIsFloat) != 0;
  const BOOL isNonInterleaved = (asbd->mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0;

  if (isNonInterleaved && list->mNumberBuffers >= channels) {
    for (uint16_t channel = 0; channel < channels; channel++) {
      AudioBuffer buffer = list->mBuffers[channel];
      for (uint32_t frame = 0; frame < frames; frame++) {
        if (isFloat) interleaved[(size_t)frame * channels + channel] = ((float *)buffer.mData)[frame];
        else interleaved[(size_t)frame * channels + channel] = ((int16_t *)buffer.mData)[frame] / 32768.0f;
      }
    }
  } else if (list->mNumberBuffers > 0) {
    AudioBuffer buffer = list->mBuffers[0];
    for (uint32_t frame = 0; frame < frames * channels; frame++) {
      if (isFloat) interleaved[frame] = ((float *)buffer.mData)[frame];
      else interleaved[frame] = ((int16_t *)buffer.mData)[frame] / 32768.0f;
    }
  }
  self.lifetime->callback(interleaved, frames * channels, (uint32_t)asbd->mSampleRate, channels, self.lifetime->context);
  free(interleaved);
  free(list);
  la_callback_end(self.lifetime);
}
@end

typedef struct {
  LAHandleKind kind;
  LACallbackLifetime *lifetime;
  SCStream *stream;
  LAStreamOutput *output;
  LAStreamDelegate *delegate;
  AVAudioEngine *engine;
} LAHandle;

void *la_start_system_audio(la_pcm_callback callback, la_error_callback error_callback, void *context) {
  if (callback == NULL || !CGPreflightScreenCaptureAccess()) return NULL;
  LACallbackLifetime *lifetime = la_callback_create(callback, error_callback, context);
  if (lifetime == NULL) return NULL;
  dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
  __block LAHandle *handle = NULL;
  __block BOOL started = NO;
  [SCShareableContent getShareableContentExcludingDesktopWindows:NO
                                             onScreenWindowsOnly:YES
                                                 completionHandler:^(SCShareableContent *content, NSError *error) {
    if (error != nil || content.displays.count == 0) { dispatch_semaphore_signal(semaphore); return; }
    SCContentFilter *filter = [[SCContentFilter alloc] initWithDisplay:content.displays[0]
                                                       excludingWindows:@[]];
    SCStreamConfiguration *configuration = [[SCStreamConfiguration alloc] init];
    configuration.capturesAudio = YES;
    configuration.excludesCurrentProcessAudio = YES;
    configuration.sampleRate = 48000;
    configuration.channelCount = 2;
    LAStreamOutput *output = [LAStreamOutput new];
    output.lifetime = lifetime;
    LAStreamDelegate *delegate = [LAStreamDelegate new];
    delegate.lifetime = lifetime;
    SCStream *stream = [[SCStream alloc] initWithFilter:filter configuration:configuration delegate:delegate];
    // Finalize every callback-owned field before startCapture can schedule a callback. The
    // completion below is the readiness barrier and only fires after this handle is complete.
    handle = calloc(1, sizeof(LAHandle));
    if (handle == NULL) { dispatch_semaphore_signal(semaphore); return; }
    handle->kind = LAHandleSystem;
    handle->lifetime = lifetime;
    handle->stream = stream;
    handle->output = output;
    handle->delegate = delegate;
    if ([stream addStreamOutput:output type:SCStreamOutputTypeAudio sampleHandlerQueue:
                              dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0) error:&error]) {
      [stream startCaptureWithCompletionHandler:^(NSError *startError) {
        started = (startError == nil);
        dispatch_semaphore_signal(semaphore);
      }];
    } else { dispatch_semaphore_signal(semaphore); }
  }];
  // Returning before this completion is unsafe: the ScreenCaptureKit callback may still
  // dereference the Rust context. The caller runs this startup on a blocking worker.
  dispatch_semaphore_wait(semaphore, DISPATCH_TIME_FOREVER);
  if (!started && handle != NULL) {
    la_callback_stop(lifetime);
    dispatch_semaphore_t stopSemaphore = dispatch_semaphore_create(0);
    [handle->stream stopCaptureWithCompletionHandler:^(NSError *stopError) {
      (void)stopError;
      dispatch_semaphore_signal(stopSemaphore);
    }];
    dispatch_semaphore_wait(stopSemaphore, DISPATCH_TIME_FOREVER);
    free(handle);
    handle = NULL;
  }
  if (!started) la_callback_destroy(lifetime);
  return handle;
}

void *la_start_microphone(la_pcm_callback callback, void *context,
                           uint32_t *sample_rate, uint16_t *channels) {
  if (callback == NULL || la_microphone_permission() == 2) return NULL;
  AVAudioEngine *engine = [AVAudioEngine new];
  AVAudioInputNode *input = engine.inputNode;
  AVAudioFormat *format = [input inputFormatForBus:0];
  if (format == nil || format.sampleRate == 0 || format.channelCount == 0) return NULL;
  LACallbackLifetime *lifetime = la_callback_create(callback, NULL, context);
  if (lifetime == NULL) return NULL;
  if (sample_rate) *sample_rate = (uint32_t)format.sampleRate;
  if (channels) *channels = (uint16_t)format.channelCount;
  [input installTapOnBus:0 bufferSize:1024 format:format
                    block:^(AVAudioPCMBuffer *buffer, AVAudioTime *when) {
    (void)when;
    uint32_t frames = buffer.frameLength;
    uint16_t count = (uint16_t)format.channelCount;
    float *interleaved = calloc((size_t)frames * count, sizeof(float));
    if (interleaved == NULL) return;
    if (!la_callback_begin(lifetime)) { free(interleaved); return; }
    if (buffer.floatChannelData != NULL) {
      for (uint16_t channel = 0; channel < count; channel++)
        for (uint32_t frame = 0; frame < frames; frame++)
          interleaved[(size_t)frame * count + channel] = buffer.floatChannelData[channel][frame];
    } else if (buffer.int16ChannelData != NULL) {
      for (uint16_t channel = 0; channel < count; channel++)
        for (uint32_t frame = 0; frame < frames; frame++)
          interleaved[(size_t)frame * count + channel] = buffer.int16ChannelData[channel][frame] / 32768.0f;
    }
    lifetime->callback(interleaved, frames * count, (uint32_t)format.sampleRate, count, lifetime->context);
    free(interleaved);
    la_callback_end(lifetime);
  }];
  NSError *error = nil;
  if (![engine startAndReturnError:&error]) {
    la_callback_stop(lifetime);
    [input removeTapOnBus:0];
    [engine stop];
    la_callback_destroy(lifetime);
    return NULL;
  }
  LAHandle *handle = calloc(1, sizeof(LAHandle));
  handle->kind = LAHandleMicrophone;
  handle->lifetime = lifetime;
  handle->engine = engine;
  return handle;
}

int32_t la_stop_capture(void *opaque) {
  LAHandle *handle = (LAHandle *)opaque;
  if (handle == NULL) return -1;
  LACallbackLifetime *lifetime = handle->lifetime;
  la_callback_stop(lifetime);
  if (handle->kind == LAHandleSystem) {
    dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
    [handle->stream stopCaptureWithCompletionHandler:^(NSError *error) { (void)error; dispatch_semaphore_signal(semaphore); }];
    // Completion is the ownership boundary. Do not release the Rust callback context until
    // ScreenCaptureKit confirms that no further callbacks can be delivered.
    dispatch_semaphore_wait(semaphore, DISPATCH_TIME_FOREVER);
  } else {
    [handle->engine.inputNode removeTapOnBus:0];
    [handle->engine stop];
  }
  free(handle);
  la_callback_destroy(lifetime);
  return 0;
}

int32_t la_screen_recording_permission(void) {
  return CGPreflightScreenCaptureAccess() ? 1 : 2;
}

int32_t la_microphone_permission(void) {
  AVAuthorizationStatus status = [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
  if (status == AVAuthorizationStatusAuthorized) return 1;
  if (status == AVAuthorizationStatusDenied || status == AVAuthorizationStatusRestricted) return 2;
  return 0;
}

int32_t la_request_screen_recording_permission(void) {
  return CGRequestScreenCaptureAccess() ? 1 : 2;
}

int32_t la_request_microphone_permission(void) {
  dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
  __block BOOL granted = NO;
  [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL accessGranted) {
    granted = accessGranted;
    dispatch_semaphore_signal(semaphore);
  }];
  dispatch_semaphore_wait(semaphore, DISPATCH_TIME_FOREVER);
  return granted ? 1 : 2;
}
