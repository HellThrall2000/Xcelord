import os
import pandas as pd
from core.audio_listener import AudioListener
from core.transcriber import Transcriber
from core.llm_engine import LLMEngine
from core.excel_ops import ExcelExecutor  # <--- Import the new module

# --- Configuration ---
EXCEL_FILE = "dummy_data.xlsx" 
TEMP_AUDIO_FILE = "voice_command.wav"

def main():
    print("--- Excel Voice Assistant Starting ---")
    
    # 1. Initialize Modules
    try:
        listener = AudioListener() 
        listener.calibrate_noise()
        transcriber = Transcriber()
        llm = LLMEngine()
        executor = ExcelExecutor() # <--- Initialize Executor
        print("✅ Modules loaded.")
    except Exception as e:
        print(f"❌ Initialization Error: {e}")
        return

    # 2. Check Data
    if not os.path.exists(EXCEL_FILE):
        print(f"Error: {EXCEL_FILE} not found. Please run create_dummy.py first.")
        return

    try:
        df = pd.read_excel(EXCEL_FILE)
        print(f"📊 Data loaded: {len(df)} rows.")
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    # --- Main Loop ---
    while True:
        print("\n" + "="*40)
        if os.path.exists(TEMP_AUDIO_FILE):
            os.remove(TEMP_AUDIO_FILE)

        input("Press Enter to speak (or Ctrl+C to exit)...")
        
        # A. Listen
        audio_file = listener.listen_and_record(TEMP_AUDIO_FILE)
        if not audio_file: continue

        # B. Transcribe
        print("📝 Transcribing...")
        user_text = transcriber.transcribe(audio_file)
        print(f"USER SAID: '{user_text}'")
        
        if "exit" in user_text.lower(): break

        # C. Generate Code
        print("🧠 Thinking...")
        columns = list(df.columns)
        code = llm.generate_code(user_text, columns)
        
        # D. Execute Code (Using the new Module)
        print("⚡ Executing...")
        success, new_df, message = executor.execute_code(df, code)
        
        if success:
            df = new_df
            save_success, save_msg = executor.save_file(df, EXCEL_FILE)
            print(f"✅ {message}")
            print(f"💾 {save_msg}")
        else:
            print(f"❌ {message}")

if __name__ == "__main__":
    main()