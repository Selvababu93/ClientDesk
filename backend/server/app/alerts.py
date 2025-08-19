import os, json, requests
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")

def send_alert(title: str, text: str):
    if not SLACK_WEBHOOK:
        return
    payload = {"text": f"*{title}*\n{text}"}
    try:
        requests.post(SLACK_WEBHOOK, data=json.dumps(payload), headers={"Content-Type":"application/json"}, timeout=5)
    except Exception:
        pass
