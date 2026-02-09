import os
import logging
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# --- Logging Setup ---
logging.basicConfig(
    filename='llm_traffic.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class LLMEngine:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key)
        self.model = "openai/gpt-oss-20b" # Or "llama3-70b-8192"

    def generate_code(self, user_prompt, columns_context):
        """
        Constructs the prompt, logs it, and gets code from the LLM.
        """
        
        system_prompt = f"""
        You are an expert Python Data Analyst.
        You are given a Pandas DataFrame named `df`.
        The columns are: {columns_context}
        
        Your task: Write Python code to fulfill the User's request.
        
        CRITICAL RULES:
        1. Operate directly on `df`. Do NOT create sample data.
        2. **DATE SAFETY**: The date columns might be loaded as strings. BEFORE using any `.dt` accessor (like .dt.year, .dt.month), YOU MUST write a line of code to convert the column to datetime. 
           Example: `df['Date'] = pd.to_datetime(df['Date'], errors='coerce')`
        3. If the user asks for a calculation, print the result.
        4. If the user asks to modify data, update `df` inplace.
        5. Return ONLY the python code. No markdown, no explanations.
        """

        messages_payload = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # --- LOGGING REQUEST ---
        log_message = f"\n{'='*20} NEW REQUEST {'='*20}\nUSER REQUEST: {user_prompt}\n"
        print(f"\n📢 [LOG] Sending Request to LLM...")
        logging.info(log_message)

        try:
            chat_completion = self.client.chat.completions.create(
                messages=messages_payload,
                model=self.model,
                temperature=0.1, 
            )
            
            response = chat_completion.choices[0].message.content
            
            # --- LOGGING RESPONSE ---
            print(f"📥 [LOG] Received Response.")
            print(f"\n--- FULL LLM RESPONSE START ---\n{response}\n--- FULL LLM RESPONSE END ---\n")
            logging.info(f"RESPONSE:\n{response}")
            
            # Cleanup
            clean_code = response.replace("```python", "").replace("```", "").strip()
            return clean_code

        except Exception as e:
            error_msg = f"API Error: {e}"
            print(f"❌ [LOG] {error_msg}")
            return f"print('{error_msg}')"