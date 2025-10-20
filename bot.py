# bot.py (Part 1/5)

import discord
from discord.ext import commands
from discord import app_commands # Use this for slash command specifics
import json
import os
import io
import asyncio
from dotenv import load_dotenv
import traceback
from datetime import datetime

# --- SETTINGS MANAGEMENT (for multi-server) ---
SETTINGS_FILE = 'settings.json'

def load_settings():
    """Loads settings from settings.json, creating it if it doesn't exist."""
    if not os.path.exists(SETTINGS_FILE):
        # Log info level, not necessarily an error if it's the first run
        print(f"[INFO] {SETTINGS_FILE} not found. Creating a new one.")
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            return {} # Return empty dict after creating
        except IOError as e:
            print(f"[ERROR] Could not create {SETTINGS_FILE}: {e}")
            return {} # Return empty dict if creation fails
    try:
        # Ensure file has content before trying to load
        if os.path.getsize(SETTINGS_FILE) == 0:
            print(f"[WARNING] {SETTINGS_FILE} is empty. Using default settings.")
            return {}
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: # Specify encoding
            return json.load(f)
    except json.JSONDecodeError:
        # Log as error, as file exists but is invalid
        print(f"[ERROR] {SETTINGS_FILE} is corrupted. Please fix or delete it. Using empty settings.")
        # Optionally backup corrupted file here
        # try: os.rename(SETTINGS_FILE, SETTINGS_FILE + f'.corrupted_{int(time.time())}')
        # except OSError: pass
        return {}
    except Exception as e:
        print(f"[ERROR] Unexpected error loading settings: {e}")
        traceback.print_exc() # Print full traceback for loading errors
        return {}


def save_settings(settings):
    """Saves settings to settings.json"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: # Specify encoding
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"[ERROR] Could not save settings to {SETTINGS_FILE}: {e}")
        traceback.print_exc() # Print full traceback for saving errors

# --- BOT SETUP ---

# Load token from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("[CRITICAL ERROR] DISCORD_TOKEN not found in .env file or environment variables. Bot cannot start.")
    exit(1) # Exit with error code

# Define intents required by the bot
intents = discord.Intents.default()
intents.messages = True         # Required for message content in DMs (appeals)
intents.guilds = True           # Required for guild operations
intents.members = True          # Required for userinfo, roles, potentially blacklist/add/remove
intents.message_content = True  # Required for reading message content (tryout prompts, appeal DMs)

# Define the Bot Class (using commands.Bot for background tasks, but commands are via tree)
class TicketBot(commands.Bot):
    def __init__(self):
        # No command_prefix needed for a slash-command-only bot
        # We still use commands.Bot to easily add views persistently in setup_hook
        super().__init__(command_prefix=commands.when_mentioned, # Fallback prefix (mentions only)
                         intents=intents,
                         help_command=None) # Disable default help command
        self.settings = load_settings() # Load settings on initialization
        self.persistent_views_added = False

    async def setup_hook(self):
        # This is run once internally by discord.py before the bot is ready
        # Register persistent views here so they work after restarts
        if not self.persistent_views_added:
            # Pass self (the bot instance) to the views upon initialization
            self.add_view(TicketPanelView(self))
            self.add_view(TicketCloseView(self))
            self.add_view(AppealReviewView(self))
            self.persistent_views_added = True
            print("[INFO] Persistent views registered successfully.")
        # Sync slash commands with Discord
        try:
            print("[INFO] Attempting to sync application commands...")
            # Sync commands globally. Can take time to propagate initially.
            synced = await self.tree.sync()
            print(f"[INFO] Synced {len(synced)} application commands.")
            # Optional: Log synced command names
            # if synced: print(f"[DEBUG] Synced commands: {[cmd.name for cmd in synced]}")
        except discord.Forbidden:
             print("[ERROR] Bot lacks 'applications.commands' scope or permissions to sync slash commands.")
        except Exception as e:
            print(f"[ERROR] Failed to sync application commands: {e}")
            traceback.print_exc()

    async def on_ready(self):
        # Called when the bot is fully connected and ready
        print(f'[INFO] Logged in as: {self.user} (ID: {self.user.id})')
        print(f'[INFO] discord.py version: {discord.__version__}')
        print('[INFO] Bot is ready and online.')
        # Set bot presence/activity
        try:
            await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for tickets"))
            print("[INFO] Bot presence set successfully.")
        except Exception as e:
            print(f"[ERROR] Could not set bot presence: {e}")
        print('------')

    def get_guild_settings(self, guild_id: int):
        """Gets settings for a specific guild, ensuring defaults and correct types."""
        guild_id_str = str(guild_id)

        # Ensure self.settings is a dict, reload/reset if necessary
        if not isinstance(self.settings, dict):
            print("[CRITICAL WARNING] self.settings is not a dict! Reloading settings...")
            self.settings = load_settings()
            if not isinstance(self.settings, dict): # Still not dict? Reset.
                print("[CRITICAL ERROR] Could not load settings as dict. Resetting all settings!")
                self.settings = {}

        # Default structure for a guild's settings
        defaults = {
            "panel_channel": None, "ticket_category": None, "archive_category": None,
            "staff_role": None, "escalation_role": None, "appeal_channel": None,
            "ticket_counter": 1, "blacklist": {}
            # Removed prefix setting
        }

        # Get current settings for the guild, or create if missing
        guild_settings = self.settings.get(guild_id_str)
        updated = False

        # If guild settings don't exist or are the wrong type, initialize with defaults
        if not isinstance(guild_settings, dict):
             print(f"[WARNING] Settings for guild {guild_id_str} are invalid or missing. Initializing with defaults.")
             guild_settings = defaults.copy() # Use a copy of defaults
             self.settings[guild_id_str] = guild_settings # Add/overwrite in main settings dict
             updated = True # Mark for saving

        # Ensure all default keys exist in the retrieved or newly created guild settings
        for key, default_value in defaults.items():
            if key not in guild_settings:
                # print(f"[DEBUG] Adding missing key '{key}' with default value for guild {guild_id_str}") # Debug log
                guild_settings[key] = default_value
                updated = True

        # Save settings only if defaults were added or structure was reset
        if updated:
            save_settings(self.settings)

        return guild_settings # Return the validated guild_settings dictionary

    def update_guild_setting(self, guild_id: int, key: str, value):
        """Updates a specific setting for a guild."""
        # Use get_guild_settings to ensure the guild entry exists and is a dict
        settings = self.get_guild_settings(guild_id)
        # Should always be a dict now, but check again for safety
        if isinstance(settings, dict):
            settings[key] = value
            save_settings(self.settings) # Save the entire settings object
        else:
            # This case should ideally not be reached anymore
            print(f"[CRITICAL ERROR] Cannot update setting '{key}' for guild {guild_id}. Settings structure invalid.")


# Initialize the Bot instance
bot = TicketBot()

# --- HELPER FUNCTIONS ---

# --- HELPER FUNCTIONS ---

def create_embed(title: str = None, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
    """Helper function to create a standard embed, handles None values."""
    # Use None as default, pass discord.Embed.Empty *only* if the value is actually None
    final_title = title if title is not None else discord.Embed.Empty
    final_description = str(description) if description is not None else discord.Embed.Empty # Ensure description is string or Empty

    # Add basic length check for description to avoid errors
    if len(final_description) > 4096: # Discord embed description limit
        print(f"Warning: Truncating embed description starting with: {final_description[:50]}...")
        final_description = final_description[:4093] + "..."

    return discord.Embed(title=final_title, description=final_description, color=color)

# ... (The async def send_embed_response function follows) ...

async def send_embed_response(interaction: discord.Interaction, title: str = discord.Embed.Empty, description: str = discord.Embed.Empty, color: discord.Color = discord.Color.blurple(), ephemeral: bool = True):
    """Sends an embed response to an interaction, handling followup logic."""
    embed = create_embed(title, description, color)
    try:
        # Check if the interaction has already been responded to or deferred
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            # If not responded/deferred, send the initial response
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except discord.NotFound:
         # Interaction might expire if processing takes too long or user dismisses
         print(f"[WARNING] Interaction not found when sending response for '{title}'. User: {interaction.user.id}")
    except discord.Forbidden:
         # Bot lacks permissions in the channel
         print(f"[ERROR] Bot lacks permissions to send embed response in channel {interaction.channel_id} (Guild: {interaction.guild_id}).")
         # Attempt to notify the user via DM if it's the first response (more likely to fail on followup)
         if not interaction.response.is_done():
              try: await interaction.user.send(f"I lack permissions to send messages in {interaction.channel.mention}.")
              except Exception: pass # Ignore if DMs fail
    except Exception as e:
        print(f"[ERROR] Failed to send embed response for '{title}': {type(e).__name__} - {e}")
        traceback.print_exc()

# --- SLASH COMMAND GLOBAL ERROR HANDLER ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Global error handler specifically for slash command errors."""
    original_error = getattr(error, 'original', error) # Get original error if wrapped
    error_title = "Error"
    error_message = "An unexpected error occurred while processing your command." # Default
    log_message = f"Error executing slash command '{interaction.command.name if interaction.command else 'unknown'}' by {interaction.user.id}"

    if isinstance(error, app_commands.errors.MissingPermissions):
        error_title = "Permission Denied"
        error_message = "You lack the required permissions to use this command."
        print(f"{log_message}: MissingPermissions - {error.missing_permissions}")
    elif isinstance(error, app_commands.errors.CheckFailure):
        # Custom checks (like is_staff_check) usually send their own response.
        # Log that the check failed, but typically don't send another message.
        print(f"{log_message}: CheckFailure (likely handled by check decorator).")
        # If the interaction is somehow not responded to, send a generic check fail message
        if not interaction.response.is_done():
             # This indicates an issue with the check decorator not responding properly
             print("[WARNING] CheckFailure occurred but interaction was not responded to by check decorator.")
             await send_embed_response(interaction, "Check Failed", "You do not meet the requirements for this command.", discord.Color.orange())
        return # Prevent further processing
    elif isinstance(error, app_commands.CommandNotFound):
         # Should not happen with synced commands, but good to handle
         error_title = "Command Not Found"
         error_message = "This command seems to be invalid or is no longer available."
         print(f"{log_message}: CommandNotFound")
    elif isinstance(original_error, discord.Forbidden):
        # Permissions error *during* command execution (e.g., cannot send message, manage roles)
        error_title = "Permissions Error"
        missing_perms_str = f"Missing: `{', '.join(original_error.missing_perms)}`" if hasattr(original_error, 'missing_perms') else ""
        error_message = f"I lack the necessary permissions to complete this action. {missing_perms_str}"
        print(f"{log_message}: Forbidden - {original_error.text}. {missing_perms_str}")
    elif isinstance(error, app_commands.errors.CommandInvokeError):
        # Generic error within the command code itself
        error_title = "Command Execution Error"
        error_message = "An internal error occurred while executing this command. The issue has been logged."
        print(f"{log_message}: CommandInvokeError - Original error below:")
        traceback.print_exception(type(original_error), original_error, original_error.__traceback__)
    else:
        # Log other unexpected slash command errors
        error_title = "Unexpected Error"
        print(f"{log_message}: UNHANDLED SLASH COMMAND ERROR ({type(error)}): {error}")
        traceback.print_exception(type(error), error, error.__traceback__)

    # Attempt to send the error message ephemerally
    try:
        await send_embed_response(interaction, error_title, error_message, discord.Color.red(), ephemeral=True)
    except Exception as e:
        print(f"Failed to send error message via interaction: {e}")

# End of Part 1/5
# bot.py (Part 2/5)

# --- HELPER FUNCTIONS CONTINUED ---
async def check_setup(interaction: discord.Interaction) -> bool:
    """Checks if the bot is fully set up for the guild via slash command context."""
    guild_id = interaction.guild_id
    if not guild_id:
        await send_embed_response(interaction, "Error", "This command must be used in a server.", discord.Color.red())
        return False # Cannot check setup outside a guild

    try:
        settings = bot.get_guild_settings(guild_id) # Fetch settings for the guild
    except Exception as e:
         print(f"[ERROR] Failed to get guild settings during setup check for guild {guild_id}: {e}")
         await send_embed_response(interaction, "Critical Error", "Could not load server configuration.", discord.Color.red())
         return False # Cannot proceed without settings

    required_settings = ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']
    # Check if the values for required keys are actually set (not None)
    missing = [s.replace("_", " ").title() for s in required_settings if not settings.get(s)]

    if missing:
        embed = discord.Embed(
            title="Bot Not Fully Configured",
            description="An administrator must configure the following settings using `/setup` commands before the bot can function correctly:",
            color=discord.Color.red()
        )
        # List missing settings more clearly
        missing_commands = [f"- `/setup {s.lower().replace(' ', '_')}`" for s in missing]
        embed.add_field(name="Required Settings Missing", value="\n".join(missing_commands), inline=False)
        await send_embed_response(interaction, embed.title, embed.description, embed.color, ephemeral=True)
        return False
    return True # All required settings are present

# Helper to count a user's open tickets of a specific type
def count_user_tickets(guild: discord.Guild, user_id: int, category_id: int, ticket_type: str = None) -> int:
    """Counts open tickets for a user within a specific category, optionally filtering by type stored in topic."""
    category = guild.get_channel(category_id)
    # Ensure the category exists and is actually a category channel
    if not category or not isinstance(category, discord.CategoryChannel):
        print(f"[WARNING] Invalid category ID {category_id} provided for counting tickets in guild {guild.id}.")
        return 0 # Cannot count tickets if category is invalid

    count = 0
    user_id_str = str(user_id)
    # Iterate only through text channels within the specified category
    for channel in category.text_channels:
        # Check if channel topic exists and contains the user ID marker
        if channel.topic and f"ticket-user-{user_id_str}" in channel.topic:
            # If a specific type is requested, check for the type marker as well
            if ticket_type:
                if f"type-{ticket_type}" in channel.topic:
                    count += 1
            else:
                # If no type specified, count all tickets matching the user ID marker
                count += 1
    return count

# Helper function to create a new ticket channel
async def create_ticket_channel(interaction: discord.Interaction, ticket_type_name: str, settings: dict):
    """Creates and configures a new ticket text channel."""
    guild = interaction.guild
    user = interaction.user # The user who initiated the interaction

    # Validate essential settings retrieved from the dictionary
    staff_role_id = settings.get('staff_role')
    category_id = settings.get('ticket_category')

    # Fetch role and category objects, handling potential errors
    staff_role = guild.get_role(staff_role_id) if staff_role_id else None
    category = guild.get_channel(category_id) if category_id else None

    # Error checking for configuration
    if not staff_role:
        await send_embed_response(interaction, "Configuration Error", "The Staff Role specified in settings is invalid or not found.", discord.Color.red(), ephemeral=True)
        return None, None # Return None tuple on failure
    if not category or not isinstance(category, discord.CategoryChannel):
        await send_embed_response(interaction, "Configuration Error", "The Ticket Category specified in settings is invalid or not found.", discord.Color.red(), ephemeral=True)
        return None, None

    # Retrieve and increment ticket counter
    ticket_num = settings.get('ticket_counter', 1) # Default to 1 if missing
    bot.update_guild_setting(guild.id, "ticket_counter", ticket_num + 1) # Update counter in settings

    # Define channel permission overwrites
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False), # Hide from @everyone
        user: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True, attach_files=True, embed_links=True), # Allow user basic perms
        guild.me: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True, embed_links=True, attach_files=True, manage_channels=True, manage_permissions=True, manage_messages=True), # Bot needs extensive perms
        staff_role: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True, manage_messages=True, attach_files=True, embed_links=True) # Allow staff necessary perms
    }

    try:
        # Sanitize username for channel name (use display_name for better readability)
        safe_user_name = "".join(c for c in user.display_name if c.isalnum() or c in ('-', '_')).lower() or "user"
        # Ensure channel name is within Discord limits (100 chars)
        channel_name = f"{ticket_type_name}-{ticket_num}-{safe_user_name}"[:100]
        # Create a descriptive topic including user ID and type markers for identification
        # Ensure topic length is within Discord limits (1024 chars)
        topic = f"Ticket #{ticket_num} ({ticket_type_name.capitalize()}) for {user.name} ({user.id}). UserID marker: [ticket-user-{user.id} type-{ticket_type_name}]"[:1024]

        print(f"[INFO] Attempting to create channel '{channel_name}' in category '{category.name}' ({category.id}) for user {user.id}")
        # Create the channel with specified settings
        new_channel = await category.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=topic,
            reason=f"Ticket created via bot by {user.name} ({user.id})" # Audit log reason
        )
        print(f"[INFO] Channel created successfully: {new_channel.mention} ({new_channel.id})")
        return new_channel, staff_role # Return channel and role object on success

    except discord.Forbidden:
        # Specific error if bot lacks permissions
        print(f"[ERROR] Bot lacks permissions to create channel or set permissions in category {category.id}")
        await send_embed_response(interaction, "Permissions Error", "I lack the required permissions to create a ticket channel or set its permissions within the designated category.", discord.Color.red(), ephemeral=True)
        return None, None
    except Exception as e:
        # Catch any other unexpected errors during channel creation
        print(f"[ERROR] Failed to create ticket channel: {e}")
        traceback.print_exc()
        await send_embed_response(interaction, "Error", "An unexpected error occurred while trying to create the ticket channel.", discord.Color.red(), ephemeral=True)
        return None, None

# Helper function to generate a transcript file content
async def generate_transcript(channel: discord.TextChannel):
    """Generates transcript content as bytes, handling size limits."""
    messages = []
    # Iterate through all messages in the channel history, oldest first
    async for msg in channel.history(limit=None, oldest_first=True):
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') # Consistent UTC timestamp
        # Clean content: remove markdown, escape mentions
        clean_content = discord.utils.remove_markdown(discord.utils.escape_mentions(msg.content))
        author_display = f"{msg.author.display_name} ({msg.author.id})" # Include display name and ID
        # Add non-bot messages to the transcript list
        if not msg.author.bot:
            messages.append(f"[{timestamp}] {author_display}: {clean_content}")
        # Include attachment URLs in the transcript
        if msg.attachments:
            for att in msg.attachments:
                messages.append(f"[{timestamp}] [Attachment from {author_display}: {att.url}]")

    # Join messages into a single string
    transcript_content = "\n".join(messages)
    if not transcript_content:
        transcript_content = "No messages were sent in this ticket."

    # Encode to check size and handle potential truncation for Discord's file limit
    encoded_content = transcript_content.encode('utf-8')
    # Set a safe maximum size (e.g., 7.5MB)
    max_size = 7 * 1024 * 1024 + 512 * 1024

    if len(encoded_content) > max_size:
        print(f"[WARNING] Transcript for channel {channel.name} ({channel.id}) is too large ({len(encoded_content)} bytes), truncating.")
        # Truncate bytes, leaving room for a truncation notice
        truncated_content = encoded_content[:max_size - 200]
        try:
            # Attempt to decode back to string, ignoring potential mid-character cuts
            transcript_content = truncated_content.decode('utf-8', errors='ignore')
            transcript_content += "\n\n--- TRANSCRIPT TRUNCATED DUE TO DISCORD FILE SIZE LIMIT ---"
            encoded_content = transcript_content.encode('utf-8') # Re-encode truncated content
        except Exception as e:
             print(f"[ERROR] Error during transcript truncation for channel {channel.id}: {e}")
             # Provide a fallback error message if truncation fails
             return io.BytesIO(b"Transcript file was too large and could not be properly truncated.")

    # Return the encoded content within a BytesIO buffer, ready for file sending
    return io.BytesIO(encoded_content)

# --- APPEAL/MODAL CLASSES ---

# --- Modal for Appeal Approve/Reject Reason ---
class AppealReasonModal(discord.ui.Modal):
    """Modal popup for staff to enter reason for approving/rejecting an appeal."""
    def __init__(self, bot_instance: TicketBot, action: str, original_message: discord.Message, guild: discord.Guild, appealing_user_id: int):
        super().__init__(title=f"Appeal {action} Reason")
        self.bot = bot_instance; self.action = action; self.original_message = original_message
        self.guild = guild; self.appealing_user_id = appealing_user_id
        self.reason_input = discord.ui.TextInput(
            label="Reason", style=discord.TextStyle.paragraph,
            placeholder=f"Please provide the reason for {action.lower()}ing this appeal...",
            required=True, min_length=5, max_length=500
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Processes the reason, updates appeal, notifies user."""
        await interaction.response.defer(ephemeral=True); staff_member = interaction.user; reason = self.reason_input.value
        try: appealing_user = await self.bot.fetch_user(self.appealing_user_id)
        except discord.NotFound: await interaction.followup.send(embed=create_embed("Error", "Could not find the appealing user to notify.", discord.Color.red())); return

        if not self.original_message or not self.original_message.embeds:
            await interaction.followup.send(embed=create_embed("Error", "Could not find the original appeal message embed.", discord.Color.red())); return
        original_embed = self.original_message.embeds[0]; new_embed = original_embed.copy()

        if self.action == "Approve":
            title = "✅ Blacklist Appeal Approved"; color = discord.Color.green()
            dm_desc = f"Your blacklist appeal for **{self.guild.name}** has been approved by staff.\n\n**Reason Provided:**\n```{reason}```\nYou should now be able to create tickets again."
            settings = self.bot.get_guild_settings(self.guild.id); user_id_str = str(self.appealing_user_id)
            if user_id_str in settings.get("blacklist", {}):
                current_blacklist = settings["blacklist"] # Get the dict
                del current_blacklist[user_id_str] # Remove the user
                self.bot.update_guild_setting(self.guild.id, "blacklist", current_blacklist) # Save the modified dict
                print(f"[INFO] User {user_id_str} unblacklisted via appeal by {staff_member.name}.")
        else: # Reject
            title = "❌ Blacklist Appeal Rejected"; color = discord.Color.red()
            dm_desc = f"Your blacklist appeal for **{self.guild.name}** has been rejected by staff.\n\n**Reason Provided:**\n```{reason}```"

        try:
            dm_embed = create_embed(title, dm_desc, color); await appealing_user.send(embed=dm_embed)
        except discord.Forbidden: print(f"[WARNING] Could not DM user {appealing_user.id} (appeal {self.action.lower()}d - DMs disabled)")
        except Exception as e: print(f"[ERROR] Sending appeal result DM to {appealing_user.id}: {e}")

        new_embed.title = f"[{self.action.upper()}D by {staff_member.name}] Blacklist Appeal"
        new_embed.color = color
        new_embed.add_field(name=f"{self.action.capitalize()}d by {staff_member.display_name}", value=f"```{reason}```", inline=False)
        try: await self.original_message.edit(embed=new_embed, view=None) # Remove buttons
        except discord.NotFound: print("[WARNING] Original appeal message not found during edit.")
        except discord.Forbidden: print("[ERROR] Lacking permissions to edit original appeal message.")

        await interaction.followup.send(embed=create_embed("Action Complete", f"The appeal has been **{self.action.lower()}d**. User notified (if DMs enabled).", color), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"[ERROR] In AppealReasonModal: {error}"); traceback.print_exc()
        try:
            response_target = interaction.followup if interaction.response.is_done() else interaction.response
            await response_target.send("An error occurred processing the reason.", ephemeral=True)
        except Exception as e: print(f"[ERROR] Sending on_error message in AppealReasonModal: {e}")

# --- Persistent View for Appeal Review Buttons in Staff Channel ---
class AppealReviewView(discord.ui.View):
    """Persistent view with Approve/Reject buttons for staff appeal channel."""
    def __init__(self, bot_instance: TicketBot):
        super().__init__(timeout=None)
        self.bot = bot_instance # Store bot instance

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Permission check: Only staff can use these buttons
        if not self.bot: self.bot = interaction.client # Fetch bot instance if missing
        if not self.bot: print("[CRITICAL ERROR] Bot instance missing in AppealReviewView."); return False # Need bot instance

        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Setup Error", "Staff role not configured.", discord.Color.red()); return False
        staff_role = interaction.guild.get_role(staff_role_id)
        if not isinstance(interaction.user, discord.Member): await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return False
        is_admin = interaction.user.guild_permissions.administrator
        if (staff_role and staff_role in interaction.user.roles) or is_admin: return True
        else: await send_embed_response(interaction, "Permission Denied", "Only staff members can review appeals.", discord.Color.red()); return False

    @discord.ui.button(label="Approve Appeal", style=discord.ButtonStyle.success, emoji="✅", custom_id="persistent_appeal:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Cannot find appeal info.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "Cannot identify user.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        modal = AppealReasonModal(bot_instance=self.bot, action="Approve", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Reject Appeal", style=discord.ButtonStyle.danger, emoji="❌", custom_id="persistent_appeal:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Cannot find appeal info.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "Cannot identify user.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        modal = AppealReasonModal(bot_instance=self.bot, action="Reject", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)

# End of Part 2/5
# bot.py (Part 3/5 - Corrected)

# --- TICKET PANEL VIEW ---
class TicketPanelView(discord.ui.View):
    """Persistent view with buttons to create different types of tickets."""
    # Pass bot instance during init for persistent views
    def __init__(self, bot_instance: TicketBot):
        super().__init__(timeout=None)
        self.bot = bot_instance # Store bot instance directly

    async def send_appeal_dm(self, user: discord.Member, guild: discord.Guild, reason: str):
        """Sends the initial DM to blacklisted users with an appeal button."""
        embed = create_embed(f"Blacklisted on {guild.name}", f"You are currently blacklisted from creating tickets.\n**Reason:**\n```{reason}```\nIf you believe this is a mistake, you may submit an appeal below.", discord.Color.red())
        # Ensure bot instance is available
        if not self.bot: print("ERROR: Cannot get bot instance for AppealStartView."); return
        view = AppealStartView(bot_instance=self.bot, guild=guild, reason=reason)
        try:
            dm_channel = await user.create_dm()
            view.message = await dm_channel.send(embed=embed, view=view) # Store message for timeout handling
        except discord.Forbidden: print(f"[INFO] Cannot send appeal DM to {user.id} (DMs disabled).")
        except Exception as e: print(f"[ERROR] Failed to send appeal DM to {user.id}: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Checks blacklist and setup status before allowing button press."""
        # Ensure bot instance is available
        if not self.bot:
             print("[CRITICAL ERROR] Bot instance missing in TicketPanelView interaction_check.")
             try: # Try to inform user if possible
                 if not interaction.response.is_done(): await interaction.response.send_message("Internal bot error. Please try again later.", ephemeral=True)
                 else: await interaction.followup.send("Internal bot error. Please try again later.", ephemeral=True)
             except: pass
             return False # Cannot proceed
        if not interaction.guild: return False # Should not happen

        settings = self.bot.get_guild_settings(interaction.guild.id)
        blacklist = settings.get("blacklist", {}); user_id_str = str(interaction.user.id)

        # --- BLACKLIST CHECK ---
        if user_id_str in blacklist:
            reason = blacklist.get(user_id_str, "No reason provided.")
            # Use send_embed_response which handles interaction state
            await send_embed_response(interaction, "Action Denied", "You are currently blacklisted and cannot create new tickets.", discord.Color.red(), ephemeral=True)
            # Send appeal DM non-blockingly
            asyncio.create_task(self.send_appeal_dm(interaction.user, interaction.guild, reason))
            return False # Stop button callback

        # --- SETUP CHECK ---
        # Use check_setup helper function
        if not await check_setup(interaction):
            # check_setup already sends the error message
            return False # Stop button callback

        return True # Allow button callback

    # --- TICKET CREATION BUTTONS ---
    @discord.ui.button(label="Standard Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="persistent_panel:standard")
    async def standard_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the creation of a standard support ticket."""
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "standard"; LIMIT = 3; category_id = settings.get('ticket_category')
        if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket category not configured.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT: await send_embed_response(interaction, "Limit Reached", f"You may only have {LIMIT} open standard tickets at a time.", discord.Color.orange()); return

        # Defer BEFORE channel creation
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role:
            await interaction.followup.send(embed=create_embed("Ticket Created", f"Your standard ticket is ready: {channel.mention}", discord.Color.green()), ephemeral=True)
            embed = discord.Embed(title="🎫 Standard Support Ticket", description=f"Welcome, {interaction.user.mention}!\nPlease describe your question or issue in detail. A member of the {staff_role.mention} team will assist you shortly.", color=discord.Color.blue())
            # Let persistent view handle buttons by not passing view= here
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}")

    @discord.ui.button(label="Tryout Application", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="persistent_panel:tryout")
    async def tryout_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the tryout application ticket process."""
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "tryout"; LIMIT = 1; category_id = settings.get('ticket_category')
        if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket category not configured.", discord.Color.red()); return
        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT: await send_embed_response(interaction, "Limit Reached", f"You may only have {LIMIT} open tryout application.", discord.Color.orange()); return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if not channel or not staff_role: return

        await interaction.followup.send(embed=create_embed("Ticket Created", f"Tryout channel ready: {channel.mention}", discord.Color.green()), ephemeral=True)
        try: await channel.send(f"{interaction.user.mention} {staff_role.mention}", delete_after=1)
        except Exception as e: print(f"[WARNING] Could not send ping in {channel.id}: {e}")

        # --- Tryout Application Logic ---
        try:
            username_embed = create_embed("⚔️ Tryout Application - Step 1/2", "Please reply with your Roblox Username.", discord.Color.green()).set_footer(text="5 minute limit.")
            await channel.send(embed=username_embed)
            def check_username(m): return m.channel == channel and m.author == interaction.user and not m.author.bot
            username_msg = await self.bot.wait_for('message', check=check_username, timeout=300.0)
            roblox_username = username_msg.content.strip()

            stats_embed = create_embed("⚔️ Tryout Application - Step 2/2", f"`{roblox_username}`\nSend stats screenshot.", discord.Color.green()).set_footer(text="5 minute limit. Must be image.")
            await channel.send(embed=stats_embed)
            def check_stats(m): return m.channel == channel and m.author == interaction.user and not m.author.bot and m.attachments and m.attachments[0].content_type and m.attachments[0].content_type.startswith('image')
            stats_msg = await self.bot.wait_for('message', check=check_stats, timeout=300.0)
            stats_screenshot_url = stats_msg.attachments[0].url if stats_msg.attachments else None

            success_embed = create_embed("✅ Tryout Application Submitted", f"{interaction.user.mention}, {staff_role.mention} will review.", discord.Color.brand_green())
            success_embed.add_field(name="Roblox Username", value=roblox_username, inline=False)
            if stats_screenshot_url:
                try: success_embed.set_image(url=stats_screenshot_url)
                except Exception as e: print(f"[ERROR] Setting image URL: {e}"); success_embed.add_field(name="Image Error", value="Could not embed.", inline=False)
            else: success_embed.add_field(name="Stats Screenshot", value="Not provided.", inline=False)

            # Let persistent view handle buttons
            await channel.send(embed=success_embed)

        except asyncio.TimeoutError:
            timeout_embed = create_embed("Ticket Closed Automatically", "Inactivity during application.", discord.Color.red())
            try: await channel.send(embed=timeout_embed); await asyncio.sleep(10); await channel.delete(reason="Tryout timeout")
            except (discord.NotFound, discord.Forbidden): pass
            except Exception as e: print(f"[ERROR] Timeout cleanup: {e}")
        except Exception as e:
            print(f"[ERROR] Tryout process ({getattr(channel, 'id', 'N/A')}): {e}"); traceback.print_exc()
            try: await channel.send(embed=create_embed("Application Error", "Unexpected error. Close ticket & try again.", discord.Color.red()))
            except Exception: pass

    @discord.ui.button(label="Report a User", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="persistent_panel:report")
    async def report_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the creation of a user report ticket."""
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "report"; LIMIT = 10; category_id = settings.get('ticket_category')
        if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket category not configured.", discord.Color.red()); return
        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT: await send_embed_response(interaction, "Limit Reached", f"Max {LIMIT} open report tickets.", discord.Color.orange()); return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role:
            await interaction.followup.send(embed=create_embed("Ticket Created", f"Report channel ready: {channel.mention}", discord.Color.green()), ephemeral=True)
            embed = discord.Embed(title="🚨 User Report", description=f"{interaction.user.mention}, provide info:\n1. Username\n2. Reason\n3. Details\n4. Proof\n{staff_role.mention} will review.", color=discord.Color.red())
            # Let persistent view handle buttons
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}")

# --- MODAL FOR TICKET CLOSE REASON ---
class CloseReasonModal(discord.ui.Modal, title="Reason for Closing Ticket"):
    """Modal popup for staff/creator to enter reason for closing ticket."""
    reason_input = discord.ui.TextInput(
        label="Reason", style=discord.TextStyle.paragraph,
        placeholder="Please provide a brief reason for closing this ticket...",
        required=True, min_length=5, max_length=1000
    )

    def __init__(self, bot_instance: TicketBot, target_channel: discord.TextChannel, closer: discord.Member):
        super().__init__()
        self.bot = bot_instance
        self.target_channel = target_channel
        self.closer = closer

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        reason = self.reason_input.value
        # Instantiate the view containing the close logic
        # Need to ensure the bot instance is passed correctly
        view_instance = TicketCloseView(self.bot)
        try:
            # Call the actual closing logic
            await view_instance.close_ticket_logic(self.target_channel, self.closer, reason)
            await interaction.followup.send("✅ Ticket closing process initiated.", ephemeral=True)
        except Exception as e:
            print(f"Error calling close_ticket_logic from modal: {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Failed to initiate ticket closing.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"ERROR in CloseReasonModal: {error}"); traceback.print_exc()
        try: await send_embed_response(interaction, "Error", "An error occurred submitting the reason.", discord.Color.red())
        except Exception as e: print(f"Error sending on_error in CloseReasonModal: {e}")

# --- PERSISTENT TICKET CLOSE VIEW ---
class TicketCloseView(discord.ui.View):
    """Persistent view with 'Close' and 'Delete' buttons inside a ticket channel."""
    # Pass bot instance during init
    def __init__(self, bot_instance: TicketBot):
        super().__init__(timeout=None)
        self.bot = bot_instance # Store bot instance directly

    # --- Interaction check to ensure bot instance is available ---
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure bot instance is present before running button callbacks."""
        if not self.bot:
             print(f"TicketCloseView interaction_check: Bot instance missing, attempting to get from client.")
             self.bot = interaction.client # Try to get bot instance
             if not self.bot:
                  print("CRITICAL ERROR: Could not get bot instance in TicketCloseView.")
                  try: # Try to notify user
                      if not interaction.response.is_done(): await interaction.response.send_message("Internal bot error. Cannot process action.", ephemeral=True)
                      else: await interaction.followup.send("Internal bot error. Cannot process action.", ephemeral=True)
                  except: pass
                  return False # Stop if bot instance is missing
        return True # Proceed if bot instance exists

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="persistent_ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Opens modal to ask for close reason after permission check."""
        # Bot instance ensured by interaction_check
        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None
        if not isinstance(interaction.user, discord.Member): await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return
        is_admin = interaction.user.guild_permissions.administrator; is_staff = (staff_role and staff_role in interaction.user.roles)
        can_close = False; channel_topic = getattr(interaction.channel, 'topic', '') or ""
        if f"ticket-user-{interaction.user.id}" in channel_topic: can_close = True # Creator
        elif is_staff or is_admin: can_close = True # Staff/Admin
        if not can_close: await send_embed_response(interaction, "Permission Denied", "Only creator or staff.", discord.Color.red()); return
        modal = CloseReasonModal(bot_instance=self.bot, target_channel=interaction.channel, closer=interaction.user)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Delete Ticket", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="persistent_ticket:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Permanently deletes ticket, staff/admin only."""
        # Bot instance ensured by interaction_check
        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id or not (staff_role := interaction.guild.get_role(staff_role_id)): await send_embed_response(interaction, "Setup Error", "Staff role invalid.", discord.Color.red()); return
        if not isinstance(interaction.user, discord.Member): await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return
        is_admin = interaction.user.guild_permissions.administrator; is_staff = staff_role in interaction.user.roles
        if not is_staff and not is_admin: await send_embed_response(interaction, "Permission Denied", "Staff/Admin only.", discord.Color.red()); return

        await interaction.response.defer(ephemeral=True, thinking=True) # Defer ephemerally
        embed = create_embed("🗑️ Confirm Ticket Deletion", f"Ticket will be **permanently deleted** by {interaction.user.mention} in 10 seconds.", discord.Color.dark_red())
        warning_message = await interaction.channel.send(embed=embed) # Non-ephemeral warning
        await interaction.followup.send("Deletion initiated.", ephemeral=True) # Confirm to user
        await asyncio.sleep(10)
        try: await interaction.channel.delete(reason=f"Deleted by {interaction.user.name} ({interaction.user.id})")
        except discord.NotFound: pass # Already gone
        except discord.Forbidden: print(f"ERROR: Lacking delete permissions for {interaction.channel.id}") # Log error
        except Exception as e: print(f"ERROR deleting ticket {interaction.channel.id}: {e}"); traceback.print_exc()

    async def close_ticket_logic(self, channel: discord.TextChannel, user: discord.Member, reason: str = "No reason provided"):
        """Handles transcript generation, messaging, and channel archival."""
        guild = channel.guild
        if not guild: print(f"ERROR: No guild context for channel {channel.id}."); return
        if not self.bot: print("CRITICAL ERROR: Bot instance missing in close_ticket_logic."); await channel.send("Internal error."); return

        settings = self.bot.get_guild_settings(guild.id)
        archive_category_id = settings.get('archive_category')
        if not archive_category_id or not (archive_category := guild.get_channel(archive_category_id)) or not isinstance(archive_category, discord.CategoryChannel):
            await channel.send(embed=create_embed("Configuration Error", "Archive category invalid.", discord.Color.red())); return

        closing_msg = None
        try: closing_msg = await channel.send(embed=create_embed("Archiving Ticket...", f"Closing by {user.mention}. Generating transcript...", discord.Color.light_grey()))
        except Exception as e: print(f"Error sending 'Archiving' msg: {e}")

        transcript_file = await generate_transcript(channel)
        embed = discord.Embed(title="Ticket Closed", description=f"Closed by: {user.mention}\n**Reason:**\n```{reason}```", color=discord.Color.orange())
        transcript_file.seek(0); transcript_message = None
        try: transcript_message = await channel.send(embed=embed, file=discord.File(transcript_file, filename=f"{channel.name}-transcript.txt"))
        except discord.HTTPException as e:
            if e.code == 40005: await channel.send(embed=create_embed("Transcript Too Large", "Archiving without upload.", discord.Color.orange()))
            else: await channel.send(embed=create_embed("Error", f"Upload failed (HTTP {e.code}): {e.text}", discord.Color.red()))
            try: await channel.send(embed=embed) # Send embed anyway
            except Exception: pass
        except discord.Forbidden: await channel.send(embed=create_embed("Error", "Lacking send/file permissions.", discord.Color.red()))
        except Exception as e: print(f"ERROR sending transcript: {e}"); traceback.print_exc(); await channel.send(embed=create_embed("Error", "Transcript send error.", discord.Color.red()))

        # Clean up "Closing..." message
        if closing_msg:
            try:
                await closing_msg.delete()
            except (discord.NotFound, discord.Forbidden): # Be specific about expected errors
                pass # Ignore if message is gone or we lack perms
            except Exception as e:
                print(f"Error deleting 'closing' message: {e}") # Log unexpected errors

        await asyncio.sleep(3)

        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True)}
        staff_role_id = settings.get('staff_role')
        if staff_role_id and (staff_role := guild.get_role(staff_role_id)): overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=False)
        try:
            base_name = channel.name.replace("closed-","")[:75]; closed_name = f"closed-{base_name}-{channel.id}"[:100]
            await channel.edit(name=closed_name, category=archive_category, overwrites=overwrites, reason=f"Closed by {user.name}. Reason: {reason}")

            # Attempt to remove view from the transcript message if it was sent successfully
            if transcript_message:
                 try:
                     await transcript_message.edit(view=None)
                 except (discord.NotFound, discord.Forbidden): # Handle specific expected errors
                     pass # Ignore if message gone or no perms
                 except Exception as edit_err:
                     print(f"Failed to remove view from transcript msg: {edit_err}") # Log other errors

            await channel.send(embed=create_embed("Ticket Archived", f"Moved to {archive_category.name} and locked.", discord.Color.greyple()))
        except discord.Forbidden: print(f"ERROR: Lacking move/edit perms for {channel.id}."); await channel.send(embed=create_embed("Error", "Lacking archive permissions.", discord.Color.red()))
        except discord.NotFound: print(f"WARNING: Channel {channel.id} not found during archival.")
        except Exception as e: print(f"ERROR archiving {channel.id}: {e}"); traceback.print_exc(); await channel.send(embed=create_embed("Error", "Archival error.", discord.Color.red()))

# End of Part 3/5
# bot.py (Part 4/5)

# --- SLASH COMMAND GROUPS ---
# Group setup commands under /setup
# default_permissions apply to all commands within the group unless overridden
setup_group = app_commands.Group(
    name="setup",
    description="Administrator commands to configure the ticket bot.",
    guild_only=True,
    default_permissions=discord.Permissions(administrator=True) # Only Admins can use /setup commands
)
# Group ticket management commands under /ticket
# Permissions for ticket commands are checked within each command using a decorator
ticket_group = app_commands.Group(
    name="ticket",
    description="Staff commands for managing tickets.",
    guild_only=True
)
# Group moderation commands under /mod
mod_group = app_commands.Group(
    name="mod",
    description="Moderation commands for announcements and blacklisting.",
    guild_only=True
)
# Group of general utility commands
utility_group = app_commands.Group(
    name="info",
    description="General utility and informational commands.",
    guild_only=True
)


# --- SETUP COMMANDS (Now under /setup group) ---

@setup_group.command(name="panel_channel", description="Sets the channel where the ticket creation panel is posted.")
@app_commands.describe(channel="The text channel designated for the ticket panel.")
async def set_panel_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Sets the channel for the ticket creation panel."""
    # Admin check is handled by the group's default_permissions
    bot.update_guild_setting(interaction.guild.id, "panel_channel", channel.id)
    await send_embed_response(interaction, "Setup Complete", f"The ticket panel channel has been successfully set to {channel.mention}.", discord.Color.green())

@setup_group.command(name="ticket_category", description="Sets the category where new tickets will be created.")
@app_commands.describe(category="The category channel for new tickets.")
async def set_ticket_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    """Sets the category for new tickets."""
    bot.update_guild_setting(interaction.guild.id, "ticket_category", category.id)
    await send_embed_response(interaction, "Setup Complete", f"New tickets will now be created in the `{category.name}` category.", discord.Color.green())

@setup_group.command(name="archive_category", description="Sets the category where closed tickets will be moved.")
@app_commands.describe(category="The category channel for archived tickets.")
async def set_archive_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    """Sets the category for archived tickets."""
    bot.update_guild_setting(interaction.guild.id, "archive_category", category.id)
    await send_embed_response(interaction, "Setup Complete", f"Closed tickets will be moved to the `{category.name}` category.", discord.Color.green())

@setup_group.command(name="staff_role", description="Sets the primary staff role for ticket access and pings.")
@app_commands.describe(role="The role designated as staff.")
async def set_staff_role(interaction: discord.Interaction, role: discord.Role):
    """Sets the main staff role."""
    bot.update_guild_setting(interaction.guild.id, "staff_role", role.id)
    await send_embed_response(interaction, "Setup Complete", f"The staff role has been set to {role.mention}.", discord.Color.green())

@setup_group.command(name="escalation_role", description="Sets the senior staff role pinged by /ticket escalate.")
@app_commands.describe(role="The role to ping for ticket escalations.")
async def set_escalation_role(interaction: discord.Interaction, role: discord.Role):
    """Sets the escalation role."""
    bot.update_guild_setting(interaction.guild.id, "escalation_role", role.id)
    await send_embed_response(interaction, "Setup Complete", f"The escalation role has been set to {role.mention}.", discord.Color.green())

@setup_group.command(name="appeal_channel", description="Sets the channel where blacklist appeals are sent.")
@app_commands.describe(channel="The channel for staff to review appeals.")
async def set_appeal_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Sets the blacklist appeal channel."""
    bot.update_guild_setting(interaction.guild.id, "appeal_channel", channel.id)
    await send_embed_response(interaction, "Setup Complete", f"Blacklist appeals will now be sent to {channel.mention}.", discord.Color.green())

# --- PANEL CREATION COMMAND (Now under /setup group) ---
@setup_group.command(name="create_panel", description="Sends the ticket creation panel to the configured channel.")
async def create_panel(interaction: discord.Interaction):
    """Sends the ticket creation panel."""
    if not await check_setup(interaction): return # Verify setup is complete

    settings = bot.get_guild_settings(interaction.guild.id)
    panel_channel_id = settings.get('panel_channel')
    panel_channel = bot.get_channel(panel_channel_id) if panel_channel_id else None

    if not panel_channel or not isinstance(panel_channel, discord.TextChannel):
        await send_embed_response(interaction, "Configuration Error", "The panel channel is invalid or not found.", discord.Color.red()); return

    # Check bot permissions in the target channel before sending
    bot_member = interaction.guild.me
    perms = panel_channel.permissions_for(bot_member)
    if not perms.send_messages or not perms.embed_links:
         await send_embed_response(interaction, "Permissions Error", f"I lack the necessary permissions (Send Messages, Embed Links) in {panel_channel.mention}.", discord.Color.red()); return

    embed = discord.Embed(title="Support & Tryouts", description="To create a ticket, please select the appropriate option below.", color=0x2b2d31)
    if interaction.guild.icon: embed.set_thumbnail(url=interaction.guild.icon.url)
    embed.add_field(name="🎫 Standard Ticket", value="For general help, questions, or other issues.", inline=False)
    embed.add_field(name="⚔️ Tryout Application", value="Apply to join the clan by completing a short application.", inline=False)
    embed.add_field(name="🚨 Report a User", value="Submit a report against a user for rule violations. Please have evidence ready.", inline=False)
    embed.set_footer(text=f"{interaction.guild.name} Support System")
    try:
        # Pass the bot instance to the persistent view
        await panel_channel.send(embed=embed, view=TicketPanelView(bot))
        await send_embed_response(interaction, "Panel Created", f"The ticket panel has been successfully sent to {panel_channel.mention}.", discord.Color.green())
    except Exception as e:
        print(f"[ERROR] Failed to send ticket panel: {e}"); traceback.print_exc()
        await send_embed_response(interaction, "Error", "An unexpected error occurred while attempting to send the panel.", discord.Color.red())

# --- PERMISSION CHECK DECORATORS FOR SLASH COMMANDS ---

async def is_staff_interaction(interaction: discord.Interaction) -> bool:
    """Async check function for slash commands to verify if a user is staff or an admin."""
    if not interaction.guild: return False # Should not happen in guild_only commands
    if not isinstance(interaction.user, discord.Member): return False # Ensure user is a member

    settings = bot.get_guild_settings(interaction.guild.id)
    staff_role_id = settings.get('staff_role')
    staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None

    # Check for administrator permissions first, then for the staff role
    if interaction.user.guild_permissions.administrator:
        return True
    if staff_role and staff_role in interaction.user.roles:
        return True

    # If neither, send a denial message and return False
    await send_embed_response(interaction, "Permission Denied", "This command is reserved for staff members only.", discord.Color.red()); return False

def is_staff_check():
    """Decorator to apply the is_staff_interaction check to an application command."""
    return app_commands.check(is_staff_interaction)

def in_ticket_channel_check():
    """Decorator to check if a command is used within an open ticket channel."""
    async def predicate(interaction: discord.Interaction) -> bool:
        settings = bot.get_guild_settings(interaction.guild.id)
        # Check if the channel's category matches the configured ticket category
        if interaction.channel and interaction.channel.category_id == settings.get('ticket_category'):
            return True
        await send_embed_response(interaction, "Invalid Channel", "This command can only be used within an open ticket channel.", discord.Color.red())
        return False
    return app_commands.check(predicate)


# --- TICKET MANAGEMENT COMMANDS (Now under /ticket group) ---

@ticket_group.command(name="add", description="Adds a user to the current ticket.")
@app_commands.describe(user="The user to add to this ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_add(interaction: discord.Interaction, user: discord.Member):
    """Adds a user to the current ticket channel."""
    try:
        await interaction.channel.set_permissions(user, read_messages=True, send_messages=True, view_channel=True)
        # Send a non-ephemeral confirmation message to the channel
        await send_embed_response(interaction, "User Added", f"{user.mention} has been added to this ticket by {interaction.user.mention}.", discord.Color.green(), ephemeral=False)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I lack the permission to modify channel permissions.", discord.Color.red())
    except Exception as e:
        await send_embed_response(interaction, "Error", f"An unexpected error occurred: {e}", discord.Color.red())

@ticket_group.command(name="remove", description="Removes a user from the current ticket.")
@app_commands.describe(user="The user to remove from this ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_remove(interaction: discord.Interaction, user: discord.Member):
    """Removes a user from the current ticket channel."""
    try:
        # Resetting permissions for the user effectively removes them
        await interaction.channel.set_permissions(user, overwrite=None)
        await send_embed_response(interaction, "User Removed", f"{user.mention} has been removed from this ticket by {interaction.user.mention}.", discord.Color.orange(), ephemeral=False)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I lack the permission to modify channel permissions.", discord.Color.red())
    except Exception as e:
        await send_embed_response(interaction, "Error", f"An unexpected error occurred: {e}", discord.Color.red())

@ticket_group.command(name="rename", description="Renames the current ticket channel.")
@app_commands.describe(new_name="The new name for the ticket channel (spaces become hyphens).")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_rename(interaction: discord.Interaction, new_name: str):
    """Renames the current ticket channel."""
    try:
        # Sanitize the new name for channel naming rules
        clean_name = "".join(c for c in new_name if c.isalnum() or c in ('-','_ ')).replace(' ','-').lower()[:100]
        # Provide a fallback name if the sanitized name is empty
        if not clean_name:
            clean_name = f"ticket-{interaction.channel.id}"

        await interaction.channel.edit(name=clean_name, reason=f"Renamed by {interaction.user.name}")
        await send_embed_response(interaction, "Ticket Renamed", f"The channel has been renamed to `{clean_name}`.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I lack the permission to rename this channel.", discord.Color.red())
    except Exception as e:
        await send_embed_response(interaction, "Error", f"An unexpected error occurred while renaming: {e}", discord.Color.red())

@ticket_group.command(name="escalate", description="Pings the senior staff role in the current ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_escalate(interaction: discord.Interaction):
    """Pings the escalation role in the ticket."""
    settings = bot.get_guild_settings(interaction.guild.id)
    esc_role_id = settings.get("escalation_role")

    if not esc_role_id or not (esc_role := interaction.guild.get_role(esc_role_id)):
        await send_embed_response(interaction, "Configuration Error", "The escalation role is not set up correctly or cannot be found.", discord.Color.red()); return

    embed = create_embed("Ticket Escalated", f"🚨 This ticket requires senior attention! Escalated by {interaction.user.mention}. {esc_role.mention}, please assist.", discord.Color.red())
    try:
        # Defer ephemerally before sending the public ping
        await interaction.response.defer(ephemeral=True)
        # Send the public ping to the ticket channel
        await interaction.channel.send(content=esc_role.mention, embed=embed)
        # Send a confirmation back to the staff member who used the command
        await interaction.followup.send("Escalation ping sent successfully.", ephemeral=True)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I was unable to send a message or ping the role in this channel.", discord.Color.red())
    except Exception as e:
        await send_embed_response(interaction, "Error", f"An unexpected error occurred during escalation: {e}", discord.Color.red())

# End of Part 4/5
# bot.py (Part 5/5)

@ticket_group.command(name="claim", description="Claims the current ticket to indicate you are handling it.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_claim(interaction: discord.Interaction):
    """Claims the current ticket."""
    current_topic = interaction.channel.topic or ""
    if "claimed-by-" in current_topic:
        # Extract claimer ID robustly
        parts = current_topic.split(" ")
        claimer_part = next((part for part in parts if part.startswith("claimed-by-")), None)
        claimer_id_str = claimer_part.split("-")[-1] if claimer_part else None
        claimer = "Unknown User"
        if claimer_id_str and claimer_id_str.isdigit():
             claimer_id = int(claimer_id_str)
             claimer_member = interaction.guild.get_member(claimer_id)
             # Use mention if member found, otherwise ID
             claimer = claimer_member.mention if claimer_member else f"User ID: {claimer_id}"
        await send_embed_response(interaction, "Already Claimed", f"This ticket is already claimed by {claimer}.", discord.Color.orange()); return

    # Reconstruct topic preserving essential parts
    topic_parts = current_topic.split(" ")
    # Find the user ID part
    base_topic = next((part for part in topic_parts if part.startswith("ticket-user-")), f"ticket-user-{interaction.channel.id}")
    # Find the type part
    type_topic = next((part for part in topic_parts if part.startswith("type-")), "")
    # Combine parts and add claimer, ensure within topic length limit
    new_topic = f"{base_topic} {type_topic} claimed-by-{interaction.user.id}".strip()[:1024]

    try:
        await interaction.channel.edit(topic=new_topic, reason=f"Claimed by {interaction.user.name}")
        await send_embed_response(interaction, "Ticket Claimed", f"🎫 {interaction.user.mention} has claimed this ticket.", discord.Color.green(), ephemeral=False)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I cannot edit the channel topic.", discord.Color.red())
    except Exception as e:
        await send_embed_response(interaction, "Error", f"Failed to claim ticket: {e}", discord.Color.red())

@ticket_group.command(name="unclaim", description="Releases the current ticket back to the queue.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_unclaim(interaction: discord.Interaction):
    """Unclaims the current ticket."""
    current_topic = interaction.channel.topic or ""
    if "claimed-by-" not in current_topic:
        await send_embed_response(interaction, "Not Claimed", "This ticket is not currently claimed.", discord.Color.orange()); return

    parts = current_topic.split(" ")
    claimer_part = next((part for part in parts if part.startswith("claimed-by-")), None)
    claimer_id_str = claimer_part.split("-")[-1] if claimer_part else None
    claimer_id = None
    if claimer_id_str and claimer_id_str.isdigit(): claimer_id = int(claimer_id_str)

    if not claimer_id:
        # If claimer ID can't be found, maybe just allow any staff to unclaim? Or deny? Deny for safety.
        await send_embed_response(interaction, "Error", "Could not identify the original claimer from the channel topic.", discord.Color.red()); return

    # Ensure interaction user is a member
    if not isinstance(interaction.user, discord.Member):
         await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return

    is_admin = interaction.user.guild_permissions.administrator
    # Allow original claimer OR admin to unclaim
    if interaction.user.id != claimer_id and not is_admin:
        claimer = interaction.guild.get_member(claimer_id) or f"User ID: {claimer_id}"
        await send_embed_response(interaction, "Permission Denied", f"This ticket is claimed by {claimer}. Only they or an administrator can unclaim it.", discord.Color.red()); return

    # Reconstruct topic without claimer part
    base_topic = next((part for part in parts if part.startswith("ticket-user-")), f"ticket-user-{interaction.channel.id}")
    type_topic = next((part for part in parts if part.startswith("type-")), "")
    new_topic = f"{base_topic} {type_topic}".strip()[:1024]

    try:
        await interaction.channel.edit(topic=new_topic, reason=f"Unclaimed by {interaction.user.name}")
        await send_embed_response(interaction, "Ticket Unclaimed", f"🔓 {interaction.user.mention} has unclaimed this ticket. It is now open for any staff member.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I cannot edit the channel topic.", discord.Color.red())
    except Exception as e:
        await send_embed_response(interaction, "Error", f"Failed to unclaim ticket: {e}", discord.Color.red())

@ticket_group.command(name="purge", description="Deletes messages in the ticket (max 100).")
@app_commands.describe(amount="Number of messages to delete (1-100).")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    """Deletes messages in the current ticket channel."""
    # Defer ephemerally before purging
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        # Slash commands don't have a visible trigger message, so limit is just amount
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(embed=create_embed("Messages Purged", f"🗑️ Successfully deleted {len(deleted)} messages.", discord.Color.green()), ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(embed=create_embed("Permissions Error", "I lack the required permission to delete messages in this channel.", discord.Color.red()), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(embed=create_embed("Error", f"An unexpected error occurred during purge: {e}", discord.Color.red()), ephemeral=True)

@ticket_group.command(name="slowmode", description="Sets slowmode in the current ticket channel.")
@app_commands.describe(delay="Slowmode delay in seconds (0 to disable, max 21600).")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_slowmode(interaction: discord.Interaction, delay: app_commands.Range[int, 0, 21600]):
    """Sets slowmode delay for the current ticket channel."""
    try:
        await interaction.channel.edit(slowmode_delay=delay, reason=f"Slowmode set by {interaction.user.name}")
        status = f"disabled" if delay == 0 else f"set to {delay} seconds"
        # Send non-ephemeral confirmation
        await send_embed_response(interaction, "Slowmode Updated", f"⏳ Slowmode has been {status} for this ticket channel.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I lack the permission to change the slowmode setting.", discord.Color.red())
    except Exception as e:
        await send_embed_response(interaction, "Error", f"An unexpected error occurred setting slowmode: {e}", discord.Color.red())


# --- MODERATION COMMANDS (Now under /mod group) ---

@mod_group.command(name="blacklist", description="Blacklists a user from creating tickets.")
@app_commands.describe(user="The user to blacklist.", reason="The reason for the blacklist (will be shown to user).")
@app_commands.checks.has_permissions(administrator=True) # Admin only check
async def mod_blacklist(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Blacklists a user."""
    if user.id == interaction.user.id: await send_embed_response(interaction, "Action Denied", "You cannot blacklist yourself.", discord.Color.orange()); return
    if user.bot: await send_embed_response(interaction, "Action Denied", "Bots cannot be blacklisted.", discord.Color.orange()); return
    # Prevent blacklisting admins? Optional check.
    # if user.guild_permissions.administrator: await send_embed_response(interaction, "Action Denied", "Administrators cannot be blacklisted.", discord.Color.orange()); return

    settings = bot.get_guild_settings(interaction.guild.id); user_id_str = str(user.id)
    blacklist_dict = settings.setdefault("blacklist", {}) # Ensure dict exists

    if user_id_str in blacklist_dict:
        await send_embed_response(interaction, "Already Blacklisted", f"{user.mention} is already blacklisted for: `{blacklist_dict[user_id_str]}`.", discord.Color.orange()); return

    # Ensure reason isn't excessively long
    reason = reason[:500] + "..." if len(reason) > 500 else reason
    blacklist_dict[user_id_str] = reason
    bot.update_guild_setting(interaction.guild.id, "blacklist", blacklist_dict) # Update whole dict
    await send_embed_response(interaction, "User Blacklisted", f"{user.mention} has been **blacklisted** from creating tickets.\nReason: `{reason}`.", discord.Color.red())

@mod_group.command(name="unblacklist", description="Removes a user from the ticket blacklist.")
@app_commands.describe(user="The user to unblacklist.")
@app_commands.checks.has_permissions(administrator=True) # Admin only check
async def mod_unblacklist(interaction: discord.Interaction, user: discord.Member):
    """Unblacklists a user."""
    settings = bot.get_guild_settings(interaction.guild.id); user_id_str = str(user.id)
    blacklist_dict = settings.get("blacklist", {})

    if user_id_str not in blacklist_dict:
        await send_embed_response(interaction, "Not Found", f"{user.mention} is not currently blacklisted.", discord.Color.orange()); return

    del blacklist_dict[user_id_str] # Remove from the dict
    bot.update_guild_setting(interaction.guild.id, "blacklist", blacklist_dict) # Save modified dict
    await send_embed_response(interaction, "User Unblacklisted", f"{user.mention} has been **unblacklisted** and can now create tickets.", discord.Color.green())

@mod_group.command(name="announce", description="Sends an announcement (plain text, image, or JSON embed).")
@app_commands.describe(
    channel="The channel to send the announcement to.",
    message="The text message (required if no JSON/image attached).",
    json_file="Attach embed JSON file (overrides message/image).",
    image_file="Attach an image file (sent with text, ignored if JSON used)."
)
@is_staff_check() # Staff check
async def mod_announce(interaction: discord.Interaction, channel: discord.TextChannel, message: str = None, json_file: discord.Attachment = None, image_file: discord.Attachment = None):
    """Sends announcement. JSON > Image > Text priority."""
    await interaction.response.defer(ephemeral=True, thinking=True) # Defer ephemerally

    embed_to_send = None; content_to_send = message; file_to_send = None

    # 1. Process JSON if provided (highest priority)
    if json_file:
        if not json_file.filename.lower().endswith('.json'): await interaction.followup.send(embed=create_embed("Error", "Invalid file type. Please attach a `.json` file for embeds.", discord.Color.red()), ephemeral=True); return
        try:
            json_bytes = await json_file.read(); embed_data = json.loads(json_bytes.decode('utf-8'))
            if not isinstance(embed_data, dict): raise ValueError("JSON must be an object (dictionary).")
            # Create embed from dict, let discord.py handle validation
            embed_to_send = discord.Embed.from_dict(embed_data)
            content_to_send = None; image_file = None # Ignore others
            print(f"[INFO] Loaded embed from {json_file.filename} for announcement.")
        except Exception as e: await interaction.followup.send(embed=create_embed("JSON Error", f"Failed to process JSON file: {e}", discord.Color.red()), ephemeral=True); return

    # 2. Process Image if provided (and no JSON)
    elif image_file:
        if not image_file.content_type or not image_file.content_type.startswith("image/"):
            await interaction.followup.send(embed=create_embed("Error", "Invalid file type. Please attach an image file.", discord.Color.red()), ephemeral=True); return
        try:
            image_bytes = await image_file.read()
            file_to_send = discord.File(io.BytesIO(image_bytes), filename=image_file.filename)
            print(f"[INFO] Prepared image file: {image_file.filename} for announcement.")
        except Exception as e: await interaction.followup.send(embed=create_embed("Error", f"Failed to read image attachment: {e}", discord.Color.red()), ephemeral=True); return

    # 3. Check if there's anything to send
    if embed_to_send is None and content_to_send is None and file_to_send is None:
         await interaction.followup.send(embed=create_embed("Error", "Nothing to announce. Please provide message text, attach an image, or attach a JSON embed file.", discord.Color.orange()), ephemeral=True); return

    # 4. Send the announcement
    try:
        await channel.send(content=content_to_send, embed=embed_to_send, file=file_to_send)
        await interaction.followup.send(embed=create_embed("Announcement Sent", f"Your message has been delivered to {channel.mention}.", discord.Color.green()), ephemeral=True)
    except discord.Forbidden: await interaction.followup.send(embed=create_embed("Permissions Error", f"I do not have permission to send messages (or files/embeds) in {channel.mention}.", discord.Color.red()), ephemeral=True)
    except discord.HTTPException as e: await interaction.followup.send(embed=create_embed("Send Error", f"Failed to send message/embed: {e}", discord.Color.red()), ephemeral=True)
    except Exception as e: print(f"[ERROR] Announce send failed: {e}"); traceback.print_exc(); await interaction.followup.send(embed=create_embed("Error", "An unexpected error occurred during sending.", discord.Color.red()), ephemeral=True)


# --- UTILITY COMMANDS (Now under /info group) ---

@utility_group.command(name="userinfo", description="Displays information about a server member.")
@app_commands.describe(member="The member to get information about (defaults to you).")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    """Shows details about a user."""
    # Ensure command is used in a guild
    if not interaction.guild: await send_embed_response(interaction, "Error", "Command unavailable in DMs.", discord.Color.red()); return
    target = member or interaction.user # Target is Member type
    embed = discord.Embed(title=f"User Information", description=f"Details for {target.mention}", color=target.color or discord.Color.blue(), timestamp=discord.utils.utcnow())
    if target.avatar: embed.set_thumbnail(url=target.avatar.url)
    embed.set_author(name=str(target), icon_url=target.display_avatar.url) # Use display_avatar

    embed.add_field(name="Username", value=f"`{target.name}`", inline=True)
    embed.add_field(name="User ID", value=f"`{target.id}`", inline=True)
    embed.add_field(name="Nickname", value=f"`{target.nick}`" if target.nick else "None", inline=True)
    embed.add_field(name="Joined Server", value=discord.utils.format_dt(target.joined_at, style='R') if target.joined_at else "Unknown", inline=True) # Relative time, handle None
    embed.add_field(name="Joined Discord", value=discord.utils.format_dt(target.created_at, style='R'), inline=True)
    embed.add_field(name="Is Bot?", value="Yes" if target.bot else "No", inline=True)
    # Roles list, excluding @everyone, reverse for hierarchy, mention roles
    roles = [role.mention for role in reversed(target.roles) if role.id != interaction.guild.id]
    role_str = ", ".join(roles) if roles else "None"
    if len(role_str) > 1020: role_str = role_str[:1020] + "..." # Truncate if needed
    embed.add_field(name=f"Roles ({len(roles)})", value=role_str or "None", inline=False)
    embed.add_field(name="Highest Role", value=target.top_role.mention if target.top_role.id != interaction.guild.id else "None", inline=True)
    embed.add_field(name="Status", value=str(target.status).capitalize(), inline=True)
    # Add activity if present and has a name
    activity_str = "None"
    if target.activity and hasattr(target.activity, 'name') and target.activity.name:
         activity_type = target.activity.type.name.capitalize() if target.activity.type else ''
         activity_str = f"{activity_type} {target.activity.name}"
    embed.add_field(name="Activity", value=activity_str, inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=False) # Not ephemeral

@utility_group.command(name="serverinfo", description="Displays information about the current server.")
async def serverinfo(interaction: discord.Interaction):
    """Shows details about the server."""
    if not interaction.guild: await send_embed_response(interaction, "Error", "Command unavailable in DMs.", discord.Color.red()); return
    guild = interaction.guild
    embed = discord.Embed(title=f"Server Information", description=f"Details for **{guild.name}**", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
    if guild.icon: embed.set_thumbnail(url=guild.icon.url)
    if guild.banner: embed.set_image(url=guild.banner.url) # Show banner if available

    embed.add_field(name="Server ID", value=f"`{guild.id}`", inline=True)
    # Fetch owner if not cached, handle potential errors
    owner_str = "Unknown"
    if guild.owner: owner_str = guild.owner.mention
    elif guild.owner_id:
         try: owner = await bot.fetch_user(guild.owner_id); owner_str = owner.mention
         except Exception: owner_str = f"ID: `{guild.owner_id}`"
    embed.add_field(name="Owner", value=owner_str, inline=True)
    embed.add_field(name="Created On", value=discord.utils.format_dt(guild.created_at, style='F'), inline=False)
    # Member counts (rely on member_count, fetch members might be too slow/intensive)
    members = guild.member_count or "N/A"
    # Estimate humans/bots based on member_count if cache is incomplete
    humans = sum(1 for m in guild.members if not m.bot) if guild.chunked else "N/A (Cache?)"
    bots = sum(1 for m in guild.members if m.bot) if guild.chunked else "N/A (Cache?)"
    embed.add_field(name="Members", value=f"Total: {members}\nHumans: ~{humans}\nBots: ~{bots}", inline=True)
    embed.add_field(name="Channels", value=f"Text: {len(guild.text_channels)}\nVoice: {len(guild.voice_channels)}\nCategories: {len(guild.categories)}", inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Boost Level", value=f"Level {guild.premium_tier}", inline=True)
    embed.add_field(name="Boosts", value=guild.premium_subscription_count or 0, inline=True)
    embed.add_field(name="Verification", value=str(guild.verification_level).capitalize(), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=False) # Not ephemeral


# --- STATS COMMAND ---
@bot.tree.command(name="ticket_stats", description="Shows ticket statistics for this server.")
@app_commands.guild_only()
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
            open_tickets = len(ticket_category.text_channels) # Count text channels
        else: await interaction.followup.send(embed=create_embed("Warning", "Ticket category invalid.", discord.Color.orange()), ephemeral=True)

    embed = discord.Embed(title=f"Ticket Statistics: {interaction.guild.name}", color=discord.Color.light_grey())
    embed.add_field(name="Total Tickets Created", value=f"**{total_created}**", inline=True);
    embed.add_field(name="Currently Open Tickets", value=f"**{open_tickets}**", inline=True)
    embed.set_footer(text="Counts include all ticket types within the category.")
    await interaction.followup.send(embed=embed, ephemeral=True) # Send stats ephemerally

# --- Register Command Groups with the Bot's Command Tree ---
bot.tree.add_command(setup_group)
bot.tree.add_command(ticket_group)
bot.tree.add_command(mod_group)
bot.tree.add_command(utility_group) # Register the new utility group


# --- RUN THE BOT ---
if __name__ == "__main__": # Standard Python entry point check
    try:
        # Run the bot with the token
        # Removed custom logging setup for simplicity, discord.py has default logging
        print("[INFO] Starting bot...")
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        print("[CRITICAL ERROR] Login Failure: Improper token passed. Verify DISCORD_TOKEN.")
    except discord.errors.PrivilegedIntentsRequired:
        print("[CRITICAL ERROR] Privileged Intents Required: Ensure Presence, Server Members, and Message Content intents are enabled in the Discord Developer Portal.")
    except Exception as e:
        # Catch any other exceptions during startup
        print(f"[CRITICAL ERROR] Bot failed to start: {e}")
        traceback.print_exc()

# End of Part 5/5