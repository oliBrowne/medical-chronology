"""Model clients. Agents depend on ``base.ChatClient``, never on a backend.

- ``ollama``: local dev on synthetic pages.
- ``fake``: scripted replies for tests, so CI needs no keys or network.
- ``jev``: TypeSafe's typed-decision model. It answers choice questions and
  does not run a tool-calling chat, so stages call it directly instead of
  through ``agents.loop``.
"""
