import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
import pytz
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -- Version 0.22 --

# File paths
CONFIG_DIR = "configs"
EVENTS_DIR = "events"
DESTINY_RAIDS_FILE = "destiny_raids.json"
DESTINY_DUNGEONS_FILE = "destiny_dungeons.json"

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(EVENTS_DIR, exist_ok=True)

# Initialize default Destiny 2 content
DEFAULT_RAIDS = [
    "Last Wish", "Garden of Salvation", "Deep Stone Crypt",
    "Vault of Glass", "Vow of the Disciple", "King's Fall",
    "Root of Nightmares", "Crota's End", "Salvation's Edge",
    "The Desert Perpetual"
]
 
DEFAULT_DUNGEONS = [
    "Shattered Throne", "Pit of Heresy", "Prophecy",
    "Grasp of Avarice", "Duality", "Spire of the Watcher",
    "Ghosts of the Deep", "Warlord's Ruin", "Vesper's Host",
    "Equilibrium"
]

def init_destiny_files():
    if not os.path.exists(DESTINY_RAIDS_FILE):
        with open(DESTINY_RAIDS_FILE, 'w') as f:
            json.dump(DEFAULT_RAIDS, f, indent=2)
    
    if not os.path.exists(DESTINY_DUNGEONS_FILE):
        with open(DESTINY_DUNGEONS_FILE, 'w') as f:
            json.dump(DEFAULT_DUNGEONS, f, indent=2)

def load_destiny_content(file_path):
    with open(file_path, 'r') as f:
        return json.load(f)

def get_config_path(guild_id):
    return os.path.join(CONFIG_DIR, f"{guild_id}.json")

def get_events_path(guild_id):
    return os.path.join(EVENTS_DIR, f"{guild_id}.json")

def load_config(guild_id):
    path = get_config_path(guild_id)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return None

def save_config(guild_id, config):
    path = get_config_path(guild_id)
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)

def load_events(guild_id):
    path = get_events_path(guild_id)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def save_events(guild_id, events):
    path = get_events_path(guild_id)
    with open(path, 'w') as f:
        json.dump(events, f, indent=2)

def load_custom_games(guild_id):
    config = load_config(guild_id)
    if config and "custom_games" in config:
        return config["custom_games"]
    return []

def save_custom_game(guild_id, game_data):
    config = load_config(guild_id)
    if not config:
        return False
    
    if "custom_games" not in config:
        config["custom_games"] = []
    
    config["custom_games"].append(game_data)
    save_config(guild_id, config)
    return True

def generate_event_code():
    return str(random.randint(10000, 99999))

class EventView(discord.ui.View):
    def __init__(self, event_id, guild_id):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.guild_id = guild_id
    
    @discord.ui.button(label="Join", style=discord.ButtonStyle.green, custom_id="join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        events = load_events(self.guild_id)
        event = events.get(self.event_id)
        
        if not event:
            await interaction.response.send_message("Event not found!", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        
        if user_id in event["participants"]:
            await interaction.response.send_message("You're already registered!", ephemeral=True)
            return
        
        if user_id in event["alternates"]:
            event["alternates"].remove(user_id)
        
        if len(event["participants"]) < event["player_limit"]:
            event["participants"].append(user_id)
            save_events(self.guild_id, events)
            await self.update_event_message(interaction)
            await interaction.response.send_message("You've joined the event!", ephemeral=True)
        else:
            await interaction.response.send_message("Event is full! Join as alternate?", ephemeral=True)
    
    @discord.ui.button(label="Join as Alternate", style=discord.ButtonStyle.blurple, custom_id="alternate")
    async def alternate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        events = load_events(self.guild_id)
        event = events.get(self.event_id)
        
        if not event:
            await interaction.response.send_message("Event not found!", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        
        if user_id in event["participants"]:
            await interaction.response.send_message("You're already a participant!", ephemeral=True)
            return
        
        if user_id in event["alternates"]:
            await interaction.response.send_message("You're already an alternate!", ephemeral=True)
            return
        
        event["alternates"].append(user_id)
        save_events(self.guild_id, events)
        await self.update_event_message(interaction)
        await interaction.response.send_message("You've joined as an alternate!", ephemeral=True)
    
    @discord.ui.button(label="Leave", style=discord.ButtonStyle.red, custom_id="leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        events = load_events(self.guild_id)
        event = events.get(self.event_id)
        
        if not event:
            await interaction.response.send_message("Event not found!", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        
        if user_id in event["participants"]:
            event["participants"].remove(user_id)
            # Promote alternate if available
            if event["alternates"]:
                promoted = event["alternates"].pop(0)
                event["participants"].append(promoted)
                guild = bot.get_guild(self.guild_id)
                promoted_user = guild.get_member(int(promoted))
                if promoted_user:
                    try:
                        await promoted_user.send(f"You've been promoted from alternate to participant for event: {event['title']}")
                    except:
                        pass
            save_events(self.guild_id, events)
            await self.update_event_message(interaction)
            await interaction.response.send_message("You've left the event!", ephemeral=True)
        elif user_id in event["alternates"]:
            event["alternates"].remove(user_id)
            save_events(self.guild_id, events)
            await self.update_event_message(interaction)
            await interaction.response.send_message("You've left the alternates!", ephemeral=True)
        else:
            await interaction.response.send_message("You're not registered for this event!", ephemeral=True)
    
    @discord.ui.button(label="Edit Event", style=discord.ButtonStyle.gray, custom_id="edit")
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        events = load_events(self.guild_id)
        event = events.get(self.event_id)
        
        if not event:
            await interaction.response.send_message("Event not found!", ephemeral=True)
            return
        
        # Check permissions
        if interaction.user.id != event["creator_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only the event creator or admins can edit!", ephemeral=True)
            return
        
        modal = EditEventModal(self.event_id, self.guild_id, event)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Cancel Event", style=discord.ButtonStyle.danger, custom_id="cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        events = load_events(self.guild_id)
        event = events.get(self.event_id)
        
        if not event:
            await interaction.response.send_message("Event not found!", ephemeral=True)
            return
        
        # Check permissions
        if interaction.user.id != event["creator_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only the event creator or admins can cancel!", ephemeral=True)
            return
        
        modal = CancelModal(self.event_id, self.guild_id)
        await interaction.response.send_modal(modal)
    
    async def update_event_message(self, interaction: discord.Interaction):
        events = load_events(self.guild_id)
        event = events.get(self.event_id)
        
        if not event:
            return
        
        embed = create_event_embed(event, interaction.guild)
        
        try:
            channel = interaction.guild.get_channel(event["message_channel_id"])
            message = await channel.fetch_message(event["message_id"])
            await message.edit(embed=embed)
        except:
            pass

class EditEventModal(discord.ui.Modal, title="Edit Event"):
    def __init__(self, event_id, guild_id, event):
        super().__init__()
        self.event_id = event_id
        self.guild_id = guild_id
        self.event = event
        
        # Parse existing datetime
        event_time = datetime.fromisoformat(event["datetime"])
        
        self.title_field = discord.ui.TextInput(
            label="Event Title",
            default=event["title"],
            max_length=100
        )
        self.add_item(self.title_field)
        
        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=event["description"],
            max_length=500,
            required=False
        )
        self.add_item(self.description)
        
        self.date = discord.ui.TextInput(
            label="Date (YYYY-MM-DD)",
            default=event_time.strftime("%Y-%m-%d"),
            max_length=10
        )
        self.add_item(self.date)
        
        self.time = discord.ui.TextInput(
            label="Time (HH:MM AM/PM)",
            default=event_time.strftime("%I:%M %p"),
            max_length=10
        )
        self.add_item(self.time)
        
        self.timezone = discord.ui.TextInput(
            label="Timezone",
            default=event["timezone"],
            max_length=3
        )
        self.add_item(self.timezone)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        events = load_events(self.guild_id)
        event = events.get(self.event_id)
        
        if not event:
            await interaction.followup.send("Event not found!", ephemeral=True)
            return
        
        # Parse new datetime
        try:
            datetime_str = f"{self.date.value} {self.time.value}"
            new_event_time = datetime.strptime(datetime_str, "%Y-%m-%d %I:%M %p")
        except:
            try:
                new_event_time = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
            except:
                await interaction.followup.send("Invalid date/time format!", ephemeral=True)
                return
        
        # Convert to timezone-aware
        tz_map = {
            "GMT": "GMT",
            "AST": "America/Halifax",
            "EST": "America/New_York",
            "CST": "America/Chicago",
            "PST": "America/Los_Angeles"
        }
        
        tz_str = tz_map.get(self.timezone.value.upper(), "America/New_York")
        tz = pytz.timezone(tz_str)
        new_event_time = tz.localize(new_event_time)
        
        # Update event data
        event["title"] = self.title_field.value
        event["description"] = self.description.value if self.description.value else ""
        event["datetime"] = new_event_time.isoformat()
        event["timezone"] = self.timezone.value
        
        # Check if time changed
        old_time = datetime.fromisoformat(self.event["datetime"])
        if old_time.tzinfo is None:
            old_time = pytz.UTC.localize(old_time)
        time_changed = new_event_time != old_time
        
        guild = interaction.guild
        
        if time_changed:
            # Reset reminder flags
            event["reminded_15"] = False
            event["reminded_5"] = False
            event["voice_created"] = False
            
            # Delete existing voice channel if it was already created
            if event.get("voice_channel_id"):
                try:
                    voice_channel = guild.get_channel(event["voice_channel_id"])
                    if voice_channel:
                        await voice_channel.delete()
                    event["voice_channel_id"] = None
                except Exception as e:
                    print(f"Failed to delete voice channel during edit: {e}")
        
        save_events(self.guild_id, events)
        
        # Update the message
        embed = create_event_embed(event, guild)
        
        try:
            channel = guild.get_channel(event["message_channel_id"])
            message = await channel.fetch_message(event["message_id"])
            await message.edit(embed=embed)
        except Exception as e:
            print(f"Failed to update message: {e}")
        
        # Handle Discord scheduled event update
        if event.get("scheduled_event_id"):
            try:
                scheduled_event = guild.get_scheduled_event(event["scheduled_event_id"])
                if scheduled_event:
                    # Determine the correct title based on game type
                    if event["game"] == "Destiny 2":
                        discord_event_title = f"Destiny 2 - {event['mode']}: {event['title']}"
                    else:
                        if event["mode"]:
                            discord_event_title = f"{event['game']} - {event['mode']}"
                        else:
                            discord_event_title = event['game']
                    
                    description = f"{event['description'][:1000] if event['description'] else ''}\n\nA voice channel will be created, and a reminder will be sent 15 min before the event starts. Please feel free to join the fun by following the link to our events channel."
                    
                    if time_changed:
                        # Time changed - check if event has already started
                        now = datetime.now(pytz.UTC)
                        event_has_started = now >= old_time
                        
                        if event_has_started:
                            # Event already started - delete and recreate
                            try:
                                await scheduled_event.delete()
                            except Exception as e:
                                print(f"Failed to delete old scheduled event: {e}")
                            
                            # Create new scheduled event
                            try:
                                new_scheduled_event = await guild.create_scheduled_event(
                                    name=discord_event_title,
                                    description=description,
                                    start_time=new_event_time,
                                    end_time=new_event_time + timedelta(hours=2),
                                    location=f"https://discord.com/channels/{guild.id}/{event['message_channel_id']}/{event['message_id']}",
                                    entity_type=discord.EntityType.external,
                                    privacy_level=discord.PrivacyLevel.guild_only
                                )
                                event["scheduled_event_id"] = new_scheduled_event.id
                                save_events(self.guild_id, events)
                            except Exception as e:
                                print(f"Failed to create new scheduled event: {e}")
                                event["scheduled_event_id"] = None
                                save_events(self.guild_id, events)
                        else:
                            # Event hasn't started - update time and details
                            try:
                                await scheduled_event.edit(
                                    name=discord_event_title,
                                    description=description,
                                    start_time=new_event_time,
                                    end_time=new_event_time + timedelta(hours=2)
                                )
                            except Exception as e:
                                print(f"Failed to update scheduled event time: {e}")
                    else:
                        # Only details changed (title/description), not time - just edit
                        try:
                            await scheduled_event.edit(
                                name=discord_event_title,
                                description=description
                            )
                        except Exception as e:
                            print(f"Failed to update scheduled event details: {e}")
            except Exception as e:
                print(f"Failed to handle scheduled event: {e}")
        
        # Log the edit
        config = load_config(self.guild_id)
        log_channel = guild.get_channel(config["event_log_channel_id"])
        if log_channel:
            log_embed = discord.Embed(
                title="Event Edited",
                description=f"**{event['title']}** has been edited",
                color=discord.Color.blue()
            )
            log_embed.add_field(name="Edited by", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="Event ID", value=self.event_id, inline=True)
            if time_changed:
                log_embed.add_field(name="Note", value="Time changed - voice channel and reminders reset", inline=False)
                await log_channel.send(embed=log_embed)
        
        await interaction.followup.send("Event updated successfully!", ephemeral=True)
        
class CancelModal(discord.ui.Modal, title="Cancel Event"):
    def __init__(self, event_id, guild_id):
        super().__init__()
        self.event_id = event_id
        self.guild_id = guild_id
    
    reason = discord.ui.TextInput(
        label="Cancellation Reason (Visible to all)",
        style=discord.TextStyle.paragraph,
        placeholder="This reason will be sent to all participants...",
        required=True,
        max_length=500
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await cancel_event(interaction, self.guild_id, self.event_id, self.reason.value, user_initiated=True)

def create_event_embed(event, guild):
    embed = discord.Embed(
        title=event["title"],
        description=event["description"],
        color=0xf08328
    )
    
    event_time = datetime.fromisoformat(event["datetime"])
    # Ensure event_time is timezone aware
    if event_time.tzinfo is None:
        event_time = pytz.UTC.localize(event_time)
    
    # Convert to Unix timestamp for Discord's automatic timezone conversion
    timestamp = int(event_time.timestamp())
    
    # Discord will automatically show this in each user's local time
    # <t:timestamp:F> = Full date/time format
    # <t:timestamp:R> = Relative time (e.g., "in 2 hours")
    embed.add_field(
        name="Date & Time", 
        value=f"<t:{timestamp}:F>\n(<t:{timestamp}:R>)", 
        inline=False
    )
    
    embed.add_field(name="Player Limit", value=f"{len(event['participants'])}/{event['player_limit']}", inline=True)
    
    participants_text = ""
    for user_id in event["participants"]:
        member = guild.get_member(int(user_id))
        if member:
            participants_text += f"• {member.mention}\n"
    
    if not participants_text:
        participants_text = "No participants yet"
    
    embed.add_field(name="Participants", value=participants_text, inline=False)
    
    if event["alternates"]:
        alternates_text = ""
        for user_id in event["alternates"]:
            member = guild.get_member(int(user_id))
            if member:
                alternates_text += f"• {member.mention}\n"
        embed.add_field(name="Alternates", value=alternates_text, inline=False)
    
    return embed

async def cancel_event(interaction: discord.Interaction, guild_id, event_id, reason=None, user_initiated=False):
    events = load_events(guild_id)
    event = events.get(event_id)
    
    if not event:
        await interaction.followup.send("Event not found!", ephemeral=True)
        return
    
    guild = interaction.guild
    config = load_config(guild_id)
    
    # Only send notifications if this was a user-initiated cancel (not automatic)
    if user_initiated:
        # Get event time for the message
        event_time = datetime.fromisoformat(event["datetime"])
        if event_time.tzinfo is None:
            event_time = pytz.UTC.localize(event_time)
        timestamp = int(event_time.timestamp())
        
        # Determine the event display name
        if event["game"] == "Destiny 2":
            event_display_name = f"Destiny 2 - {event['mode']}: {event['title']}"
        else:
            if event["mode"]:
                event_display_name = f"{event['game']} - {event['mode']}"
            else:
                event_display_name = event['game']
        
        # Create cancellation embed for DMs
        cancel_embed = discord.Embed(
            title="Event Cancelled",
            description=f"Your event **{event_display_name}** scheduled for <t:{timestamp}:F> has been cancelled.",
            color=0xf08328
        )
        cancel_embed.add_field(name="Reason", value=reason, inline=False)
        
        # Notify participants
        for user_id in event["participants"] + event["alternates"]:
            member = guild.get_member(int(user_id))
            if member:
                try:
                    await member.send(embed=cancel_embed)
                except:
                    pass
        
        # Log cancellation
        log_channel = guild.get_channel(config["event_log_channel_id"])
        if log_channel:
            log_embed = discord.Embed(
                title="Event Cancelled",
                description=f"**{event['title']}** has been cancelled",
                color=discord.Color.red()
            )
            log_embed.add_field(name="Cancelled by", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="Event ID", value=event_id, inline=True)
            if reason:
                log_embed.add_field(name="Reason", value=reason, inline=False)
            await log_channel.send(embed=log_embed)
    
    # Delete message
    try:
        channel = guild.get_channel(event["message_channel_id"])
        message = await channel.fetch_message(event["message_id"])
        await message.delete()
    except:
        pass
    
    # Delete text channel
    if event.get("text_channel_id"):
        try:
            text_channel = guild.get_channel(event["text_channel_id"])
            if text_channel:
                await text_channel.delete()
        except:
            pass
    
    # Delete voice channel
    if event.get("voice_channel_id"):
        try:
            voice_channel = guild.get_channel(event["voice_channel_id"])
            if voice_channel:
                await voice_channel.delete()
        except:
            pass
    
    # Delete Discord event
    if event.get("scheduled_event_id"):
        try:
            scheduled_event = guild.get_scheduled_event(event["scheduled_event_id"])
            if scheduled_event:
                await scheduled_event.delete()
        except:
            pass
    
    # Remove from events
    del events[event_id]
    save_events(guild_id, events)
    
    if user_initiated:
        await interaction.followup.send("Event cancelled successfully!", ephemeral=True)

@bot.event
async def on_ready():
    init_destiny_files()
    print(f'{bot.user} has connected to Discord!')
    
    # Recreate persistent views for existing events
    for guild in bot.guilds:
        events = load_events(guild.id)
        for event_id, event_data in events.items():
            view = EventView(event_id, guild.id)
            bot.add_view(view, message_id=event_data.get("message_id"))
    
    await bot.tree.sync()
    event_check_loop.start()
    cleanup_loop.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Check if message is in event channel
    if message.guild:
        config = load_config(message.guild.id)
        if config and message.channel.id == config["event_channel_id"]:
            # Check if it's not a command
            if not message.content.startswith('/'):
                try:
                    await message.delete()
                except:
                    pass
    
    await bot.process_commands(message)

async def category_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    categories = [cat.name for cat in interaction.guild.categories]
    categories.append("+ Create New Category")
    return [
        app_commands.Choice(name=cat, value=cat)
        for cat in categories if current.lower() in cat.lower()
    ][:25]

async def channel_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    # Get the category parameter from the interaction
    category_name = None
    for option in interaction.namespace.__dict__.items():
        if option[0] == 'category_name':
            category_name = option[1]
            break
    
    channels = []
    if category_name and category_name != "+ Create New Category":
        category = discord.utils.get(interaction.guild.categories, name=category_name)
        if category:
            channels = [ch.name for ch in category.text_channels]
    else:
        # Show all text channels if no category selected yet
        channels = [ch.name for ch in interaction.guild.text_channels]
    
    channels.append("+ Create New Channel")
    return [
        app_commands.Choice(name=ch, value=ch)
        for ch in channels if current.lower() in ch.lower()
    ][:25]

@bot.tree.command(name="setup", description="Setup the event bot (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.autocomplete(
    category_name=category_autocomplete,
    event_channel_name=channel_autocomplete,
    event_log_channel_name=channel_autocomplete
)
async def setup(interaction: discord.Interaction, 
                category_name: str,
                event_channel_name: str,
                event_log_channel_name: str):
    
    if load_config(interaction.guild.id):
        await interaction.response.send_message("Bot is already set up! Use /reset to reconfigure.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    
    # Handle category
    if category_name == "+ Create New Category":
        category = await guild.create_category("Events")
    else:
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await guild.create_category(category_name)
    
    # Handle event channel
    if event_channel_name == "+ Create New Channel":
        event_channel = await guild.create_text_channel("events", category=category)
    else:
        event_channel = discord.utils.get(guild.text_channels, name=event_channel_name)
        if not event_channel:
            event_channel = await guild.create_text_channel(event_channel_name, category=category)
        elif event_channel.category_id != category.id:
            # Move channel to correct category if it's in a different one
            await event_channel.edit(category=category)
    
    # Handle event log channel
    if event_log_channel_name == "+ Create New Channel":
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        event_log_channel = await guild.create_text_channel("event-log", category=category, overwrites=overwrites)
    else:
        event_log_channel = discord.utils.get(guild.text_channels, name=event_log_channel_name)
        if not event_log_channel:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            event_log_channel = await guild.create_text_channel(event_log_channel_name, category=category, overwrites=overwrites)
        elif event_log_channel.category_id != category.id:
            # Move channel to correct category if it's in a different one
            await event_log_channel.edit(category=category)
    
    config = {
        "category_id": category.id,
        "event_channel_id": event_channel.id,
        "event_log_channel_id": event_log_channel.id,
        "custom_games": []
    }

    save_config(guild.id, config)
    
    await interaction.followup.send(f"Setup complete!\n"
                                   f"Category: {category.name}\n"
                                   f"Event Channel: {event_channel.mention}\n"
                                   f"Event Log Channel: {event_log_channel.mention}", ephemeral=True)

@bot.tree.command(name="repair", description="Repair missing channels (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def repair(interaction: discord.Interaction):
    config = load_config(interaction.guild.id)
    
    if not config:
        await interaction.response.send_message("No configuration found! Run /setup first.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    repaired = []
    
    # Check category
    category = guild.get_channel(config["category_id"])
    if not category:
        category = await guild.create_category("Events")
        config["category_id"] = category.id
        repaired.append("Category")
    
    # Check event channel
    event_channel = guild.get_channel(config["event_channel_id"])
    if not event_channel:
        event_channel = await guild.create_text_channel("events", category=category)
        config["event_channel_id"] = event_channel.id
        repaired.append("Event Channel")
    
    # Check event log channel
    event_log_channel = guild.get_channel(config["event_log_channel_id"])
    if not event_log_channel:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        event_log_channel = await guild.create_text_channel("event-log", category=category, overwrites=overwrites)
        config["event_log_channel_id"] = event_log_channel.id
        repaired.append("Event Log Channel")
    
    save_config(guild.id, config)
    
    if repaired:
        await interaction.followup.send(f"Repaired: {', '.join(repaired)}", ephemeral=True)
    else:
        await interaction.followup.send("Nothing needed repair!", ephemeral=True)

@bot.tree.command(name="reset", description="Reset bot configuration (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def reset(interaction: discord.Interaction):
    config_path = get_config_path(interaction.guild.id)
    
    if os.path.exists(config_path):
        os.remove(config_path)
        await interaction.response.send_message("Configuration reset! Run /setup to reconfigure.", ephemeral=True)
    else:
        await interaction.response.send_message("No configuration found!", ephemeral=True)
 
async def raid_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    raids = load_destiny_content(DESTINY_RAIDS_FILE)
    return [
        app_commands.Choice(name=raid, value=raid)
        for raid in raids if current.lower() in raid.lower()
    ][:25]

async def dungeon_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    dungeons = load_destiny_content(DESTINY_DUNGEONS_FILE)
    return [
        app_commands.Choice(name=dungeon, value=dungeon)
        for dungeon in dungeons if current.lower() in dungeon.lower()
    ][:25]

async def custom_game_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    custom_games = load_custom_games(interaction.guild.id)
    choices = []
    for game in custom_games:
        display_name = game['name']
        if game['mode']:
            display_name += f" - {game['mode']}"
        if current.lower() in display_name.lower():
            choices.append(app_commands.Choice(name=display_name, value=json.dumps(game)))
    return choices[:25]

@bot.tree.command(name="destiny-2-raid", description="Create a Destiny 2 raid event")
@app_commands.autocomplete(raid=raid_autocomplete)
async def destiny2_raid(interaction: discord.Interaction, raid: str):
    if not load_config(interaction.guild.id):
        await interaction.response.send_message("Bot not set up! Ask an admin to run /setup.", ephemeral=True)
        return
    
    modal = EventModalSimple("Destiny 2", "Raid", raid, 6)
    await interaction.response.send_modal(modal)

@bot.tree.command(name="destiny-2-dungeon", description="Create a Destiny 2 dungeon event")
@app_commands.autocomplete(dungeon=dungeon_autocomplete)
async def destiny2_dungeon(interaction: discord.Interaction, dungeon: str):
    if not load_config(interaction.guild.id):
        await interaction.response.send_message("Bot not set up! Ask an admin to run /setup.", ephemeral=True)
        return
    
    modal = EventModalSimple("Destiny 2", "Dungeon", dungeon, 3)
    await interaction.response.send_modal(modal)

@bot.tree.command(name="other-game", description="Create a custom game event")
@app_commands.autocomplete(game=custom_game_autocomplete)
async def other_game(interaction: discord.Interaction, game: str):
    config = load_config(interaction.guild.id)
    if not config:
        await interaction.response.send_message("Bot not set up! Ask an admin to run /setup.", ephemeral=True)
        return
    
    custom_games = load_custom_games(interaction.guild.id)
    if not custom_games:
        await interaction.response.send_message("No custom games configured! Use /create-other first.", ephemeral=True)
        return
    
    try:
        game_data = json.loads(game)
        # Use empty string for mode if not specified, instead of "Event"
        mode = game_data['mode'] if game_data['mode'] else ""
        modal = EventModalSimple(game_data['name'], mode, 
                                game_data['name'] + (f" - {mode}" if mode else ""), 
                                game_data['player_limit'])
        await interaction.response.send_modal(modal)
    except:
        await interaction.response.send_message("Invalid game selection!", ephemeral=True)

@bot.tree.command(name="add-game", description="Create a custom game template")
async def create_other(interaction: discord.Interaction):
    if not load_config(interaction.guild.id):
        await interaction.response.send_message("Bot not set up! Ask an admin to run /setup.", ephemeral=True)
        return
    
    modal = CreateCustomGameModal()
    await interaction.response.send_modal(modal)

class CreateCustomGameModal(discord.ui.Modal, title="Create Custom Game Template"):
    game_name = discord.ui.TextInput(label="Game Name", placeholder="e.g., Valorant", max_length=50)
    game_mode = discord.ui.TextInput(label="Game Mode (Optional)", placeholder="e.g., Competitive", required=False, max_length=50)
    player_limit = discord.ui.TextInput(label="Player Limit (0 = unlimited)", placeholder="e.g., 5", max_length=3)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.player_limit.value)
            if limit < 0:
                limit = 0
        except:
            await interaction.response.send_message("Invalid player limit!", ephemeral=True)
            return
        
        # Check for duplicates (case-insensitive)
        existing_games = load_custom_games(interaction.guild.id)
        game_name_lower = self.game_name.value.lower()
        game_mode_lower = self.game_mode.value.lower() if self.game_mode.value else ""
        
        for existing in existing_games:
            existing_name_lower = existing['name'].lower()
            existing_mode_lower = existing['mode'].lower() if existing['mode'] else ""
            
            if existing_name_lower == game_name_lower and existing_mode_lower == game_mode_lower:
                await interaction.response.send_message(
                    f"A template for **{self.game_name.value}**" + 
                    (f" - **{self.game_mode.value}**" if self.game_mode.value else "") + 
                    " already exists!", 
                    ephemeral=True
                )
                return
    
        game_data = {
            "name": self.game_name.value,
            "mode": self.game_mode.value if self.game_mode.value else "",
            "player_limit": limit
        }
        
        save_custom_game(interaction.guild.id, game_data)
        
        display_name = game_data["name"]
        if game_data["mode"]:
            display_name += f" - {game_data['mode']}"
        
        await interaction.response.send_message(f"Custom game template created: {display_name}", ephemeral=True)

class CustomGameModal(discord.ui.Modal, title="Create Custom Game Event"):
    def __init__(self, custom_games):
        super().__init__()
        self.custom_games = custom_games
        
        # Create dropdown options
        options_text = "\n".join([f"{i+1}. {g['name']}" + (f" - {g['mode']}" if g['mode'] else "") 
                                  for i, g in enumerate(custom_games)])
        
        self.game_choice = discord.ui.TextInput(
            label="Choose Game (Enter number)",
            placeholder=options_text,
            max_length=2
        )
        self.add_item(self.game_choice)
        
        self.title_field = discord.ui.TextInput(label="Event Title", placeholder="Event title", max_length=100)
#        self.add_item(self.title_field)
        
        
        self.date = discord.ui.TextInput(label="Date (YYYY-MM-DD)", placeholder="2026-12-31", max_length=10)
        self.add_item(self.date)
        
        self.time = discord.ui.TextInput(label="Time (HH:MM AM/PM)", placeholder="07:00 PM", max_length=8)
        self.add_item(self.time)
        
        self.description = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False, max_length=500)
        self.add_item(self.description)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            choice = int(self.game_choice.value) - 1
            if choice < 0 or choice >= len(self.custom_games):
                raise ValueError()
            game = self.custom_games[choice]
        except:
            await interaction.response.send_message("Invalid game choice!", ephemeral=True)
            return
        
        await create_event_from_modal(interaction, game["name"], game["mode"] if game["mode"] else "Event", 
                                     game["player_limit"], self.title_field.value, self.description.value,
                                     self.date.value, self.time.value, "EST")

class EventModalSimple(discord.ui.Modal):
    def __init__(self, game, mode, activity_name, player_limit):
        super().__init__(title=f"Create {game} {mode} Event")
        self.game = game
        self.mode = mode
        self.activity_name = activity_name
        self.player_limit = player_limit
        
        self.title_field = discord.ui.TextInput(
            label="Event Title",
            placeholder=f"{activity_name}",
            default=activity_name,
            max_length=100
        )
#        self.add_item(self.title_field)
        
        self.date = discord.ui.TextInput(
            label="Date (YYYY-MM-DD)",
            placeholder="2026-12-31",
            max_length=10
        )
        self.add_item(self.date)
        
        self.time = discord.ui.TextInput(
            label="Time (HH:MM AM/PM)",
            placeholder="07:00 PM",
            max_length=8
        )
        self.add_item(self.time)
        
        self.timezone = discord.ui.TextInput(
            label="Timezone",
            placeholder="EST, CST, PST, GMT, AST",
            max_length=3
        )
        self.add_item(self.timezone)
        
        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            placeholder="Event details...",
            required=False,
            max_length=500
        )
        self.add_item(self.description)
        
    async def on_submit(self, interaction: discord.Interaction):
        await create_event_from_modal(interaction, self.game, self.mode, self.player_limit,
                                     self.title_field.value, self.description.value,
                                     self.date.value, self.time.value, self.timezone.value)

class EventModal(discord.ui.Modal):
    def __init__(self, game, mode, activities, player_limit):
        super().__init__(title=f"Create {game} {mode} Event")
        self.game = game
        self.mode = mode
        self.activities = activities
        self.player_limit = player_limit
        
        activities_text = ", ".join(activities[:5])
        if len(activities) > 5:
            activities_text += "..."
        
        self.activity = discord.ui.TextInput(
            label=f"{mode} Name",
            placeholder=activities_text,
            max_length=100
        )
#        self.add_item(self.activity)
        
        self.date = discord.ui.TextInput(
            label="Date (YYYY-MM-DD)",
            placeholder="2026-12-31",
            max_length=10
        )
        self.add_item(self.date)
        
        self.time = discord.ui.TextInput(
            label="Time (HH:MM AM/PM)",
            placeholder="07:00 PM",
            max_length=8
        )
        self.add_item(self.time)
        
        self.timezone = discord.ui.TextInput(
            label="Timezone",
            placeholder="EST, CST, PST, GMT, AST",
            max_length=3
        )
        self.add_item(self.timezone)

        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            placeholder="Event details...",
            required=False,
            max_length=500
        )
        self.add_item(self.description)
            
    async def on_submit(self, interaction: discord.Interaction):
        await create_event_from_modal(interaction, self.game, self.mode, self.player_limit,
                                     self.activity.value, self.description.value,
                                     self.date.value, self.time.value, self.timezone.value)

async def create_event_from_modal(interaction, game, mode, player_limit, title, description, date_str, time_str, timezone):
    await interaction.response.defer(ephemeral=True)
    
    config = load_config(interaction.guild.id)
    guild = interaction.guild
    
    # Parse datetime
    try:
        datetime_str = f"{date_str} {time_str}"
        event_time = datetime.strptime(datetime_str, "%Y-%m-%d %I:%M %p")
    except:
        try:
            event_time = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
        except:
            await interaction.followup.send("Invalid date/time format!", ephemeral=True)
            return
    
    # Convert timezone string to pytz timezone and make datetime timezone-aware
    tz_map = {
        "GMT": "GMT",
        "AST": "America/Halifax",
        "EST": "America/New_York",
        "CST": "America/Chicago",
        "PST": "America/Los_Angeles"
    }
    
    tz_str = tz_map.get(timezone.upper(), "America/New_York")
    tz = pytz.timezone(tz_str)
    event_time = tz.localize(event_time)
    
    # Generate event code
    event_code = generate_event_code()
    
    # Determine channel name and Discord event title based on game type
    if game == "Destiny 2":
        # For Destiny 2: channel = "raid-name-12345", Discord event = "Destiny 2 - Raid: Vault of Glass"
        channel_name = f"{title.lower().replace(' ', '-')}-{event_code}"
        discord_event_title = f"Destiny 2 - {mode}: {title}"
    else:
        # For other games: channel = "game-name-12345", Discord event = "Game Name" or "Game Name - Mode"
        channel_name = f"{game.lower().replace(' ', '-')}-{event_code}"
        if mode:
            discord_event_title = f"{game} - {mode}"
        else:
            discord_event_title = game
    
    # Event ID for internal tracking - use "custom" instead of empty mode
    event_id = f"{game}-{mode if mode else 'custom'}-{event_code}"
    
    # Create text channel
    category = guild.get_channel(config["category_id"])
    text_channel = await guild.create_text_channel(channel_name, category=category)
    
    # Create event embed and message
    event_data = {
        "id": event_id,
        "title": title,
        "description": description,
        "game": game,
        "mode": mode,
        "datetime": event_time.isoformat(),
        "timezone": timezone,
        "player_limit": player_limit,
        "creator_id": interaction.user.id,
        "participants": [],
        "alternates": [],
        "text_channel_id": text_channel.id,
        "message_channel_id": config["event_channel_id"],
        "reminded_15": False,
        "reminded_5": False,
        "voice_created": False
    }
    
    embed = create_event_embed(event_data, guild)
    event_channel = guild.get_channel(config["event_channel_id"])
    view = EventView(event_id, guild.id)
    message = await event_channel.send(embed=embed, view=view)
    
    event_data["message_id"] = message.id
    
    # Create Discord scheduled event
    try:
        scheduled_event = await guild.create_scheduled_event(
            name=discord_event_title,
            description=f"{description[:1000] if description else ''}\n\nA voice channel will be created, and a reminder will be sent 15 min before the event starts. Please feel free to join the fun by following the link to our events channel.",
            start_time=event_time,
            end_time=event_time + timedelta(hours=2),
            location=message.jump_url,
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only
        )
        event_data["scheduled_event_id"] = scheduled_event.id
    except Exception as e:
        print(f"Failed to create scheduled event: {e}")
    
    # Save event
    events = load_events(guild.id)
    events[event_id] = event_data
    save_events(guild.id, events)
    
    # Log creation
    log_channel = guild.get_channel(config["event_log_channel_id"])
    if log_channel:
        log_embed = discord.Embed(
            title="Event Created",
            description=f"**{title}** has been created",
            color=discord.Color.green()
        )
        log_embed.add_field(name="Created by", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Event ID", value=event_id, inline=True)
        log_embed.add_field(name="Date & Time", value=f"{date_str} {time_str} {timezone}", inline=False)
        await log_channel.send(embed=log_embed)
    
    await interaction.followup.send(f"Event created! Check {event_channel.mention} for details.", ephemeral=True)

@tasks.loop(minutes=1)
async def event_check_loop():
    """Check for events that need reminders or voice channels"""
    now = datetime.now(pytz.UTC)
    
    for guild in bot.guilds:
        events = load_events(guild.id)
        
        for event_id, event in list(events.items()):
            event_time = datetime.fromisoformat(event["datetime"])
            # Ensure event_time is timezone aware
            if event_time.tzinfo is None:
                event_time = pytz.UTC.localize(event_time)
            
            time_until = event_time - now
            
            # 15 minute reminder
            if not event["reminded_15"] and timedelta(minutes=14) <= time_until <= timedelta(minutes=16):
                event["reminded_15"] = True
                save_events(guild.id, events)
                
                # Determine the event display name
                if event["game"] == "Destiny 2":
                    event_display_name = f"Destiny 2 - {event['mode']}: {event['title']}"
                else:
                    if event["mode"]:
                        event_display_name = f"{event['game']} - {event['mode']}"
                    else:
                        event_display_name = event['game']
                
                timestamp = int(event_time.timestamp())
                
                reminder_embed = discord.Embed(
                    title="15 minutes until your event starts!",
                    color=0xf08328
                )
                reminder_embed.add_field(name="Event", value=event_display_name, inline=False)
                reminder_embed.add_field(name="Starts", value=f"<t:{timestamp}:R>", inline=False)
                reminder_embed.add_field(name="Voice Channel", value="A voice channel will be available soon!", inline=False)
                
                for user_id in event["participants"]:
                    member = guild.get_member(int(user_id))
                    if member:
                        try:
                            await member.send(embed=reminder_embed)
                        except:
                            pass
            
            # 5 minute reminder
            if not event["reminded_5"] and timedelta(minutes=4) <= time_until <= timedelta(minutes=6):
                event["reminded_5"] = True
                save_events(guild.id, events)
                
                # Determine the event display name
                if event["game"] == "Destiny 2":
                    event_display_name = f"Destiny 2 - {event['mode']}: {event['title']}"
                else:
                    if event["mode"]:
                        event_display_name = f"{event['game']} - {event['mode']}"
                    else:
                        event_display_name = event['game']
                
                timestamp = int(event_time.timestamp())
                
                reminder_embed = discord.Embed(
                    title="5 minutes until your event starts!",
                    color=0xf08328
                )
                reminder_embed.add_field(name="Event", value=event_display_name, inline=False)
                reminder_embed.add_field(name="Starts", value=f"<t:{timestamp}:R>", inline=False)
                reminder_embed.add_field(name="Voice Channel", value="A voice channel is now open and ready for you to join!", inline=False)
                
                for user_id in event["participants"]:
                    member = guild.get_member(int(user_id))
                    if member:
                        try:
                            await member.send(embed=reminder_embed)
                        except:
                            pass
            
            # Create voice channel 15 minutes before
            if not event["voice_created"] and timedelta(minutes=14) <= time_until <= timedelta(minutes=16):
                event["voice_created"] = True
                config = load_config(guild.id)
                category = guild.get_channel(config["category_id"])
                
                if category:
                    # Determine voice channel name based on game type
                    if event["game"] == "Destiny 2":
                        voice_name = f"{event['title'].lower().replace(' ', '-')}-{event['id'].split('-')[-1]}"
                    else:
                        voice_name = f"{event['game'].lower().replace(' ', '-')}-{event['id'].split('-')[-1]}"
                    
                    voice_channel = await guild.create_voice_channel(
                        voice_name,
                        category=category
                    )
                    event["voice_channel_id"] = voice_channel.id
                    save_events(guild.id, events)

@tasks.loop(minutes=5)
async def cleanup_loop():
    """Clean up events that have ended"""
    now = datetime.now(pytz.UTC)
    
    for guild in bot.guilds:
        events = load_events(guild.id)
        config = load_config(guild.id)
        
        if not config:
            continue
        
        for event_id, event in list(events.items()):
            event_time = datetime.fromisoformat(event["datetime"])
            # Ensure event_time is timezone aware
            if event_time.tzinfo is None:
                event_time = pytz.UTC.localize(event_time)
            
            time_since = now - event_time
            
            # Clean up 1 hour after event if voice channel is empty or doesn't exist
            if time_since >= timedelta(hours=1):
                should_cleanup = False
                
                if event.get("voice_channel_id"):
                    voice_channel = guild.get_channel(event["voice_channel_id"])
                    if not voice_channel or len(voice_channel.members) == 0:
                        should_cleanup = True
                else:
                    should_cleanup = True
                
                if should_cleanup:
                    # Delete text channel
                    if event.get("text_channel_id"):
                        try:
                            text_channel = guild.get_channel(event["text_channel_id"])
                            if text_channel:
                                await text_channel.delete()
                        except:
                            pass
                    
                    # Delete voice channel
                    if event.get("voice_channel_id"):
                        try:
                            voice_channel = guild.get_channel(event["voice_channel_id"])
                            if voice_channel:
                                await voice_channel.delete()
                        except:
                            pass
                    
                    # Delete message
                    try:
                        channel = guild.get_channel(event["message_channel_id"])
                        message = await channel.fetch_message(event["message_id"])
                        await message.delete()
                    except:
                        pass
                    
                    # Delete Discord scheduled event
                    if event.get("scheduled_event_id"):
                        try:
                            scheduled_event = guild.get_scheduled_event(event["scheduled_event_id"])
                            if scheduled_event:
                                await scheduled_event.delete()
                        except:
                            pass
                    
                    # Remove from events
                    del events[event_id]
                    save_events(guild.id, events)

@bot.event
async def on_scheduled_event_delete(event):
    """Handle when a Discord scheduled event is deleted"""
    guild = event.guild
    events = load_events(guild.id)
    config = load_config(guild.id)
    
    if not config:
        return
    
    for event_id, event_data in list(events.items()):
        if event_data.get("scheduled_event_id") == event.id:
            # Event was deleted - silently clean up without notifying users
            
            # Log cancellation (admin only)
            log_channel = guild.get_channel(config["event_log_channel_id"])
            if log_channel:
                log_embed = discord.Embed(
                    title="Event Cancelled (Discord Event Deleted)",
                    description=f"**{event_data['title']}** was cancelled due to Discord event deletion",
                    color=discord.Color.red()
                )
                log_embed.add_field(name="Event ID", value=event_id, inline=True)
                await log_channel.send(embed=log_embed)
            
            # Delete message
            try:
                channel = guild.get_channel(event_data["message_channel_id"])
                if channel:
                    message = await channel.fetch_message(event_data["message_id"])
                    await message.delete()
            except:
                pass
            
            # Delete text channel
            if event_data.get("text_channel_id"):
                try:
                    text_channel = guild.get_channel(event_data["text_channel_id"])
                    if text_channel:
                        await text_channel.delete()
                except:
                    pass
            
            # Delete voice channel
            if event_data.get("voice_channel_id"):
                try:
                    voice_channel = guild.get_channel(event_data["voice_channel_id"])
                    if voice_channel:
                        await voice_channel.delete()
                except:
                    pass
            
            # Remove from events
            del events[event_id]
            save_events(guild.id, events)
            break

@bot.event
async def on_raw_message_delete(payload):
    """Handle when an event message is deleted"""
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    events = load_events(guild.id)
    config = load_config(guild.id)
    
    if not config:
        return
    
    for event_id, event_data in list(events.items()):
        if event_data.get("message_id") == payload.message_id:
            # Event message was deleted - silently clean up without notifying users
            
            # Log cancellation (admin only)
            log_channel = guild.get_channel(config["event_log_channel_id"])
            if log_channel:
                log_embed = discord.Embed(
                    title="Event Cancelled (Message Deleted)",
                    description=f"**{event_data['title']}** was cancelled due to message deletion",
                    color=discord.Color.red()
                )
                log_embed.add_field(name="Event ID", value=event_id, inline=True)
                await log_channel.send(embed=log_embed)
            
            # Delete text channel
            if event_data.get("text_channel_id"):
                try:
                    text_channel = guild.get_channel(event_data["text_channel_id"])
                    if text_channel:
                        await text_channel.delete()
                except:
                    pass
            
            # Delete voice channel
            if event_data.get("voice_channel_id"):
                try:
                    voice_channel = guild.get_channel(event_data["voice_channel_id"])
                    if voice_channel:
                        await voice_channel.delete()
                except:
                    pass
            
            # Delete Discord scheduled event
            if event_data.get("scheduled_event_id"):
                try:
                    scheduled_event = guild.get_scheduled_event(event_data["scheduled_event_id"])
                    if scheduled_event:
                        await scheduled_event.delete()
                except:
                    pass
            
            # Remove from events
            del events[event_id]
            save_events(guild.id, events)
            break

async def main():
    async with bot:
        await load_cogs()
        # Load your bot token from environment variable or config
        TOKEN = os.getenv('DISCORD_BOT_TOKEN')
        if not TOKEN:
            print("Error: DISCORD_BOT_TOKEN not found in environment variables")
            return
        await bot.start(TOKEN)

# Run the bot
if __name__ == '__main__':
    asyncio.run(main())
