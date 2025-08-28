import json
import os
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Dict, List
from pathlib import Path
from fbchat2 import Client, Message, ThreadType, Mention, Sticker
import threading
import random
import time
import youtube_dl
import asyncio

# Logging setup
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# In-memory storage
bot_settings = {
    "autoSpamAccept": False,
    "autoMessageAccept": False,
    "prefix": "!",
    "admin_id": "",
    "running": False,
    "antiout": False,
    "group_name_lock": False,
    "nickname_lock": False,
    "sticker_spam": False,
    "loder_target": None,
    "autoconvo": False
}
abuse_messages: List[str] = []

# File paths
SETTINGS_FILE = Path("settings.json")
ABUSE_FILE = Path("abuse.txt")

# Load settings
def load_settings():
    global bot_settings
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                bot_settings.update(json.load(f))
            logger.info("Settings loaded from file")
        except Exception as e:
            logger.error(f"Failed to load settings: {e}", exc_info=True)

# Save settings
def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(bot_settings, f, indent=2)
        logger.info("Settings saved to file")
    except Exception as e:
        logger.error(f"Failed to save settings: {e}", exc_info=True)

# Load abuse messages
def load_abuse_messages():
    global abuse_messages
    if ABUSE_FILE.exists():
        try:
            with open(ABUSE_FILE, "r") as f:
                abuse_messages = [line.strip() for line in f if line.strip()]
            logger.info(f"Loaded {len(abuse_messages)} abuse messages")
        except Exception as e:
            logger.error(f"Failed to load abuse messages: {e}", exc_info=True)

# Save abuse messages
def save_abuse_messages(content: str):
    global abuse_messages
    try:
        abuse_messages = [line.strip() for line in content.splitlines() if line.strip()]
        with open(ABUSE_FILE, "w") as f:
            f.write(content)
        logger.info(f"Saved {len(abuse_messages)} abuse messages")
    except Exception as e:
        logger.error(f"Failed to save abuse messages: {e}", exc_info=True)

load_settings()
load_abuse_messages()

# Custom Facebook Bot
class FacebookBot(Client):
    def __init__(self, session_cookies: dict, prefix: str, admin_id: str):
        super().__init__(session_cookies=session_cookies)
        self.prefix = prefix
        self.admin_id = admin_id
        self.running = False
        self.listen_thread = None
        self.sticker_thread = None
        self.loder_thread = None
        self.autoconvo_thread = None

    def start(self):
        try:
            self.running = True
            self.listen_thread = threading.Thread(target=self.listen)
            self.listen_thread.daemon = True
            self.listen_thread.start()
            logger.info("Bot started successfully")
            return True
        except Exception as e:
            logger.error(f"Bot start failed: {e}", exc_info=True)
            return False

    def stop(self):
        self.running = False
        if self.listen_thread:
            self.listen_thread.join(timeout=5)
        if self.sticker_thread:
            self.sticker_thread.join(timeout=5)
        if self.loder_thread:
            self.loder_thread.join(timeout=5)
        if self.autoconvo_thread:
            self.autoconvo_thread.join(timeout=5)
        self.logout()
        logger.info("Bot stopped")

    def on_message(self, author_id, message_object, thread_id, thread_type, **kwargs):
        self.mark_as_delivered(thread_id, message_object.uid)
        self.mark_as_read(thread_id)

        if bot_settings["autoSpamAccept"]:
            self.accept_pending_messages()
        if bot_settings["autoMessageAccept"]:
            self.approve_message_request(thread_id)

        if author_id != self.uid and message_object.text:
            msg = message_object.text
            if msg.startswith(self.prefix):
                command = msg[len(self.prefix):].strip().split()
                if command:
                    self.handle_command(command, author_id, message_object, thread_id, thread_type)

    def on_name_changed(self, thread_id, new_name, author_id, **kwargs):
        if bot_settings["group_name_lock"] and author_id != self.uid:
            self.change_thread_title(bot_settings.get("locked_group_name", ""), thread_id)

    def on_nickname_changed(self, thread_id, user_id, new_nickname, author_id, **kwargs):
        if bot_settings["nickname_lock"] and author_id != self.uid:
            self.change_nickname(bot_settings.get("locked_nickname", ""), user_id, thread_id)

    def on_person_removed(self, removed_id, author_id, thread_id, **kwargs):
        if bot_settings["antiout"] and author_id != self.uid and removed_id != self.uid:
            self.add_users_to_group([removed_id], thread_id=thread_id)

    def sticker_spam(self, thread_id, thread_type):
        while bot_settings["sticker_spam"]:
            self.send(Sticker("369239263222822"), thread_id=thread_id, thread_type=thread_type)
            time.sleep(1)

    def loder_target(self, user_id, thread_id, thread_type, duration):
        end_time = time.time() + int(duration)
        while time.time() < end_time and bot_settings["loder_target"]:
            message = random.choice(abuse_messages) if abuse_messages else "No abuse messages available"
            self.send(Message(text=message, mentions=[Mention(user_id, length=len(message))]),
                      thread_id=thread_id, thread_type=thread_type)
            time.sleep(1)

    def autoconvo(self, thread_id, thread_type, duration):
        end_time = time.time() + int(duration)
        while time.time() < end_time and bot_settings["autoconvo"]:
            message = random.choice(abuse_messages) if abuse_messages else "Hello!"
            self.send(Message(text=message), thread_id=thread_id, thread_type=thread_type)
            time.sleep(5)

    def handle_command(self, command: list, author_id: str, message_object, thread_id: str, thread_type):
        cmd = command[0].lower()
        args = command[1:]
        response = None

        if cmd == "help":
            response = "Available Commands: !help - Show all commands\n!groupnamelock on/off <name> - Lock/unlock group name\n!nicknamelock on/off <nickname> - Lock/unlock all nicknames\n!tid - Get group ID\n!uid - Get your ID\n!uid @mention - Get mentioned user's ID\n!info @mention - Get user information\n!groupinfo - Get group information\n!antiout on/off - Toggle anti-out feature\n!send sticker start/stop - Sticker spam\n!autospam accept - Auto accept spam messages\n!automessage accept - Auto accept message requests\n!loder target on <time> @user - Target a user with timer\n!loder stop - Stop targeting\n!autoconvo on/off <time> - Toggle auto conversation with timer\n!pair - Pair two random group members\n!music <song name> - Download music from YouTube"

        if response:
            self.send(Message(text=response), thread_id=thread_id, thread_type=thread_type)

# Global bot instance
bot_instance = None

# Serve HTML
@app.get("/")
async def get_root():
    try:
        with open("index.html", "r") as f:
            html = f.read()
        logger.info("Served index.html")
        return HTMLResponse(html)
    except FileNotFoundError:
        logger.error("index.html not found")
        return HTMLResponse("Error: index.html not found", status_code=404)
    except Exception as e:
        logger.error(f"Error serving root: {e}", exc_info=True)
        return HTMLResponse("Server Error", status_code=500)

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    global bot_instance

    await websocket.send_text(json.dumps({"type": "settings", **bot_settings}))
    logger.info("WebSocket connection established")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "log", "message": "Invalid JSON data"}))
                logger.error("Invalid JSON received")
                continue

            if msg["type"] == "start":
                cookie_content = msg.get("cookieContent", "")
                prefix = msg.get("prefix", "!")
                admin_id = msg.get("adminId", "")

                if not cookie_content:
                    await websocket.send_text(json.dumps({"type": "log", "message": "Cookie is required"}))
                    logger.warning("Start requested without cookie")
                    continue

                try:
                    session_cookies = json.loads(cookie_content)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"type": "log", "message": "Invalid cookie JSON"}))
                    logger.error("Invalid cookie JSON")
                    continue

                bot_settings["prefix"] = prefix
                bot_settings["admin_id"] = admin_id
                bot_instance = FacebookBot(session_cookies, prefix, admin_id)

                if bot_instance.start():
                    bot_settings["running"] = True
                    await websocket.send_text(json.dumps({"type": "log", "message": f"Bot started with prefix: {prefix}"}))
                    await websocket.send_text(json.dumps({"type": "status", "running": True}))
                    logger.info(f"Bot started with prefix: {prefix}")
                else:
                    await websocket.send_text(json.dumps({"type": "log", "message": "Failed to start bot: Invalid cookie"}))
                    bot_settings["running"] = False
                    logger.error("Bot start failed: Invalid cookie")

            elif msg["type"] == "stop":
                if bot_instance:
                    bot_instance.stop()
                bot_settings["running"] = False
                await websocket.send_text(json.dumps({"type": "log", "message": "Bot stopped"}))
                await websocket.send_text(json.dumps({"type": "status", "running": False}))
                logger.info("Bot stopped")

            elif msg["type"] == "uploadAbuse":
                content = msg.get("content", "")
                if content:
                    save_abuse_messages(content)
                    await websocket.send_text(json.dumps({"type": "log", "message": f"Abuse file uploaded with {len(abuse_messages)} messages"}))
                    logger.info("Abuse file uploaded")
                else:
                    await websocket.send_text(json.dumps({"type": "log", "message": "No content in abuse file"}))
                    logger.warning("Abuse upload with no content")

            elif msg["type"] == "saveSettings":
                bot_settings["autoSpamAccept"] = msg.get("autoSpamAccept", False)
                bot_settings["autoMessageAccept"] = msg.get("autoMessageAccept", False)
                save_settings()
                await websocket.send_text(json.dumps({"type": "log", "message": "Settings saved"}))
                await websocket.send_text(json.dumps({"type": "settings", **bot_settings}))
                logger.info("Settings saved")

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        await websocket.send_text(json.dumps({"type": "log", "message": f"Server error: {str(e)}"}))

# For standalone run
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 20239))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, ws_ping_interval=20, ws_ping_timeout=20)
