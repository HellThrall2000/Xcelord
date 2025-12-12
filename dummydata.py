import pandas as pd
import random
from datetime import datetime, timedelta

# 1. Setup lists for random generation
first_names = [
    "Alice", "Bob", "Charlie", "David", "Eve", "Frank", "Grace", "Heidi", 
    "Ivan", "Judy", "Kevin", "Laura", "Mike", "Nina", "Oscar", "Paul", 
    "Quinn", "Rachel", "Steve", "Tina", "Victor", "Wendy", "Xavier", "Yara", "Zack"
]
last_names = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", 
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", 
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"
]
departments = ["Sales", "IT", "HR", "Marketing", "Finance", "Operations", "Legal"]

# 2. Generate 100 rows
data = []

for _ in range(100):
    # Create a random name
    fname = random.choice(first_names)
    lname = random.choice(last_names)
    full_name = f"{fname} {lname}"
    
    # Random Department and Sales
    dept = random.choice(departments)
    sales = random.randint(1000, 50000) # Sales between 1k and 50k
    
    # Random Date (within the last 365 days)
    days_offset = random.randint(0, 365)
    date_obj = datetime.now() - timedelta(days=days_offset)
    date_str = date_obj.strftime("%Y-%m-%d")

    data.append([full_name, dept, sales, date_str])

# 3. Create DataFrame
df = pd.DataFrame(data, columns=["Employee", "Department", "Sales", "Date"])

# 4. Save to Excel
filename = "data.xlsx"
df.to_excel(filename, index=False)

print(f"✅ Successfully created '{filename}' with 100 records.")
print("\n--- Preview of first 5 rows ---")
print(df.head())