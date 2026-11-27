"""The "/" command menu users see in Telegram, registered through setMyCommands (no BotFather needed)."""
import logging

import config
from services import botapi

log = logging.getLogger("commands")

EVERYONE = [
    ("start", "Welcome & main menu"),
    ("help", "All commands"),
    ("ping", "Check bot speed & uptime"),
    ("id", "Show your Telegram ID"),
    ("settings", "Group / bot settings"),
    ("premium", "Premium info"),
    ("myplaylists", "Your playlists"),
    ("createplaylist", "Create a playlist"),
    ("addtoplaylist", "Add the current song to a playlist"),
    ("playlistinfo", "Show a playlist"),
    ("deleteplaylist", "Delete a playlist"),
]

GROUPS = [
    ("play", "Play a song or link"),
    ("vplay", "Play a video"),
    ("fplay", "Play now, ahead of the queue"),
    ("fvplay", "Play a video now"),
    ("mix", "Queue a mix of related songs"),
    ("search", "Pick from search results"),
    ("playplaylist", "Play one of your playlists"),
    ("skip", "Next song"),
    ("pause", "Pause"),
    ("resume", "Resume"),
    ("stop", "Stop and clear the queue"),
    ("seek", "Jump forward/back (seconds)"),
    ("mute", "Mute the stream"),
    ("unmute", "Unmute the stream"),
    ("volume", "Set volume 1-200"),
    ("queue", "Show the queue"),
    ("remove", "Remove a queued song"),
    ("clear", "Empty the queue"),
    ("shuffle", "Shuffle the queue"),
    ("loop", "Loop off / track / queue"),
    ("autoplay", "Autoplay on / off"),
    ("lyrics", "Lyrics of the current song"),
    ("auth", "Let a member use admin commands"),
    ("unauth", "Remove that permission"),
    ("authlist", "Authorized members"),
    ("tagall", "Mention everyone"),
    ("stoptag", "Stop tagging"),
    ("reload", "Refresh settings"),
]

OWNER = [
    ("owner", "Owner panel (buttons)"),
    ("stats", "Bot statistics"),
    ("av", "Active voice chats"),
    ("diag", "Diagnostics"),
    ("addkey", "Add a YouTube API key"),
    ("keys", "List API keys"),
    ("addproxy", "Add proxies"),
    ("proxies", "List proxies"),
    ("setcookies", "Add cookies"),
    ("cookies", "List cookies"),
    ("grant", "Grant premium"),
    ("revoke", "Revoke premium"),
    ("broadcast", "Message all users"),
    ("emojis", "Premium emoji settings"),
    ("logger", "Toggle the log chat"),
    ("clearass", "Clear cache"),
    ("leaveall", "Helpers leave idle chats"),
]


def _cmds(rows):
    return [{"command": c, "description": d} for c, d in rows]


async def register():
    """Best effort: a failure here must never stop the bot."""
    try:
        await botapi.call("setMyCommands", commands=_cmds(EVERYONE), scope={"type": "all_private_chats"})
        await botapi.call("setMyCommands", commands=_cmds(EVERYONE + GROUPS), scope={"type": "all_group_chats"})
        await botapi.call("setMyCommands", commands=_cmds(EVERYONE + GROUPS))
        if config.OWNER_ID not in (0, 123456789):
            await botapi.call("setMyCommands", commands=_cmds(OWNER + EVERYONE),
                              scope={"type": "chat", "chat_id": config.OWNER_ID})
        log.info("command menu registered")
    except Exception as e:
        log.warning("couldn't register the command menu: %s", e)
