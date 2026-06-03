"""
JARV Backend - Voice Command Router

Routes voice commands to the Orchestrator agent for processing.
"""
from typing import Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime
import asyncio
import logging

from app.agents.orchestrator import OrchestratorAgent
from app.core.agents.base import AuthorityLevel, AgentConfig, AgentContext
from .stt import STTAdapter, STTProvider
from .tts import TTSAdapter, TTSProvider

logger = logging.getLogger(__name__)


class VoiceCommandRouter:
    """
    Routes voice commands to the Orchestrator agent.

    Flow:
    1. Receive audio input
    2. Convert speech to text (STT)
    3. Route command to Orchestrator
    4. Get response from Orchestrator
    5. Convert response to speech (TTS)
    6. Return spoken response
    """

    def __init__(
        self,
        workspace_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        stt_provider: STTProvider = STTProvider.GOOGLE,
        tts_provider: TTSProvider = TTSProvider.GOOGLE,
        stt_api_key: Optional[str] = None,
        tts_api_key: Optional[str] = None,
    ):
        self.workspace_id = workspace_id
        self.user_id = user_id

        # Initialize STT and TTS adapters
        self.stt = STTAdapter(provider=stt_provider, api_key=stt_api_key)
        self.tts = TTSAdapter(provider=tts_provider, api_key=tts_api_key)

        # Initialize Orchestrator
        config = AgentConfig(
            agent_id=uuid4(),
            workspace_id=workspace_id,
            user_id=user_id,
            authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS,
        )
        self.orchestrator = OrchestratorAgent(config=config)

    async def process_voice_command(
        self,
        audio_data: bytes,
        language: str = "en-US",
        voice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process voice command end-to-end.

        Args:
            audio_data: Raw audio bytes from microphone
            language: Language code
            voice: TTS voice ID for response

        Returns:
            Dict with:
                - command_text: Transcribed command text
                - response_text: Agent response text
                - response_audio: Spoken response audio bytes
                - execution_time: Total processing time
                - success: Whether command was processed successfully
        """
        start_time = datetime.utcnow()

        try:
            # Step 1: Speech-to-Text
            logger.info("Converting speech to text...")
            command_text = await self.stt.transcribe_audio(audio_data, language)
            logger.info(f"Command transcribed: {command_text}")

            # Step 2: Route to Orchestrator
            logger.info("Routing command to Orchestrator...")
            response = await self.route_to_orchestrator(command_text)
            response_text = response.get("response", "Command processed.")

            # Step 3: Text-to-Speech
            logger.info("Converting response to speech...")
            response_audio = await self.tts.synthesize_speech(
                response_text,
                voice=voice,
                language=language,
            )

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                "command_text": command_text,
                "response_text": response_text,
                "response_audio": response_audio,
                "execution_time": execution_time,
                "success": True,
            }

        except Exception as e:
            logger.error(f"Error processing voice command: {e}")
            execution_time = (datetime.utcnow() - start_time).total_seconds()

            # Generate error response
            error_text = f"I encountered an error processing your command: {str(e)}"

            try:
                error_audio = await self.tts.synthesize_speech(error_text, voice=voice, language=language)
            except Exception:
                error_audio = b""

            return {
                "command_text": "",
                "response_text": error_text,
                "response_audio": error_audio,
                "execution_time": execution_time,
                "success": False,
                "error": str(e),
            }

    async def route_to_orchestrator(self, command_text: str) -> Dict[str, Any]:
        """
        Route command text to Orchestrator agent.

        Args:
            command_text: Transcribed command text

        Returns:
            Dict with agent response
        """
        try:
            # Prepare input data for Orchestrator
            input_data = {
                "mission": command_text,
                "context": "Voice command received via voice router",
                "priority": "normal",
            }

            # Create agent context
            context = AgentContext(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                session_id=None,
                task_id=None,
                parent_agent_id=None,
                metadata={
                    "source": "voice_command",
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            # Execute command through Orchestrator
            result = await self.orchestrator.execute(
                input_data=input_data,
                context=context,
            )

            return {
                "response": result.output_text or "Command executed successfully.",
                "success": result.success,
                "agent_id": str(result.agent_id),
            }

        except Exception as e:
            logger.error(f"Error routing to Orchestrator: {e}")
            return {
                "response": f"Error executing command: {str(e)}",
                "success": False,
                "error": str(e),
            }

    async def process_text_command(
        self,
        command_text: str,
        voice: Optional[str] = None,
        language: str = "en-US",
    ) -> Dict[str, Any]:
        """
        Process text command (skip STT, go straight to orchestrator).

        Useful for testing or when text input is available without speech.

        Args:
            command_text: Command as text
            voice: TTS voice for response
            language: Language code

        Returns:
            Dict with response text and audio
        """
        start_time = datetime.utcnow()

        try:
            # Route to Orchestrator
            response = await self.route_to_orchestrator(command_text)
            response_text = response.get("response", "Command processed.")

            # Convert response to speech
            response_audio = await self.tts.synthesize_speech(
                response_text,
                voice=voice,
                language=language,
            )

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                "command_text": command_text,
                "response_text": response_text,
                "response_audio": response_audio,
                "execution_time": execution_time,
                "success": True,
            }

        except Exception as e:
            logger.error(f"Error processing text command: {e}")
            return {
                "command_text": command_text,
                "response_text": f"Error: {str(e)}",
                "response_audio": b"",
                "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                "success": False,
                "error": str(e),
            }

    def get_router_info(self) -> Dict[str, Any]:
        """Get information about the voice command router"""
        return {
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "stt_provider": self.stt.provider.value,
            "tts_provider": self.tts.provider.value,
            "stt_info": self.stt.get_provider_info(),
            "tts_info": self.tts.get_provider_info(),
            "orchestrator_id": str(self.orchestrator.config.agent_id),
        }
