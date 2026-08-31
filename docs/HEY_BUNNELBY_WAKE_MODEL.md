# Hey Bunnelby — Neural Wake-Word Contract

Status: **LOCKED for Part 10 custom neural wake-word work**

## Canonical wake phrase

- Primary phrase: `Hey Bunnelby`
- Canonical normalized text: `hey bunnelby`
- Runtime model filename: `hey_bunnelby.onnx`
- Runtime sample rate: `16000 Hz`
- Runtime channel layout: mono
- Runtime PCM format: signed 16-bit integer
- Runtime inference: CPU / ONNX Runtime only

The former experimental wake-word paths are not production candidates:

- sherpa-onnx GigaSpeech custom keyword spotting: **REJECTED** after repeated live false-negative tests and acoustic diagnostics.
- personalized MFCC + DTW template matching: **REJECTED** after clean confirmed enrollment still failed class separation.

Do not re-enable either path as a production fallback without new measured evidence.

## Why `Hey Bunnelby`

`Hey Bunnelby` provides more acoustic context than the single word `Bunnelby`, which should improve phrase discrimination and reduce accidental activation risk. The final decision remains measurement-driven: if the trained model cannot satisfy the deployment gate below, it must not ship.

## Training target

Use a proper phrase-specific neural classifier compatible with the openWakeWord ONNX inference pipeline:

```text
16 kHz mono PCM
  -> melspectrogram.onnx
  -> embedding_model.onnx
  -> hey_bunnelby.onnx
  -> probability
  -> deterministic threshold/debounce policy
```

Training may use PyTorch in a separate one-time environment, but the Bunnelby Windows runtime must not require PyTorch.

## Positive phrase set

Train primarily on:

- `hey bunnelby`

Do not silently broaden activation to `bunnelby` alone. A future alternate phrase requires separate evaluation and an explicit product decision.

## Hard-negative phrase set

At minimum include acoustically/confusably related phrases such as:

- `hey bunny`
- `hey bundle`
- `hey bumblebee`
- `hey buddy`
- `hey ben`
- `hey billy`
- `bunny`
- `bundle`
- `bumblebee`
- `bunnelby`
- `hey bunnel bee`
- `hey bunelby`

Also include ordinary speech, keyboard noise, TV/video speech, music, room noise, and silence during validation/training as appropriate.

## Security and privacy invariants

- Wake inference runs locally.
- No continuous microphone stream is uploaded to a cloud service.
- Runtime model loading is from an application-controlled local path.
- Model assets must be integrity-validated before production use.
- ONNX Runtime CPU provider only for the always-on path unless a later explicit benchmark and security review approves another provider.
- No pickle-based model loading.
- No shell execution for wake-word runtime.
- A wake detection is an input event only; it does not authorize privileged tools or external writes.

## Deployment gate

A trained model is not accepted because it merely triggers once. Validate on the actual Windows laptop and microphone.

Minimum initial gate:

- positive recall: **>= 80%** on real `Hey Bunnelby` recordings
- false accepts: **<= 0.5 per hour** on representative ordinary room audio
- silence false accepts: **0** in the validation corpus
- hard-negative phrases above must not trigger in the validation set
- repeated wake events from one utterance must be prevented by deterministic debounce/cooldown

If the model cannot satisfy both recall and false-accept requirements at one threshold, do not lower the bar to force deployment. Retrain or change the wake phrase.

## Runtime handoff

After a validated detection:

```text
WAKE_ARMED
  -> HEY_BUNNELBY_DETECTED
  -> cooldown / wake stream reset
  -> COMMAND_LISTENING
  -> Silero VAD utterance aggregation
  -> faster-whisper STT
  -> /chat / tool orchestration
  -> TTS
  -> WAKE_ARMED
```

Wake-word audio must not be included in command STT audio.

## Part 10 completion condition for wake word

The wake-word slice is complete only when all of the following are true:

1. `hey_bunnelby.onnx` exists and passes local integrity/model-shape validation.
2. Windows CPU inference initializes without PyTorch.
3. Real microphone positive trials meet the recall gate.
4. Representative negative-audio testing meets the false-accept gate.
5. Wake-to-command handoff is verified so the wake phrase is excluded from STT.
6. Security and regression tests pass.
