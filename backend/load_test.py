import requests
import time

URL = "http://127.0.0.1:8000/ask"

payload = {
    "question": "What is the academic integrity policy?",
    "role": "Student"
}

for i in range(15):
    response = requests.post(URL, json=payload)
    print(f"Request {i+1}: {response.status_code}")
    time.sleep(0.2)