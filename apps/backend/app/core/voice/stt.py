"""
JARV Backend - Speech-to-Text (STT) Adapter

Converts spoken audio input to text for voice command processing.
"""
from typing import Optional, Dict, Any
from enum import Enum
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class STTProvider(str, Enum):
    """Available STT providers"""
    GOOGLE = "google"
    OPENAI_WHISPER = "openai_whisper"
    AZURE = "azure"
    AWS_TRANSCRIBE = "aws_transcribe"


class STTIntegrationRequiredError(Exception):
    """Raised when STT requires external service integration"""
    pass


class STTAdapter:
    """
    Speech-to-Text adapter for converting audio to text.

    Supports multiple providers:
    - Google Speech Recognition (requires API key)
    - OpenAI Whisper (local or API)
    - Azure Speech Services (requires credentials)
    - AWS Transcribe (requires credentials)
    """

    def __init__(
        self,
        provider: STTProvider = STTProvider.GOOGLE,
        api_key: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.config = config or {}
        self._validate_configuration()

    def _validate_configuration(self):
        """Validate provider configuration"""
        if self.provider == STTProvider.GOOGLE and not self.api_key:
            logger.warning("Google STT requires API key for production use")

        if self.provider == STTProvider.AZURE:
            if not self.config.get("subscription_key") or not self.config.get("region"):
                raise STTIntegrationRequiredError(
                    "Azure Speech Services requires configuration. "
                    "Set: subscription_key and region in config. "
                    "Get credentials from: https://portal.azure.com/ → Speech Services"
                )

        if self.provider == STTProvider.AWS_TRANSCRIBE:
            if not self.config.get("access_key_id") or not self.config.get("secret_access_key"):
                raise STTIntegrationRequiredError(
                    "AWS Transcribe requires configuration. "
                    "Set: access_key_id, secret_access_key, and region in config. "
                    "Get credentials from: AWS IAM console with transcribe:* permissions"
                )

    async def transcribe_audio(
        self,
        audio_data: bytes,
        language: str = "en-US",
        audio_format: str = "wav",
    ) -> str:
        """
        Transcribe audio data to text.

        Args:
            audio_data: Raw audio bytes
            language: Language code (e.g., 'en-US', 'es-ES')
            audio_format: Audio format (wav, mp3, flac, etc.)

        Returns:
            Transcribed text string

        Raises:
            STTIntegrationRequiredError: When provider integration is not configured
        """
        if self.provider == STTProvider.GOOGLE:
            return await self._transcribe_google(audio_data, language)
        elif self.provider == STTProvider.OPENAI_WHISPER:
            return await self._transcribe_whisper(audio_data, language)
        elif self.provider == STTProvider.AZURE:
            return await self._transcribe_azure(audio_data, language)
        elif self.provider == STTProvider.AWS_TRANSCRIBE:
            return await self._transcribe_aws(audio_data, language)
        else:
            raise ValueError(f"Unsupported STT provider: {self.provider}")

    async def _transcribe_google(self, audio_data: bytes, language: str) -> str:
        """Transcribe using Google Speech Recognition"""
        raise STTIntegrationRequiredError(
            "Google Speech Recognition requires integration. "
            "Install: pip install SpeechRecognition google-cloud-speech. "
            "Setup: (1) Create project at https://console.cloud.google.com/, "
            "(2) Enable Speech-to-Text API, "
            "(3) Create service account and download JSON key, "
            "(4) Set GOOGLE_APPLICATION_CREDENTIALS environment variable"
        )

    async def _transcribe_whisper(self, audio_data: bytes, language: str) -> str:
        """Transcribe using OpenAI Whisper (local or API)"""
        raise STTIntegrationRequiredError(
            "OpenAI Whisper requires integration. "
            "For local: pip install openai-whisper torch. "
            "For API: pip install openai, set OPENAI_API_KEY env var. "
            "Local model will be downloaded automatically on first use (large file ~3GB for base model). "
            "API usage: Set api_key parameter with OpenAI API key from https://platform.openai.com/api-keys"
        )

    async def _transcribe_azure(self, audio_data: bytes, language: str) -> str:
        """Transcribe using Azure Speech Services"""
        raise STTIntegrationRequiredError(
            "Azure Speech Services requires integration. "
            "Install: pip install azure-cognitiveservices-speech. "
            "Setup: (1) Create Speech resource at https://portal.azure.com/, "
            "(2) Get subscription key and region from Keys and Endpoint, "
            "(3) Set subscription_key and region in config"
        )

    async def _transcribe_aws(self, audio_data: bytes, language: str) -> str:
        """Transcribe using AWS Transcribe"""
        raise STTIntegrationRequiredError(
            "AWS Transcribe requires integration. "
            "Install: pip install boto3. "
            "Setup: (1) Create IAM user with transcribe:* permissions, "
            "(2) Get access key and secret from IAM console, "
            "(3) Set access_key_id, secret_access_key, and region in config, "
            "(4) Or configure AWS CLI: aws configure"
        )

    async def transcribe_file(
        self,
        audio_file_path: str,
        language: str = "en-US",
    ) -> str:
        """
        Transcribe audio file to text.

        Args:
            audio_file_path: Path to audio file
            language: Language code

        Returns:
            Transcribed text string
        """
        audio_path = Path(audio_file_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

        audio_data = audio_path.read_bytes()
        audio_format = audio_path.suffix.lstrip('.')

        return await self.transcribe_audio(audio_data, language, audio_format)

    def get_supported_languages(self) -> list[str]:
        """Get list of supported language codes for the current provider"""
        if self.provider == STTProvider.GOOGLE:
            return ["en-US", "es-ES", "fr-FR", "de-DE", "it-IT", "pt-BR", "zh-CN", "ja-JP", "ko-KR"]
        elif self.provider == STTProvider.OPENAI_WHISPER:
            return ["en", "es", "fr", "de", "it", "pt", "zh", "ja", "ko", "multilingual"]
        elif self.provider == STTProvider.AZURE:
            return ["en-US", "es-ES", "fr-FR", "de-DE", "it-IT", "pt-BR", "zh-CN", "ja-JP", "ko-KR"]
        elif self.provider == STTProvider.AWS_TRANSCRIBE:
            return ["en-US", "es-US", "fr-FR", "de-DE", "it-IT", "pt-BR", "zh-CN", "ja-JP", "ko-KR"]
        return []

    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about the current provider"""
        return {
            "provider": self.provider.value,
            "configured": self.api_key is not None or bool(self.config),
            "supported_languages": self.get_supported_languages(),
            "requires_api_key": self.provider in [STTProvider.GOOGLE, STTProvider.OPENAI_WHISPER],
            "requires_config": self.provider in [STTProvider.AZURE, STTProvider.AWS_TRANSCRIBE],
        }
