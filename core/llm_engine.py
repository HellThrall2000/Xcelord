import os
import logging
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# --- Logging Setup ---
# This sets up a file named 'llm_traffic.log' to store all requests
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
        self.model = "openai/gpt-oss-20b" 

    def generate_code(self, user_prompt, columns_context):
        """
        Constructs the prompt, logs it, and gets code from Llama 3.
        """
        
        system_prompt = f"""
        You are an expert Python Data Analyst.
        You are given a Pandas DataFrame named `df`.
        The columns are: {columns_context}
        
        Your task: Write Python code to fulfill the User's request.
        
        RULES:
        1. Operate directly on `df`.
        2. Do NOT create sample data. Use the existing `df` provided in the environment.
        3. If the user asks for a calculation (like average, sum), print the result using print().
        4. If the user asks to modify data (sort, filter, add column), update `df` inplace or reassign it (e.g., df = df.sort_values...).
        5. Return ONLY the python code. Do not wrap it in markdown (```). Do not write explanations.
        """

        messages_payload = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # --- LOGGING REQUEST ---
        log_message = f"\n{'='*20} NEW REQUEST {'='*20}\nUSER REQUEST: {user_prompt}\nSYSTEM PROMPT: {system_prompt}\n"
        print(f"\n📢 [LOG] Sending Request to LLM... (See llm_traffic.log for full details)")
        logging.info(log_message)

        try:
            chat_completion = self.client.chat.completions.create(
                messages=messages_payload,
                model=self.model,
                temperature=0.1, 
            )
            
            response = chat_completion.choices[0].message.content
            
            # --- LOGGING RESPONSE ---
            response_log = f"\n{'-'*20} RAW RESPONSE {'-'*20}\n{response}\n{'='*50}\n"
            print(f"📥 [LOG] Received Response from LLM.")
            # Print full response to console for debugging as requested
            print(f"\n--- FULL LLM RESPONSE START ---\n{response}\n--- FULL LLM RESPONSE END ---\n")
            logging.info(response_log)
            
            # Cleanup
            clean_code = response.replace("```python", "").replace("```", "").strip()
            return clean_code

        except Exception as e:
            error_msg = f"API Error: {e}"
            print(f"❌ [LOG] {error_msg}")
            logging.error(error_msg)
            return f"print('{error_msg}')"