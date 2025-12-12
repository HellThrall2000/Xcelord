import pandas as pd

class ExcelExecutor:
    def __init__(self):
        pass

    def execute_code(self, df, code_snippet):
        """
        Safely executes the code snippet on the given DataFrame.
        Returns: (success: bool, updated_df: DataFrame, message: str)
        """
        # Context where the code will run
        local_vars = {'df': df, 'pd': pd}
        
        try:
            # Run the AI's code
            exec(code_snippet, {}, local_vars)
            
            # Retrieve the modified dataframe
            if 'df' in local_vars:
                return True, local_vars['df'], "Execution successful."
            else:
                return False, df, "Error: The code deleted the 'df' variable."
                
        except Exception as e:
            return False, df, f"Python Error: {e}"

    def save_file(self, df, filepath):
        """
        Saves the DataFrame to Excel.
        """
        try:
            df.to_excel(filepath, index=False)
            return True, "File saved successfully."
        except Exception as e:
            return False, f"Error saving file: {e}"