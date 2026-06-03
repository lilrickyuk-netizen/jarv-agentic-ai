"""
JARV Backend - Text-to-Speech (TTS) Adapter

Converts text responses to spoken audio output for voice feedback.
"""
from typing import Optional, Dict, Any
from enum import Enum
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class TTSProvider(str, Enum):
    """Available TTS providers"""
    GOOGLE = "google"
    OPENAI = "openai"
    AZURE = "azure"
    AWS_POLLY = "aws_polly"
    ELEVENLABS = "elevenlabs"


class TTSIntegrationRequiredError(Exception):
    """Raised when TTS requires external service integration"""
    pass


class TTSAdapter:
    """
    Text-to-Speech adapter for converting text to audio.

    Supports multiple providers:
    - Google Text-to-Speech (requires API key)
    - OpenAI TTS (requires API key)
    - Azure Speech Services (requires credentials)
    - AWS Polly (requires credentials)
    - ElevenLabs (requires API key, high quality)
    """

    def __init__(
        self,
        provider: TTSProvider = TTSProvider.GOOGLE,
        api_key: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.config = config or {}
        self._validate_configuration()

    def _validate_configuration(self):
        """Validate provider configuration"""
        if self.provider == TTSProvider.GOOGLE and not self.api_key:
            logger.warning("Google TTS requires API key for production use")

        if self.provider == TTSProvider.OPENAI and not self.api_key:
            raise TTSIntegrationRequiredError(
                "OpenAI TTS requires API key. "
                "Get from: https://platform.openai.com/api-keys. "
                "Set: api_key parameter or OPENAI_API_KEY environment variable"
            )

        if self.provider == TTSProvider.AZURE:
            if not self.config.get("subscription_key") or not self.config.get("region"):
                raise TTSIntegrationRequiredError(
                    "Azure Speech Services requires configuration. "
                    "Set: subscription_key and region in config. "
                    "Get credentials from: https://portal.azure.com/ → Speech Services"
                )

        if self.provider == TTSProvider.AWS_POLLY:
            if not self.config.get("access_key_id") or not self.config.get("secret_access_key"):
                raise TTSIntegrationRequiredError(
                    "AWS Polly requires configuration. "
                    "Set: access_key_id, secret_access_key, and region in config. "
                    "Get credentials from: AWS IAM console with polly:* permissions"
                )

        if self.provider == TTSProvider.ELEVENLABS and not self.api_key:
            raise TTSIntegrationRequiredError(
                "ElevenLabs TTS requires API key. "
                "Get from: https://elevenlabs.io/app/settings/api. "
                "Set: api_key parameter. "
                "Note: ElevenLabs provides high-quality, realistic voices"
            )

    async def synthesize_speech(
        self,
        text: str,
        voice: Optional[str] = None,
        language: str = "en-US",
        output_format: str = "mp3",
    ) -> bytes:
        """
        Synthesize speech from text.

        Args:
            text: Text to convert to speech
            voice: Voice ID/name (provider-specific)
            language: Language code (e.g., 'en-US', 'es-ES')
            output_format: Audio format (mp3, wav, ogg, etc.)

        Returns:
            Audio data as bytes

        Raises:
            TTSIntegrationRequiredError: When provider integration is not configured
        """
        if self.provider == TTSProvider.GOOGLE:
            return await self._synthesize_google(text, voice, language, output_format)
        elif self.provider == TTSProvider.OPENAI:
            return await self._synthesize_openai(text, voice, output_format)
        elif self.provider == TTSProvider.AZURE:
            return await self._synthesize_azure(text, voice, language, output_format)
        elif self.provider == TTSProvider.AWS_POLLY:
            return await self._synthesize_aws(text, voice, language, output_format)
        elif self.provider == TTSProvider.ELEVENLABS:
            return await self._synthesize_elevenlabs(text, voice, output_format)
        else:
            raise ValueError(f"Unsupported TTS provider: {self.provider}")

    async def _synthesize_google(
        self,
        text: str,
        voice: Optional[str],
        language: str,
        output_format: str,
    ) -> bytes:
        """Synthesize using Google Text-to-Speech"""
        raise TTSIntegrationRequiredError(
            "Google Text-to-Speech requires integration. "
            "Install: pip install google-cloud-texttospeech. "
            "Setup: (1) Create project at https://console.cloud.google.com/, "
            "(2) Enable Text-to-Speech API, "
            "(3) Create service account and download JSON key, "
            "(4) Set GOOGLE_APPLICATION_CREDENTIALS environment variable"
        )

    async def _synthesize_openai(
        self,
        text: str,
        voice: Optional[str],
        output_format: str,
    ) -> bytes:
        """Synthesize using OpenAI TTS"""
        raise TTSIntegrationRequiredError(
            "OpenAI TTS requires integration. "
            "Install: pip install openai. "
            "Setup: Set OPENAI_API_KEY environment variable or api_key parameter. "
            "Get API key from: https://platform.openai.com/api-keys. "
            "Available voices: alloy, echo, fable, onyx, nova, shimmer"
        )

    async def _synthesize_azure(
        self,
        text: str,
        voice: Optional[str],
        language: str,
        output_format: str,
    ) -> bytes:
        """Synthesize using Azure Speech Services"""
        raise TTSIntegrationRequiredError(
            "Azure Speech Services requires integration. "
            "Install: pip install azure-cognitiveservices-speech. "
            "Setup: (1) Create Speech resource at https://portal.azure.com/, "
            "(2) Get subscription key and region from Keys and Endpoint, "
            "(3) Set subscription_key and region in config"
        )

    async def _synthesize_aws(
        self,
        text: str,
        voice: Optional[str],
        language: str,
        output_format: str,
    ) -> bytes:
        """Synthesize using AWS Polly"""
        raise TTSIntegrationRequiredError(
            "AWS Polly requires integration. "
            "Install: pip install boto3. "
            "Setup: (1) Create IAM user with polly:SynthesizeSpeech permission, "
            "(2) Get access key and secret from IAM console, "
            "(3) Set access_key_id, secret_access_key, and region in config, "
            "(4) Or configure AWS CLI: aws configure"
        )

    async def _synthesize_elevenlabs(
        self,
        text: str,
        voice: Optional[str],
        output_format: str,
    ) -> bytes:
        """Synthesize using ElevenLabs"""
        raise TTSIntegrationRequiredError(
            "ElevenLabs TTS requires integration. "
            "Install: pip install elevenlabs. "
            "Setup: Get API key from https://elevenlabs.io/app/settings/api. "
            "Set: api_key parameter. "
            "ElevenLabs provides high-quality, realistic voices with emotion and intonation"
        )

    async def synthesize_to_file(
        self,
        text: str,
        output_file_path: str,
        voice: Optional[str] = None,
        language: str = "en-US",
        output_format: str = "mp3",
    ) -> str:
        """
        Synthesize speech and save to file.

        Args:
            text: Text to convert to speech
            output_file_path: Path where audio file will be saved
            voice: Voice ID/name (provider-specific)
            language: Language code
            output_format: Audio format

        Returns:
            Path to the saved audio file
        """
        audio_data = await self.synthesize_speech(text, voice, language, output_format)

        output_path = Path(output_file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_data)

        logger.info(f"Synthesized speech saved to: {output_file_path}")
        return str(output_path)

    def get_available_voices(self) -> list[Dict[str, str]]:
        """Get list of available voices for the current provider"""
        if self.provider == TTSProvider.GOOGLE:
            return [
                {"id": "en-US-Wavenet-A", "name": "US English Female", "language": "en-US"},
                {"id": "en-US-Wavenet-B", "name": "US English Male", "language": "en-US"},
                {"id": "en-GB-Wavenet-A", "name": "UK English Female", "language": "en-GB"},
            ]
        elif self.provider == TTSProvider.OPENAI:
            return [
                {"id": "alloy", "name": "Alloy", "language": "multilingual"},
                {"id": "echo", "name": "Echo", "language": "multilingual"},
                {"id": "fable", "name": "Fable", "language": "multilingual"},
                {"id": "onyx", "name": "Onyx", "language": "multilingual"},
                {"id": "nova", "name": "Nova", "language": "multilingual"},
                {"id": "shimmer", "name": "Shimmer", "language": "multilingual"},
            ]
        elif self.provider == TTSProvider.AZURE:
            return [
                {"id": "en-US-JennyNeural", "name": "Jenny (US Female)", "language": "en-US"},
                {"id": "en-US-GuyNeural", "name": "Guy (US Male)", "language": "en-US"},
            ]
        elif self.provider == TTSProvider.AWS_POLLY:
            return [
                {"id": "Joanna", "name": "Joanna (US Female)", "language": "en-US"},
                {"id": "Matthew", "name": "Matthew (US Male)", "language": "en-US"},
                {"id": "Ivy", "name": "Ivy (US Child)", "language": "en-US"},
            ]
        elif self.provider == TTSProvider.ELEVENLABS:
            return [
                {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "language": "en"},
                {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "language": "en"},
                {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "language": "en"},
            ]
        return []

    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about the current provider"""
        return {
            "provider": self.provider.value,
            "configured": self.api_key is not None or bool(self.config),
            "available_voices": self.get_available_voices(),
            "requires_api_key": self.provider in [
                TTSProvider.OPENAI,
                TTSProvider.GOOGLE,
                TTSProvider.ELEVENLABS,
            ],
            "requires_config": self.provider in [TTSProvider.AZURE, TTSProvider.AWS_POLLY],
        }
