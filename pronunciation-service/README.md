# pronunciation-service

Standalone English passage read-aloud pronunciation assessment HTTP service.
No HomeAgent Asset / Brain / Runtime imports. Mirrors `ocr-service` layout.

## Endpoints

- `GET /health` — liveness + engine status (whisper model, device, mfa/gopt flags).
- `POST /v1/assess` — `multipart/form-data` with two audio files:
  - field `reference` — standard reading audio
  - field `student` — child's read-along recording

  Returns the fixed response JSON (doc section 6):

  ```json
  {
    "overall_score": 84,
    "accuracy_score": 87,
    "fluency_score": 79,
    "completeness_score": 92,
    "prosody_score": 81,
    "duration": {"reference": 61.4, "student": 78.2},
    "problem_words": [{"word": "environment", "score": 58, "start": 31.2, "end": 32.8, "phoneme_errors": [], "reason": "low_confidence"}],
    "problem_phonemes": [],
    "fluency": {"speech_rate": 0, "pause_count": 0, "long_pause_count": 0, "repetition_count": 0},
    "raw_alignment": [],
    "feedback_text": "本次朗读 84 分。需要注意的词：environment。"
  }
  ```

## Pipeline (V1: WhisperX baseline)

1. WhisperX ASR + VAD + word/phoneme alignment on **both** audios.
2. Reference text taken from the reference audio's ASR (no separate text input).
3. Levenshtein alignment of student words vs reference words — tolerates missing /
   extra / repeated words, different speech rate / pauses (doc section 5).
4. Scoring from WhisperX alignment features:
   - accuracy: per-word match × alignment confidence; missed words score 0.
   - completeness: fraction of reference words the student read.
   - fluency: pause count, long pauses, speech rate, repetitions.
   - prosody: speech-rate ratio vs reference (coarse; learned model is a later upgrade).
5. Aggregation: phoneme → word → passage; problem words/phonemes with time offsets.

No model training in V1; pretrained WhisperX only.

## Upgrade stages (optional, loaded only when configured)

- **MFA** (Montreal Forced Aligner): finer reference phoneme alignment. Enable by
  installing `montreal_forced_aligner` or setting `MFA_BIN` to the `mfa` executable.
  Hook: `engine.mfa_reference_phonemes`.
- **GOPT** (Goodness Of Pronunciation Transformer): learned pronunciation scoring.
  Enable by setting `GOPT_MODEL_DIR` to the pretrained model directory.
  Hook: `engine.gopt_score`.

Both hooks raise `PronunciationEngineError` until their integration is filled in;
the WhisperX baseline keeps the service real and runnable without them.

## Run locally

```bash
python3 -m venv pyenv
./pyenv/bin/pip install -r requirements.txt
./run.sh
```

First run downloads the Whisper model into `$HF_HOME` (default `./hf-cache`).

## Run in Docker

```bash
docker compose up -d --build
```

Bind loopback only (`127.0.0.1:9190`); Mac Edge on the same host calls it.

## Test

```bash
curl -s http://127.0.0.1:9190/health
curl -s -F reference=@ref.wav -F student=@stu.wav http://127.0.0.1:9190/v1/assess
```
