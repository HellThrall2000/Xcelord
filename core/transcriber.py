import os
from groq import Groq
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Transcriber:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found in .env file")
        
        self.client = Groq(api_key=self.api_key)

    def transcribe(self, audio_filepath):
        """
        Sends audio to Groq Whisper and returns text.
        """
        if not os.path.exists(audio_filepath):
            return "Error: Audio file not found."

        try:
            with open(audio_filepath, "rb") as file:
                transcription = self.client.audio.transcriptions.create(
                    file=(audio_filepath, file.read()),
                    model="whisper-large-v3", # Groq's super fast Whisper model
                    response_format="json",
                    language="en",
                    temperature=0.0
                )
            return transcription.text
        except Exception as e:
            return f"Error during transcription: {e}"

# Test block
if __name__ == "__main__":
    t = Transcriber()
    # Ensure you have a 'test_output.wav' from the previous step
    print(t.transcribe("test_output.wav"))