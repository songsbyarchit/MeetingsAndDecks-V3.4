import requests
import os

WEBEX_TOKEN = os.getenv("WEBEX_ACCESS_TOKEN")

def list_webhooks():
    url = "https://webexapis.com/v1/webhooks"
    headers = {"Authorization": f"Bearer {WEBEX_TOKEN}"}

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        webhooks = response.json().get("items", [])
        if not webhooks:
            print("🚫 No webhooks found.")
        else:
            for webhook in webhooks:
                print(f"ID: {webhook['id']}, Name: {webhook['name']}, Target: {webhook['targetUrl']}")
    else:
        print(f"❌ Failed to list webhooks: {response.status_code} - {response.text}")

list_webhooks()