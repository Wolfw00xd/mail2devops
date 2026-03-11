import os
from flask import Flask, redirect, request
from google_auth_oauthlib.flow import Flow

# -----------------------------
# CONFIG
# -----------------------------
CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:3000/oauth2callback"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify"
]

app = Flask(__name__)

# -----------------------------
# 1. Start authorization
# -----------------------------
@app.route("/auth")
def auth():
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uris": [REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",   
        include_granted_scopes="true"
    )
    return redirect(auth_url)

# -----------------------------
# 2. Callback after entering
# -----------------------------
@app.route("/oauth2callback")
def oauth2callback():
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "redirect_uris": [REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )

        flow.fetch_token(code=request.args.get("code"))
        creds = flow.credentials

        print("Access Token:", creds.token)
        print("Refresh Token:", creds.refresh_token)

        return "Authorization complete. Check the console for refresh token"
    except Exception as e:
        print("Error getting token:", e)
        return "Authorization error", 500

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(port=3000, debug=True)