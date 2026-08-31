# Hey Bunnelby — Custom Neural Wake-Word Training

This directory defines the one-time training path for Bunnelby's production wake phrase:

> **Hey Bunnelby**

The Windows Bunnelby runtime must remain ONNX/CPU-only. Training is deliberately isolated from the laptop because the local Windows environment has previously blocked PyTorch DLLs through Application Control.

## Source pin

Use the 2026 Colab compatibility toolkit at this exact reviewed commit:

- repository: `saintpete/openwakeword-colab-toolkit`
- commit: `2e7379fd0980e83332d637c2f2b7496de48b2b41`

Do not silently train from an unpinned future `main` branch. Re-review before changing this pin.

The toolkit is a compatibility layer around openWakeWord's custom model trainer for current Colab/Python environments. Bunnelby's project-specific configuration is:

- `training/wakeword/hey_bunnelby.yaml`

## Cost constraint

The intended first attempt uses a **free Google Colab T4**. Free GPU availability and uninterrupted runtime are not guaranteed. Do not purchase Colab or another service without an explicit user decision.

If a free session is reclaimed, preserve completed generated assets/checkpoints where the toolkit supports it and retry later rather than silently moving to a paid service.

## Licensing rule

Bunnelby's first-pass training configuration intentionally does **not** use the ACAV100M/openwakeword_features negative feature file.

Reason: that dataset can impose non-commercial restrictions incompatible with a future commercial Bunnelby product. Do not add it to the training set without a separate license review and explicit product decision.

The first pass therefore relies on:

- synthetic positive `hey bunnelby` clips,
- generated adversarial/phonetic negatives,
- hard negative phrases defined in `hey_bunnelby.yaml`,
- room/background augmentation prepared by the training toolkit,
- real-device deployment validation after training.

If false accepts remain too high, add **our own** legally clean negative recordings/features (keyboard, room noise, TV speech, music, ordinary speech, near-homophones) and retrain.

## Training procedure

1. Open Google Colab.
2. Request a T4 GPU runtime. If no GPU is available on the free tier, stop and retry later; do not fall back to hours of local PyTorch training on the Windows laptop.
3. Obtain the pinned toolkit commit above.
4. Use its current Colab notebook/environment setup.
5. Replace the example training YAML with the contents of `hey_bunnelby.yaml`.
6. Confirm before training:
   - `model_name: hey_bunnelby`
   - only `hey bunnelby` is a positive target phrase
   - ACAV feature data is absent
   - hard negatives remain negative labels
7. Run generation, augmentation, and model training.
8. Preserve/export the resulting ONNX artifact(s).
9. Convert an external-data ONNX pair to a single ONNX file if necessary before importing into Bunnelby.
10. Never treat successful export as deployment approval. Run the Bunnelby model validator and live deployment gate first.

## Expected artifact

Canonical runtime filename:

`hey_bunnelby.onnx`

The model must be a standard openWakeWord phrase classifier compatible with the generic openWakeWord melspectrogram and embedding backbone.

## Model acceptance gate

Before production use on the actual Windows laptop:

- local model validation passes,
- ONNX Runtime CPU initialization passes,
- at least 20 real positive utterances are measured,
- recall is >= 80%,
- representative negative-room audio is measured,
- false accepts <= 0.5/hour,
- zero silence triggers in the validation corpus,
- hard negatives such as `hey bunny`, `hey bundle`, `hey bumblebee` do not trigger,
- deterministic debounce prevents multiple activations from one utterance.

If one threshold cannot satisfy both recall and false-accept requirements, the model does **not** ship. Retrain with better data or reconsider the phrase.
