import requests
from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env

WEBEX_API_URL = "https://webexapis.com/v1/webhooks"
ACCESS_TOKEN = os.getenv("WEBEX_ACCESS_TOKEN")
WEBHOOK_URL = os.getenv("WEBEX_WEBHOOK_URL")
ROOM_ID = os.getenv("WEBEX_ROOM_ID")

webhook_data = {
    "name": "My Webex Webhook",
    "targetUrl": WEBHOOK_URL,        # This should match your Flask '/webhook' endpoint
    "resource": "messages",
    "event": "created",
    # Filter ensures the webhook only fires for new messages in the given ROOM_ID
    "filter": f"roomId={ROOM_ID}"
}

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

response = requests.post(WEBEX_API_URL, json=webhook_data, headers=headers)

if response.status_code in [200, 201]:
    print("Webhook successfully created!")
else:
    print(f"Failed to create webhook: {response.status_code} {response.text}")