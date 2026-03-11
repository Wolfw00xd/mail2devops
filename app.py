import base64
import json
import re
import os
import requests
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# -----------------------------
# LOAD ENV
# -----------------------------
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

AZURE_ORG = os.getenv("AZURE_ORG")
AZURE_PROJECT = os.getenv("AZURE_PROJECT")
AZURE_PAT = os.getenv("AZURE_PAT")

GMAIL_SUBJECT = os.getenv("GMAIL_SUBJECT")
GMAIL_FROM = os.getenv("GMAIL_FROM")

AREA_PATH = os.getenv("AREA_PATH")
ITERATION_PATH = os.getenv("ITERATION_PATH")

TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")

PARENT_TASK = os.getenv("PARENT_TASK")

# -----------------------------
# HELPERS
# -----------------------------

def sanitize(text: str) -> str:
    """Remove control characters and trim."""
    if not text:
        return ""
    return re.sub(r"[\u0000-\u001F\u007F]", "", text).strip()


def get_access_token():
    print("[AUTH] Getting access token...")
    url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token"
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    print("[AUTH] Access token received")
    return r.json()["access_token"]


def get_gmail_service():
    token = get_access_token()
    creds = Credentials(token)
    service = build("gmail", "v1", credentials=creds)
    print("[GMAIL] Gmail service initialized")
    return service


def get_unread_messages(service):
    print("[GMAIL] Looking for unread emails...")

    query = f"is:unread subject:{GMAIL_SUBJECT} from:{GMAIL_FROM}"

    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=10
    ).execute()

    messages = results.get("messages", [])
    print(f"[GMAIL] Found {len(messages)} new messages")
    return messages


def get_message_body(service, msg_id):
    print(f"[GMAIL] Reading email ID: {msg_id}")
    msg = service.users().messages().get(userId="me", id=msg_id).execute()

    payload = msg["payload"]
    body_data = ""

    if "parts" in payload:
        body_data = payload["parts"][0]["body"].get("data", "")
    else:
        body_data = payload["body"].get("data", "")

    decoded = base64.urlsafe_b64decode(body_data).decode("utf-8")
    print(f"[GMAIL] Email body:\n{decoded}")
    return decoded


def mark_as_read(service, msg_id):
    print(f"[GMAIL] Marking message {msg_id} as read...")
    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()
    print(f"[GMAIL] Email {msg_id} marked as read")


def send_to_teams(link, title):
    if not TEAMS_WEBHOOK_URL:
        print("[TEAMS] Webhook URL not set")
        return
    payload = {
        "text": f"✅ User Story created: [{title}]({link})"
    }
    r = requests.post(TEAMS_WEBHOOK_URL, json=payload)
    if r.status_code != 200:
        print("[TEAMS ERROR]", r.status_code, r.text)
    else:
        print("[TEAMS] Message sent")


def parse_email_body(body: str):
    """Parse email body by flags User:, Title:, Description:"""
    user = title = description = ""
    lines = body.splitlines()
    capture_desc = False
    capture_title = False
    capture_user = False

    for line in lines:
        line = sanitize(line)
        if line.startswith("User:"):
            capture_user = True
            continue
        elif line.startswith("Title:"):
            capture_title = True
            continue
        elif line.startswith("Description:"):
            capture_desc = True
            continue

        if capture_user and line:
            user = line
            capture_user = False
        elif capture_title and line:
            title = line
            capture_title = False
        elif capture_desc:
            description += line + "\n"

    return user.strip(), title.strip(), description.strip()


def create_azure_story(user, title, description):
    title = sanitize(title)
    description = sanitize(description)

    if not description:
        print("[WARN] Description empty — set the default value")
        description = "TBD"

    print(f'[AZURE] Creating a User Story: "{title}"')

    url = f"https://dev.azure.com/{AZURE_ORG}/{AZURE_PROJECT}/_apis/wit/workitems/$User%20Story?api-version=7.0"

    payload = [   
        {"op": "add", "path": "/fields/System.Title", "value": title},
        {"op": "add", "path": "/fields/System.Description", "value": description},
        {"op": "add", "path": "/fields/System.AreaPath", "value": AREA_PATH},
        {"op": "add", "path": "/fields/System.IterationPath", "value": ITERATION_PATH},
        {"op": "add", "path": "/fields/System.History", "value": f"Created automatically - {user}"},
        {"op": "add", "path": "/fields/Custom.BuildEnvironment", "value": "Dev"},
        {"op": "add", "path": "/fields/Custom.BranchName", "value": "main"},
        {"op": "add", "path": "/fields/Microsoft.VSTS.Common.AcceptanceCriteria", "value": "TBD"}
    ]

    headers = {
        "Content-Type": "application/json-patch+json",
        "Authorization": "Basic " + base64.b64encode(f":{AZURE_PAT}".encode()).decode()
    }

    r = requests.post(url, headers=headers, data=json.dumps(payload))

    if r.status_code >= 400:
        print("[AZURE ERROR] Status:", r.status_code)
        print("[AZURE ERROR] Data:", r.text)
        r.raise_for_status()

    data = r.json()
    print("[AZURE] Answer DevOps:", data)
    print(f'[AZURE] User Story created. ID: {data["id"]}')

    if PARENT_TASK:
        link_to_parent(data["id"], PARENT_TASK)

    link = f"https://dev.azure.com/{AZURE_ORG}/{AZURE_PROJECT}/_workitems/edit/{data['id']}"
    send_to_teams(link, title)

    return data["id"]


def link_to_parent(story_id, parent_id):
    print(f"[AZURE] Linking User Story {story_id} to Parent {parent_id}...")
    url = f"https://dev.azure.com/{AZURE_ORG}/{AZURE_PROJECT}/_apis/wit/workitems/{story_id}?api-version=7.0"
    payload = [
        {"op": "add", "path": "/relations/-", "value": {
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": f"https://dev.azure.com/{AZURE_ORG}/{AZURE_PROJECT}/_apis/wit/workItems/{parent_id}"
        }}
    ]
    headers = {
        "Content-Type": "application/json-patch+json",
        "Authorization": "Basic " + base64.b64encode(f":{AZURE_PAT}".encode()).decode()
    }
    r = requests.patch(url, headers=headers, data=json.dumps(payload))
    if r.status_code >= 400:
        print("[AZURE ERROR] Linking failed:", r.status_code, r.text)
    else:
        print(f"[AZURE] User Story {story_id} linked to parent {parent_id}")


# -----------------------------
# MAIN LOGIC
# -----------------------------

def main():
    print("=== START JOB ===")

    service = get_gmail_service()
    messages = get_unread_messages(service)

    for msg in messages:
        msg_id = msg["id"]
        print(f"\n=== Email processing {msg_id} ===")

        body = get_message_body(service, msg_id)

        user, title, description = parse_email_body(body)

        if not title:
            print("[WARN] Title not found. Skip.")
            continue

        print(f"[PARSE] User: {user}")
        print(f"[PARSE] Title: {title}")
        print(f"[PARSE] Description:\n{description}")

        story_id = create_azure_story(user, title, description)
        mark_as_read(service, msg_id)

        print(f"=== Email {msg_id} successfully processed → User Story {story_id} ===")

    print("=== END JOB ===")


if __name__ == "__main__":
    main()