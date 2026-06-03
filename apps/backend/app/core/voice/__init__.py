"""
JARV Backend - Voice Command System

Complete voice command system with:
- Speech-to-Text (STT) for voice input
- Text-to-Speech (TTS) for voice output
- Wake word detection for hands-free activation
- Voice command routing to Orchestrator
- Spoken status replies for feedback
"""
from .stt import STTAdapter, STTProvider, STTIntegrationRequiredError
from .tts import TTSAdapter, TTSProvider, TTSIntegrationRequiredError
from .wake_word import WakeWordDetector, WakeWordProvider, WakeWordIntegrationRequiredError
from .router import VoiceCommandRouter
from .status_replies import SpokenStatusReplies, StatusType

__all__ = [
    # STT
    "STTAdapter",
    "STTProvider",
    "STTIntegrationRequiredError",
    # TTS
    "TTSAdapter",
    "TTSProvider",
    "TTSIntegrationRequiredError",
    # Wake Word
    "WakeWordDetector",
    "WakeWordProvider",
    "WakeWordIntegrationRequiredError",
    # Router
    "VoiceCommandRouter",
    # Status Replies
    "SpokenStatusReplies",
    "StatusType",
]
