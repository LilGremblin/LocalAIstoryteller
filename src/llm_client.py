"""
Async LLM client — works with any OpenAI-compatible local backend.
Supports streaming via async generators.
"""

import json
import httpx
from src import config


async def stream_chat_completion(
    messages: list[dict],
    sampling: dict | None = None,
    endpoint: str | None = None,
) -> any:
    """
    Stream a chat completion from the local LLM backend.
    Yields token strings as they arrive.
    """
    endpoint = endpoint or config.get("LLM_ENDPOINT", config.LLM_ENDPOINT)
    url = f"{endpoint}/chat/completions"

    params = dict(config.DEFAULT_SAMPLING)
    if sampling:
        params.update(sampling)

    body = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": params.get("temperature", 0.95),
        "max_tokens": params.get("max_tokens", 800),
    }

    # Add optional params that not all backends support
    if "min_p" in params and params["min_p"] > 0:
        body["min_p"] = params["min_p"]
    if "top_p" in params and params["top_p"] < 1.0:
        body["top_p"] = params["top_p"]
    if "top_k" in params and params["top_k"] > 0:
        body["top_k"] = params["top_k"]
    if "repetition_penalty" in params and params["repetition_penalty"] != 1.0:
        body["repetition_penalty"] = params["repetition_penalty"]

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", url, json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def chat_completion(
    messages: list[dict],
    sampling: dict | None = None,
    endpoint: str | None = None,
) -> str:
    """
    Non-streaming chat completion. Used for summarization and other utility calls.
    Returns the full response text.
    """
    endpoint = endpoint or config.get("LLM_ENDPOINT", config.LLM_ENDPOINT)
    url = f"{endpoint}/chat/completions"

    params = dict(config.DEFAULT_SAMPLING)
    if sampling:
        params.update(sampling)

    body = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": params.get("temperature", 0.7),
        "max_tokens": params.get("max_tokens", 600),
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, json=body)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def check_connection(endpoint: str | None = None) -> dict:
    """Check if the LLM backend is reachable. Auto-discovers common ports."""
    endpoint = endpoint or config.get("LLM_ENDPOINT", config.LLM_ENDPOINT)

    # Try the configured endpoint first
    result = await _try_endpoint(endpoint)
    if result["connected"]:
        return result

    # Auto-discover: try common LLM backend ports
    common_endpoints = [
        "http://localhost:5001/v1",   # KoboldCPP default
        "http://localhost:5000/v1",   # KoboldCPP alt
        "http://localhost:1234/v1",   # LM Studio default
        "http://localhost:11434/v1",  # Ollama default
        "http://localhost:8080/v1",   # llama.cpp server
    ]

    for try_endpoint in common_endpoints:
        if try_endpoint == endpoint:
            continue  # Already tried
        result = await _try_endpoint(try_endpoint)
        if result["connected"]:
            # Auto-save the discovered endpoint
            config.save_user_config({
                **config.load_user_config(),
                "LLM_ENDPOINT": try_endpoint,
            })
            result["auto_discovered"] = try_endpoint
            return result

    return {"connected": False, "model": None}


async def _try_endpoint(endpoint: str) -> dict:
    """Try connecting to a single endpoint."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            # Try /v1/models (OpenAI-compatible)
            resp = await client.get(f"{endpoint}/models")
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                model_name = models[0]["id"] if models else "unknown"
                return {"connected": True, "model": model_name}
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            # Fallback: KoboldCPP native API
            base = endpoint.replace("/v1", "")
            resp = await client.get(f"{base}/api/v1/model")
            if resp.status_code == 200:
                data = resp.json()
                return {"connected": True, "model": data.get("result", "unknown")}
    except Exception:
        pass

    return {"connected": False, "model": None}

