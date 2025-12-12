import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import time
import os

class AudioListener:
    def __init__(self, sample_rate=16000, silence_duration=2.0, threshold_multiplier=3.0):
        """
        :param sample_rate: Hz (16000 is optimal for Whisper)
        :param silence_duration: Seconds of silence before stopping recording
        :param threshold_multiplier: How much louder than background noise to trigger recording
        """
        self.sample_rate = sample_rate
        self.silence_duration = silence_duration
        self.threshold_multiplier = threshold_multiplier
        self.threshold = 0
        self.recording = []

    def calibrate_noise(self, duration=1.0):
        """
        Listens for a second to understand background noise levels.
        """
        print("Adjusting to ambient noise... please remain silent.")
        # Record a short chunk
        recording = sd.rec(int(duration * self.sample_rate), 
                           samplerate=self.sample_rate, channels=1)
        sd.wait() # Wait for recording to finish
        
        # Calculate Volume (RMS amplitude)
        rms = np.sqrt(np.mean(recording**2))
        
        # Set threshold slightly higher than ambient noise
        self.threshold = rms * self.threshold_multiplier
        
        # Safety: If environment is dead silent, set a minimum threshold
        if self.threshold < 0.001:
            self.threshold = 0.001
            
        print(f"Calibration complete. Threshold set to: {self.threshold:.5f}")

    def listen_and_record(self, output_filename="input_command.wav"):
        """
        Blocks execution until speech is detected, recorded, and finished.
        Returns the filename.
        """
        self.recording = []
        
        # This function runs every time the mic captures a chunk of audio
        def callback(indata, frames, time_info, status):
            if status:
                print(status)
            self.recording.append(indata.copy())

        print("🎤 Listening... (Speak now)")
        
        # Open Microphone Stream
        with sd.InputStream(samplerate=self.sample_rate, channels=1, callback=callback):
            start_time = time.time()
            speech_started = False
            last_speech_time = time.time()
            
            while True:
                if not self.recording:
                    time.sleep(0.1)
                    continue
                
                # Check volume of the most recent audio chunk
                # We analyze the last 0.5 seconds (approx sample_rate/2 frames)
                if len(self.recording) > 5:
                    recent_data = np.concatenate(self.recording[-5:])
                else:
                    recent_data = self.recording[-1]
                    
                current_volume = np.sqrt(np.mean(recent_data**2))

                # LOGIC:
                # 1. Waiting for speech to start
                if not speech_started:
                    if current_volume > self.threshold:
                        print("Detected speech, recording...")
                        speech_started = True
                        last_speech_time = time.time()
                    # Optional timeout if no one speaks for 15 seconds
                    elif time.time() - start_time > 15:
                        print("Timeout: No speech detected.")
                        return None
                
                # 2. Speech has started, looking for silence to stop
                else:
                    if current_volume > self.threshold:
                        last_speech_time = time.time() # Reset timer if we hear sound
                    
                    # If silence exceeds limit, stop
                    if time.time() - last_speech_time > self.silence_duration:
                        print("Silence detected. Stopping.")
                        break
                
                # Max recording length safety (30 seconds)
                if time.time() - start_time > 30:
                    print("Max duration reached.")
                    break
                
                time.sleep(0.1)

        # Process and Save File
        if self.recording:
            full_audio = np.concatenate(self.recording, axis=0)
            wav.write(output_filename, self.sample_rate, full_audio)
            print(f"Audio saved to {output_filename}")
            return output_filename
        else:
            return None

# --- Testing Block ---
if __name__ == "__main__":
    listener = AudioListener()
    listener.calibrate_noise()
    listener.listen_and_record("test_output.wav")