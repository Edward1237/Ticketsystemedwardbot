# bot.py (Part 1/4)

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import io
import asyncio
from dotenv import load_dotenv
import traceback # Added for detailed error logging
# import time # Uncomment if using time for backup filenames

# --- SETTINGS MANAGEMENT (for multi-server) ---
SETTINGS_FILE = 'settings.json'

def load_settings():
    """Loads settings from settings.json"""
    if not os.path.exists(SETTINGS_FILE):
        print(f"Info: {SETTINGS_FILE} not found. Creating a new one.")
        return {} # Return empty dict if file doesn't exist
    try:
        # Ensure file has content before trying to load
        if os.path.getsize(SETTINGS_FILE) == 0:
            print(f"Warning: {SETTINGS_FILE} is empty. Starting with default settings.")
            return {}
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: # Specify encoding
            return json.load(f)
    except json.JSONDecodeError:
        print(f"ERROR: {SETTINGS_FILE} is corrupted. Please fix or delete it. Starting with empty settings.")
        # Optionally backup corrupted file here
        # try: os.rename(SETTINGS_FILE, SETTINGS_FILE + f'.corrupted_{int(time.time())}')
        # except OSError: pass
        return {}
    except Exception as e:
        print(f"ERROR loading settings: {e}")
        traceback.print_exc() # Print full traceback for loading errors
        return {}


def save_settings(settings):
    """Saves settings to settings.json"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: # Specify encoding
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"ERROR saving settings: {e}")
        traceback.print_exc() # Print full traceback for saving errors

# --- BOT SETUP ---

# Load token from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("CRITICAL ERROR: DISCORD_TOKEN not found in .env file or environment variables.")
    exit(1) # Exit with error code

# Define intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

# --- DYNAMIC PREFIX FUNCTION ---
def get_prefix(bot_instance, message):
    """Gets the prefix for the specific guild."""
    if not message.guild:
        # Ignore messages in DMs for prefix commands entirely
        return commands.when_mentioned(bot_instance, message) # Only allow mentions in DMs

    # Ensure settings are loaded correctly
    if not isinstance(bot_instance.settings, dict):
         print("CRITICAL WARNING: Bot settings are not a dictionary. Using default prefix. Settings may be lost.")
         bot_instance.settings = load_settings()
         if not isinstance(bot_instance.settings, dict):
              bot_instance.settings = {} # Reset to empty dict as last resort

    settings_for_guild = bot_instance.settings.get(str(message.guild.id), {})
    prefix = settings_for_guild.get("prefix", "!") # Default '!'
    # Return both mention and the custom/default prefix
    return commands.when_mentioned_or(prefix)(bot_instance, message)

# Bot definition
class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, intents=intents)
        self.settings = load_settings() # Load settings on init
        self.persistent_views_added = False
        self.remove_command('help') # Remove default help to use our custom one

    async def setup_hook(self):
        # This is run once internally before the bot is ready
        if not self.persistent_views_added:
            self.add_view(TicketPanelView(bot=self))
            self.add_view(TicketCloseView(bot=self))
            self.add_view(AppealReviewView(bot=self)) # For appeal buttons
            self.persistent_views_added = True
            print("Persistent views added.")
        try:
            print("Attempting to sync slash commands...")
            # Sync commands and get the list of synced commands
            synced = await self.tree.sync()
            print(f"Slash commands synced: {len(synced)} commands.")
            # Optionally print names of synced commands:
            # for cmd in synced: print(f"- Synced: {cmd.name}")
        except Exception as e:
            print(f"ERROR: Failed to sync slash commands: {e}")
            traceback.print_exc()

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print(f'discord.py version: {discord.__version__}')
        print('Bot is ready and listening for commands.')
        # Set a status
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="tickets"))
        print('------')

    def get_guild_settings(self, guild_id):
        """Gets settings for a specific guild, ensuring defaults and correct types."""
        guild_id_str = str(guild_id)

        # Ensure self.settings is a dict, reload/reset if necessary
        if not isinstance(self.settings, dict):
            print("CRITICAL WARNING: self.settings is not a dict in get_guild_settings. Reloading...")
            self.settings = load_settings()
            if not isinstance(self.settings, dict): # Still not dict? Reset.
                print("CRITICAL ERROR: Could not load settings as dict. Resetting settings.")
                self.settings = {}

        # Default structure for a guild's settings
        defaults = {
            "panel_channel": None, "ticket_category": None, "archive_category": None,
            "staff_role": None, "escalation_role": None, "appeal_channel": None,
            "prefix": "!", "ticket_counter": 1, "blacklist": {}
        }

        # Get current settings for the guild, or create if missing
        guild_settings = self.settings.get(guild_id_str)
        updated = False

        if not isinstance(guild_settings, dict):
             print(f"WARNING: Settings for guild {guild_id_str} are not a dict ({type(guild_settings)}). Resetting guild settings.")
             guild_settings = defaults.copy() # Use a copy of defaults
             self.settings[guild_id_str] = guild_settings # Add/overwrite in main settings dict
             updated = True # Mark for saving

        # Ensure all default keys exist in the guild's settings
        for key, default_value in defaults.items():
            if key not in guild_settings:
                print(f"Adding missing key '{key}' with default value for guild {guild_id_str}")
                guild_settings[key] = default_value
                updated = True

        # Save settings if any defaults were added or structure was reset
        if updated:
            save_settings(self.settings)

        return guild_settings # Return the potentially corrected guild_settings


    def update_guild_setting(self, guild_id, key, value):
        # Use get_guild_settings to ensure the structure exists and is correct before updating
        settings = self.get_guild_settings(guild_id)
        # Check type again just in case get_guild_settings failed somehow
        if isinstance(settings, dict):
            settings[key] = value
            save_settings(self.settings)
        else:
            # This case should ideally not be reached anymore
            print(f"CRITICAL ERROR: Could not update setting '{key}' for guild {guild_id}. Settings structure invalid.")


bot = TicketBot()

# --- GLOBAL CHECK TO IGNORE DMS ---
@bot.check
async def globally_ignore_dms(ctx):
    # This prevents ANY command from running in DMs, including default help
    if ctx.guild is None and ctx.command is not None:
        # Silently ignore DM commands
        return False
    # Allow commands invoked in guilds
    return True

# --- HELPER FUNCTIONS ---

def create_embed(title: str, description: str, color: discord.Color) -> discord.Embed:
    # Basic embed creation, ensures description is not None
    return discord.Embed(title=title, description=str(description) if description is not None else "", color=color)

async def send_embed_response(ctx_or_interaction, title: str, description: str, color: discord.Color, ephemeral: bool = True):
    # Sends embed response, handles Interaction vs Context and response state
    embed = create_embed(title, description, color)
    target = None # For logging purposes
    try:
        if isinstance(ctx_or_interaction, discord.Interaction):
            target = ctx_or_interaction
            if target.response.is_done():
                # Already responded or deferred, use followup
                await target.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                # First response to the interaction
                await target.response.send_message(embed=embed, ephemeral=ephemeral)

        elif isinstance(ctx_or_interaction, commands.Context):
            target = ctx_or_interaction
            # Prefix commands can't send ephemeral directly in send()
            # If ephemeral=True is desired, need to delete the response after delay
            msg = await target.send(embed=embed)
            if ephemeral:
                 # Add a short delay then delete if ephemeral requested for prefix command
                 await asyncio.sleep(10) # Adjust delay as needed
                 try:
                     await msg.delete()
                 except (discord.NotFound, discord.Forbidden):
                     pass # Ignore if message already deleted or lacking perms

    except discord.NotFound:
         # This often happens if the original interaction/message was deleted before responding
         print(f"WARNING: Interaction/Context not found when sending embed (target: {target}).")
    except discord.Forbidden:
         # Bot lacks permissions to send messages/embeds in the channel or DM
         print(f"ERROR: Bot lacks permissions to send embed response (target: {target}).")
         # Try to notify the user in DMs if it's a context
         if isinstance(target, commands.Context):
             try:
                 await target.author.send(f"I don't have permission to send messages in {target.channel.mention}.")
             except Exception:
                 pass # Ignore if DMs fail too
    except Exception as e:
        print(f"ERROR sending embed response: {type(e).__name__} - {e} (target: {target})")
        traceback.print_exc()

# --- ERROR HANDLING ---
@bot.event
async def on_command_error(ctx, error):
    # More robust error handling
    if isinstance(error, commands.MissingPermissions):
        await send_embed_response(ctx, "Permission Denied", "You don't have permission.", discord.Color.red(), ephemeral=True) # Try ephemeral
    elif isinstance(error, commands.CheckFailure):
        # Specific checks (like is_staff) often send their own message now.
        # Can add a generic fallback if needed, but 'pass' is often fine.
        pass
    elif isinstance(error, commands.ChannelNotFound):
        param = getattr(error, 'argument', 'channel') # Try to get specific arg name
        await send_embed_response(ctx, "Error", f"Channel '{param}' not found.", discord.Color.red(), ephemeral=True)
    elif isinstance(error, commands.RoleNotFound):
        param = getattr(error, 'argument', 'role')
        await send_embed_response(ctx, "Error", f"Role '{param}' not found.", discord.Color.red(), ephemeral=True)
    elif isinstance(error, commands.MissingRequiredArgument):
        await send_embed_response(ctx, "Error", f"Missing argument: `{error.param.name}`.", discord.Color.orange(), ephemeral=True)
    elif isinstance(error, commands.CommandNotFound):
        pass # Ignore unknown commands silently
    elif isinstance(error, commands.BadArgument):
         # Provides more context about the conversion failure
         await send_embed_response(ctx, "Error", f"Invalid argument provided: {error}", discord.Color.orange(), ephemeral=True)
    elif isinstance(error, commands.CommandInvokeError):
        # Errors raised *within* the command's code
        original = error.original
        print(f"ERROR during command execution ({ctx.command}):")
        traceback.print_exception(type(original), original, original.__traceback__) # Print full traceback
        await send_embed_response(ctx, "Runtime Error", "An error occurred executing command.", discord.Color.dark_red(), ephemeral=True)
    elif isinstance(error, app_commands.errors.CommandInvokeError) and isinstance(ctx, discord.Interaction):
         # Handle errors specifically from slash command invocations
         original = error.original
         print(f"ERROR during slash command execution ({ctx.command.qualified_name}):")
         traceback.print_exception(type(original), original, original.__traceback__)
         # Use the interaction context to send the error message
         await send_embed_response(ctx, "Runtime Error", "An error occurred executing command.", discord.Color.dark_red(), ephemeral=True)

    else:
        # Log unexpected/unhandled errors
        print(f"UNHANDLED ERROR ({type(error)}) in command '{ctx.command}': {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        try:
            # Send generic error, ephemeral if possible
            is_interaction = isinstance(ctx, discord.Interaction)
            await send_embed_response(ctx, "Error", "An unexpected error occurred.", discord.Color.dark_red(), ephemeral=is_interaction)
        except Exception as e: print(f"Failed to send generic error message: {e}")

# --- HELPER FUNCTIONS ---
async def check_setup(ctx_or_interaction):
    """Checks if the bot is fully set up for the guild."""
    if not ctx_or_interaction.guild:
        print("check_setup called without guild context.")
        return False
    try:
        settings = bot.get_guild_settings(ctx_or_interaction.guild.id)
    except Exception as e:
         print(f"Error getting guild settings during setup check: {e}")
         await send_embed_response(ctx_or_interaction, "Critical Error", "Could not load server settings.", discord.Color.red())
         return False

    required_settings = ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']
    missing = [s for s in required_settings if not settings.get(s)]

    if missing:
        embed = discord.Embed(
            title="Bot Not Fully Setup!",
            description="Admin needs to run setup commands:", color=discord.Color.red()
        )
        embed.add_field(name="`/set_panel_channel`", value="Channel for panel.", inline=False)
        embed.add_field(name="`/set_ticket_category`", value="Category for new tickets.", inline=False)
        embed.add_field(name="`/set_archive_category`", value="Category for closed tickets.", inline=False)
        embed.add_field(name="`/set_staff_role`", value="Staff role.", inline=False)
        embed.set_footer(text=f"Missing: {', '.join(missing)}")
        try:
            # Use send_embed_response to handle context/interaction state
             await send_embed_response(ctx_or_interaction, embed.title, embed.description, embed.color, ephemeral=True)
        except Exception as e: print(f"Error sending setup warning: {e}")
        return False
    return True

# --- Helper to count user's open tickets ---
def count_user_tickets(guild: discord.Guild, user_id: int, category_id: int, ticket_type: str = None) -> int:
    category = guild.get_channel(category_id)
    if not category or not isinstance(category, discord.CategoryChannel):
        print(f"Warning: Category ID {category_id} not found/invalid for counting tickets.")
        return 0

    count = 0; user_id_str = str(user_id)
    for channel in category.text_channels:
        if channel.topic and f"ticket-user-{user_id_str}" in channel.topic:
            if ticket_type:
                if f"type-{ticket_type}" in channel.topic: count += 1
            else: count += 1
    return count

# --- create_ticket_channel adds type to topic ---
async def create_ticket_channel(interaction: discord.Interaction, ticket_type_name: str, settings: dict):
    guild = interaction.guild; user = interaction.user
    staff_role_id = settings.get('staff_role'); category_id = settings.get('ticket_category')

    if not staff_role_id: await send_embed_response(interaction, "Setup Error", "Staff Role not set.", discord.Color.red()); return None, None
    staff_role = guild.get_role(staff_role_id)
    if not staff_role: await send_embed_response(interaction, "Setup Error", "Staff Role not found.", discord.Color.red()); return None, None
    if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket Category not set.", discord.Color.red()); return None, None
    category = guild.get_channel(category_id)
    if not category or not isinstance(category, discord.CategoryChannel): await send_embed_response(interaction, "Setup Error", "Ticket Category invalid.", discord.Color.red()); return None, None

    # General hard limit
    if count_user_tickets(guild, user.id, category.id) > 15:
        await send_embed_response(interaction, "Limit Reached", "Too many open tickets.", discord.Color.orange()); return None, None

    ticket_num = settings.get('ticket_counter', 1)
    bot.update_guild_setting(guild.id, "ticket_counter", ticket_num + 1)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False, view_channel=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, view_channel=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, view_channel=True, manage_permissions=True, manage_messages=True, embed_links=True),
        staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, view_channel=True)
    }

    try:
        safe_user_name = "".join(c for c in user.name if c.isalnum() or c in ('-', '_')).lower() or "user"
        channel_name = f"{ticket_type_name}-{ticket_num}-{safe_user_name}"[:100]
        topic = f"ticket-user-{user.id} type-{ticket_type_name}"
        print(f"Attempting to create channel '{channel_name}' in category '{category.name}' ({category.id})") # Debug print
        new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites, topic=topic)
        print(f"Channel created successfully: {new_channel.mention} ({new_channel.id})") # Debug print
    except discord.Forbidden:
        print(f"ERROR: Forbidden - Bot lacks permissions to create channel in category {category.id}")
        await send_embed_response(interaction, "Permissions Error", "Cannot create channel/set perms.", discord.Color.red()); return None, None
    except Exception as e:
        print(f"ERROR creating channel: {e}")
        traceback.print_exc()
        await send_embed_response(interaction, "Error", f"Error creating channel: {e}", discord.Color.red()); return None, None
    return new_channel, staff_role

# End of Part 1/4
# bot.py (Part 2/4)

async def generate_transcript(channel: discord.TextChannel):
    # Generates a transcript, escaping markdown and mentions, handles large files
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True): # Get all messages
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
        # Escape markdown and mentions to prevent formatting issues/pings in transcript file
        clean_content = discord.utils.remove_markdown(discord.utils.escape_mentions(msg.content))
        author_display = f"{msg.author.display_name} ({msg.author.id})"
        if not msg.author.bot:
            messages.append(f"[{timestamp}] {author_display}: {clean_content}")
        # Include attachments in the log
        if msg.attachments:
            for att in msg.attachments:
                messages.append(f"[{timestamp}] [Attachment from {author_display}: {att.url}]")

    transcript_content = "\n".join(messages)
    if not transcript_content:
        transcript_content = "No messages were sent in this ticket."

    # Encode to check size and handle potential truncation
    encoded_content = transcript_content.encode('utf-8')
    # Use a slightly smaller max size to be safe (Discord limit is 8MB, use ~7.5MB)
    max_size = 7 * 1024 * 1024 + 512 * 1024 # Approx 7.5MB

    if len(encoded_content) > max_size:
        print(f"Transcript for {channel.name} too large ({len(encoded_content)} bytes), truncating.")
        # Truncate content, ensuring space for the truncation message
        truncated_content = encoded_content[:max_size - 200]
        try:
            # Decode back, ignoring errors if it cuts mid-character
            transcript_content = truncated_content.decode('utf-8', errors='ignore')
            transcript_content += "\n\n--- TRANSCRIPT TRUNCATED DUE TO SIZE LIMIT ---"
            encoded_content = transcript_content.encode('utf-8') # Re-encode truncated content
        except Exception as e:
             print(f"Error during transcript truncation: {e}")
             # Fallback if decoding/re-encoding fails badly
             return io.BytesIO(b"Transcript too large and could not be properly truncated.")

    return io.BytesIO(encoded_content) # Return as bytes buffer

# --- APPEAL/MODAL CLASSES ---
# --- Modal for Appeal Approve/Reject Reason ---
class AppealReasonModal(discord.ui.Modal):
    def __init__(self, bot: TicketBot, action: str, original_message: discord.Message, guild: discord.Guild, appealing_user_id: int):
        super().__init__(title=f"Appeal {action} Reason")
        self.bot = bot; self.action = action; self.original_message = original_message
        self.guild = guild; self.appealing_user_id = appealing_user_id
        self.reason_input = discord.ui.TextInput(
            label="Reason", style=discord.TextStyle.paragraph,
            placeholder=f"Reason for {action.lower()}ing...", required=True, min_length=3
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True); staff_member = interaction.user; reason = self.reason_input.value
        try: appealing_user = await self.bot.fetch_user(self.appealing_user_id)
        except discord.NotFound: await interaction.followup.send(embed=create_embed("Error", "Could not find user.", discord.Color.red())); return

        if not self.original_message.embeds: await interaction.followup.send(embed=create_embed("Error", "Original embed missing.", discord.Color.red())); return
        original_embed = self.original_message.embeds[0]; new_embed = original_embed.copy()

        if self.action == "Approve":
            title = "✅ Appeal Approved"; color = discord.Color.green()
            try: dm_embed = create_embed(title, f"Appeal for **{self.guild.name}** approved.\nReason:\n```{reason}```", color); await appealing_user.send(embed=dm_embed)
            except discord.Forbidden: print(f"Could not DM user {appealing_user.id} (appeal approved)")
            settings = self.bot.get_guild_settings(self.guild.id); user_id_str = str(self.appealing_user_id)
            # Use .get() for safer access to blacklist dict
            if user_id_str in settings.get("blacklist", {}):
                del settings["blacklist"][user_id_str]; save_settings(self.bot.settings)
                print(f"User {user_id_str} unblacklisted via appeal.")
        else: # Reject
            title = "❌ Appeal Rejected"; color = discord.Color.red()
            try: dm_embed = create_embed(title, f"Appeal for **{self.guild.name}** rejected.\nReason:\n```{reason}```", color); await appealing_user.send(embed=dm_embed)
            except discord.Forbidden: print(f"Could not DM user {appealing_user.id} (appeal rejected)")

        new_embed.title = f"[{self.action.upper()}D] Blacklist Appeal"; new_embed.color = color
        new_embed.add_field(name=f"{title} by {staff_member.display_name}", value=f"```{reason}```", inline=False)
        try:
            await self.original_message.edit(embed=new_embed, view=None) # Remove buttons after action
        except discord.NotFound: print("Original appeal message not found during edit.")
        except discord.Forbidden: print("Lacking permissions to edit original appeal message.")
        await interaction.followup.send(embed=create_embed("Success", f"Appeal {self.action.lower()}d. User notified.", color)) # More informative success

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"ERROR in AppealReasonModal: {error}"); traceback.print_exc()
        await interaction.followup.send("Error processing appeal reason.", ephemeral=True)

# --- Persistent View for Appeal Review Buttons in Staff Channel ---
class AppealReviewView(discord.ui.View):
    def __init__(self, bot: TicketBot = None):
        super().__init__(timeout=None); self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Check if bot is attached, crucial after restarts
        if not self.bot:
            print("AppealReviewView: Bot instance not found, attaching from interaction.")
            self.bot = interaction.client # Get bot instance from interaction
            if not self.bot:
                 print("CRITICAL ERROR: Could not get bot instance in AppealReviewView interaction_check.")
                 await interaction.response.send_message("Internal bot error.", ephemeral=True)
                 return False # Cannot proceed without bot instance

        # Permission check: Only staff can use these buttons
        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Error", "Staff role not configured.", discord.Color.red()); return False
        staff_role = interaction.guild.get_role(staff_role_id)
        # Check if interaction user is a Member before checking roles
        if not isinstance(interaction.user, discord.Member):
             print(f"Warning: interaction.user is not a Member in AppealReviewView check ({type(interaction.user)})")
             # Allow if they have admin perms even if not member? Risky. Better to deny.
             await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return False

        is_admin = interaction.user.guild_permissions.administrator
        if (staff_role and staff_role in interaction.user.roles) or is_admin: return True
        else: await send_embed_response(interaction, "Permission Denied", "Staff only.", discord.Color.red()); return False

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅", custom_id="appeal:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Embed missing.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "User ID missing.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        # Ensure bot instance is available for the Modal
        if not self.bot: self.bot = interaction.client
        modal = AppealReasonModal(bot=self.bot, action="Approve", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id="appeal:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Embed missing.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "User ID missing.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        # Ensure bot instance is available for the Modal
        if not self.bot: self.bot = interaction.client
        modal = AppealReasonModal(bot=self.bot, action="Reject", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)

# --- View for Final Appeal Confirmation (DM) ---
class ConfirmAppealView(discord.ui.View):
    def __init__(self, bot: TicketBot, answers: dict, guild: discord.Guild, appeal_channel: discord.TextChannel, messages_to_delete: list):
        super().__init__(timeout=600); self.bot = bot; self.answers = answers; self.guild = guild
        self.appeal_channel = appeal_channel; self.messages_to_delete = messages_to_delete; self.message = None # To store the view's message object

    async def cleanup(self, interaction: discord.Interaction = None):
        # Stops the view and deletes all tracked messages in the DM
        self.stop()
        print(f"Cleaning up {len(self.messages_to_delete)} messages from appeal DM.")
        for msg in self.messages_to_delete:
            try: await msg.delete()
            except (discord.NotFound, discord.Forbidden): pass # Ignore if already gone or no perms
        try:
            # Delete the final confirmation message itself
            target_message = interaction.message if interaction else self.message
            if target_message: await target_message.delete()
        except (discord.NotFound, discord.Forbidden): pass
        except Exception as e: print(f"Error cleaning up final appeal message: {e}")

    @discord.ui.button(label="Submit Appeal", style=discord.ButtonStyle.success, emoji="✅")
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() # Acknowledge click, process below
        embed = create_embed("New Blacklist Appeal", f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n**Server:** {self.guild.name}", discord.Color.gold())
        embed.add_field(name="1. Unfairly?", value=f"```{self.answers.get('q1','N/A')}```", inline=False) # Use .get()
        embed.add_field(name="2. Why Unblacklist?", value=f"```{self.answers.get('q2','N/A')}```", inline=False)
        embed.add_field(name="3. Proof", value=self.answers.get('proof','N/A'), inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}") # For review buttons
        # Make sure bot instance is available for the view
        view_bot = self.bot or interaction.client
        view_to_send = AppealReviewView(bot=view_bot)

        try:
            await self.appeal_channel.send(embed=embed, view=view_to_send) # Send to staff channel
        except discord.Forbidden:
             print(f"ERROR: Bot lacks permission to send appeal to channel {self.appeal_channel.id}")
             await interaction.followup.send(embed=create_embed("Error", "Cannot submit appeal (Bot permissions).", discord.Color.red()))
        except Exception as e:
            print(f"ERROR submitting appeal: {e}"); traceback.print_exc()
            await interaction.followup.send(embed=create_embed("Error", "Unexpected error submitting appeal.", discord.Color.red()))
        else: # Only send success if it worked
            await interaction.followup.send(embed=create_embed("✅ Appeal Submitted", "Sent to staff.", discord.Color.green()))

        await self.cleanup(interaction) # Clean up DM messages regardless of submission success

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.followup.send(embed=create_embed("Appeal Cancelled", "", discord.Color.red()))
        await self.cleanup(interaction)

    async def on_timeout(self):
        # Disable buttons visually and clean up
        print("ConfirmAppealView timed out.")
        for item in self.children: item.disabled = True
        try:
            if self.message: # Check message exists
                 # Edit message to show timeout, keep disabled view
                 await self.message.edit(embed=create_embed("Appeal Timed Out", "Did not submit in time.", discord.Color.red()), view=self)
                 # Schedule cleanup after a short delay to let user see the timeout message
                 await asyncio.sleep(15)
        except (discord.NotFound, discord.Forbidden): pass # Ignore if message gone or no perms
        except Exception as e: print(f"Error editing message on ConfirmAppealView timeout: {e}")
        # Clean up messages after timeout (or after delay)
        await self.cleanup()

# --- View for Starting Appeal (DM) ---
class AppealStartView(discord.ui.View):
    def __init__(self, bot: TicketBot, guild: discord.Guild, reason: str):
        super().__init__(timeout=1800); self.bot = bot; self.guild = guild; self.reason = reason; self.message = None # Store message this view is attached to

    async def ask_question(self, channel, user, embed, min_length=0, check_proof=False, timeout=600.0):
        # Helper to ask question, wait for response, track messages for deletion
        bot_msgs_to_delete = []
        user_msg = None
        ask_msg = None
        err_msg = None
        try:
            ask_msg = await channel.send(embed=embed); bot_msgs_to_delete.append(ask_msg)
            while True:
                msg = await self.bot.wait_for('message', check=lambda m: m.author == user and m.channel == channel, timeout=timeout)
                user_msg = msg # Store user message
                # Immediately add user message to list for deletion
                bot_msgs_to_delete.append(user_msg)

                # Clear previous error message if any
                if err_msg:
                    try: await err_msg.delete(); bot_msgs_to_delete.remove(err_msg); err_msg = None
                    except: pass # Ignore delete errors

                if check_proof: return bot_msgs_to_delete, user_msg # Proof is just the message
                if len(msg.content) < min_length:
                     err_msg = await channel.send(embed=create_embed("Too Short", f"Min {min_length} chars.", discord.Color.orange())); bot_msgs_to_delete.append(err_msg)
                     continue # Ask again
                return bot_msgs_to_delete, user_msg # Valid text answer
        except asyncio.TimeoutError:
            await channel.send(embed=create_embed("Timed Out", "Appeal cancelled.", discord.Color.red()))
            # Don't delete messages here on timeout, let ConfirmAppealView handle final cleanup or timeout
            return bot_msgs_to_delete, None # Signal timeout
        except Exception as e:
             print(f"Error in ask_question: {e}"); traceback.print_exc()
             await channel.send(embed=create_embed("Error", "An error occurred asking question.", discord.Color.red()))
             # Don't delete messages here on error
             return bot_msgs_to_delete, None # Signal error


    @discord.ui.button(label="Start Appeal", style=discord.ButtonStyle.primary, emoji="📜")
    async def start_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable button immediately
        for item in self.children: item.disabled = True
        try:
            await interaction.response.edit_message(view=self) # Acknowledge and edit original message
        except discord.NotFound:
             print("AppealStartView: Original message not found on button click.")
             # Cannot proceed without original message context usually
             return
        except Exception as e:
             print(f"Error editing original message in start_appeal: {e}")
             # Try to proceed anyway? Might fail later.

        channel = interaction.channel; user = interaction.user
        messages_to_delete = [interaction.message]; answers = {} # Track original interaction msg

        # Ensure bot has instance
        if not self.bot: self.bot = interaction.client
        if not self.bot: print("CRITICAL ERROR: Bot instance lost in start_appeal."); await channel.send("Internal error."); return

        settings = self.bot.get_guild_settings(self.guild.id); appeal_channel_id = settings.get("appeal_channel")
        if not appeal_channel_id: await channel.send(embed=create_embed("Error", f"Appeal system for **{self.guild.name}** not configured.", discord.Color.red())); return
        appeal_channel = self.guild.get_channel(appeal_channel_id)
        if not appeal_channel or not isinstance(appeal_channel, discord.TextChannel): await channel.send(embed=create_embed("Error", f"Appeal system for **{self.guild.name}** broken.", discord.Color.red())); return

        # --- Ask Questions ---
        q1_embed = create_embed("Appeal: Q1/3", "Why unfairly blacklisted?", discord.Color.blue()).set_footer(text="10 min, min 3 chars.")
        bot_msgs, answer1_msg = await self.ask_question(channel, user, q1_embed, 3); messages_to_delete.extend(bot_msgs)
        if not answer1_msg: await self.cleanup_on_fail(messages_to_delete); return # Timeout/Error
        answers['q1'] = answer1_msg.content

        q2_embed = create_embed("Appeal: Q2/3", "Why unblacklist?", discord.Color.blue()).set_footer(text="10 min, min 3 chars.")
        bot_msgs, answer2_msg = await self.ask_question(channel, user, q2_embed, 3); messages_to_delete.extend(bot_msgs)
        if not answer2_msg: await self.cleanup_on_fail(messages_to_delete); return
        answers['q2'] = answer2_msg.content

        q3_embed = create_embed("Appeal: Q3/3", "Provide proof (screenshots, etc.) or type `N/A`.", discord.Color.blue()).set_footer(text="10 min.")
        bot_msgs, answer3_msg = await self.ask_question(channel, user, q3_embed, 0, check_proof=True); messages_to_delete.extend(bot_msgs)
        if not answer3_msg: await self.cleanup_on_fail(messages_to_delete); return
        proof_content = answer3_msg.content if answer3_msg.content else "N/A"
        if answer3_msg.attachments: proof_urls = "\n".join([att.url for att in answer3_msg.attachments]); proof_content = f"{proof_content}\n{proof_urls}" if proof_content != "N/A" else proof_urls
        answers['proof'] = proof_content

        # --- Confirmation Step ---
        summary_embed = create_embed("Confirm Appeal", "Review answers. Submit?", discord.Color.green())
        summary_embed.add_field(name="1. Unfairly?", value=f"```{answers['q1']}```", inline=False)
        summary_embed.add_field(name="2. Why Unblacklist?", value=f"```{answers['q2']}```", inline=False)
        summary_embed.add_field(name="3. Proof", value=answers['proof'], inline=False)
        # Pass ALL messages collected so far to ConfirmAppealView for eventual deletion
        confirm_view = ConfirmAppealView(self.bot, answers, self.guild, appeal_channel, messages_to_delete)
        confirm_view.message = await channel.send(embed=summary_embed, view=confirm_view)
        # Do NOT add confirm_view.message to messages_to_delete here. Confirm view handles itself.

    async def cleanup_on_fail(self, messages: list):
        # Helper to clean up messages if a step fails (e.g., timeout) before confirm view
        print("Cleaning up messages after appeal step failure.")
        for msg in messages:
            try: await msg.delete()
            except (discord.NotFound, discord.Forbidden): pass

    async def on_timeout(self):
        # Disables button if user doesn't click "Start Appeal"
        print("AppealStartView timed out.")
        for item in self.children: item.disabled = True
        try:
             if self.message: # Check if message exists before editing
                await self.message.edit(embed=create_embed(f"Blacklisted on {self.guild.name}", f"Reason:\n```{self.reason}```\nAppeal window expired.", discord.Color.red()), view=self) # Update embed too
        except (discord.NotFound, discord.Forbidden): pass # Ignore if message gone or no perms
        except Exception as e: print(f"Failed edit appeal start on timeout: {e}")

# --- TICKET PANEL VIEW ---
class TicketPanelView(discord.ui.View):
    # This is the main persistent view with the ticket creation buttons
    def __init__(self, bot: TicketBot = None):
        super().__init__(timeout=None); self.bot = bot

    async def send_appeal_dm(self, user: discord.Member, guild: discord.Guild, reason: str):
        # Sends the initial DM to blacklisted users
        embed = create_embed(f"Blacklisted on {guild.name}", f"Reason:\n```{reason}```\nIf you believe this is a mistake, you may submit an appeal below.", discord.Color.red())
        view = AppealStartView(bot=self.bot, guild=guild, reason=reason)
        try:
            dm_channel = await user.create_dm()
            view.message = await dm_channel.send(embed=embed, view=view) # Store message for timeout handling
        except discord.Forbidden: print(f"Cannot send appeal DM to {user.id} (DMs disabled).")
        except Exception as e: print(f"Failed to send appeal DM to {user.id}: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Runs before any button callback in this view
        if not self.bot:
             print("TicketPanelView: Bot instance missing, attaching from interaction.")
             self.bot = interaction.client
             if not self.bot:
                 print("CRITICAL ERROR: Could not get bot instance in TicketPanelView interaction_check.")
                 await interaction.response.send_message("Internal bot error.", ephemeral=True)
                 return False

        if not interaction.guild: return False # Should not happen with guild buttons

        settings = self.bot.get_guild_settings(interaction.guild.id)
        blacklist = settings.get("blacklist", {}); user_id_str = str(interaction.user.id)

        # --- BLACKLIST CHECK ---
        if user_id_str in blacklist:
            reason = blacklist.get(user_id_str, "No reason provided.")
            # Respond ephemerally first
            await send_embed_response(interaction, "Blacklisted", "You cannot create tickets.", discord.Color.red())
            # Then attempt to send DM (doesn't need interaction context after initial response)
            await self.send_appeal_dm(interaction.user, interaction.guild, reason)
            return False # Stop button callback

        # --- SETUP CHECK ---
        if not all(settings.get(key) for key in ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']):
            # Respond ephemerally
            await send_embed_response(interaction, "System Offline", "Bot not fully configured.", discord.Color.red())
            return False # Stop button callback

        return True # Allow button callback to proceed

# End of Part 2/4
# bot.py (Part 3/4)

    # --- TICKET CREATION BUTTONS ---
    @discord.ui.button(label="Standard Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="panel:standard")
    async def standard_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "ticket"; LIMIT = 3; category_id = settings.get('ticket_category')
        if not category_id:
            # Check if already responded by interaction_check
            if not interaction.response.is_done():
                await send_embed_response(interaction, "Error", "Category not set.", discord.Color.red())
            return # Stop if category invalid

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"Max {LIMIT} standard tickets.", discord.Color.orange())
            return

        # Defer response *before* potentially long-running operations like channel creation
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role:
            # Use followup since we deferred
            await interaction.followup.send(embed=create_embed("Ticket Created", f"{channel.mention}", discord.Color.green()), ephemeral=True)
            embed = discord.Embed(title="🎫 Standard Ticket", description=f"Welcome, {interaction.user.mention}!\nDescribe issue. {staff_role.mention} will assist.", color=discord.Color.blue())
            # Ensure bot instance is available for the view
            view_bot = self.bot or interaction.client
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=view_bot))
        # No else needed if create_ticket_channel handled the error response

    @discord.ui.button(label="Tryout", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="panel:tryout")
    async def tryout_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "tryout"; LIMIT = 1; category_id = settings.get('ticket_category')
        if not category_id:
             if not interaction.response.is_done(): await send_embed_response(interaction, "Error", "Category not set.", discord.Color.red());
             return
        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"Max {LIMIT} tryout ticket.", discord.Color.orange()); return

        await interaction.response.defer(ephemeral=True, thinking=True) # Defer BEFORE creating channel
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if not channel or not staff_role: return # Exit if channel/role creation failed

        await interaction.followup.send(embed=create_embed("Ticket Created", f"{channel.mention}", discord.Color.green()), ephemeral=True) # Use followup
        try: await channel.send(f"{interaction.user.mention} {staff_role.mention}", delete_after=1) # Initial ping
        except Exception as e: print(f"Warning: Could not send initial ping in {channel.id}: {e}")

        # --- Tryout Application Logic (No Deletion) ---
        bot_msg_1 = None; username_msg = None; bot_msg_2 = None; stats_msg = None # Define vars outside try
        try:
            username_embed = create_embed("⚔️ Tryout: Step 1/2", "Reply with Roblox Username.", discord.Color.green()).set_footer(text="5 min.")
            bot_msg_1 = await channel.send(embed=username_embed)
            def check_username(m): return m.channel == channel and m.author == interaction.user and not m.author.bot
            username_msg = await self.bot.wait_for('message', check=check_username, timeout=300.0)
            roblox_username = username_msg.content

            stats_embed = create_embed("⚔️ Tryout: Step 2/2", f"Username: `{roblox_username}`\nSend stats screenshot.", discord.Color.green()).set_footer(text="5 min, must be image.")
            bot_msg_2 = await channel.send(embed=stats_embed)
            def check_stats(m): return m.channel == channel and m.author == interaction.user and not m.author.bot and m.attachments and m.attachments[0].content_type and m.attachments[0].content_type.startswith('image')
            stats_msg = await self.bot.wait_for('message', check=check_stats, timeout=300.0)
            stats_screenshot_url = stats_msg.attachments[0].url if stats_msg.attachments else None

            success_embed = create_embed("✅ Tryout Complete!", f"{interaction.user.mention}, {staff_role.mention} will review.", discord.Color.brand_green())
            success_embed.add_field(name="Roblox Username", value=roblox_username, inline=False)
            if stats_screenshot_url:
                try: success_embed.set_image(url=stats_screenshot_url)
                except Exception as e: print(f"Error setting image URL ({stats_screenshot_url}): {e}"); success_embed.add_field(name="Image Error", value="Could not embed.", inline=False)
            else: success_embed.add_field(name="Stats Image", value="Not provided/found.", inline=False)

            # Ensure bot instance is available
            view_bot = self.bot or interaction.client
            await channel.send(embed=success_embed, view=TicketCloseView(bot=view_bot))

        except asyncio.TimeoutError:
            timeout_embed = create_embed("Ticket Closed", "Auto-closed: Inactivity during application.", discord.Color.red())
            try:
                # Check if channel still exists before sending/deleting
                await channel.send(embed=timeout_embed)
                await asyncio.sleep(10)
                await channel.delete(reason="Tryout timeout")
            except discord.NotFound: pass # Channel already gone
            except discord.Forbidden: print(f"ERROR: Lacking permissions to delete channel {channel.id} after timeout.")
            except Exception as e: print(f"Error during tryout timeout cleanup for {channel.id}: {e}")
        except Exception as e:
            print(f"ERROR during tryout process in channel {getattr(channel, 'id', 'N/A')}: {e}")
            traceback.print_exc()
            try:
                 # Check if channel exists before sending error message
                 if channel:
                     await channel.send(embed=create_embed("Error", "Unexpected error during application. Try again or create standard ticket.", discord.Color.red()))
            except Exception as send_error:
                 print(f"Error sending error message to tryout channel: {send_error}")

    @discord.ui.button(label="Report a User", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="panel:report")
    async def report_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "report"; LIMIT = 10; category_id = settings.get('ticket_category')
        if not category_id:
             if not interaction.response.is_done(): await send_embed_response(interaction, "Error", "Category not set.", discord.Color.red());
             return
        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"Max {LIMIT} report tickets.", discord.Color.orange()); return

        await interaction.response.defer(ephemeral=True, thinking=True) # Defer BEFORE creating channel
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role:
            await interaction.followup.send(embed=create_embed("Ticket Created", f"{channel.mention}", discord.Color.green()), ephemeral=True) # Use followup
            embed = discord.Embed(title="🚨 User Report", description=f"{interaction.user.mention}, provide user, reason, proof. {staff_role.mention} will assist.", color=discord.Color.red())
            view_bot = self.bot or interaction.client
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=view_bot))


# --- MODAL FOR TICKET CLOSE REASON ---
class CloseReasonModal(discord.ui.Modal, title="Close Ticket Reason"):
    reason_input = discord.ui.TextInput(
        label="Reason for Closing", style=discord.TextStyle.paragraph,
        placeholder="Enter the reason...", required=True, min_length=3, max_length=1000 # Add max length
    )

    def __init__(self, bot_instance: TicketBot, target_channel: discord.TextChannel, closer: discord.Member):
        super().__init__()
        self.bot = bot_instance
        self.target_channel = target_channel
        self.closer = closer

    async def on_submit(self, interaction: discord.Interaction):
        # Defer here as close_ticket_logic can take time (API calls, file gen)
        await interaction.response.defer(ephemeral=True, thinking=True)
        reason = self.reason_input.value
        # Need to instantiate the view to call its method
        view_instance = TicketCloseView(bot=self.bot)
        try:
            # Pass reason to the logic handler
            await view_instance.close_ticket_logic(self.target_channel, self.closer, reason)
            await interaction.followup.send("✅ Ticket closing process initiated.", ephemeral=True) # Give success feedback
        except Exception as e:
            print(f"Error during close_ticket_logic call from modal: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Failed to initiate ticket closing.", ephemeral=True)


    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"ERROR in CloseReasonModal: {error}"); traceback.print_exc()
        try:
            # Check if response already sent before sending followup
            if not interaction.response.is_done():
                 await interaction.response.send_message("An error occurred submitting the reason.", ephemeral=True)
            else:
                 await interaction.followup.send("An error occurred submitting the reason.", ephemeral=True)
        except Exception as e:
             print(f"Error sending on_error message in CloseReasonModal: {e}")

# --- UPDATED TICKET CLOSE VIEW ---
class TicketCloseView(discord.ui.View):
    # This view contains the "Close" and "Delete" buttons within a ticket
    def __init__(self, bot: TicketBot = None):
        super().__init__(timeout=None); self.bot = bot

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Opens modal to ask for close reason after permission check."""
        # Ensure bot instance is available
        if not self.bot:
            print("TicketCloseView: Bot instance missing, attaching from interaction.")
            self.bot = interaction.client
            if not self.bot:
                 print("CRITICAL ERROR: Could not get bot instance in TicketCloseView.")
                 await interaction.response.send_message("Internal bot error.", ephemeral=True)
                 return

        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None

        # Ensure interaction.user is a Member for role checks
        is_member = isinstance(interaction.user, discord.Member)
        is_admin = interaction.user.guild_permissions.administrator if is_member else False
        is_staff = (staff_role and is_member and staff_role in interaction.user.roles)

        can_close = False
        # Allow creator OR staff/admin to close
        # Use .get() on topic to avoid error if None
        channel_topic = getattr(interaction.channel, 'topic', '') or ""
        if f"ticket-user-{interaction.user.id}" in channel_topic:
            can_close = True # Original creator
        elif is_staff or is_admin:
            can_close = True # Staff/Admin

        if not can_close:
            await send_embed_response(interaction, "Permission Denied", "Only creator or staff can close.", discord.Color.red())
            return

        # Open the modal to get the reason
        modal = CloseReasonModal(bot_instance=self.bot, target_channel=interaction.channel, closer=interaction.user)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Delete Ticket", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="ticket:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Permanently deletes ticket, staff only."""
        if not self.bot:
             print("TicketCloseView: Bot instance missing, attaching from interaction.")
             self.bot = interaction.client
             if not self.bot: print("CRITICAL ERROR: Bot instance lost."); await interaction.response.send_message("Internal error.", ephemeral=True); return

        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Error", "Staff role not configured.", discord.Color.red()); return
        staff_role = interaction.guild.get_role(staff_role_id)
        if not staff_role: await send_embed_response(interaction, "Error", "Staff role not found.", discord.Color.red()); return

        # Ensure interaction.user is a Member
        if not isinstance(interaction.user, discord.Member):
             await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return

        is_admin = interaction.user.guild_permissions.administrator
        is_staff = staff_role in interaction.user.roles

        if not is_staff and not is_admin:
            await send_embed_response(interaction, "Permission Denied", "Staff/Admin only.", discord.Color.red()); return

        # Defer first before sending warning message
        await interaction.response.defer(ephemeral=True) # Ephemeral defer is fine, warning is followup
        embed = create_embed("🗑️ Ticket Deletion", f"Marked by {interaction.user.mention}.\n**Deleting in 10s.**", discord.Color.dark_red())
        # Send non-ephemeral warning
        warning_message = await interaction.followup.send(embed=embed, ephemeral=False, wait=True)

        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason=f"Deleted by {interaction.user.name}")
            # Try to delete the warning message after channel deletion (might fail if perms change fast)
            # try: await warning_message.delete()
            # except: pass # Ignore if delete fails
        except discord.NotFound: pass # Channel already gone
        except discord.Forbidden:
             print(f"ERROR: Lacking delete permissions for channel {interaction.channel.id}")
             # Try sending ephemeral error *if possible*
             try: await interaction.followup.send(embed=create_embed("Error", "Lacking delete permissions.", discord.Color.red()), ephemeral=True)
             except Exception: pass
        except Exception as e:
            print(f"ERROR deleting ticket channel {interaction.channel.id}: {e}")
            traceback.print_exc()
            try: await interaction.followup.send(embed=create_embed("Error", "Failed to delete ticket.", discord.Color.red()), ephemeral=True)
            except Exception: pass

    # --- Close Ticket Logic (Handles Archiving) ---
    async def close_ticket_logic(self, channel: discord.TextChannel, user: discord.Member, reason: str = "No reason provided"):
        """Handles transcript generation, message sending, and channel archival."""
        guild = channel.guild
        if not guild: return # Should not happen in guild channel context

        # Ensure bot has instance
        if not self.bot:
             print("CRITICAL ERROR: Bot instance missing in close_ticket_logic.")
             try: await channel.send("Internal error closing ticket.")
             except: pass
             return

        settings = self.bot.get_guild_settings(guild.id)
        archive_category_id = settings.get('archive_category')
        if not archive_category_id:
            await channel.send(embed=create_embed("Error", "Archive category not set.", discord.Color.red())); return
        archive_category = guild.get_channel(archive_category_id)
        if not archive_category or not isinstance(archive_category, discord.CategoryChannel):
            await channel.send(embed=create_embed("Error", "Archive category invalid.", discord.Color.red())); return

        # Send "Closing..." message immediately
        closing_msg = await channel.send(embed=create_embed("Archiving...", f"Ticket is being closed by {user.mention} and archived.", discord.Color.light_grey()))

        # Generate Transcript (can take time)
        transcript_file = await generate_transcript(channel)

        # Prepare closing embed with reason
        embed = discord.Embed(title="Ticket Closed", description=f"Closed by: {user.mention}\n**Reason:**\n```{reason}```", color=discord.Color.orange())
        transcript_file.seek(0)
        transcript_message = None
        try:
            # Send transcript file with the embed
            transcript_message = await channel.send(
                embed=embed,
                file=discord.File(transcript_file, filename=f"{channel.name}-transcript.txt")
            )
        except discord.HTTPException as e:
            if e.code == 40005: # Request Entity Too Large
                await channel.send(embed=create_embed("Transcript Too Large", "Transcript exceeds Discord's file size limit.", discord.Color.orange()))
                # Still send the closing embed without the file
                try: await channel.send(embed=embed)
                except Exception as send_err: print(f"Error sending closing embed after transcript fail: {send_err}")
            else:
                await channel.send(embed=create_embed("Error", f"Could not upload transcript: {e}", discord.Color.red()))
                try: await channel.send(embed=embed) # Try sending embed anyway
                except Exception as send_err: print(f"Error sending closing embed after transcript fail: {send_err}")
        except discord.Forbidden:
             await channel.send(embed=create_embed("Error", "Lacking permissions to send file/embed.", discord.Color.red()))
        except Exception as e:
             print(f"ERROR sending transcript for {channel.id}: {e}")
             traceback.print_exc()
             await channel.send(embed=create_embed("Error", f"Transcript send error: {e}", discord.Color.red()))

        # Clean up "Closing..." message
        try: await closing_msg.delete()
        except: pass

        await asyncio.sleep(3) # Shorter delay before moving

        # Prepare overwrites for archived channel (deny @everyone, allow bot, allow staff read-only)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, view_channel=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, view_channel=True) # Ensure bot can see it
        }
        staff_role_id = settings.get('staff_role')
        if staff_role_id:
             staff_role = guild.get_role(staff_role_id)
             if staff_role:
                 overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False, view_channel=True) # Staff read-only

        # Try to move and edit permissions
        try:
            # Sanitize name further for archival to avoid potential conflicts
            base_name = channel.name.replace("closed-","") # Remove previous "closed-" if any
            closed_name = f"closed-{base_name[:75]}-{channel.id}"[:100] # Ensure unique and within limits

            await channel.edit(
                name=closed_name,
                category=archive_category,
                overwrites=overwrites,
                reason=f"Closed by {user.name}. Reason: {reason}"
            )

            # Attempt to remove view from the *transcript message*
            if transcript_message:
                 try:
                     await transcript_message.edit(view=None)
                 except (discord.NotFound, discord.Forbidden): pass # Ignore if message gone or no perms
                 except Exception as edit_err: print(f"Failed to remove view from transcript msg: {edit_err}")

            # Send final confirmation
            await channel.send(embed=create_embed("Archived", f"Moved to {archive_category.name} and locked.", discord.Color.greyple()))

        except discord.Forbidden:
            print(f"ERROR: Bot lacks permissions to move/edit channel {channel.id} to archive.")
            await channel.send(embed=create_embed("Error", "Lacking permissions to archive.", discord.Color.red()))
        except discord.NotFound:
            print(f"WARNING: Channel {channel.id} not found during archival (possibly deleted).")
        except Exception as e:
            print(f"ERROR during archival of {channel.id}: {e}")
            traceback.print_exc()
            await channel.send(embed=create_embed("Error", f"Archival error: {e}", discord.Color.red()))

# End of Part 3/4
# bot.py (Part 4/4)

# --- SETUP COMMANDS (Hybrid - Works as '!' and '/') ---
# Use 4 spaces for decorators and def, 8 spaces inside functions

@bot.hybrid_command(name="set_panel_channel", description="Sets channel for the ticket panel.")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="Channel for the ticket panel.")
async def set_panel_channel(ctx: commands.Context, channel: discord.TextChannel):
    bot.update_guild_setting(ctx.guild.id, "panel_channel", channel.id)
    await send_embed_response(ctx, "Setup", f"Panel channel set to {channel.mention}", discord.Color.green())

@bot.hybrid_command(name="set_ticket_category", description="Sets category for new tickets.")
@commands.has_permissions(administrator=True)
@app_commands.describe(category="Category for new tickets.")
async def set_ticket_category(ctx: commands.Context, category: discord.CategoryChannel):
    bot.update_guild_setting(ctx.guild.id, "ticket_category", category.id)
    await send_embed_response(ctx, "Setup", f"Ticket category set to `{category.name}`", discord.Color.green())

@bot.hybrid_command(name="set_archive_category", description="Sets category for closed tickets.")
@commands.has_permissions(administrator=True)
@app_commands.describe(category="Category for archived tickets.")
async def set_archive_category(ctx: commands.Context, category: discord.CategoryChannel):
    bot.update_guild_setting(ctx.guild.id, "archive_category", category.id)
    await send_embed_response(ctx, "Setup", f"Archive category set to `{category.name}`", discord.Color.green())

@bot.hybrid_command(name="set_staff_role", description="Sets the main staff role.")
@commands.has_permissions(administrator=True)
@app_commands.describe(role="Your staff/support role.")
async def set_staff_role(ctx: commands.Context, role: discord.Role):
    bot.update_guild_setting(ctx.guild.id, "staff_role", role.id)
    await send_embed_response(ctx, "Setup", f"Staff role set to {role.mention}", discord.Color.green())

@bot.hybrid_command(name="set_escalation_role", description="Sets role for !escalate.")
@commands.has_permissions(administrator=True)
@app_commands.describe(role="Senior staff/manager role.")
async def set_escalation_role(ctx: commands.Context, role: discord.Role):
    bot.update_guild_setting(ctx.guild.id, "escalation_role", role.id)
    await send_embed_response(ctx, "Setup", f"Escalation role set to {role.mention}", discord.Color.green())

@bot.hybrid_command(name="set_prefix", description="Sets bot prefix for this server.")
@commands.has_permissions(administrator=True)
@app_commands.describe(prefix="New prefix (max 5 chars).")
async def set_prefix(ctx: commands.Context, prefix: str):
    if len(prefix) == 0: # Prevent empty prefix
        await send_embed_response(ctx, "Error", "Prefix cannot be empty.", discord.Color.orange()); return
    if len(prefix) > 5:
        await send_embed_response(ctx, "Error", "Prefix max 5 chars.", discord.Color.red()); return
    bot.update_guild_setting(ctx.guild.id, "prefix", prefix)
    await send_embed_response(ctx, "Setup", f"Prefix set to `{prefix}`", discord.Color.green())

@bot.hybrid_command(name="set_appeal_channel", description="Sets channel for blacklist appeals.")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="Channel for appeal reviews.")
async def set_appeal_channel(ctx: commands.Context, channel: discord.TextChannel):
    bot.update_guild_setting(ctx.guild.id, "appeal_channel", channel.id)
    await send_embed_response(ctx, "Setup", f"Appeal channel set to {channel.mention}", discord.Color.green())

# --- PANEL CREATION COMMAND ---
@bot.hybrid_command(name="create_panel", description="Sends the ticket panel.")
@commands.has_permissions(administrator=True)
async def create_panel(ctx: commands.Context):
    if not await check_setup(ctx): return # Check setup first
    settings = bot.get_guild_settings(ctx.guild.id); panel_channel_id = settings.get('panel_channel')
    if not panel_channel_id: await send_embed_response(ctx, "Error", "Panel channel not set.", discord.Color.red()); return
    panel_channel = bot.get_channel(panel_channel_id)
    if not panel_channel: await send_embed_response(ctx, "Error", "Panel channel not found.", discord.Color.red()); return

    # Check bot permissions in panel channel *before* sending
    bot_member = ctx.guild.me
    perms = panel_channel.permissions_for(bot_member)
    if not perms.send_messages or not perms.embed_links:
         await send_embed_response(ctx, "Error", f"I lack Send Messages or Embed Links permission in {panel_channel.mention}.", discord.Color.red()); return

    embed = discord.Embed(title="Support & Tryouts", description="Select an option below to create a ticket.", color=0x2b2d31) # Dark color
    if ctx.guild.icon: embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.add_field(name="🎫 Standard Ticket", value="General help, questions, issues.", inline=False)
    embed.add_field(name="⚔️ Tryout", value="Apply to join the clan.", inline=False)
    embed.add_field(name="🚨 Report a User", value="Report rule breakers.", inline=False)
    embed.set_footer(text=f"{ctx.guild.name} Support")
    try:
        # Pass bot instance to the view
        await panel_channel.send(embed=embed, view=TicketPanelView(bot=bot))
        await send_embed_response(ctx, "Panel Created", f"Panel sent to {panel_channel.mention}", discord.Color.green())
    except discord.Forbidden: await send_embed_response(ctx, "Error", f"Failed to send panel to {panel_channel.mention} (Permission error).", discord.Color.red())
    except Exception as e:
        print(f"Error sending panel: {e}"); traceback.print_exc()
        await send_embed_response(ctx, "Error", f"Could not send panel: {e}", discord.Color.red())

# --- TICKET MANAGEMENT COMMANDS ---

# --- STAFF CHECKERS ---
def is_staff():
    """Decorator check if user is staff or admin."""
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild: return False # Not in a guild
        if not isinstance(ctx.author, discord.Member): return False # Ensure author is member

        settings = bot.get_guild_settings(ctx.guild.id); staff_role_id = settings.get('staff_role')
        # Check if staff role is set *and* valid
        staff_role = ctx.guild.get_role(staff_role_id) if staff_role_id else None

        # Check for admin first, then staff role
        if ctx.author.guild_permissions.administrator: return True
        if staff_role and staff_role in ctx.author.roles: return True

        # If neither, send error and return False
        await send_embed_response(ctx, "Permission Denied", "Staff command only.", discord.Color.red()); return False
    return commands.check(predicate)

async def is_staff_interaction(interaction: discord.Interaction) -> bool:
    """Async check function for slash commands if user is staff or admin."""
    if not interaction.guild: return False # Not in a guild
    if not isinstance(interaction.user, discord.Member): return False # Ensure user is member

    settings = bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
    staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None

    if interaction.user.guild_permissions.administrator: return True
    if staff_role and staff_role in interaction.user.roles: return True

    await send_embed_response(interaction, "Permission Denied", "Staff command only.", discord.Color.red()); return False

# --- TICKET CHANNEL CHECK ---
def in_ticket_channel():
    """Decorator check if command is used in an open ticket channel."""
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild: return False # Safety check
        settings = bot.get_guild_settings(ctx.guild.id)
        # Check if channel exists and its category matches the configured ticket category
        if ctx.channel and ctx.channel.category_id == settings.get('ticket_category'): return True
        await send_embed_response(ctx, "Error", "Only usable in open ticket channels.", discord.Color.red()); return False
    return commands.check(predicate)

# --- HELP COMMAND ---
@bot.command(name="help")
@commands.guild_only()
@is_staff()
async def help_command(ctx: commands.Context):
    """Shows the staff help menu for the bot."""
    settings = bot.get_guild_settings(ctx.guild.id); prefix = settings.get("prefix", "!")
    embed = discord.Embed(title="🛠️ Staff Help", description=f"My prefix here is `{prefix}`", color=discord.Color.blue())
    embed.add_field(name="Setup (Admin Only)", value=
        "`/set_panel_channel`\n`/set_ticket_category`\n`/set_archive_category`\n"
        "`/set_staff_role`\n`/set_escalation_role`\n`/set_appeal_channel`\n"
        f"`{prefix}setprefix` or `/set_prefix`\n`/create_panel`", inline=False)
    embed.add_field(name="Tickets (Staff Only)", value=
        f"`{prefix}close` (Use button)\n`{prefix}add @user`\n`{prefix}remove @user`\n"
        f"`{prefix}rename <name>`\n`{prefix}claim`\n`{prefix}unclaim`\n"
        f"`{prefix}escalate`\n`{prefix}purge <amount>`\n`{prefix}help`", inline=False)
    embed.add_field(name="Moderation (Admin Only)", value=
        f"`{prefix}blacklist @user <reason>`\n`{prefix}unblacklist @user`\n"
        "`/announce <#channel> <message>`\n`/ticket_stats`", inline=False)
    embed.set_footer(text="Staff also use buttons: Close, Delete, Approve, Reject")
    await ctx.send(embed=embed, ephemeral=True) # Help is ephemeral

# --- STANDARD TICKET COMMANDS ---
@bot.command(name="close")
@commands.guild_only() # Let button logic handle detailed permission check
async def close(ctx: commands.Context):
    """Directs user to use the close button (which includes reason modal)."""
    settings = bot.get_guild_settings(ctx.guild.id)
    category_id = settings.get('ticket_category'); archive_id = settings.get('archive_category')
    # Basic check if it's potentially a ticket channel or already archived
    if ctx.channel.category_id not in [category_id, archive_id] or category_id is None:
        await send_embed_response(ctx, "Error", "Not a ticket channel.", discord.Color.red()); return
    if ctx.channel.category_id == archive_id:
        await send_embed_response(ctx, "Error", "Already closed.", discord.Color.red()); return
    # Direct to button for consistency and reason modal
    await send_embed_response(ctx, "Use Button", "Please use the 'Close Ticket' button below.", discord.Color.blue(), ephemeral=True)


@bot.command(name="add")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def add(ctx: commands.Context, user: discord.Member):
    """Adds a user to the current ticket channel."""
    try:
        await ctx.channel.set_permissions(user, read_messages=True, send_messages=True, view_channel=True)
        await send_embed_response(ctx, "User Added", f"{user.mention} added by {ctx.author.mention}.", discord.Color.green(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(ctx, "Error", "Lacking permissions.", discord.Color.red())
    except Exception as e: await send_embed_response(ctx, "Error", f"Failed: {e}", discord.Color.red())


@bot.command(name="remove")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def remove(ctx: commands.Context, user: discord.Member):
    """Removes a user from the current ticket channel."""
    try:
        # Check if user is the original ticket creator (don't remove them easily?)
        # For simplicity, allow removal, but could add a check here.
        await ctx.channel.set_permissions(user, overwrite=None) # Reset perms
        await send_embed_response(ctx, "User Removed", f"{user.mention} removed by {ctx.author.mention}.", discord.Color.orange(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(ctx, "Error", "Lacking permissions.", discord.Color.red())
    except Exception as e: await send_embed_response(ctx, "Error", f"Failed: {e}", discord.Color.red())

# --- TICKET TOOL COMMANDS ---
@bot.command(name="rename")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def rename(ctx: commands.Context, *, new_name: str):
    """Renames the current ticket channel."""
    try:
        # Basic sanitization
        clean_name = "".join(c for c in new_name if c.isalnum() or c in ('-','_')).lower()[:100] or f"ticket-{ctx.channel.id}"
        await ctx.channel.edit(name=clean_name)
        await send_embed_response(ctx, "Renamed", f"Channel renamed to `{clean_name}`.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(ctx, "Error", "Lacking rename permissions.", discord.Color.red())
    except Exception as e: await send_embed_response(ctx, "Error", f"Rename failed: {e}", discord.Color.red())

@bot.command(name="escalate")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def escalate(ctx: commands.Context):
    """Pings the escalation role in the ticket."""
    settings = bot.get_guild_settings(ctx.guild.id); esc_role_id = settings.get("escalation_role")
    if not esc_role_id: await send_embed_response(ctx, "Error", "Escalation role not set.", discord.Color.red()); return
    esc_role = ctx.guild.get_role(esc_role_id)
    if not esc_role: await send_embed_response(ctx, "Error", "Escalation role not found.", discord.Color.red()); return
    embed = create_embed("Ticket Escalated", f"🚨 By {ctx.author.mention}. {esc_role.mention} has been notified.", discord.Color.red())
    try:
        await ctx.send(content=esc_role.mention, embed=embed) # Ping the role
    except discord.Forbidden: await send_embed_response(ctx, "Error", "Cannot send message/ping.", discord.Color.red())
    except Exception as e: await send_embed_response(ctx, "Error", f"Escalation failed: {e}", discord.Color.red())


@bot.command(name="claim")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def claim(ctx: commands.Context):
    """Claims the current ticket, adding info to the topic."""
    current_topic = ctx.channel.topic or ""
    if "claimed-by-" in current_topic:
        claimer_id_str = current_topic.split("claimed-by-")[-1].split(" ")[0]
        try: claimer_id = int(claimer_id_str); claimer = ctx.guild.get_member(claimer_id) or f"ID: {claimer_id}"
        except ValueError: claimer = "Unknown User"
        await send_embed_response(ctx, "Error", f"Already claimed by {claimer}.", discord.Color.orange()); return

    base_topic_parts = current_topic.split(" ")
    base_topic = base_topic_parts[0] # Assume 'ticket-user-ID' is first
    # Add simple fallback if topic doesn't start correctly
    if not base_topic.startswith("ticket-user-"): base_topic = f"ticket-user-{ctx.channel.id}"
    new_topic = f"{base_topic} claimed-by-{ctx.author.id}"
    try:
        await ctx.channel.edit(topic=new_topic)
        await send_embed_response(ctx, "Ticket Claimed", f"🎫 Claimed by {ctx.author.mention}.", discord.Color.green(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(ctx, "Error", "Cannot edit topic.", discord.Color.red())
    except Exception as e: await send_embed_response(ctx, "Error", f"Failed claim: {e}", discord.Color.red())

@bot.command(name="unclaim")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def unclaim(ctx: commands.Context):
    """Unclaims the current ticket."""
    current_topic = ctx.channel.topic or ""
    if "claimed-by-" not in current_topic:
        await send_embed_response(ctx, "Error", "Not claimed.", discord.Color.orange()); return

    claimer_id_str = current_topic.split("claimed-by-")[-1].split(" ")[0]
    try: claimer_id = int(claimer_id_str)
    except ValueError: await send_embed_response(ctx, "Error", "Could not identify claimer.", discord.Color.red()); return

    is_admin = ctx.author.guild_permissions.administrator
    if ctx.author.id != claimer_id and not is_admin:
        claimer = ctx.guild.get_member(claimer_id) or f"ID: {claimer_id}"
        await send_embed_response(ctx, "Permission Denied", f"Claimed by {claimer}.", discord.Color.red()); return

    base_topic_parts = current_topic.split(" ")
    base_topic = base_topic_parts[0] # Assume 'ticket-user-ID' is first
    if not base_topic.startswith("ticket-user-"): base_topic = f"ticket-user-{ctx.channel.id}" # Fallback
    try:
        await ctx.channel.edit(topic=base_topic) # Restore original part of topic
        await send_embed_response(ctx, "Ticket Unclaimed", "🔓 Unclaimed.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(ctx, "Error", "Cannot edit topic.", discord.Color.red())
    except Exception as e: await send_embed_response(ctx, "Error", f"Failed unclaim: {e}", discord.Color.red())

# --- CORRECTED PURGE COMMAND ---
@bot.command(name="purge")
@commands.guild_only()
@is_staff()
@in_ticket_channel() # Ensure it's in an open ticket channel
async def purge(ctx: commands.Context, amount: int):
    """Deletes messages in the ticket channel (max 100)."""
    if amount <= 0: await send_embed_response(ctx, "Error", "Amount must be > 0.", discord.Color.orange()); return
    if amount > 100: await send_embed_response(ctx, "Error", "Max 100 messages.", discord.Color.orange()); return

    try:
        # Purge amount + 1 to include the command message itself (if it's a prefix command)
        limit = amount + 1 if ctx.prefix else amount # Slash commands don't have a visible trigger message to delete
        deleted = await ctx.channel.purge(limit=limit)
        deleted_count = len(deleted)
        # Adjust count if command message was included and deleted
        if ctx.prefix and ctx.message in deleted: deleted_count -= 1

        await send_embed_response(ctx, "Purged", f"🗑️ Deleted {deleted_count} messages.", discord.Color.green(), ephemeral=True) # Ephemeral confirm
    except discord.Forbidden: await send_embed_response(ctx, "Error", "No permission to delete.", discord.Color.red())
    except Exception as e: await send_embed_response(ctx, "Error", f"Purge failed: {e}", discord.Color.red())


# --- BLACKLIST COMMANDS ---
@bot.hybrid_command(name="blacklist", description="Blacklist a user from creating tickets.")
@commands.has_permissions(administrator=True) # Admin only
@app_commands.describe(user="User to blacklist.", reason="Reason for blacklist.")
async def blacklist(ctx: commands.Context, user: discord.Member, *, reason: str):
    settings = bot.get_guild_settings(ctx.guild.id); user_id_str = str(user.id)
    if user.id == ctx.author.id: await send_embed_response(ctx, "Error", "Cannot blacklist self.", discord.Color.orange()); return
    if user.bot: await send_embed_response(ctx, "Error", "Cannot blacklist bots.", discord.Color.orange()); return
    # Use .get() to safely access blacklist dict, provide empty dict if missing
    if user_id_str in settings.get("blacklist", {}): await send_embed_response(ctx, "Error", "Already blacklisted.", discord.Color.orange()); return
    # Ensure blacklist key exists before assigning
    if "blacklist" not in settings: settings["blacklist"] = {}
    settings["blacklist"][user_id_str] = reason; save_settings(bot.settings) # Save changes
    await send_embed_response(ctx, "User Blacklisted", f"{user.mention} blacklisted: `{reason}`.", discord.Color.red())

@bot.hybrid_command(name="unblacklist", description="Unblacklist a user.")
@commands.has_permissions(administrator=True) # Admin only
@app_commands.describe(user="User to unblacklist.")
async def unblacklist(ctx: commands.Context, user: discord.Member):
    settings = bot.get_guild_settings(ctx.guild.id); user_id_str = str(user.id)
    blacklist_dict = settings.get("blacklist", {}) # Use .get()
    if user_id_str not in blacklist_dict: await send_embed_response(ctx, "Error", "Not blacklisted.", discord.Color.orange()); return
    del blacklist_dict[user_id_str] # Remove from the dict
    settings["blacklist"] = blacklist_dict # Update settings with modified dict
    save_settings(bot.settings) # Save changes
    await send_embed_response(ctx, "User Unblacklisted", f"{user.mention} unblacklisted.", discord.Color.green())

# --- ANNOUNCE COMMAND ---
@bot.hybrid_command(name="announce", description="Send an announcement to a channel.")
@is_staff() # Staff only
@app_commands.describe(channel="Channel to announce in.", message="The announcement message.")
# Note: Slash commands need explicit Attachment option for file uploads
# @app_commands.describe(attachment="Optional image to attach.") # Uncomment if adding slash attachment
async def announce(ctx: commands.Context, channel: discord.TextChannel, *, message: str): # Add attachment: discord.Attachment = None for slash
    """Sends an announcement embed, checks for image in prefix command."""
    embed = discord.Embed(title="📢 Announcement", description=message, color=discord.Color.blue())
    author_name = ctx.author.display_name if isinstance(ctx.author, discord.Member) else ctx.author.name
    embed.set_footer(text=f"By {author_name}")

    # Check for attachments only in prefix command context for now
    image_url = None
    if isinstance(ctx, commands.Context) and ctx.message.attachments:
        attachment = ctx.message.attachments[0]
        # Basic check if it's likely an image
        if attachment.content_type and attachment.content_type.startswith("image/"):
            image_url = attachment.url
            embed.set_image(url=image_url)
        else:
            embed.add_field(name="Attachment", value=f"[Link]({attachment.url})", inline=False)
    # TODO: Add proper handling for slash command attachments if needed later

    try:
        await channel.send(embed=embed)
        await send_embed_response(ctx, "Sent", f"To {channel.mention}.", discord.Color.green(), ephemeral=True)
    except discord.Forbidden: await send_embed_response(ctx, "Error", f"No permission in {channel.mention}.", discord.Color.red(), ephemeral=True)
    except Exception as e: await send_embed_response(ctx, "Error", f"Send failed: {e}", discord.Color.red(), ephemeral=True)


# --- SLASH-ONLY COMMAND ---
@bot.tree.command(name="ticket_stats", description="Shows server ticket stats.")
@app_commands.guild_only() # Ensure it's used in a guild
async def ticket_stats(interaction: discord.Interaction):
    """Shows stats about tickets on the server (Staff Only)."""
    if not await is_staff_interaction(interaction): return # Check staff permissions
    await interaction.response.defer(ephemeral=True) # Defer ephemerally

    settings = bot.get_guild_settings(interaction.guild.id)
    total_created = settings.get("ticket_counter", 1) - 1
    ticket_category_id = settings.get("ticket_category")
    open_tickets = 0

    if ticket_category_id:
        ticket_category = interaction.guild.get_channel(ticket_category_id)
        if ticket_category and isinstance(ticket_category, discord.CategoryChannel):
            # Count only text channels within the category
            open_tickets = len(ticket_category.text_channels)
        else:
            # Send warning if category is invalid, use followup because we deferred
             await interaction.followup.send(embed=create_embed("Warning", "Ticket category invalid/not found.", discord.Color.orange()), ephemeral=True)

    embed = discord.Embed(title=f"Ticket Stats: {interaction.guild.name}", color=discord.Color.light_grey())
    embed.add_field(name="Total Created", value=f"**{total_created}**", inline=True);
    embed.add_field(name="Open Tickets", value=f"**{open_tickets}**", inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True) # Send stats ephemerally


# --- RUN THE BOT ---
if __name__ == "__main__": # Good practice to wrap run call
    try:
        print("Attempting to run bot...")
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        print("CRITICAL ERROR: Login Failure - Improper token passed. Check .env file.")
    except discord.errors.PrivilegedIntentsRequired:
        print("CRITICAL ERROR: Privileged Intents Required - Enable Presence, Server Members, and Message Content intents in Developer Portal.")
    except Exception as e:
        print(f"CRITICAL ERROR during bot startup: {e}")
        traceback.print_exc()

# End of Part 4/4