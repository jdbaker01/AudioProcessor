"""
Audio Transcription Service using Whisper models.
This service provides transcription capabilities for audio files from local filesystem or S3.
"""

from typing import Literal, Optional
from faster_whisper import WhisperModel


def _format_timestamp(seconds):
    """Format seconds into HH:MM:SS.mmm format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

class AudioTranscriptionService:
    """
    A service for transcribing audio files using Whisper models.
    
    This class provides methods to transcribe audio files from either local filesystem
    or Amazon S3 storage. It uses the faster-whisper implementation for efficient transcription.
    """
    
    def __init__(self, model_name: str = "base", beam_size: int = 5, device: str = "cpu", compute_type: str = "int8"):
        """
        Initialize the AudioTranscriptionService with the specified model and parameters.
        
        Args:
            model_name (str): The name of the Whisper model to use (tiny, base, small, medium, large-v3)
            beam_size (int): The beam size to use for transcription
            device (str): The device to use for computation (cpu, cuda)
            compute_type (str): The compute type to use (float16, int8)
        """
        self.model_name = model_name
        self.beam_size = beam_size
        self.device = "cpu"
        self.compute_type = "int8"
        self.model = None
    
    def _load_model(self):
        """
        Load the Whisper model if it hasn't been loaded yet.
        """
        if self.model is None:
            self.model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type
            )


    def transcribe(self, audio_file_path: str, path_type: Literal["file", "s3"]) -> dict:
        """
        Transcribe an audio file from either local filesystem or S3.
        
        Args:
            audio_file_path (str): Path to the audio file
            path_type (str): Type of path, either "file" for local filesystem or "s3" for S3 bucket path
            
        Returns:
            dict: A dictionary containing the transcription results
            
        Raises:
            NotImplementedError: This method is not yet implemented
        """
        self._load_model()

        if path_type == "s3":
            raise NotImplementedError("S3 path is not yet implemented")

        segments, info = self.model.transcribe(audio_file_path, beam_size=self.beam_size)

        # Collect all segments
        transcription_parts = []
        detailed_transcription = []

        for segment in segments:
            transcription_parts.append(segment.text)
            start_time = _format_timestamp(segment.start)
            end_time = _format_timestamp(segment.end)
            detailed_transcription.append(f"[{start_time} --> {end_time}] {segment.text}")


        transcription = " ".join(transcription_parts)

        return transcription, detailed_transcription
