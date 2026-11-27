from __future__ import annotations

from job_agent.llm.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekCompatibleProvider(OpenAICompatibleProvider):
    """DeepSeek JSON-mode transport; schema validation remains in LLMHarness."""

    provider_name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com/v1",
        timeout_s: float = 30.0,
        thinking: str | None = None,
    ) -> None:
        if base_url.rstrip("/") not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
            raise ValueError("deepseek_endpoint_not_allowlisted")
        if model not in {"deepseek-chat", "deepseek-reasoner", "deepseek-flash", "deepseek-v4-pro"}:
            raise ValueError("deepseek_model_not_allowlisted")
        if not api_key:
            raise ValueError("deepseek_credential_missing")
        if thinking not in {None, "disabled", "enabled"}:
            raise ValueError("deepseek_thinking_not_allowlisted")
        self.thinking = thinking
        super().__init__(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_s=timeout_s,
            response_format_mode="json_object",
        )

    def _extra_request_fields(self) -> dict:
        return {"thinking": {"type": self.thinking}} if self.thinking is not None else {}
