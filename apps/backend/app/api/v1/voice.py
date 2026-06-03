"""
JARV Backend - Voice Command API

API endpoints for voice command system including push-to-talk functionality.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import Optional
from pydantic import BaseModel
from uuid import UUID

from app.core.voice import (
    VoiceCommandRouter,
    STTProvider,
    TTSProvider,
    SpokenStatusReplies,
    StatusType,
)

router = APIRouter(prefix="/voice", tags=["voice"])


# Request/Response Models

class VoiceCommandRequest(BaseModel):
    """Request for text-based voice command"""
    command: str
    language: str = "en-US"
    voice: Optional[str] = None


class VoiceCommandResponse(BaseModel):
    """Response from voice command processing"""
    command_text: str
    response_text: str
    execution_time: float
    success: bool
    error: Optional[str] = None


class VoiceStatusRequest(BaseModel):
    """Request for spoken status"""
    status_type: str
    details: Optional[str] = None


class VoiceStatusResponse(BaseModel):
    """Response with spoken status text"""
    status_text: str
    status_type: str


# Endpoints

@router.post("/push-to-talk", response_model=VoiceCommandResponse)
async def push_to_talk(
    audio: UploadFile = File(...),
    language: str = "en-US",
    voice: Optional[str] = None,
):
    """
    Push-to-talk voice command endpoint.

    Process voice command from audio file:
    1. Transcribe audio to text (STT)
    2. Route command to Orchestrator
    3. Generate spoken response (TTS)

    Args:
        audio: Audio file (wav, mp3, flac, etc.)
        language: Language code (e.g., 'en-US')
        voice: TTS voice ID

    Returns:
        Command text, response text, and execution time

    Example:
        curl -X POST "http://localhost:8000/api/v1/voice/push-to-talk" \\
             -F "audio=@command.wav" \\
             -F "language=en-US"
    """
    try:
        # Read audio file
        audio_data = await audio.read()

        # Initialize voice router (with no API keys, will raise IntegrationRequiredError)
        router_instance = VoiceCommandRouter(
            stt_provider=STTProvider.GOOGLE,
            tts_provider=TTSProvider.GOOGLE,
        )

        # Process voice command
        result = await router_instance.process_voice_command(
            audio_data=audio_data,
            language=language,
            voice=voice,
        )

        return VoiceCommandResponse(
            command_text=result["command_text"],
            response_text=result["response_text"],
            execution_time=result["execution_time"],
            success=result["success"],
            error=result.get("error"),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Voice command processing failed: {str(e)}"
        )


@router.post("/command/text", response_model=VoiceCommandResponse)
async def text_command(request: VoiceCommandRequest):
    """
    Process text command with spoken response.

    Skip STT, process text directly and generate spoken response.
    Useful for testing or when text input is available.

    Args:
        request: Command text, language, and voice

    Returns:
        Response text and audio

    Example:
        curl -X POST "http://localhost:8000/api/v1/voice/command/text" \\
             -H "Content-Type: application/json" \\
             -d '{"command": "What is the system status?", "language": "en-US"}'
    """
    try:
        router_instance = VoiceCommandRouter(
            stt_provider=STTProvider.GOOGLE,
            tts_provider=TTSProvider.GOOGLE,
        )

        result = await router_instance.process_text_command(
            command_text=request.command,
            voice=request.voice,
            language=request.language,
        )

        return VoiceCommandResponse(
            command_text=result["command_text"],
            response_text=result["response_text"],
            execution_time=result["execution_time"],
            success=result["success"],
            error=result.get("error"),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Text command processing failed: {str(e)}"
        )


@router.post("/status/speak", response_model=VoiceStatusResponse)
async def speak_status(request: VoiceStatusRequest):
    """
    Get spoken status text.

    Generate natural language status reply for given status type.

    Args:
        request: Status type and optional details

    Returns:
        Spoken status text

    Example:
        curl -X POST "http://localhost:8000/api/v1/voice/status/speak" \\
             -H "Content-Type: application/json" \\
             -d '{"status_type": "success", "details": "File uploaded successfully"}'
    """
    try:
        replies = SpokenStatusReplies(language="en-US")

        # Map string to StatusType enum
        try:
            status_type = StatusType(request.status_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status type: {request.status_type}. "
                       f"Valid types: {[s.value for s in StatusType]}"
            )

        status_text = replies.get_status_reply(
            status_type=status_type,
            details=request.details,
        )

        return VoiceStatusResponse(
            status_text=status_text,
            status_type=request.status_type,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Status generation failed: {str(e)}"
        )


@router.get("/providers")
async def get_providers():
    """
    Get available voice service providers.

    Returns:
        STT and TTS providers with configuration requirements

    Example:
        curl http://localhost:8000/api/v1/voice/providers
    """
    return {
        "stt_providers": [
            {
                "id": "google",
                "name": "Google Speech Recognition",
                "requires": "API key",
            },
            {
                "id": "openai_whisper",
                "name": "OpenAI Whisper",
                "requires": "API key or local model",
            },
            {
                "id": "azure",
                "name": "Azure Speech Services",
                "requires": "Subscription key + region",
            },
            {
                "id": "aws_transcribe",
                "name": "AWS Transcribe",
                "requires": "AWS credentials",
            },
        ],
        "tts_providers": [
            {
                "id": "google",
                "name": "Google Text-to-Speech",
                "requires": "API key",
            },
            {
                "id": "openai",
                "name": "OpenAI TTS",
                "requires": "API key",
            },
            {
                "id": "azure",
                "name": "Azure Speech Services",
                "requires": "Subscription key + region",
            },
            {
                "id": "aws_polly",
                "name": "AWS Polly",
                "requires": "AWS credentials",
            },
            {
                "id": "elevenlabs",
                "name": "ElevenLabs (High Quality)",
                "requires": "API key",
            },
        ],
    }


@router.get("/health")
async def voice_health():
    """
    Check voice system health.

    Returns:
        Health status of voice command system

    Example:
        curl http://localhost:8000/api/v1/voice/health
    """
    return {
        "status": "operational",
        "components": {
            "stt": "integration_required",
            "tts": "integration_required",
            "wake_word": "integration_required",
            "router": "operational",
            "status_replies": "operational",
        },
        "message": "Voice system framework operational. Provider integration required for full functionality.",
    }
