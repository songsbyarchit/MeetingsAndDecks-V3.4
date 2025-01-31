import os
import requests
import openai
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import date, time, datetime, timedelta
import pytz
import time  # Add this at the top of your file if not already imported


today_str = date.today().strftime("%B %d, %Y")

load_dotenv()

app = Flask(__name__)

WEBEX_TOKEN = os.getenv("WEBEX_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
bot_token = os.getenv("BOT_ACCESS_TOKEN")

# Configure OpenAI
openai.api_key = OPENAI_API_KEY

@app.before_request
def log_request():
    print(f"📥 Incoming request: {request.method} {request.path} from {request.remote_addr}")

def ensure_webhook_exists():
    """
    Ensures a Webex webhook exists for this integration.
    If any unwanted webhooks exist (like 'DonnaBotWebhook'), they are deleted.
    """
    WEBHOOK_NAME = "MeetingsAndDecksWebhook"
    WEBHOOK_TARGET_URL = "https://jennet-amazing-sailfish.ngrok-free.app/webhook"  # Replace with your actual URL
    WEBHOOK_RESOURCE = "messages"
    WEBHOOK_EVENT = "created"
    WEBEX_ROOM_ID = os.getenv("WEBEX_ROOM_ID")

    url = "https://webexapis.com/v1/webhooks"
    headers = {
        "Authorization": f"Bearer {WEBEX_TOKEN}",
        "Content-Type": "application/json"
    }

    # Step 1: Check existing webhooks
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        webhooks = response.json().get("items", [])
        existing_webhook = None

        for webhook in webhooks:
            if webhook["name"] == WEBHOOK_NAME and webhook["targetUrl"] == WEBHOOK_TARGET_URL:
                existing_webhook = webhook
            elif webhook["name"] != WEBHOOK_NAME:  # Delete any other webhooks
                delete_url = f"https://webexapis.com/v1/webhooks/{webhook['id']}"
                delete_response = requests.delete(delete_url, headers=headers)
                if delete_response.status_code == 204:
                    print(f"🗑️ Deleted old webhook '{webhook['name']}' (ID: {webhook['id']})")
                else:
                    print(f"❌ Failed to delete webhook '{webhook['name']}': {delete_response.text}")

        if existing_webhook:
            print(f"✅ Webhook '{WEBHOOK_NAME}' already exists.")
            return  # Webhook exists, no need to create a new one

    # Step 2: If no webhook exists, create one
    payload = {
        "name": WEBHOOK_NAME,
        "targetUrl": WEBHOOK_TARGET_URL,
        "resource": WEBHOOK_RESOURCE,
        "event": WEBHOOK_EVENT,
        "filter": f"roomId={WEBEX_ROOM_ID}"  # Ensuring it only triggers for the right room
    }

    create_response = requests.post(url, json=payload, headers=headers)

    if create_response.status_code == 200:
        print(f"✅ Created new webhook '{WEBHOOK_NAME}' successfully!")
    else:
        print(f"❌ Failed to create webhook: {create_response.status_code} - {create_response.text}")

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handles incoming Webex webhooks."""
    webhook_data = request.json
    print("🔔 Webhook triggered with data:", webhook_data)

    # 1. Verify the webhook event is a new message in the correct room
    resource = webhook_data.get("resource")
    event = webhook_data.get("event")
    data = webhook_data.get("data", {})

    if resource == "messages" and event == "created":
        room_id = data.get("roomId")
        if room_id != os.getenv("WEBEX_ROOM_ID"):
            print(f"🚫 Ignoring message from room {room_id}. Not the configured integration space.")
            return jsonify({"status": "ignored"}), 200

            message_text = fetch_webex_message_text(message_id)
            print(f"Received message: {message_text}")
            
            # Prevent infinite loop by ignoring messages sent by the integration itself or the bot's own confirmation messages
            if webhook_data.get("actorId") == "Y2lzY29zcGFyazovL3VzL0FQUExJQ0FUSU9OLzZjMzlkY2JhLTZmYjAtNDkxNS04NjNlLWFiZWQ3ZDZkMDI1Zg":  # Bot's actorId
                print("🚫 Ignoring message from the bot to prevent infinite loop.")
                return jsonify({"status": "ignored"}), 200

            # Prevent infinite loop by ignoring bot's own confirmation messages
            if data.get("personEmail") == "madfrontend@webex.bot" and "All done! Meeting" in message_text:
                print("🚫 Ignoring confirmation message from the bot to prevent infinite loop.")
                return jsonify({"status": "ignored"}), 200
        
        message_id = data.get("id")

        if message_id:
            # 2. Get the actual text of the message from Webex
            message_text = fetch_webex_message_text(message_id)
            print(f"Received message: {message_text}")

            # 3. Send this text to your OpenAI function
            openai_response = process_natural_language_input(message_text)

            # 4. Print or handle the OpenAI response
            print(f"OpenAI response: {openai_response}")

            try:
                booking_data = json.loads(openai_response)
                # booking_data should look like: 
                # {"attendees":["user@example.com"], "date":"tomorrow", "time":"5pm"}
            except json.JSONDecodeError:
                print("Could not parse JSON from OpenAI response.")
                booking_data = None

            if booking_data:
                # 5. Create a Webex meeting link
                webex_meeting_url = create_webex_meeting(booking_data)  # We'll define function below

                # 6. Create a Google Calendar event as archit.sachdeva007@gmail.com
                create_google_calendar_event(
                    host_email="archit.sachdeva007@gmail.com",
                    booking_data=booking_data,
                    webex_link=webex_meeting_url
                )
    
                # 7. Send a confirmation message in Webex
                confirmation_message = (
                    f"All done! Meeting with {booking_data.get('attendees', [''])[0]} "
                    f"is booked at {booking_data.get('date')} {booking_data.get('time')}.\n\n"
                    f"Here's ya link: {webex_meeting_url}"
                )

                # 7. Send a confirmation message in Webex (to a different room)
                send_webex_bot_message(room_id, confirmation_message, is_notification=True)

    return jsonify({"status": "ok"}), 200

def create_webex_meeting(booking_data):
    """
    Uses the Webex Meetings API to create a scheduled meeting for arsachde@cisco.com.
    Returns the meeting join link.
    """
    # Example minimal body. 
    # In real usage, you'd parse booking_data["date"] and "time" into a proper RFC3339 datetime for start/endTime.
    webex_api_url = "https://webexapis.com/v1/meetings"
    headers = {
        "Authorization": f"Bearer {WEBEX_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "title": "Scheduled via Webex + GPT",  # or use booking_data details
        "start": "2025-02-01T17:00:00Z",       # parse booking_data for correct date/time
        "end": "2025-02-01T17:30:00Z",         # example: 30 min meeting
        "enabledAutoRecordMeeting": False,
        "allowAnyUserToBeCoHost": False
    }

    resp = requests.post(webex_api_url, json=payload, headers=headers)
    if resp.status_code == 200:
        meeting_info = resp.json()["items"][0] if "items" in resp.json() else resp.json()
        meeting_link = meeting_info.get("webLink")
        print(f"Created Webex meeting link: {meeting_link}")
        return meeting_link
    else:
        print(f"Failed to create Webex meeting: {resp.text}")
        return None

def get_recent_conversations():
    """Fetches a list of all unique people from 1-on-1 DMs and group spaces, sorted by recency (DMs first)."""
    url = "https://webexapis.com/v1/rooms"
    headers = {
        "Authorization": f"Bearer {WEBEX_TOKEN}",
        "Content-Type": "application/json"
    }

    # Fetch all direct (1-on-1) conversations
    direct_params = {"type": "direct"}
    direct_response = requests.get(url, headers=headers, params=direct_params)
    
    # Fetch all group spaces
    group_params = {"type": "group"}
    group_response = requests.get(url, headers=headers, params=group_params)

    if direct_response.status_code == 200 and group_response.status_code == 200:
        direct_rooms = direct_response.json().get("items", [])
        group_rooms = group_response.json().get("items", [])

        # Sort direct rooms by last activity timestamp (most recent first)
        sorted_direct_rooms = sorted(direct_rooms, key=lambda r: r.get("lastActivity", ""), reverse=True)

        # Get unique people from 1-on-1 DMs
        unique_people = {}
        for room in sorted_direct_rooms:
            person_email = room.get("creatorId", "Unknown")  # Get the participant in DM
            if person_email != "Unknown":
                unique_people[person_email] = room.get("lastActivity", "")

        # Now fetch participants from group spaces
        for room in group_rooms:
            room_id = room.get("id")
            if not room_id:
                continue

            membership_url = f"https://webexapis.com/v1/memberships?roomId={room_id}"
            membership_response = requests.get(membership_url, headers=headers)

            if membership_response.status_code == 200:
                members = membership_response.json().get("items", [])
                for member in members:
                    person_email = member.get("personEmail")
                    last_active = room.get("lastActivity", "")
                    if person_email and person_email not in unique_people:  # Avoid duplicates
                        unique_people[person_email] = last_active
                        # Fetch display name from Webex API
                        # Track time before API call
                        start_time = time.time()

                        # Fetch display name from Webex API
                        person_url = f"https://webexapis.com/v1/people?email={person_email}"
                        person_response = requests.get(person_url, headers=headers)

                        # Track time after API call
                        end_time = time.time()
                        elapsed_time = end_time - start_time

                        if person_response.status_code == 200:
                            person_data = person_response.json().get("items", [])
                            if person_data:
                                display_name = person_data[0].get("displayName", person_email)  # Fallback to email if no name
                            else:
                                display_name = person_email  # Fallback
                        else:
                            display_name = person_email  # Fallback

                        # Print time taken for each call
                        print(f"✅ Fetched display name for {person_email}: {display_name} (⏱️ {elapsed_time:.2f} seconds)")


                        if person_response.status_code == 200:
                            person_data = person_response.json().get("items", [])
                            if person_data:
                                display_name = person_data[0].get("displayName", person_email)  # Fallback to email if no name
                            else:
                                display_name = person_email  # Fallback
                        else:
                            display_name = person_email  # Fallback

                        # Store as (display_name, email, last_active) instead of just email
                        unique_people[person_email] = (display_name, last_active)


        # Sort people by recency (DMs first, then group members)
        sorted_people = sorted(unique_people.items(), key=lambda x: x[1][1] if isinstance(x[1], tuple) else "", reverse=True)

        return sorted_people
    else:
        print(f"❌ Failed to retrieve conversations: {direct_response.text} {group_response.text}")
        return []

def search_contacts_by_first_name(contacts, first_name):
    """Searches for all contacts matching a given first name."""
    matching_contacts = [
        (email, data[1]) for email, data in contacts if isinstance(data, tuple) and email.split("@")[0].lower() == first_name.lower()
    ]

    if matching_contacts:
        return sorted(matching_contacts, key=lambda x: x[1], reverse=True)  # Sort by recency
    else:
        return []


def send_webex_bot_message(room_id, message, is_notification=False):
    """Sends a message from the bot to a Webex space."""
    bot_token = os.getenv("BOT_ACCESS_TOKEN")
    url = "https://webexapis.com/v1/messages"
    
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json"
    }

    # Use the notification room if is_notification is True
    target_room = os.getenv("NOTIFICATION_ROOM_ID") if is_notification else room_id

    payload = {
        "roomId": target_room,
        "text": message
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        print(f"✅ Sent message from bot to Webex space: {message}")
    else:
        print(f"❌ Failed to send message: {response.text}")

@app.route("/callback", methods=["GET"])
def oauth_callback():
    """Handles OAuth callback from Webex."""
    code = request.args.get("code")
    state = request.args.get("state")
    
    if not code:
        return "Error: No authorization code received.", 400

    print(f"✅ Received OAuth Code: {code}")
    return "OAuth successful! You can close this window.", 200

def fetch_webex_message_text(message_id):
    """Fetch the text of a Webex message by its ID."""
    url = f"https://webexapis.com/v1/messages/{message_id}"
    headers = {
        "Authorization": f"Bearer {WEBEX_TOKEN}",
        "Content-Type": "application/json"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        message_data = response.json()
        return message_data.get("text", "")
    else:
        print(f"Failed to retrieve message: {response.text}")
        return ""

def create_google_calendar_event(host_email, booking_data, webex_link):
    """
    Creates a Google Calendar event (hosted by host_email) with the provided attendees,
    date/time from booking_data, and sets the Webex link in the event location.
    """
    # 1. Build Google Calendar service using your stored OAuth credentials.
    #    You'll need to load credentials from your tokens or environment.
    if not os.path.exists("meetndecks_tokens.json"):
        print("Error: No stored Google OAuth tokens. Please authorize via /google_callback first.")
        return

    creds = Credentials.from_authorized_user_file("meetndecks_tokens.json", ["https://www.googleapis.com/auth/calendar"])
    service = build("calendar", "v3", credentials=creds)

    # 2. Convert booking_data's date/time to RFC3339 (2025-02-01T17:00:00-07:00, etc.)
    #    This is just an example placeholder:
    # Example (simple parse). Use an actual datetime library for more accuracy:
    user_date = booking_data.get("date")       # e.g. "tomorrow" or "2025-02-01"
    user_time = booking_data.get("time")       # e.g. "5pm"

    # Convert to a real datetime. For a quick placeholder:
    start_datetime = f"2025-02-01T17:00:00-05:00"
    end_datetime = f"2025-02-01T17:30:00-05:00"


    # 3. Create the event body
    # Extract first part of emails (before @)
    attendee_names = [email.split("@")[0] for email in booking_data.get("attendees", [])]
    attendee_names.append("arsachde")  # Ensuring 'arsachde' (arsachde@cisco.com) is included

    # Create the meeting title
    meeting_title = " // ".join(attendee_names)

    uk_tz = pytz.timezone("Europe/London")
    start_time = datetime.strptime(f"{user_date} {user_time}", "%B %d, %Y %I:%M %p")
    start_time = uk_tz.localize(start_time)  # Ensure it's in UK time zone
    end_time = start_time + timedelta(minutes=30)  # Default meeting length: 30 minutes

    event_body = {
        "summary": meeting_title,
        "location": webex_link,  # or "Webex Meeting" etc.
        "start": {"dateTime": start_time.isoformat(), "timeZone": "Europe/London"},
        "end": {"dateTime": end_time.isoformat(), "timeZone": "Europe/London"},
        "attendees": [{"email": email} for email in booking_data.get("attendees", [])] + [{"email": "arsachde@cisco.com"}],
        "organizer": {"email": host_email},  # tries to set the host as archit
    }

    event = service.events().insert(calendarId=host_email, body=event_body, sendUpdates="all").execute()
    print(f"Google event created: {event.get('htmlLink')}")

def process_natural_language_input(user_text):
    """
    Uses OpenAI's GPT-3.5-turbo to process user text and return structured data.
    """

    try:
        # Example prompt + system role. Adjust to your own logic!
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a meeting scheduling assistant. "
                        f"Today's date is {today_str}. "
                        "You MUST always return a JSON object with only three fields: 'attendees', 'date', and 'time'.\n"
                        "You MUST NOT include any other text, explanations, or formatting outside of the JSON object.\n"
                        "You MUST strictly follow these formatting rules:\n"
                        "- 'date' MUST be in the strict format 'Month DD, YYYY' (e.g., 'January 31, 2025').\n"
                        "- 'time' MUST be in 12-hour format with AM/PM (e.g., '5:30 PM').\n"
                        "- If the user specifies 'tomorrow' or another relative date, you MUST resolve it into an absolute 'Month DD, YYYY' format.\n"
                        "- If the user specifies a time in 24-hour format (e.g., 17:30), you MUST convert it to 12-hour format (e.g., 5:30 PM). Include AM/PM.\n"
                        "You MUST NOT return any other text outside of the JSON.\n"
                        "Example output:\n"
                        "{\"attendees\": [\"user@example.com\"], \"date\": \"January 31, 2025\", \"time\": \"5:30 PM\"}"
                    )
                },
                {
                    "role": "user",
                    "content": user_text
                }
            ],
            temperature=0.7
        )

        # Extract the response text from the OpenAI API response
        assistant_message = response["choices"][0]["message"]["content"]
        return assistant_message

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return {"error": str(e)}

@app.route("/google_auth")
def google_auth():
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        "meetndecks_creds.json",  # This still uses the initial creds.json for initial authorization
        scopes=["https://www.googleapis.com/auth/calendar"],
        redirect_uri="https://jennet-amazing-sailfish.ngrok-free.app/google_callback"  # Ensure this matches your app's redirect URI
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    return jsonify({"auth_url": authorization_url})

@app.route("/google_callback")
def google_callback():
    """
    Handle Google's OAuth callback. Exchange the 'code' query parameter
    for tokens and store them in meetndecks_tokens.json.
    """
    from google_auth_oauthlib.flow import Flow

    code = request.args.get("code")
    if not code:
        return "Missing Google OAuth code.", 400

    flow = Flow.from_client_secrets_file(
        "meetndecks_creds.json",  # This is only used for the initial OAuth flow
        scopes=["https://www.googleapis.com/auth/calendar"],
        redirect_uri="https://jennet-amazing-sailfish.ngrok-free.app/google_callback"
    )
    flow.fetch_token(code=code)

    # Save the credentials to meetndecks_tokens.json
    creds = flow.credentials
    with open("meetndecks_tokens.json", "w") as token_file:
        token_file.write(creds.to_json())

    return "Google OAuth successful. You can close this window."

if __name__ == "__main__":
    people = get_recent_conversations()
    print("🔍 Recent unique contacts:")
    for email, (display_name, last_active) in people:
        print(f"- {display_name} ({email}) (Last Active: {last_active})")

    # Test searching for a specific first name
    search_name = "Peter"
    results = search_contacts_by_first_name(people, search_name)
    
    if results:
        print(f"\n🔍 Contacts matching '{search_name}':")
        for email, last_active in results:
            print(f"- {email} (Last Active: {last_active})")
    else:
        print(f"\n❌ No contacts found with the name '{search_name}'.")
    #ensure_webhook_exists()  # Ensure a Webex webhook is set up before running
    #app.run(host="0.0.0.0", port=5001, debug=True)