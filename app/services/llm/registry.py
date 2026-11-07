from app.services.llm.openai_responses_adapter import OpenAIResponsesAdapter


def build_openai_responses_adapter(*, client):
    return OpenAIResponsesAdapter(client)


ADAPTER_FACTORIES = {
    ("openai", "responses"): build_openai_responses_adapter,
}


def resolve_adapter(*, provider: str, transport: str, client):
    factory = ADAPTER_FACTORIES.get((provider, transport))

    if factory is None:
        raise ValueError(
            f"Unsupported LLM provider/transport: {provider}/{transport}"
        )

    return factory(client=client)