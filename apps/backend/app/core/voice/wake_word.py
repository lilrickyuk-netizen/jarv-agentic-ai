"""
JARV Backend - Wake Word Detection

Detects wake words for hands-free voice command activation.
"""
from typing import Optional, Callable, List
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)


class WakeWordProvider(str, Enum):
    """Available wake word detection providers"""
    PORCUPINE = "porcupine"  # Picovoice Porcupine (offline, low latency)
    SNOWBOY = "snowboy"  # Snowboy (offline, custom wake words)
    PRECISE = "precise"  # Mycroft Precise (offline)


class WakeWordIntegrationRequiredError(Exception):
    """Raised when wake word detection requires external integration"""
    pass


class WakeWordDetector:
    """
    Wake word detector for hands-free voice command activation.

    Supports:
    - Porcupine: Offline, low-latency, multiple built-in wake words
    - Snowboy: Offline, custom wake word training
    - Precise: Offline, Mycroft's wake word engine
    """

    def __init__(
        self,
        provider: WakeWordProvider = WakeWordProvider.PORCUPINE,
        wake_words: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        sensitivity: float = 0.5,
        audio_callback: Optional[Callable] = None,
    ):
        self.provider = provider
        self.wake_words = wake_words or ["jarv"]
        self.api_key = api_key
        self.sensitivity = sensitivity
        self.audio_callback = audio_callback
        self.is_listening = False
        self._validate_configuration()

    def _validate_configuration(self):
        """Validate provider configuration"""
        if self.provider == WakeWordProvider.PORCUPINE and not self.api_key:
            raise WakeWordIntegrationRequiredError(
                "Porcupine wake word detection requires API key. "
                "Install: pip install pvporcupine. "
                "Setup: (1) Sign up at https://console.picovoice.ai/, "
                "(2) Get free API key from console, "
                "(3) Set api_key parameter. "
                "Built-in wake words: porcupine, bumblebee, alexa, computer, jarvis, etc."
            )

        if self.provider == WakeWordProvider.SNOWBOY:
            raise WakeWordIntegrationRequiredError(
                "Snowboy wake word detection requires setup. "
                "Install: pip install snowboy (may require manual build). "
                "Setup: (1) Get pre-trained models from https://github.com/Kitt-AI/snowboy/, "
                "(2) Or train custom wake word at https://snowboy.kitt.ai/, "
                "(3) Download .pmdl model file, "
                "(4) Set model_path in config. "
                "Note: Snowboy is deprecated but still usable for offline detection"
            )

        if self.provider == WakeWordProvider.PRECISE:
            raise WakeWordIntegrationRequiredError(
                "Mycroft Precise wake word detection requires setup. "
                "Install: pip install precise-runner. "
                "(1) Download pre-trained model or train custom model, "
                "(2) Get models from https://github.com/MycroftAI/precise-data/, "
                "(3) Set model_path in config. "
                "Precise provides good accuracy for custom wake words"
            )

    async def start_listening(self):
        """
        Start listening for wake words.

        Continuously monitors audio input and triggers callback when wake word is detected.
        """
        if self.is_listening:
            logger.warning("Wake word detector is already listening")
            return

        self.is_listening = True
        logger.info(f"Started listening for wake words: {', '.join(self.wake_words)}")

        try:
            await self._listen_loop()
        except Exception as e:
            logger.error(f"Error in wake word detection loop: {e}")
            self.is_listening = False

    async def stop_listening(self):
        """Stop listening for wake words"""
        self.is_listening = False
        logger.info("Stopped listening for wake words")

    async def _listen_loop(self):
        """Main listen loop for wake word detection"""
        if self.provider == WakeWordProvider.PORCUPINE:
            await self._listen_porcupine()
        elif self.provider == WakeWordProvider.SNOWBOY:
            await self._listen_snowboy()
        elif self.provider == WakeWordProvider.PRECISE:
            await self._listen_precise()

    async def _listen_porcupine(self):
        """Listen using Porcupine"""
        raise WakeWordIntegrationRequiredError(
            "Porcupine listening requires full integration. "
            "After installing pvporcupine and setting API key: "
            "(1) Initialize Porcupine with keywords, "
            "(2) Set up audio stream (PyAudio or sounddevice), "
            "(3) Process audio frames in real-time, "
            "(4) Call callback when wake word detected"
        )

    async def _listen_snowboy(self):
        """Listen using Snowboy"""
        raise WakeWordIntegrationRequiredError(
            "Snowboy listening requires full integration. "
            "After installing snowboy and setting up models: "
            "(1) Initialize Snowboy detector with .pmdl model, "
            "(2) Set up audio stream, "
            "(3) Process audio frames, "
            "(4) Call callback when wake word detected"
        )

    async def _listen_precise(self):
        """Listen using Mycroft Precise"""
        raise WakeWordIntegrationRequiredError(
            "Precise listening requires full integration. "
            "After installing precise-runner and setting up models: "
            "(1) Initialize Precise engine with model, "
            "(2) Set up audio stream, "
            "(3) Process audio frames, "
            "(4) Call callback when wake word detected"
        )

    def get_supported_wake_words(self) -> List[str]:
        """Get list of supported wake words for the current provider"""
        if self.provider == WakeWordProvider.PORCUPINE:
            return [
                "porcupine",
                "picovoice",
                "bumblebee",
                "alexa",
                "computer",
                "jarvis",
                "terminator",
                "grasshopper",
            ]
        elif self.provider == WakeWordProvider.SNOWBOY:
            return ["custom"]  # Custom wake words via training
        elif self.provider == WakeWordProvider.PRECISE:
            return ["hey-mycroft", "custom"]  # Pre-trained or custom
        return []

    def get_provider_info(self) -> dict:
        """Get information about the current provider"""
        return {
            "provider": self.provider.value,
            "configured": self.api_key is not None,
            "wake_words": self.wake_words,
            "sensitivity": self.sensitivity,
            "supported_wake_words": self.get_supported_wake_words(),
            "is_listening": self.is_listening,
            "requires_api_key": self.provider == WakeWordProvider.PORCUPINE,
            "requires_model": self.provider in [WakeWordProvider.SNOWBOY, WakeWordProvider.PRECISE],
        }
