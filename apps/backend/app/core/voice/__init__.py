"""
JARV Backend - Voice

- engine: speech-to-text, text-to-speech, wake-phrase detection on a clip,
  and spoken commands routed through the Command Center (Repair 12e-4c).
- wake_service: the local sherpa-onnx keyword spotter and its model install.
- status_replies: short spoken status phrases.
"""
from .status_replies import SpokenStatusReplies, StatusType

__all__ = ["SpokenStatusReplies", "StatusType"]
