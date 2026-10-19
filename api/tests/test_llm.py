from unittest.mock import Mock, patch

from secondchance.llm import BedrockClaude


def test_bedrock_claude_uses_private_runtime_converse() -> None:
    client = Mock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": "Grounded answer"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 4},
    }

    with patch("boto3.client", return_value=client) as make_client:
        result = BedrockClaude("eu.anthropic.claude-haiku-5-5").complete("system", "question")

    make_client.assert_called_once_with("bedrock-runtime", region_name="eu-central-1")
    client.converse.assert_called_once_with(
        modelId="eu.anthropic.claude-haiku-5-5",
        system=[{"text": "system"}],
        messages=[{"role": "user", "content": [{"text": "question"}]}],
        inferenceConfig={"maxTokens": 8000, "temperature": 0.1},
    )
    assert result.text == "Grounded answer"
    assert result.input_tokens == 12
    assert result.output_tokens == 4
    assert result.refused is False


def test_bedrock_claude_marks_filtered_output_as_refused() -> None:
    client = Mock()
    client.converse.return_value = {
        "output": {"message": {"content": []}},
        "stopReason": "content_filtered",
        "usage": {"inputTokens": 7, "outputTokens": 0},
    }

    with patch("boto3.client", return_value=client):
        result = BedrockClaude("eu.anthropic.claude-haiku-5-5").complete("system", "question")

    assert result.refused is True
    assert result.text == ""
