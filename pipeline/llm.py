"""Appel au modèle de langue pour l'étape édito, quel que soit le fournisseur.

Fournisseur choisi par --llm ou la variable LLM_PROVIDER :
  claude-cli  le CLI `claude -p` (abonnement Claude, aucune clé)            modèle par défaut : sonnet
  anthropic   API Anthropic, clé ANTHROPIC_API_KEY                          modèle par défaut : claude-sonnet-5-5
  gemini      API Google Gemini, clé GEMINI_API_KEY                         modèle par défaut : gemini-2.5-pro
  openai      API OpenAI, clé OPENAI_API_KEY ; OPENAI_BASE_URL pour tout
              service compatible (Ollama, OpenRouter, Mistral, Groq...)     modèle par défaut : gpt-4.1

Le modèle se change avec --model ou LLM_MODEL. La réponse doit contenir un objet JSON ;
on renvoie le premier objet trouvé dans le texte.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

PROVIDERS = ("claude-cli", "anthropic", "gemini", "openai")
DEFAULT_MODELS = {
    "claude-cli": "sonnet",
    "anthropic": "claude-sonnet-5-5",
    "gemini": "gemini-2.5-pro",
    "openai": "gpt-4.1",
}
TIMEOUT = 600
MAX_TOKENS = 16000


def resolve(provider: str | None, model: str | None) -> tuple[str, str]:
    provider = (provider or os.environ.get("LLM_PROVIDER") or "claude-cli").lower()
    if provider not in PROVIDERS:
        raise SystemExit(f"Fournisseur inconnu « {provider} » ; choix : {', '.join(PROVIDERS)}")
    return provider, model or os.environ.get("LLM_MODEL") or DEFAULT_MODELS[provider]


def _key(name: str, provider: str) -> str:
    key = os.environ.get(name, "")
    if not key:
        raise SystemExit(f"{name} manquante pour le fournisseur {provider} (voir .env.example)")
    return key


def _post(url: str, headers: dict, payload: dict) -> dict:
    import requests

    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise SystemExit(f"{url} a répondu {r.status_code} :\n{r.text[:800]}")
    return r.json()


def _claude_cli(prompt: str, model: str) -> str:
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)  # autorise l'appel depuis une session Claude Code
    r = subprocess.run(["claude", "-p", "--model", model, "--output-format", "text"],
                       input=prompt, capture_output=True, text=True, env=env, timeout=TIMEOUT)
    if r.returncode != 0:
        raise SystemExit(f"claude -p a échoué :\n{r.stderr}")
    return r.stdout


def _anthropic(prompt: str, model: str) -> str:
    data = _post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": _key("ANTHROPIC_API_KEY", "anthropic"), "anthropic-version": "2023-06-01"},
                 {"model": model, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": prompt}]})
    return "".join(b.get("text", "") for b in data.get("content", []))


def _gemini(prompt: str, model: str) -> str:
    data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                 {"x-goog-api-key": _key("GEMINI_API_KEY", "gemini")},
                 {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": MAX_TOKENS}})
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _openai(prompt: str, model: str) -> str:
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    # un service local (Ollama) n'exige pas de clé
    key = os.environ.get("OPENAI_API_KEY") or ("local" if "localhost" in base or "127.0.0.1" in base else _key("OPENAI_API_KEY", "openai"))
    data = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {key}"},
                 {"model": model, "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}})
    return data["choices"][0]["message"]["content"]


CALLS = {"claude-cli": _claude_cli, "anthropic": _anthropic, "gemini": _gemini, "openai": _openai}


def complete_json(prompt: str, provider: str | None = None, model: str | None = None, log=print) -> dict:
    """Envoie le prompt au fournisseur choisi et renvoie l'objet JSON de la réponse."""
    provider, model = resolve(provider, model)
    log(f"$ {provider} {model} (édito)")
    raw = CALLS[provider](prompt, model).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise SystemExit(f"Réponse sans JSON ({provider}) :\n{raw[:800]}")
    return json.loads(m.group(0))
