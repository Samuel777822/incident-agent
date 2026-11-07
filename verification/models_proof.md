# Model Routing, Live Catalogue & Fallback Proof (Proof E)

## 1. Live Provider Catalogue Check (`https://openrouter.ai/api/v1/models`)
- Live OpenRouter models fetched: **460**
- Environment API keys present on host (values never read/printed): `{"OPENROUTER_API_KEY": false, "ANTHROPIC_API_KEY": false, "GROQ_API_KEY": false, "OPENAI_API_KEY": false, "GEMINI_API_KEY": false}`

| Tier | Direct Model | OpenRouter Model | In Live OpenRouter Catalogue? | Verified Catalogue Replacement |
|---|---|---|---|---|
| `groq` (Low effort) | `openai/gpt-oss-120b` | `openai/gpt-oss-120b:free` | `False` | `openai/gpt-oss-120b` |
| `haiku` (Normal) | `claude-haiku-5-5` | `anthropic/claude-haiku-5.5` | `True` | `-` |
| `sonnet` (High) | `claude-sonnet-5-5` | `anthropic/claude-sonnet-5.5` | `True` | `-` |
| `opus` (Extra) | `claude-opus-5-5` | `anthropic/claude-opus-5.5` | `True` | `-` |

## 2. Router Decision Progression (`fixengine/router.py`)

| Step | Chosen Tier | Mode Label | Forced? | Reason |
|---|---|---|---|---|
| `initial_bug_try_1` | `groq` | Low effort | `True` | free first: try 1 of 3 |
| `after_3_free_tries_haiku_floor_1` | `haiku` | Normal | `True` | Haiku floor: 0 of 2 tries done |
| `haiku_floor_2` | `haiku` | Normal | `True` | Haiku floor: 1 of 2 tries done |
| `haiku_unusable_twice_waives_floor` | `sonnet` | High | `False` | lowest expected cost: about Rs 7.24 |
| `after_haiku_floor_escalate_sonnet` | `sonnet` | High | `False` | lowest expected cost: about Rs 13.74 |
| `drop_back_to_haiku_with_strong_diag` | `haiku` | Normal | `True` | drop back to Haiku with the stronger model's diagnosis |
| `escalate_to_opus_when_sonnet_exhausted` | `opus` | Extra | `False` | lowest expected cost: about Rs 19.72 |

## 3. Adapter Request Formatting & Response Normalization

| Provider | Tier | Model ID | Prompt Caching Header/Block | Normalized Tokens (in / out / cache) | Finish |
|---|---|---|---|---|---|
| `openrouter` | `haiku` | `anthropic/claude-haiku-5.5` | `True` | `4200 / 180 / 3000` | `stop` |
| `anthropic` | `sonnet` | `claude-sonnet-5-5` | `True` | `3500 / 220 / 2000` | `end_turn` |

## 4. Fallback & Simulated Model-Not-Found Replacement Proofs

| Scenario | Provider | Models Attempted in Order | Final Model Used | Normalized Output |
|---|---|---|---|---|
| Groq HTTP 429 rate limit -> automatic fallback model | `groq` | `openai/gpt-oss-120b -> openai/gpt-oss-20b` | `openai/gpt-oss-20b` | `{"diagnosis":"handled by fallback","cannot_determine":false,"edits":[]}` |
| OpenRouter HTTP 404 on unavailable :free model -> live catalogue lookup -> verified replacement retry | `openrouter` | `openai/gpt-oss-120b:free -> openai/gpt-oss-120b` | `openai/gpt-oss-120b` | `{"diagnosis":"recovered via live OpenRouter catalogue","cannot_determine":false,"edits":[]}` |
| OpenRouter HTTP 404 on retired Claude model -> live catalogue verification -> anthropic/claude-sonnet-5.5 retry | `openrouter` | `anthropic/claude-3-5-sonnet-20241022 -> anthropic/claude-sonnet-5.5` | `anthropic/claude-sonnet-5.5` | `{"diagnosis":"claude replacement ok","cannot_determine":false,"edits":[]}` |
| Anthropic HTTP 404 not_found_error -> live catalogue verification -> claude-haiku-5-5 retry | `anthropic` | `claude-3-haiku-20240307 -> claude-haiku-5-5` | `claude-haiku-5-5` | `{"diagnosis":"anthropic replacement ok","cannot_determine":false,"edits":[]}` |
