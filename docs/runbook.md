# Runbook

Operational notes for running the Chief-of-Staff Notes Assistant. Newest concerns
at the top.

## Model serving — make the local backbone reliable (P0-A)

The agent is only as reliable as the local model behind the OpenAI-compatible
endpoint. Three serving settings prevent the documented weak-model footguns. The
launcher soft-probes the endpoint at startup and **warns** (never aborts) if a
structured-output smoke test does not return valid JSON.

### 1. Context window — `num_ctx ≥ 16384`

Ollama defaults the context window to **4096 even for models that support far
more**, which silently truncates tool definitions and breaks tool calling — it
looks like "the model can't use tools" when it is a config problem. Set it
explicitly.

- **Ollama Modelfile:**
  ```
  FROM qwen3:30b-a3b
  PARAMETER num_ctx 16384
  ```
  then `ollama create <name> -f Modelfile`. (Or raise the server default.)
- The `num_ctx` value cannot be read back through the OpenAI-compatible API, so
  the launcher probe does **not** check it — verify it yourself here.

### 2. Structured output — keep Qwen3 "thinking" enabled

Qwen3 served with `enable_thinking=False` **and** guided JSON produces invalid
output — stray braces, fenced ```` ``` ````, or prose instead of JSON
(vLLM #18819). Since the propose→confirm ingest depends on a valid JSON proposal,
keep thinking **on** at the serving layer (use `/no_think` in the prompt only if
you want to suppress *visible* reasoning while leaving thinking enabled). The
launcher's structured-output probe is what catches a regression here.

### 3. Grammar-constrained decoding for the proposal (vLLM/SGLang)

When serving via vLLM/SGLang/TensorRT-LLM, enable **XGrammar** guided decoding so
the `present_propose` tool-call arguments are guaranteed structurally valid. Apply
it CRANE-style: let the model **reason in free text first**, and constrain only the
final tool-call span — forcing the structured field before the reasoning measurably
hurts accuracy. On plain Ollama (no guided decoding), the `present_propose` tool's
validate-and-retry loop is the fallback safety net.

### What the launcher checks

`launcher/run.py::_soft_probe_model` reads `(baseURL, model_id)` from
`opencode.json`, posts a tiny "reply with a JSON object" chat completion, and warns
if the reply is not valid JSON. It is warn-only and best-effort (5 s timeout,
fails closed to a warning) — it never blocks launch.

### Latency expectation

A ~30B-A3B MoE needs a resident-in-VRAM fit (≈48 GB card) for sub-10 s turns; on a
16 GB box it spills to CPU and turns take minutes (not daily-usable). This is a
hardware prerequisite, not a software setting.
