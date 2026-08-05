"""
LLM Provider Service.
=====================
Abstraction layer for communicating with the underlying Large Language Model.
This service is kept simple and single-purpose — it handles network calls,
enforces JSON mode, and handles basic error wrapping.
"""

import logging
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

class LLMProviderError(Exception):
    """Base class for exceptions raised by the LLM Provider."""
    pass

class LLMTimeoutError(LLMProviderError):
    """Raised when the LLM API call times out."""
    pass

class LLMProvider:
    def __init__(self, api_key: str, model_name: str = "llama-3.1-8b-instant", timeout: int = 30):
        """
        Initialize the LLM provider.
        
        Args:
            api_key: The Groq API key (passed down from Django settings).
            model_name: The Groq model to use.
            timeout: Network timeout in seconds.
        """
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        
        # Max retries = 0 because the Orchestrator layer owns retry logic
        self.client = ChatGroq(
            api_key=api_key,
            model_name=model_name,
            timeout=timeout,
            max_retries=0, 
        ).bind(response_format={"type": "json_object"})

    def request_template(self, system_prompt: str, user_prompt: str) -> str:
        """
        Calls the LLM API requesting JSON output.
        
        Args:
            system_prompt: The system instructions.
            user_prompt: The user prompt.
            
        Returns:
            The raw response string containing JSON (e.g., '{"summaryTemplate": "..."}').
            
        Raises:
            LLMTimeoutError: If the request times out.
            LLMProviderError: For other API or network errors.
        """
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = self.client.invoke(messages)
            # Content should be a string containing JSON
            if isinstance(response.content, str):
                return response.content
            # In some cases, LangChain might parse it if bind doesn't return raw content
            # but usually content is a string.
            import json
            return json.dumps(response.content)
        except TimeoutError as e:
            logger.error(f"LLM API request timed out after {self.timeout}s: {e}")
            raise LLMTimeoutError(f"LLM request timed out: {e}") from e
        except Exception as e:
            # Check if it's an httpx Timeout
            error_str = str(e).lower()
            if "timeout" in error_str:
                logger.error(f"LLM API request timed out after {self.timeout}s: {e}")
                raise LLMTimeoutError(f"LLM request timed out: {e}") from e
                
            logger.error(f"LLM API request failed: {e}")
            raise LLMProviderError(f"LLM request failed: {e}") from e
