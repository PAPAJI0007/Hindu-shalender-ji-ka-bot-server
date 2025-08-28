import json
import os
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Dict, List
from pathlib import Path
import asyncio
from fbchat_asyncio import Client, Message, ThreadType, Mention, Sticker
import random
import time
import youtube_dl

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
        self.listen_task = None
        self.sticker_task = None
        self.loder_task = None
        self.autoconvo_task = None

    async def start(self):
        try:
            await self.start_listening()
            self.running = True
            self.listen_task = asyncio.create_task(self.listen())
            logger.info("Bot started successfully")
            return True
        except Exception as e:
            logger.error(f"Bot start failed: {e}", exc_info=True)
            return False

    async def stop(self):
        self.running = False
        if self.listen_task:
            self.listen_task.cancel()
        if self.sticker_task:
            self.sticker_task.cancel()
        if self.loder_task:
            self.loder_task.cancel()
        if self.autoconvo_task:
            self.autoconvo_task.cancel()
        await self.stop_listening()
        logger.info("Bot stopped")

    async def on_message(self, author_id, message_object, thread_id, thread_type, **kwargs):
        await self.mark_as_delivered(thread_id, message_object.uid)
        await self.mark_as_read(thread_id)

        if bot_settings["autoSpamAccept"]:
            await self.accept_pending_messages()
        if bot_settings["autoMessageAccept"]:
            await self.approve_message_request(thread_id)

        if author_id != self.uid and message_object.text:
            msg = message_object.text
            if msg.startswith(self.prefix):
                command = msg[len(self.prefix):].strip().split()
                if command:
                    await self.handle_command(command, author_id, message_object, thread_id, thread_type)

    async def on_name_changed(self, thread_id, new_name, author_id, **kwargs):
        if bot_settings["group_name_lock"] and author_id != self.uid:
            await self.change_thread_title(bot_settings.get("locked_group_name", ""), thread_id)

    async def on_nickname_changed(self, thread_id, user_id, new_nickname, author_id, **kwargs):
        if bot_settings["nickname_lock"] and author_id != self.uid:
            await self.change_nickname(bot_settings.get("locked_nickname", ""), user_id, thread_id)

    async def on_person_removed(self, removed_id, author_id, thread_id, **kwargs):
        if bot_settings["antiout"] and author_id != self.uid and removed_id != self.uid:
            await self.add_users_to_group([removed_id], thread_id=thread_id)

    async def sticker_spam(self, thread_id, thread_type):
        while bot_settings["sticker_spam"]:
            await self.send(Sticker("369239263222822"), thread_id=thread_id, thread_type=thread_type)
            await asyncio.sleep(1)

    async def loder_target(self, user_id, thread_id, thread_type, duration):
        end_time = time.time() + int(duration)
        while time.time() < end_time and bot_settings["loder_target"]:
            message = random.choice(abuse_messages) if abuse_messages else "No abuse messages available"
            await self.send(Message(text=message, mentions=[Mention(user_id, length=len(message))]),
                          thread_id=thread_id, thread_type=thread_type)
            await asyncio.sleep(1)

    async def autoconvo(self, thread_id, thread_type, duration):
        end_time = time.time() + int(duration)
        while time.time() < end_time and bot_settings["autoconvo"]:
            message = random.choice(abuse_messages) if abuse_messages else "Hello!"
            await self.send(Message(text=message), thread_id=thread_id, thread_type=thread_type)
            await asyncio.sleep(5)

    async def handle_command(self, command: list, author_id: str, message_object, thread_id: str, thread_type):
        cmd = command[0].lower()
        args = command[1:]
        response = None

        if cmd == "help":
            response = "Available Commands: !help - Show all commands\n!groupnamelock on/off <name> - Lock/unlock group name\n!nicknamelock on/off <nickname> - Lock/unlock all nicknames\n!tid - Get group ID\n!uid - Get your ID\n!uid @mention - Get mentioned user's ID\n!info @mention - Get user information\n!groupinfo - Get group information\n!antiout on/off - Toggle anti-out feature\n!send sticker start/stop - Sticker spam\n!autospam accept - Auto accept spam messages\n!automessage accept - Auto accept message requests\n!loder target on <time> @user - Target a user with timer\n!loder stop - Stop targeting\n!autoconvo on/off <time> - Toggle auto conversation with timer\n!pair - Pair two random group members\n!music <song name> - Download music from YouTube"

        elif cmd == "groupnamelock":
            if author_id == bot_settings["admin_id"]:
                if args[0] == "on" and len(args) > 1:
                    bot_settings["group_name_lock"] = True
                    bot_settings["locked_group_name"] = " ".join(args[1:])
                    await self.change_thread_title(bot_settings["locked_group_name"], thread_id)
                    response = f"Group name locked to: {bot_settings['locked_group_name']}"
                elif args[0] == "off":
                    bot_settings["group_name_lock"] = False
                    response = "Group name unlocked"
                else:
                    response = "Usage: !groupnamelock on/off <name>"
            else:
                response = "Admin only command"

        elif cmd == "nicknamelock":
            if author_id == bot_settings["admin_id"]:
                if args[0] == "on" and len(args) > 1:
                    bot_settings["nickname_lock"] = True
                    bot_settings["locked_nickname"] = " ".join(args[1:])
                    thread_info = await self.fetch_thread_info(thread_id)
                    for user_id in thread_info[thread_id].participants:
                        await self.change_nickname(bot_settings["locked_nickname"], user_id, thread_id)
                    response = f"Nicknames locked to: {bot_settings['locked_nickname']}"
                elif args[0] == "off":
                    bot_settings["nickname_lock"] = False
                    response = "Nicknames unlocked"
                else:
                    response = "Usage: !nicknamelock on/off <nickname>"
            else:
                response = "Admin only command"

        elif cmd == "tid":
            response = f"Group ID: {thread_id}"

        elif cmd == "uid":
            if message_object.mentions:
                mentioned_id = message_object.mentions[0].thread_id
                response = f"User ID: {mentioned_id}"
            else:
                response = f"Your ID: {author_id}"

        elif cmd == "info":
            if message_object.mentions:
                user_id = message_object.mentions[0].thread_id
                user_info = (await self.fetch_user_info(user_id))[user_id]
                response = f"Name: {user_info.name}\nGender: {user_info.gender or 'Unknown'}\nProfile: {user_info.profile_url or 'N/A'}"
            else:
                response = "Please mention a user"

        elif cmd == "groupinfo":
            thread_info = (await self.fetch_thread_info(thread_id))[thread_id]
            response = f"Group Name: {thread_info.name}\nMembers: {len(thread_info.participants)}\nAdmins: {len(thread_info.admin_ids)}"

        elif cmd == "antiout":
            if author_id == bot_settings["admin_id"]:
                if args[0] == "on":
                    bot_settings["antiout"] = True
                    response = "Anti-out enabled"
                elif args[0] == "off":
                    bot_settings["antiout"] = False
                    response = "Anti-out disabled"
                else:
                    response = f"Anti-out status: {'on' if bot_settings['antiout'] else 'off'}"
            else:
                response = "Admin only command"

        elif cmd == "send":
            if author_id == bot_settings["admin_id"]:
                if args[0] == "sticker" and args[1] == "start":
                    bot_settings["sticker_spam"] = True
                    self.sticker_task = asyncio.create_task(self.sticker_spam(thread_id, thread_type))
                    response = "Sticker spam started"
                elif args[0] == "sticker" and args[1] == "stop":
                    bot_settings["sticker_spam"] = False
                    response = "Sticker spam stopped"
                else:
                    response = "Usage: !send sticker start/stop"
            else:
                response = "Admin only command"

        elif cmd == "autospam":
            if author_id == bot_settings["admin_id"]:
                if args[0] == "accept":
                    bot_settings["autoSpamAccept"] = True
                    response = "Auto spam accept enabled"
                else:
                    response = "Usage: !autospam accept"
            else:
                response = "Admin only command"

        elif cmd == "automessage":
            if author_id == bot_settings["admin_id"]:
                if args[0] == "accept":
                    bot_settings["autoMessageAccept"] = True
                    response = "Auto message accept enabled"
                else:
                    response = "Usage: !automessage accept"
            else:
                response = "Admin only command"

        elif cmd == "loder":
            if author_id == bot_settings["admin_id"]:
                if args[0] == "target" and args[1] == "on" and len(args) > 2 and message_object.mentions:
                    time = args[2]
                    user_id = message_object.mentions[0].thread_id
                    bot_settings["loder_target"] = user_id
                    self.loder_task = asyncio.create_task(self.loder_target(user_id, thread_id, thread_type, time))
                    response = f"Targeting started for {time} seconds"
                elif args[0] == "stop":
                    bot_settings["loder_target"] = None
                    response = "Targeting stopped"
                else:
                    response = "Usage: !loder target on <time> @user | !loder stop"
            else:
                response = "Admin only command"

        elif cmd == "autoconvo":
            if author_id == bot_settings["admin_id"]:
                if args[0] == "on" and len(args) > 1:
                    time = args[1]
                    bot_settings["autoconvo"] = True
                    self.autoconvo_task = asyncio.create_task(self.autoconvo(thread_id, thread_type, time))
                    response = f"Auto conversation enabled every {time} seconds"
                elif args[0] == "off":
                    bot_settings["autoconvo"] = False
                    response = "Auto conversation disabled"
                else:
                    response = "Usage: !autoconvo on/off <time>"
            else:
                response = "Admin only command"

        elif cmd == "pair":
            if thread_type == ThreadType.GROUP:
                thread_info = (await self.fetch_thread_info(thread_id))[thread_id]
                participants = thread_info.participants
                user1, user2 = random.sample(participants, 2)
                user1_info = (await self.fetch_user_info(user1))[user1]
                user2_info = (await self.fetch_user_info(user2))[user2]
                response = f"{user1_info.name} paired with {user2_info.name}! ❤️"
            else:
                response = "Use in a group"

        elif cmd == "music":
            song_name = " ".join(args)
            ydl_opts = {'format': 'bestaudio', 'outtmpl': '%(title)s.%(ext)s', 'quiet': True}
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch:{song_name}", download=False)
                if info["entries"]:
                    url = info["entries"][0]["webpage_url"]
                    response = f"Found: {url}"
                else:
                    response = "Song not found"

        if response:
            await self.send(Message(text=response), thread_id=thread_id, thread_type=thread_type)

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

                if await bot_instance.start():
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
                    await bot_instance.stop()
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
    port = int(os.environ.get("PORT", 10000))  # Render का डिफॉल्ट पोर्ट, ENV से लेगा
    logger.info(f"Starting server on port {port}")
    config = uvicorn.Config(app, host="0.0.0.0", port=port, ws_ping_interval=20, ws_ping_timeout=20)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
