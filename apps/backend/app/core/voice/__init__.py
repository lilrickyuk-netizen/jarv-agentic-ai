"""
JARV Backend - Voice

- engine: speech-to-text, text-to-speech, wake-phrase detection on a clip,
  and spoken commands routed through the Command Center (Repair 12e-4c).
- live: live spoken conversation through OpenAI Realtime (session secrets and the actions JARV
  takes during a conversation).
- wake_service: the local sherpa-onnx keyword spotter and its model install.
- status_replies: short spoken status phrases.
"""
from .status_replies import SpokenStatusReplies, StatusType

__all__ = ["SpokenStatusReplies", "StatusType"]
