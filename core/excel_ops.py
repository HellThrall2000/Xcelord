import pandas as pd
import io
import contextlib

class ExcelExecutor:
    def __init__(self):
        pass

    def load_sheet(self, filepath):
        """
        Loads the Excel file and robustly converts date columns.
        This fixes the '.dt accessor' error by forcing text dates into real datetime objects.
        """
        try:
            df = pd.read_excel(filepath)
            
            # --- Robust Date Detection ---
            for col in df.columns:
                # 1. Skip if already datetime or numeric
                if pd.api.types.is_datetime64_any_dtype(df[col]) or pd.api.types.is_numeric_dtype(df[col]):
                    continue
                
                # 2. Try converting with 'coerce' (turns bad values into NaT)
                try:
                    # 'dayfirst' helps with international dates, but isn't strictly necessary if ISO
                    converted_col = pd.to_datetime(df[col], errors='coerce')
                    
                    # 3. CHECK: Is this actually a date column?
                    # logic: If conversion worked for >50% of the non-empty rows, it's a date column.
                    non_na_count = converted_col.notna().sum()
                    original_count = df[col].notna().sum()
                    
                    if original_count > 0 and (non_na_count / original_count) > 0.5:
                        df[col] = converted_col
                        
                except Exception:
                    continue
            
            return True, df, "Spreadsheet loaded and dates processed."
        except Exception as e:
            return False, None, f"Error loading file: {e}"

    def execute_code(self, df, code_snippet):
        """
        Safely executes code and captures print() output for the UI.
        """
        local_vars = {'df': df, 'pd': pd}
        output_buffer = io.StringIO()
        
        try:
            with contextlib.redirect_stdout(output_buffer):
                exec(code_snippet, {}, local_vars)
            
            captured_output = output_buffer.getvalue().strip()
            
            if 'df' in local_vars:
                # Return the printed answer if available, otherwise just success message
                message = captured_output if captured_output else "Execution successful."
                return True, local_vars['df'], message
            else:
                return False, df, "Error: The code deleted the 'df' variable."
                
        except Exception as e:
            return False, df, f"Python Error: {e}"

    def save_file(self, df, filepath):
        try:
            df.to_excel(filepath, index=False)
            return True, "File saved successfully."
        except Exception as e:
            return False, f"Error saving file: {e}"