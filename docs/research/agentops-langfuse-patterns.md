# AgentOps & Langfuse SDK Patterns — Research Summary

**Date:** 2026-03-27
**Purpose:** Patterns to adopt for PixelPulse adapter layer

## Key Patterns to Adopt

### 1. CommonInstrumentor + WrapConfig (from AgentOps)

```python
@dataclass
class WrapConfig:
    trace_name: str       # OTEL span name
    package: str          # e.g. "openai.resources.chat.completions"
    class_name: str       # e.g. "Completions"
    method_name: str      # e.g. "create"
    handler: Callable     # (args, kwargs, return_value) -> AttributeMap
    is_async: bool = False
```

Base class owns lifecycle: init tracer → wrap methods → custom_wrap hook.
Subclasses just declare WrapConfig lists + override 3 hooks.

### 2. Auto-Detection via Import Hook (from AgentOps)

Replace `builtins.__import__` to detect framework installs at import time.
Critical safety: `_is_installed_package()` validates against `site.getsitepackages()`.
Priority rule: agentic library wins over LLM provider (prevents double-counting).

### 3. @observe() Decorator (from Langfuse)

```python
@observe(as_type="agent")
async def my_agent(input):
    result = await llm.complete(input)
    return result
```

Dual-mode (with/without parens). Auto-detects async/sync/generator.
Context propagation via `contextvars.copy_context()`.

### 4. Version Compatibility

- **WrapConfig with min/max version**: `OpenAiDefinition(method="parse", min_version="1.50.0")`
- **Runtime branch**: `if not is_openai_v1(): use V0Instrumentor`
- Pattern A for minor surface changes, Pattern B for major breaks

### 5. Token Normalization (from AgentOps)

Multi-path extraction order:
1. `response.usage.{prompt,completion,total}_tokens` (OpenAI)
2. `response.usage.{input,output}_tokens` (Anthropic)
3. `response.usage_metadata.{prompt,candidates}_token_count` (Google)
4. `response.token_usage` as string (CrewAI — needs parser)

### 6. Framework Integration Strategy

| Framework | Best Approach |
|-----------|--------------|
| OpenAI Agents SDK | Native tracing: `agents.set_trace_processors([processor])` |
| LangChain/LangGraph | Callback handler interface |
| CrewAI | Monkey-patch `Crew.kickoff`, `Agent.execute_task` |
| AutoGen | Event hooks / monkey-patch |
| Claude Code | HTTP hooks via `.claude/settings.json` |
| User code | `@observe()` decorator |

### 7. Claude Code Integration

- Hooks are the ONLY integration surface (no Python SDK)
- HTTP hooks → PixelPulse local endpoint for PreToolUse/PostToolUse
- `transcript_path` (.jsonl) available in every hook event
- `SubagentStop.agent_transcript_path` for complete subagent traces
- Tool timing: timestamp before PreToolUse, timestamp after PostToolUse

## Sources

- AgentOps: github.com/AgentOps-AI/agentops (CommonInstrumentor, WrapConfig, TokenUsageExtractor)
- Langfuse: github.com/langfuse/langfuse-python (@observe, OpenAI wrapper, BatchSpanProcessor)
- Claude Code Hooks: code.claude.com/docs/en/hooks
