# Third-Party Licenses

Vestige is MIT-licensed. It depends on the following third-party packages and services.

---

## Libraries with notable licenses

### Coqui-TTS — Mozilla Public License 2.0 (MPL-2.0)
Local XTTS-v2 TTS fallback engine.
Source: https://github.com/idiap/coqui-ai-TTS
License: https://www.mozilla.org/en-US/MPL/2.0/

MPL-2.0 is a file-level weak copyleft license. Vestige uses Coqui-TTS as an
unmodified library dependency. No Vestige source files incorporate or are
derived from Coqui-TTS source code. If you fork Vestige and modify Coqui-TTS
internals directly, those modified files must be released under MPL-2.0.

---

## Libraries under permissive licenses

The packages below are used under MIT, BSD, or Apache 2.0 licenses.
Full license texts are available from their respective repositories or
via `pip show <package>` / `npm info <package> license`.

### Backend (Python)

| Package | License | Repository |
|---|---|---|
| FastAPI | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | BSD 3-Clause | https://github.com/encode/uvicorn |
| SQLAlchemy | MIT | https://github.com/sqlalchemy/sqlalchemy |
| Alembic | MIT | https://github.com/sqlalchemy/alembic |
| aiosqlite | MIT | https://github.com/omnilib/aiosqlite |
| Pydantic / pydantic-settings | MIT | https://github.com/pydantic/pydantic |
| Anthropic Python SDK | MIT | https://github.com/anthropics/anthropic-sdk-python |
| OpenAI Python SDK | MIT | https://github.com/openai/openai-python |
| Deepgram Python SDK | MIT | https://github.com/deepgram/deepgram-python-sdk |
| ElevenLabs Python SDK | MIT | https://github.com/elevenlabs/elevenlabs-python |
| edge-tts | MIT | https://github.com/rany2/edge-tts |
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| silero-vad | MIT | https://github.com/snakers4/silero-vad |
| HuggingFace Transformers | Apache 2.0 | https://github.com/huggingface/transformers |
| sentence-transformers | Apache 2.0 | https://github.com/UKPLab/sentence-transformers |
| PyTorch | BSD 3-Clause | https://github.com/pytorch/pytorch |
| NumPy | BSD 3-Clause | https://github.com/numpy/numpy |
| SciPy | BSD 3-Clause | https://github.com/scipy/scipy |
| sounddevice | MIT | https://github.com/spatialaudio/python-sounddevice |
| imageio-ffmpeg | BSD 2-Clause | https://github.com/imageio/imageio-ffmpeg |
| structlog | MIT / Apache 2.0 | https://github.com/hynek/structlog |
| python-dotenv | BSD 3-Clause | https://github.com/theskumar/python-dotenv |
| PyYAML | MIT | https://github.com/yaml/pyyaml |
| OpenTelemetry SDK | Apache 2.0 | https://github.com/open-telemetry/opentelemetry-python |
| arize-phoenix-otel | Apache 2.0 | https://github.com/Arize-ai/phoenix |
| pytest / pytest-asyncio | MIT | https://github.com/pytest-dev/pytest |
| httpx | BSD 3-Clause | https://github.com/encode/httpx |

### Frontend (Node.js)

| Package | License | Repository |
|---|---|---|
| React / React DOM | MIT | https://github.com/facebook/react |
| React Router | MIT | https://github.com/remix-run/react-router |
| Zustand | MIT | https://github.com/pmndrs/zustand |
| TanStack Query | MIT | https://github.com/TanStack/query |
| Vite | MIT | https://github.com/vitejs/vite |
| ESLint | MIT | https://github.com/eslint/eslint |
| Vitest | MIT | https://github.com/vitest-dev/vitest |
| Testing Library | MIT | https://github.com/testing-library/react-testing-library |

---

## External API services

The following services are called at runtime. They are not distributed with
Vestige; users must supply their own API keys and agree to each provider's
terms of service.

| Service | Purpose | Terms |
|---|---|---|
| Anthropic (Claude) | Emotional/story LLM responses | https://www.anthropic.com/legal/usage-policy |
| OpenAI (GPT-4o) | Fast LLM responses, emotion tag generation | https://openai.com/policies/usage-policies |
| Deepgram | Streaming speech-to-text (nova-3) | https://deepgram.com/legal/terms-of-service |
| ElevenLabs | Streaming text-to-speech | https://elevenlabs.io/terms-of-service |

**Note on edge-tts:** The `edge-tts` package (MIT) is used as a no-key TTS
fallback. It communicates with Microsoft's Azure Neural TTS endpoint via an
unofficial, undocumented API. Microsoft has not authorised this use. The
fallback may stop working if Microsoft changes their endpoint, and users
exercise it at their own discretion.
