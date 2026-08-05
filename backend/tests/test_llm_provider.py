import pytest
from unittest.mock import MagicMock
from core.llm_provider import LLMProvider, LLMTimeoutError, LLMProviderError

@pytest.fixture
def provider():
    return LLMProvider(api_key="test_key", model_name="test_model", timeout=1)

def test_request_template_success(provider):
    provider.client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"summaryTemplate": "Test"}'
    provider.client.invoke.return_value = mock_response
    
    result = provider.request_template("system", "user")
    assert result == '{"summaryTemplate": "Test"}'
    provider.client.invoke.assert_called_once()

def test_request_template_timeout(provider):
    provider.client = MagicMock()
    provider.client.invoke.side_effect = TimeoutError("mock timeout")
    
    with pytest.raises(LLMTimeoutError):
        provider.request_template("system", "user")

def test_request_template_httpx_timeout(provider):
    provider.client = MagicMock()
    provider.client.invoke.side_effect = Exception("A request timeout occurred")
    
    with pytest.raises(LLMTimeoutError):
        provider.request_template("system", "user")

def test_request_template_other_error(provider):
    provider.client = MagicMock()
    provider.client.invoke.side_effect = Exception("API error")
    
    with pytest.raises(LLMProviderError):
        provider.request_template("system", "user")
