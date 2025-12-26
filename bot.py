# bot.py — Destiny 2 Event Bot (updated)
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import json
import asyncio
import re
import random

# ---------------- CONFIG ----------------
ADMIN_ROLE_NAME = "admin"                # role name to give admin access to event channels
DEFAULT_SERVER_TZ = "America/New_York"   # fallback tz if detection fails
EVENTS_FILE = "events.json"
# ----------------------------------------



intents = discord.Intents.default()
intents.members = True  # Required to fetch members
bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory events store
EVENTS = {}  # event_id -> dict

# Timezone storage
TZ_MAP = {
    "AST": "America/Halifax",
    "EST": "America/New_York",
    "CST": "America/Chicago",
    "PST": "America/Los_Angeles"
}

# Example activity lists (you can edit)
D2_RAIDS = [
    "The Desert Perpetual (Epic)", "The Desert Perpetual", "Salvations Edge", "Root of Nightmares",
    "Crotas End", "Kings Fall", "Vault of Glass", "Vow of the Disciple", "Deep Stone Crypt",
    "Garden of Salvation", "Last Wish"
]
D2_DUNGEONS = [
    "Prophecy", "Duality", "Ghosts of the Deep", "Pit of Heresy", "Grasp of Avarice",
    "Spire of the Watcher", "Sundered Doctrine", "Vesper's Host", "Warlords Ruin", "Equilibrium"
]

# ---------- Persistence ----------
def save_events_to_disk():
    try:
        serializable = {}
        for eid, data in EVENTS.items():
            copy = data.copy()
            copy["start_time"] = copy["start_time"].isoformat()
            serializable[str(eid)] = copy
        with open(EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)
    except Exception as e:
        print("save_events_to_disk error:", e)

def load_events_from_disk():
    try:
        if not os.path.exists(EVENTS_FILE):
            return
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for eid_str, data in raw.items():
            data["start_time"] = datetime.fromisoformat(data["start_time"])
            EVENTS[int(eid_str)] = data
    except Exception as e:
        print("load_events_from_disk error:", e)

@tasks.loop(seconds=30)
async def autosave_task():
    save_events_to_disk()

@autosave_task.error
async def autosave_task_error(error):
    print("[TASK ERROR] autosave_task crashed:", error)

    if not autosave_task.is_running():
        print("[TASK] Restarting autosave_task")
        autosave_task.start()

# ---------- Utilities ----------
def safe_channel_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\- ]+", "", name)
    s = s.strip().lower().replace(" ", "-")
    s = re.sub(r"-+", "-", s)
    return s[:90]

def ensure_event_defaults(event: dict):
    """
    Ensures all required keys exist on an event object.
    Safe to call repeatedly.
    """
    event.setdefault("players", [])
    event.setdefault("alternates", [])
    event.setdefault("interested", [])
    event.setdefault("max_players", None)
    event.setdefault("creator_id", None)
    event.setdefault("text_channel_id", None)
    event.setdefault("voice_channel_id", None)
    event.setdefault("voice_failed", False) # VC Guard
    event.setdefault("description", "None")
    event.setdefault("ended", False)

    # Reminder tracking
    event.setdefault("reminders_sent", {
        "15": False,
        "5": False
    })

async def restore_views_on_startup():
    await bot.wait_until_ready()

    for event_id, event in EVENTS.items():
        try:
            channel = bot.get_channel(event["channel_id"])
            if not channel:
                continue

            msg = await channel.fetch_message(event["message_id"])
            await msg.edit(view=SignupView(event_id))

        except Exception as e:
            print(f"[VIEW RESTORE] Failed for event {event_id}: {e}")

# ---------- Channel creation & permissions ----------
def generate_event_code():
    existing = {e.get("code") for e in EVENTS.values()}
    
    while True:
        code = random.randint(10000, 99999)
        if code not in existing:
            return code

async def post_event_log(guild: discord.Guild, event_id: int, message: str):
    event = EVENTS.get(event_id)
    if not event:
        return

    channel_id = event.get("text_channel_id")
    if not channel_id:
        return

    channel = guild.get_channel(channel_id)
    if not channel:
        return

    try:
        await channel.send(message)
    except Exception as e:
        print(f"[EVENT LOG ERROR] {e}")


async def create_event_text_channel(guild: discord.Guild, activity_name: str, creator: discord.Member, event_id: int):
    event = EVENTS[event_id]
    code = event.get("code", "00000")

    base = f"{activity_name}-{code}"
    channel_name = safe_channel_name(base)

    events_category = discord.utils.get(guild.categories, name="Events")
    if not events_category:
        events_category = await guild.create_category("Events")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),

        guild.me: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True
        ),
    }

    # Creator
    if creator:
        overwrites[creator] = discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True
        )

    # Admin Role
    admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
    if admin_role:
        overwrites[admin_role] = discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True
        )

    # Players & Alternates
    for uid in event.get("players", []) + event.get("alternates", []):
        member = guild.get_member(uid)
        if member:
            overwrites[member] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True
            )

    channel = await guild.create_text_channel(
        channel_name,
        category=events_category,
        overwrites=overwrites
    )

    return channel.id

async def refresh_event_channel_permissions(guild: discord.Guild, event_id: int):
    event = EVENTS.get(event_id)
    if not event:
        return

    channel = guild.get_channel(event.get("text_channel_id"))
    if not channel:
        return

    try:
        admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
        allowed_user_ids = set(event.get("players", []) + event.get("alternates", []))
        creator_id = event.get("creator_id")
        if creator_id:
            allowed_user_ids.add(creator_id)

        # Reset base perms
        await channel.set_permissions(guild.default_role, read_messages=False)
        await channel.set_permissions(guild.me, read_messages=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True)

        if admin_role:
            await channel.set_permissions(admin_role, read_messages=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True)

        # Apply member permissions
        for uid in allowed_user_ids:
            try:
                member = await guild.fetch_member(uid)
                await channel.set_permissions(member, read_messages=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True)
            except Exception as e:
                print(f"[PERMS][ERROR] Could not set permissions for UID {uid}: {e}")

    except Exception as e:
        print(f"[PERMS] General error updating event {event_id}: {e}")
        
async def refresh_event_voice_permissions(guild, event_id):
    event = EVENTS.get(event_id)
    if not event:
        return

    vc = guild.get_channel(event.get("voice_channel_id"))
    if not vc:
        return

    allowed = set(event.get("players", []) + event.get("alternates", []))

    for uid in allowed:
        try:
            member = await guild.fetch_member(uid)
            await vc.set_permissions(
                member,
                connect=True,
                speak=True,
                use_vad=True,
                stream=True,
                video=True
            )
        except Exception:
            pass

async def create_event_voice_channel(guild: discord.Guild, event):
    category = discord.utils.get(guild.categories, name="Events")
    if not category:
        category = await guild.create_category("Events")

    code = event.get("code", "00000")
    clean_name = event["name"]
    if ": " in clean_name:
        clean_name = clean_name.split(": ", 1)[1]
    name = safe_channel_name(f"{clean_name}-{code}")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            connect=True,   # may join & listen
            speak=False,    # cannot talk
            stream=False
        ),

        guild.me: discord.PermissionOverwrite(
            connect=True,
            speak=True,
            stream=True
        )
    }

    vc = await guild.create_voice_channel(
        name=name,
        category=category,
        overwrites=overwrites
    )

    # Players & Alternates get full permissions
    for uid in event.get("players", []) + event.get("alternates", []):
        member = guild.get_member(uid)
        if member:
            await vc.set_permissions(
                member,
                connect=True,
                speak=True,
                stream=True
            )

    return vc.id

# ---------- Signup View ----------
class SignupView(View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    @discord.ui.button(label="Join", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: Button):
        await handle_signup(interaction, self.event_id, as_alternate=False)

    @discord.ui.button(label="Join as Alternate", style=discord.ButtonStyle.blurple)
    async def alt_button(self, interaction: discord.Interaction, button: Button):
        await handle_signup(interaction, self.event_id, as_alternate=True)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: Button):
        await handle_leave(interaction, self.event_id)

    @discord.ui.button(label="Edit Event", style=discord.ButtonStyle.gray, emoji="🛠️")
    async def edit_button(self, interaction: discord.Interaction, button: Button):
        await open_edit_modal(interaction, self.event_id)


# ---------- Handlers ----------
async def handle_signup(interaction: discord.Interaction, event_id: int, as_alternate: bool):
    event = EVENTS.get(event_id)
    if not event:
        return await interaction.response.send_message("Event not found.", ephemeral=True)

    uid = interaction.user.id
    guild = interaction.guild

    # Mark interested
    if uid not in event.get("interested", []):
        event.setdefault("interested", []).append(uid)

    # Avoid duplicates
    if uid in event.get("players", []) or uid in event.get("alternates", []):
        return await interaction.response.send_message("You are already signed up.", ephemeral=True)

    max_players = event.get("max_players")

    # ----- JOIN AS ALTERNATE -----
    if as_alternate:
        if max_players is None or (max_players >= 3 and max_players <= 6):
            event.setdefault("alternates", []).append(uid)

            await interaction.response.send_message("✅ Added as an alternate.", ephemeral=True)

            # 🔹 NEW: Log to event text channel
            await post_event_log(
                guild,
                event_id,
                f"🕙 **{interaction.user.display_name}** joined as an alternate."
            )

        else:
            await interaction.response.send_message("❌ Alternates not allowed for unlimited events.", ephemeral=True)
            return

    # ----- JOIN AS PLAYER -----
    else:
        if max_players is None or len(event.get("players", [])) < max_players:
            event.setdefault("players", []).append(uid)

            await interaction.response.send_message("✅ You joined the event!", ephemeral=True)

            # 🔹 NEW: Log to event text channel
            await post_event_log(
                guild,
                event_id,
                f"✅ **{interaction.user.display_name}** joined the event."
            )

        else:
            # Full, add as alternate if allowed
            if max_players >= 3 and max_players <= 6:
                event.setdefault("alternates", []).append(uid)

                await interaction.response.send_message("Event full — added as alternate.", ephemeral=True)

                # 🔹 NEW: Log to event text channel
                await post_event_log(
                    guild,
                    event_id,
                    f"🕙 **{interaction.user.display_name}** added as alternate (event was full)."
                )

            else:
                await interaction.response.send_message("Event full.", ephemeral=True)
                return

    # Refresh permissions + UI
    await refresh_event_channel_permissions(guild, event_id)
    await update_event_message(bot, event_id)
    save_events_to_disk()


async def send_dm_reminder(guild: discord.Guild, event: dict, message: str):
    user_ids = set()

    user_ids.update(event.get("players", []))
    user_ids.update(event.get("alternates", []))

    if event.get("creator_id"):
        user_ids.add(event["creator_id"])

    for uid in user_ids:
        try:
            member = await guild.fetch_member(uid)
            await member.send(
                f"{message}\n\n"
                f"**Event:** {event['name']}\n"
                f"**Starts:** <t:{int(event['start_time'].timestamp())}:R>\n"
                f"🔊 Voice channel will open shortly."
            )
        except discord.Forbidden:
            # User has DMs disabled — ignore
            pass
        except Exception as e:
            print(f"[DM ERROR] Could not DM user {uid}: {e}")

@tasks.loop(seconds=60)
async def reminder_and_cleanup_task():
    now = datetime.now(tz=ZoneInfo("UTC"))
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    for event_id, event in list(EVENTS.items()):
        # 🔹 Ensure schema safety for older events
        ensure_event_defaults(event)

        start = event["start_time"]
        delta = (start - now).total_seconds() / 60

        # ---------- REMINDER: 15 MIN ----------
        if 14.5 <= delta <= 15.5 and not event["reminders_sent"]["15"]:
            event["reminders_sent"]["15"] = True

            # Create voice channel at 15 min mark
            if not event.get("voice_channel_id") and not event.get("voice_failed"):
                try:
                    vc_id = await create_event_voice_channel(guild, event)
                    event["voice_channel_id"] = vc_id
                    save_events_to_disk()
                except Exception as e:
                    event["voice_failed"] = True # VC Guard
                    save_events_to_disk()
                    print(f"[VOICE ERROR] Failed to create VC for event {event_id}: {e}")

            await send_dm_reminder(guild, event, "⏰ **15 minutes until start!**")
            save_events_to_disk()

        # ---------- REMINDER: 5 MIN ----------
        if 4.5 <= delta <= 5.5 and not event["reminders_sent"]["5"]:
            event["reminders_sent"]["5"] = True
            await send_dm_reminder(guild, event, "⚠️ **5 minutes until start!**")
            save_events_to_disk()

        # ---------- CLEANUP CHECK ----------
        if now > start + timedelta(hours=1):
            vc_id = event.get("voice_channel_id")
            vc = guild.get_channel(vc_id) if vc_id else None

            # Only cleanup once VC is empty
            if vc and len(vc.members) > 0:
                continue

            await cleanup_event(guild, event_id)

@reminder_and_cleanup_task.error
async def reminder_and_cleanup_task_error(error):
    print("[TASK ERROR] reminder_and_cleanup_task crashed:", error)

    if not reminder_and_cleanup_task.is_running():
        print("[TASK] Restarting reminder_and_cleanup_task")
        reminder_and_cleanup_task.start()

async def cleanup_event(guild: discord.Guild, event_id: int):
    event = EVENTS.get(event_id)
    if not event:
        return

    # Delete signup message
    try:
        chan = guild.get_channel(event["channel_id"])
        if chan:
            msg = await chan.fetch_message(event["message_id"])
            await msg.delete()
    except Exception:
        pass

    # Delete text channel
    try:
        tc = guild.get_channel(event.get("text_channel_id"))
        if tc:
            await tc.delete()
    except Exception:
        pass

    # Delete voice channel
    try:
        vc = guild.get_channel(event.get("voice_channel_id"))
        if vc:
            await vc.delete()
    except Exception:
        pass

    # Delete scheduled event
    try:
        sched = await guild.fetch_scheduled_event(event_id)
        await sched.delete()
    except Exception:
        pass

    # ✅ SAFE removal (no KeyError)
    EVENTS.pop(event_id, None)
    save_events_to_disk()

    print(f"Cleaned up event {event_id}")

async def apply_event_edits(guild: discord.Guild, event_id: int):
    event = EVENTS[event_id]

    # Update scheduled event
    try:
        sched = await guild.fetch_scheduled_event(event_id)
        # Build signup post URL
        try:
            guild_id = guild.id
            channel_id = event["channel_id"]
            message_id = event["message_id"]
            message_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
        except Exception:
            message_url = None

        # Preserve + append signup link
        desc = (event.get("description") or "None")
        if message_url:
            desc = f"{desc}\n\n👉 **Signup Post:** {message_url}"

        try:
            await sched.edit(
                name=event["name"],
                description=desc,
                start_time=event["start_time"]
            )
        except Exception as e:
            print(f"[EVENT LINK ERROR] Failed to update event description: {e}")
    except Exception:
        pass

    # ---------- Rename Channels (preserve event code & original base) ----------
    code = event.get("code", "00000")
    base = event.get("base_name", safe_channel_name(event["name"]))
    safe_name = f"{base}-{code}"

    # Rename text channel
    tc = guild.get_channel(event.get("text_channel_id"))
    if tc:
        await tc.edit(name=safe_name)

    # Rename voice channel if exists
    vc = guild.get_channel(event.get("voice_channel_id"))
    if vc:
        await vc.edit(name=safe_name)

    await update_event_message(bot, event_id)
    await refresh_event_channel_permissions(guild, event_id)

async def handle_leave(interaction: discord.Interaction, event_id: int):
    event = EVENTS.get(event_id)
    if not event:
        return await interaction.response.send_message("Event not found.", ephemeral=True)

    uid = interaction.user.id
    guild = interaction.guild

    was_player = uid in event.get("players", [])
    was_alt = uid in event.get("alternates", [])

    # If not signed up
    if not was_player and not was_alt:
        return await interaction.response.send_message("You are not signed up.", ephemeral=True)

    # ---------- REMOVE PLAYER ----------
    if was_player:
        event["players"].remove(uid)

        await interaction.response.send_message("❌ You left the event.", ephemeral=True)

        # 🔹 LOG TO EVENT CHANNEL
        await post_event_log(
            guild,
            event_id,
            f"❌ **{interaction.user.display_name}** left the event."
        )

        # If alternates exist, promote first alternate
        if event.get("alternates"):
            new_player = event["alternates"].pop(0)
            event["players"].append(new_player)

            member = guild.get_member(new_player)

            # 🔹 Notify promoted user privately
            try:
                await member.send(f"🎉 You have been promoted from alternate to main slot for **{event['name']}**!")
            except:
                pass

            # 🔹 Log promotion in event channel
            await post_event_log(
                guild,
                event_id,
                f"⬆️ **{member.display_name}** has been promoted from alternate to player."
            )

    # ---------- REMOVE ALTERNATE ----------
    elif was_alt:
        event["alternates"].remove(uid)

        await interaction.response.send_message("❌ You are no longer an alternate.", ephemeral=True)

        # 🔹 LOG TO EVENT CHANNEL
        await post_event_log(
            guild,
            event_id,
            f"❌ **{interaction.user.display_name}** removed themselves as an alternate."
        )

    # ---------- FINALIZE ----------
    await refresh_event_channel_permissions(guild, event_id)
    await update_event_message(bot, event_id)
    save_events_to_disk()


# ---------- Message / Event Updates ----------
async def update_event_message(bot_client: commands.Bot, event_id: int):
    event = EVENTS.get(event_id)
    if not event:
        return
    try:
        channel = bot_client.get_channel(event["channel_id"])
        if not channel:
            return
        msg = await channel.fetch_message(event["message_id"])
    except Exception:
        return

    players_section = "None"
    if event.get("players"):
        players_section = "\n".join(f"{i+1}. <@{uid}>" for i, uid in enumerate(event["players"]))

    alts_section = "None"
    if event.get("alternates"):
        alts_section = "\n".join(f"A{i+1}. <@{uid}>" for i, uid in enumerate(event["alternates"]))

    interested_count = len(event.get("interested", []))
    desc = event.get("description") or "None"
    text_channel_ref = f"<#{event['text_channel_id']}>" if event.get("text_channel_id") else "None"

    roster_text = (
        f"**{event['name']}**\n"
        f"**Starts:** <t:{int(event['start_time'].timestamp())}:F>\n"
        f"**Text Channel:** {text_channel_ref}\n"
        f"**Description:** {desc}\n\n"
        f"**Players ({len(event.get('players', []))}/{event.get('max_players') or '∞'}):**\n{players_section}\n\n"
        f"**Alternates:**\n{alts_section}\n\n"
        f"💬 Interested: {interested_count}\n"
    )

    try:
        await msg.edit(content=roster_text, view=SignupView(event_id))
    except Exception as e:
        print("update_event_message error:", e)

# ---------- Modals & Slash Commands ----------
class EventModal(Modal):
    def __init__(
        self,
        interaction: discord.Interaction,
        activity_name: str,
        activity_type: str,
        max_players: int = None
    ):
        super().__init__(title="Set Date & Time for Event")

        self.interaction = interaction
        self.activity_name = activity_name
        self.activity_type = activity_type
        self.max_players = max_players

        self.date_input = TextInput(
            label="Event Date (YYYY-MM-DD)",
            placeholder="2025-12-12",
            required=True
        )

        self.time_input = TextInput(
            label="Event Time (HH:MM AM/PM)",
            placeholder="07:30 PM",
            required=True
        )

        self.timezone_input = TextInput(
            label="Timezone (AST / EST / CST / PST)",
            placeholder="est (default)",
            required=False
        )

        self.description_input = TextInput(
            label="Description (optional)",
            style=discord.TextStyle.paragraph,
            required=False
        )

        self.add_item(self.date_input)
        self.add_item(self.time_input)
        self.add_item(self.timezone_input)
        self.add_item(self.description_input)

    async def on_submit(self, modal_interaction: discord.Interaction):
        try:
            await modal_interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        # ---------- Parse date / time / timezone ----------
        try:
            dt_str = f"{self.date_input.value} {self.time_input.value}"
            naive_dt = datetime.strptime(dt_str, "%Y-%m-%d %I:%M %p")

            tz_code = (self.timezone_input.value or "EST").strip().upper()
            if tz_code not in TZ_MAP:
                return await modal_interaction.followup.send(
                    "❌ Invalid timezone. Use AST, EST, CST, or PST.",
                    ephemeral=True
                )

            user_tz = ZoneInfo(TZ_MAP[tz_code])
            localized_dt = naive_dt.replace(tzinfo=user_tz)
            start_time = localized_dt.astimezone(ZoneInfo("UTC"))

        except Exception:
            return await modal_interaction.followup.send(
                "❌ Invalid date, time, or timezone format.",
                ephemeral=True
            )

        duration = timedelta(hours=2 if self.activity_type == "raid" else 1)
        location = "A voice channel will open 15min before the event"
        description = self.description_input.value or "None"

        try:
            event = await modal_interaction.guild.create_scheduled_event(
                name=f"{self.activity_type.capitalize()}: {self.activity_name}",
                description=f"{description}\nCreated by: {modal_interaction.user.display_name}",
                start_time=start_time,
                end_time=start_time + duration,
                entity_type=discord.EntityType.external,
                location=location,
                privacy_level=discord.PrivacyLevel.guild_only
            )
        except Exception as e:
            return await modal_interaction.followup.send(
                f"❌ Failed to create scheduled event: {e}",
                ephemeral=True
            )

        EVENTS[event.id] = {
            "code": generate_event_code(),
            "type": self.activity_type,
            "max_players": self.max_players,
            "players": [modal_interaction.user.id],
            "alternates": [],
            "interested": [modal_interaction.user.id],
            "channel_id": modal_interaction.channel.id,
            "message_id": None,
            "name": event.name,
            "start_time": start_time,
            "creator_id": modal_interaction.user.id,
            "text_channel_id": None,
            "description": description,
            "timezone": tz_code,
            "base_name": safe_channel_name(self.activity_name)
        }

        # ---------- Create text channel ----------
        text_channel_id = await create_event_text_channel(
            modal_interaction.guild,
            self.activity_name,
            modal_interaction.user,
            event.id
        )

        EVENTS[event.id]["text_channel_id"] = text_channel_id

        # ---------- Send signup message ----------
        msg = await modal_interaction.channel.send(
            f"**Event:** {event.name}\n"
            f"**Starts:** <t:{int(start_time.timestamp())}:F>\n"
            f"**Text Channel:** <#{text_channel_id}>\n"
            f"**Description:** {description}\n\n"
            f"**Players (1/{self.max_players or '∞'}):**\n"
            f"1. {modal_interaction.user.mention}\n\n"
            f"**Alternates:**\nNone\n\n"
            f"Sign up below!",
            view=SignupView(event.id)
        )

        EVENTS[event.id]["message_id"] = msg.id
        save_events_to_disk()

        # -------------------------------
        # 🔗 ADD THIS
        # Build message URL
        guild_id = modal_interaction.guild.id
        channel_id = modal_interaction.channel.id
        message_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{msg.id}"

        # Update scheduled event description to include it
        try:
            await event.edit(
                description=f"{description}\n\n👉 **Signup Post:** {message_url}"
            )
        except Exception as e:
            print(f"[EVENT LINK ERROR] Failed to update event description: {e}")
        # -------------------------------

        await modal_interaction.followup.send(
            "✅ Event created — you were added automatically.",
            ephemeral=True
        )


# ---------- Edit event -----------

class EditEventModal(discord.ui.Modal, title="Edit Event"):
    def __init__(self, event_id: int):
        super().__init__()
        self.event_id = event_id
        event = EVENTS.get(event_id)

        # Safety for older events
        event.setdefault("timezone", "EST")

        event_tz = ZoneInfo(TZ_MAP[event["timezone"]])

        self.name_input = TextInput(
            label="Event Name",
            default=event.get("name", ""),
            required=False
        )

        self.date_input = TextInput(
            label="Date (YYYY-MM-DD)",
            default=event["start_time"]
                .astimezone(event_tz)
                .strftime("%Y-%m-%d"),
            required=False
        )

        self.time_input = TextInput(
            label="Time (HH:MM AM/PM)",
            default=event["start_time"]
                .astimezone(event_tz)
                .strftime("%I:%M %p"),
            required=False
        )

        self.description_input = TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=event.get("description", ""),
            required=False
        )

        self.max_players_input = TextInput(
            label="Max Players (blank = unchanged)",
            default=str(event["max_players"]) if event.get("max_players") else "",
            required=False
        )

        self.add_item(self.name_input)
        self.add_item(self.date_input)
        self.add_item(self.time_input)
        self.add_item(self.description_input)
        self.add_item(self.max_players_input)


    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        event = EVENTS.get(self.event_id)
        if not event:
            return await interaction.followup.send("❌ Event not found.", ephemeral=True)

        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if interaction.user.id != event["creator_id"] and admin_role not in interaction.user.roles:
            return await interaction.followup.send("❌ You cannot edit this event.", ephemeral=True)

        time_changed = False

        # ----- Name -----
        if self.name_input.value.strip():
            event["name"] = self.name_input.value.strip()

        # ----- Description -----
        if self.description_input.value is not None:
            event["description"] = self.description_input.value.strip() or "None"

        # ----- Date / Time / Timezone -----
        if self.date_input.value.strip() or self.time_input.value.strip():
            try:
                tz_code = event.get("timezone", "EST")
                if tz_code not in TZ_MAP:
                    tz_code = "EST"

                user_tz = ZoneInfo(TZ_MAP[tz_code])

                d = self.date_input.value.strip() or event["start_time"].astimezone(
                    user_tz
                ).strftime("%Y-%m-%d")

                t = self.time_input.value.strip() or event["start_time"].astimezone(
                    user_tz
                ).strftime("%I:%M %p")

                naive = datetime.strptime(f"{d} {t}", "%Y-%m-%d %I:%M %p")

                event["start_time"] = naive.replace(
                    tzinfo=user_tz
                ).astimezone(ZoneInfo("UTC"))

                event["timezone"] = tz_code
                time_changed = True

            except ValueError:
                return await interaction.followup.send(
                    "❌ Invalid date or time format.",
                    ephemeral=True
                )

        # ----- Max Players -----
        if self.max_players_input.value.strip():
            try:
                limit = int(self.max_players_input.value.strip())
                event["max_players"] = limit

                while len(event["players"]) > limit:
                    event.setdefault("alternates", []).append(
                        event["players"].pop()
                    )
            except ValueError:
                return await interaction.followup.send(
                    "❌ Max players must be a number.",
                    ephemeral=True
                )

        # ----- Reset reminders if time changed -----
        if time_changed:
            event["reminders_sent"] = {"15": False, "5": False}

        await apply_event_edits(interaction.guild, self.event_id)
        save_events_to_disk()

        await interaction.followup.send(
            "✅ Event updated successfully.",
            ephemeral=True
        )


async def post_reminder(guild, event, message):
    channel = guild.get_channel(event["channel_id"])
    if not channel:
        return

    await channel.send(
        f"{message}\n"
        f"**Event:** {event['name']}\n"
        f"**Starts:** <t:{int(event['start_time'].timestamp())}:R>\n"
        f"🔊 Voice channel will be used for the run."
    )

async def open_edit_modal(interaction: discord.Interaction, event_id: int):
    event = EVENTS.get(event_id)
    if not event:
        return await interaction.response.send_message("Event not found.", ephemeral=True)

    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
    if interaction.user.id != event["creator_id"] and admin_role not in interaction.user.roles:
        return await interaction.response.send_message("You cannot edit this event.", ephemeral=True)

    await interaction.response.send_modal(EditEventModal(event_id))

# ------------ Slash commands -------------------
@bot.tree.command(name="raid", description="Create a Destiny 2 raid event.")
@app_commands.describe(raid_name="Which raid?")
async def raid(interaction: discord.Interaction, raid_name: str):
    await interaction.response.send_modal(EventModal(interaction, raid_name, "raid", max_players=6))

@raid.autocomplete("raid_name")
async def raid_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=r, value=r) for r in D2_RAIDS if current.lower() in r.lower()][:25]

@bot.tree.command(name="dungeon", description="Create a Destiny 2 dungeon event.")
@app_commands.describe(dungeon_name="Which dungeon?")
async def dungeon(interaction: discord.Interaction, dungeon_name: str):
    await interaction.response.send_modal(EventModal(interaction, dungeon_name, "dungeon", max_players=3))

@dungeon.autocomplete("dungeon_name")
async def dungeon_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=d, value=d) for d in D2_DUNGEONS if current.lower() in d.lower()][:25]

# /other command
@bot.tree.command(name="other", description="Create a custom event with optional player limit.")
@app_commands.describe(title="Event title", max_players="Optional: Max number of players")
async def other(interaction: discord.Interaction, title: str, max_players: str = None):
    try:
        max_players_int = int(max_players) if max_players else None
    except:
        max_players_int = None
    await interaction.response.send_modal(EventModal(interaction, title, "other", max_players=max_players_int))

# ---------- Cleanup: message deleted or admin cancel ----------
@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    for event_id, data in list(EVENTS.items()):
        if data.get("message_id") == payload.message_id:
            guild = bot.get_guild(payload.guild_id)
            if not guild:
                del EVENTS[event_id]
                save_events_to_disk()
                return

            # ---------- DELETE TEXT CHANNEL ----------
            text_chan = guild.get_channel(data.get("text_channel_id"))
            try:
                if text_chan:
                    await text_chan.delete()
            except Exception:
                pass

            # ---------- 🧹 NEW: DELETE VOICE CHANNEL ----------
            try:
                vc = guild.get_channel(data.get("voice_channel_id"))
                if vc:
                    await vc.delete()
            except Exception as e:
                print(f"[CLEANUP][VOICE] Failed to delete VC: {e}")

            # ---------- DELETE SCHEDULED EVENT ----------
            try:
                scheduled = await guild.fetch_scheduled_event(event_id)
                await scheduled.delete()
            except Exception:
                pass

            # ---------- REMOVE FROM MEMORY ----------
            del EVENTS[event_id]
            save_events_to_disk()

            print(f"Removed event {event_id} because signup message was deleted.")
            return

@bot.event
async def on_scheduled_event_delete(scheduled_event: discord.ScheduledEvent):
    event_id = scheduled_event.id
    data = EVENTS.get(event_id)

    if not data:
        return

    guild = scheduled_event.guild
    if not guild:
        EVENTS.pop(event_id, None)
        save_events_to_disk()
        return

    # ---------- DELETE TEXT CHANNEL ----------
    try:
        tc = guild.get_channel(data.get("text_channel_id"))
        if tc:
            await tc.delete()
    except Exception as e:
        print(f"[CLEANUP][TEXT] Failed: {e}")

    # ---------- DELETE VOICE CHANNEL ----------
    try:
        vc = guild.get_channel(data.get("voice_channel_id"))
        if vc:
            await vc.delete()
    except Exception as e:
        print(f"[CLEANUP][VOICE] Failed: {e}")

    # ---------- DELETE SIGNUP MESSAGE ----------
    try:
        chan = bot.get_channel(data.get("channel_id"))
        if chan:
            msg = await chan.fetch_message(data.get("message_id"))
            await msg.delete()
    except Exception:
        pass

    # ---------- REMOVE FROM MEMORY ----------
    EVENTS.pop(event_id, None)
    save_events_to_disk()

    print(f"Removed event {event_id} because Discord Scheduled Event was deleted.")


@bot.tree.command(name="cancel_event", description="Admin: Cancel an event by ID (deletes channel & event).")
@app_commands.describe(event_id="The scheduled event ID (numeric)")
async def cancel_event(interaction: discord.Interaction, event_id: int):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
    if admin_role not in interaction.user.roles:
        return await interaction.response.send_message("You are not authorized to cancel events.", ephemeral=True)

    data = EVENTS.get(event_id)
    if not data:
        return await interaction.response.send_message("Event not found.", ephemeral=True)

    # delete text channel
    text_chan = interaction.guild.get_channel(data.get("text_channel_id"))
    if text_chan:
        try:
            await text_chan.delete()
        except Exception:
            pass

    # delete signup message
    try:
        chan = bot.get_channel(data["channel_id"])
        if chan:
            msg = await chan.fetch_message(data["message_id"])
            await msg.delete()
    except Exception:
        pass

    # delete scheduled event
    try:
        scheduled = await interaction.guild.fetch_scheduled_event(event_id)
        await scheduled.delete()
    except Exception:
        pass

    # delete voice channel
    try:
        vc = interaction.guild.get_channel(data.get("voice_channel_id"))
        if vc:
            await vc.delete()
    except Exception:
        pass
        
    del EVENTS[event_id]
    save_events_to_disk()
    await interaction.response.send_message(f"Event {event_id} cancelled and removed.", ephemeral=True)

# ---------- Bot startup ----------
@bot.event
async def on_ready():
    load_events_from_disk()

    # 1️⃣ MIGRATE OLD EVENTS (schema safety)
    for event in EVENTS.values():
        ensure_event_defaults(event)

    guild = bot.guilds[0] if bot.guilds else None

    # 2️⃣ CLEAN UP STALE EVENTS (JSON drift fix)
    if guild:
        for eid in list(EVENTS.keys()):
            try:
                await guild.fetch_scheduled_event(eid)
            except Exception:
                del EVENTS[eid]

        save_events_to_disk()

    # 3️⃣ START BACKGROUND TASKS
    autosave_task.start()
    reminder_and_cleanup_task.start()

    # 4️⃣ SYNC SLASH COMMANDS
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Failed to sync commands:", e)

    # 5️⃣ RESTORE BUTTON VIEWS  ← 🔥 THIS GOES HERE
    await restore_views_on_startup()

    # 6️⃣ REFRESH CHANNEL PERMISSIONS
    if guild:
        await asyncio.sleep(2)
        for eid in list(EVENTS.keys()):
            try:
                await refresh_event_channel_permissions(guild, eid)
            except Exception:
                pass

    print(f"Eyes up guardian, startup complete.")



# ---------- Run ----------
if __name__ == "__main__":
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("ERROR: BOT_TOKEN not set.")
        exit(1)
    bot.run(token)
