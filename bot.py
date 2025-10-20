# bot.py (Part 1/4)

import discord
from discord.ext import commands
from discord import app_commands
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
        print(f"Info: {SETTINGS_FILE} not found. Creating a new one.")
        with open(SETTINGS_FILE, 'w') as f:
            json.dump({}, f)
        return {}
    try:
        # Ensure file has content before trying to load
        if os.path.getsize(SETTINGS_FILE) == 0:
            print(f"Warning: {SETTINGS_FILE} is empty. Starting with an empty dictionary.")
            return {}
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"ERROR: {SETTINGS_FILE} is corrupted. Please fix or delete it. Starting with empty settings.")
        return {}
    except Exception as e:
        print(f"ERROR loading settings: {e}")
        traceback.print_exc()
        return {}


def save_settings(settings):
    """Saves settings to settings.json"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"ERROR saving settings: {e}")
        traceback.print_exc()

# --- BOT SETUP ---

# Load token from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("CRITICAL ERROR: DISCORD_TOKEN not found in .env file or environment variables.")
    exit(1)

# Define intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

# Bot definition for Slash Commands Only
class TicketBot(commands.Bot):
    def __init__(self):
        # We don't need a command_prefix for a slash-only bot
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = load_settings()
        self.persistent_views_added = False

    async def setup_hook(self):
        # This is run once internally before the bot is ready
        if not self.persistent_views_added:
            self.add_view(TicketPanelView(bot=self))
            self.add_view(TicketCloseView(bot=self))
            self.add_view(AppealReviewView(bot=self))
            self.persistent_views_added = True
            print("Persistent views have been registered.")
        try:
            print("Attempting to sync slash commands...")
            synced = await self.tree.sync()
            print(f"Slash commands synced: {len(synced)} commands.")
        except Exception as e:
            print(f"ERROR: Failed to sync slash commands: {e}")
            traceback.print_exc()

    # Inside the TicketBot class

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print(f'discord.py version: {discord.__version__}')
        print('Bot is ready.')
        # Set status to "Playing managing tickets"
        try:
            await self.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name="managing tickets"))
            print("Presence set successfully.")
        except Exception as e:
            print(f"Error setting presence: {e}")
        print('------')

    # ADD THIS FUNCTION (ensure it's indented like on_ready)
    async def on_disconnect(self):
        print("-----------------------------------------")
        # Uses datetime imported at the top
        print(f"[{datetime.now()}] Bot disconnected from Discord.")
        print("-----------------------------------------")

    # ... (rest of your class methods like get_guild_settings follow here) ...

    def get_guild_settings(self, guild_id: int):
        """Gets settings for a specific guild, ensuring defaults and correct types."""
        guild_id_str = str(guild_id)

        if not isinstance(self.settings, dict):
            print("CRITICAL WARNING: self.settings is not a dict. Reloading...")
            self.settings = load_settings()
            if not isinstance(self.settings, dict):
                print("CRITICAL ERROR: Could not load settings as dict. Resetting settings.")
                self.settings = {}

        defaults = {
            "panel_channel": None, "ticket_category": None, "archive_category": None,
            "staff_role": None, "escalation_role": None, "appeal_channel": None,
            "ticket_counter": 1, "blacklist": {}
        }
        guild_settings = self.settings.get(guild_id_str)
        updated = False

        if not isinstance(guild_settings, dict):
             print(f"WARNING: Settings for guild {guild_id_str} are invalid. Resetting.")
             guild_settings = defaults.copy()
             self.settings[guild_id_str] = guild_settings
             updated = True

        for key, default_value in defaults.items():
            if key not in guild_settings:
                print(f"Adding missing key '{key}' for guild {guild_id_str}")
                guild_settings[key] = default_value
                updated = True
        if updated:
            save_settings(self.settings)
        return guild_settings

    def update_guild_setting(self, guild_id: int, key: str, value):
        settings = self.get_guild_settings(guild_id)
        if isinstance(settings, dict):
            settings[key] = value
            save_settings(self.settings)
        else:
            print(f"CRITICAL ERROR: Cannot update setting '{key}' for guild {guild_id}.")

bot = TicketBot()

# --- HELPER FUNCTIONS ---

def create_embed(title: str, description: str, color: discord.Color) -> discord.Embed:
    # Basic embed creation, ensures description is not None
    return discord.Embed(title=title, description=str(description) if description is not None else "", color=color)

async def send_embed_response(interaction: discord.Interaction, title: str, description: str, color: discord.Color, ephemeral: bool = True):
    # Sends embed responses specifically for interactions
    embed = create_embed(title, description, color)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except discord.NotFound:
         print(f"WARNING: Interaction not found when sending embed '{title}'. It may have expired.")
    except discord.Forbidden:
         print(f"ERROR: Bot lacks permissions to send embed response in channel {interaction.channel_id}.")
    except Exception as e:
        print(f"ERROR sending embed response: {type(e).__name__} - {e}")
        traceback.print_exc()


# --- SLASH COMMAND GLOBAL ERROR HANDLER ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Global error handler for all slash commands."""
    if isinstance(error, app_commands.errors.MissingPermissions):
        await send_embed_response(interaction, "Permission Denied", "You lack the required permissions to use this command.", discord.Color.red())
    elif isinstance(error, app_commands.errors.CheckFailure):
        # This catches errors from checks like is_staff().
        # The check function itself sends the response, so we can often just pass.
        print(f"Check failure for command '{interaction.command.name}' by {interaction.user.name} (already handled).")
        pass
    elif isinstance(error, app_commands.errors.CommandInvokeError):
        # Error raised from within the command's code
        original = error.original
        print(f"ERROR during slash command execution ({interaction.command.name}):")
        traceback.print_exception(type(original), original, original.__traceback__)
        await send_embed_response(interaction, "Command Error", "An unexpected error occurred while running this command.", discord.Color.dark_red())
    else:
        # Log any other unexpected slash command errors
        print(f"UNHANDLED SLASH COMMAND ERROR ({type(error)}) in command '{interaction.command.name}': {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        # Send a generic error message if possible
        if not interaction.response.is_done():
            await send_embed_response(interaction, "Error", "An unknown error occurred.", discord.Color.dark_red())

# --- HELPER FUNCTIONS CONTINUED ---
async def check_setup(interaction: discord.Interaction):
    """Checks if the bot is fully set up for the guild."""
    settings = bot.get_guild_settings(interaction.guild.id)
    required_settings = ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']
    missing = [s.replace("_", " ").title() for s in required_settings if not settings.get(s)]

    if missing:
        embed = discord.Embed(
            title="Bot Not Fully Configured",
            description="An administrator must run all setup commands first:", color=discord.Color.red()
        )
        embed.add_field(name="Required Settings", value="\n".join([f"- `/setup {s.lower().replace(' ', '_')}`" for s in missing]), inline=False)
        await send_embed_response(interaction, embed.title, embed.description, embed.color, ephemeral=True)
        return False
    return True

# Helper to count user's open tickets
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

# create_ticket_channel adds type to topic
async def create_ticket_channel(interaction: discord.Interaction, ticket_type_name: str, settings: dict):
    guild = interaction.guild; user = interaction.user
    staff_role_id = settings.get('staff_role'); category_id = settings.get('ticket_category')

    if not staff_role_id or not (staff_role := guild.get_role(staff_role_id)):
        await send_embed_response(interaction, "Configuration Error", "The Staff Role is not set up correctly.", discord.Color.red()); return None, None
    if not category_id or not (category := guild.get_channel(category_id)) or not isinstance(category, discord.CategoryChannel):
        await send_embed_response(interaction, "Configuration Error", "The Ticket Category is not set up correctly.", discord.Color.red()); return None, None

    # Hard limit to prevent abuse
    if count_user_tickets(guild, user.id, category.id) > 15:
        await send_embed_response(interaction, "Limit Reached", "You have too many open tickets across all types.", discord.Color.orange()); return None, None

    ticket_num = settings.get('ticket_counter', 1)
    bot.update_guild_setting(guild.id, "ticket_counter", ticket_num + 1)

    # Permissions for the new channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False, view_channel=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, view_channel=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, view_channel=True, manage_permissions=True, manage_messages=True, embed_links=True),
        staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, view_channel=True)
    }

    try:
        # Sanitize username for channel name
        safe_user_name = "".join(c for c in user.name if c.isalnum() or c in ('-', '_')).lower() or "user"
        channel_name = f"{ticket_type_name}-{ticket_num}-{safe_user_name}"[:100]
        topic = f"Ticket for {user.name} ({user.id}). Type: {ticket_type_name}. Do not modify 'ticket-user-ID'. ticket-user-{user.id} type-{ticket_type_name}"
        
        print(f"Attempting to create channel '{channel_name}' in category '{category.name}' ({category.id})")
        new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites, topic=topic)
        print(f"Channel created successfully: {new_channel.mention} ({new_channel.id})")
    except discord.Forbidden:
        print(f"ERROR: Forbidden - Bot lacks permissions to create channel in category {category.id}")
        await send_embed_response(interaction, "Permissions Error", "I lack the required permissions to create channels or set permissions in that category.", discord.Color.red()); return None, None
    except Exception as e:
        print(f"ERROR creating channel: {e}"); traceback.print_exc()
        await send_embed_response(interaction, "Error", f"An unknown error occurred while creating the channel.", discord.Color.red()); return None, None

    return new_channel, staff_role
# End of Part 1/4
# bot.py (Part 2/4)

async def generate_transcript(channel: discord.TextChannel):
    """Generates a text file transcript of the channel's messages."""
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True): # Get all messages
        # Use UTC for timestamps
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
        # Escape markdown and mentions to prevent formatting issues/pings
        clean_content = discord.utils.remove_markdown(discord.utils.escape_mentions(msg.content))
        author_display = f"{msg.author.display_name} ({msg.author.id})"
        if not msg.author.bot:
            messages.append(f"[{timestamp}] {author_display}: {clean_content}")
        # Include attachments
        if msg.attachments:
            for att in msg.attachments:
                messages.append(f"[{timestamp}] [Attachment from {author_display}: {att.url}]")

    transcript_content = "\n".join(messages)
    if not transcript_content:
        transcript_content = "No messages were sent in this ticket."

    # Encode to check size and handle potential truncation
    encoded_content = transcript_content.encode('utf-8')
    # Use a slightly smaller max size (Discord limit is 8MB, use ~7.5MB)
    max_size = 7 * 1024 * 1024 + 512 * 1024 # Approx 7.5MB

    if len(encoded_content) > max_size:
        print(f"Transcript for {channel.name} too large ({len(encoded_content)} bytes), truncating.")
        truncated_content = encoded_content[:max_size - 200] # Leave space for message
        try:
            # Decode back, ignoring errors
            transcript_content = truncated_content.decode('utf-8', errors='ignore')
            transcript_content += "\n\n--- TRANSCRIPT TRUNCATED DUE TO SIZE LIMIT ---"
            encoded_content = transcript_content.encode('utf-8') # Re-encode
        except Exception as e:
             print(f"Error during transcript truncation: {e}")
             return io.BytesIO(b"Transcript too large and could not be properly truncated.")

    return io.BytesIO(encoded_content) # Return as bytes buffer

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

        if not self.original_message.embeds: await interaction.followup.send(embed=create_embed("Error", "Could not find the original appeal message embed.", discord.Color.red())); return
        original_embed = self.original_message.embeds[0]; new_embed = original_embed.copy()

        if self.action == "Approve":
            title = "✅ Blacklist Appeal Approved"; color = discord.Color.green()
            dm_desc = f"Your blacklist appeal for **{self.guild.name}** has been approved by staff.\n\n**Reason Provided:**\n```{reason}```\nYou should now be able to create tickets again."
            # Unblacklist the user
            settings = self.bot.get_guild_settings(self.guild.id); user_id_str = str(self.appealing_user_id)
            if user_id_str in settings.get("blacklist", {}):
                del settings["blacklist"][user_id_str]; save_settings(self.bot.settings)
                print(f"User {user_id_str} unblacklisted via appeal approval by {staff_member.name}.")
        else: # Reject
            title = "❌ Blacklist Appeal Rejected"; color = discord.Color.red()
            dm_desc = f"Your blacklist appeal for **{self.guild.name}** has been rejected by staff.\n\n**Reason Provided:**\n```{reason}```"

        # Try to DM the user
        try:
            dm_embed = create_embed(title, dm_desc, color)
            await appealing_user.send(embed=dm_embed)
        except discord.Forbidden: print(f"Could not DM user {appealing_user.id} (appeal {self.action.lower()}d)")
        except Exception as e: print(f"Error sending appeal result DM to {appealing_user.id}: {e}")

        # Edit the staff message
        new_embed.title = f"[{self.action.upper()}D] Blacklist Appeal"
        new_embed.color = color
        new_embed.add_field(name=f"{self.action.capitalize()}d by {staff_member.display_name}", value=f"```{reason}```", inline=False)
        try:
            await self.original_message.edit(embed=new_embed, view=None) # Remove buttons
        except discord.NotFound: print("Original appeal message not found during edit.")
        except discord.Forbidden: print("Lacking permissions to edit original appeal message.")

        await interaction.followup.send(embed=create_embed("Action Complete", f"The appeal has been **{self.action.lower()}d**. The user has been notified (if DMs are enabled).", color), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"ERROR in AppealReasonModal: {error}"); traceback.print_exc()
        # Check if already responded before sending followup
        if not interaction.response.is_done():
            await interaction.response.send_message("An error occurred processing the reason.", ephemeral=True)
        else:
            await interaction.followup.send("An error occurred processing the reason.", ephemeral=True)

# --- Persistent View for Appeal Review Buttons in Staff Channel ---

class AppealReviewView(discord.ui.View):
    """Persistent view with Approve/Reject buttons for staff appeal channel."""
    def __init__(self, bot: TicketBot): # Added ': TicketBot' type hint
        super().__init__(timeout=None)
        self.bot = bot # Store the bot instance

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Check permissions dynamically on button press
        # Use a local variable for the bot instance for this check
        current_bot = self.bot_ref or interaction.client
        if not current_bot:
             print("CRITICAL ERROR: Could not get bot instance in AppealReviewView interaction_check.")
             await interaction.response.send_message("Internal bot error.", ephemeral=True)
             return False

        # Permission check: Only staff can use these buttons
        settings = current_bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Error", "Staff role not configured.", discord.Color.red()); return False
        staff_role = interaction.guild.get_role(staff_role_id)
        if not isinstance(interaction.user, discord.Member):
             await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return False
        is_admin = interaction.user.guild_permissions.administrator
        if (staff_role and staff_role in interaction.user.roles) or is_admin: return True
        else: await send_embed_response(interaction, "Permission Denied", "Only staff members can review appeals.", discord.Color.red()); return False

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅", custom_id="persistent_appeal:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_bot = self.bot_ref or interaction.client # Get bot instance
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Cannot find appeal information.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "Cannot identify user from appeal.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        modal = AppealReasonModal(bot_instance=current_bot, action="Approve", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id="persistent_appeal:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_bot = self.bot_ref or interaction.client # Get bot instance
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Cannot find appeal information.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "Cannot identify user from appeal.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        modal = AppealReasonModal(bot_instance=current_bot, action="Reject", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)

# --- View for Final Appeal Confirmation (DM - Non-persistent) ---
class ConfirmAppealView(discord.ui.View):
    """View shown in DM to confirm appeal submission."""
    def __init__(self, bot_instance: TicketBot, answers: dict, guild: discord.Guild, appeal_channel: discord.TextChannel, messages_to_delete: list):
        super().__init__(timeout=600); self.bot = bot_instance; self.answers = answers; self.guild = guild
        self.appeal_channel = appeal_channel; self.messages_to_delete = messages_to_delete; self.message = None # To store the view's message

    async def cleanup(self, interaction: discord.Interaction = None):
        """Stops the view and deletes all tracked messages in the DM."""
        self.stop()
        print(f"Cleaning up {len(self.messages_to_delete)} messages from appeal DM.")
        # Delete messages in reverse order to reduce potential race conditions
        for msg in reversed(self.messages_to_delete):
            try: await msg.delete()
            except (discord.NotFound, discord.Forbidden): pass
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
        embed.add_field(name="1. Reason for appeal (Why unfair?)", value=f"```{self.answers.get('q1','Not Provided')}```", inline=False)
        embed.add_field(name="2. Justification for unblacklist", value=f"```{self.answers.get('q2','Not Provided')}```", inline=False)
        embed.add_field(name="3. Supporting Proof/Statement", value=self.answers.get('proof','N/A'), inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}") # For review buttons
        # Make sure bot instance is available for the view
        view_bot = self.bot or interaction.client
        view_to_send = AppealReviewView(bot_instance=view_bot)

        try:
            await self.appeal_channel.send(embed=embed, view=view_to_send) # Send to staff channel
        except discord.Forbidden:
             print(f"ERROR: Bot lacks permission to send appeal to channel {self.appeal_channel.id}")
             await interaction.followup.send(embed=create_embed("Error", "Could not submit appeal (Bot permissions error).", discord.Color.red()), ephemeral=True)
        except Exception as e:
            print(f"ERROR submitting appeal: {e}"); traceback.print_exc()
            await interaction.followup.send(embed=create_embed("Error", "An unexpected error occurred while submitting the appeal.", discord.Color.red()), ephemeral=True)
        else: # Only send success if it worked
            await interaction.followup.send(embed=create_embed("✅ Appeal Submitted", "Your appeal has been sent to the staff. You will be contacted if a decision is made.", discord.Color.green()), ephemeral=True)

        await self.cleanup(interaction) # Clean up DM messages

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.followup.send(embed=create_embed("Appeal Cancelled", "Your appeal submission has been cancelled.", discord.Color.red()), ephemeral=True)
        await self.cleanup(interaction)

    async def on_timeout(self):
        # Disable buttons visually and clean up
        print("ConfirmAppealView timed out.")
        for item in self.children: item.disabled = True
        try:
            if self.message: # Check message exists
                 # Edit message to show timeout, keep disabled view
                 await self.message.edit(embed=create_embed("Appeal Timed Out", "You did not confirm the submission in time. The appeal has been cancelled.", discord.Color.red()), view=self)
                 # Schedule cleanup after a short delay
                 await asyncio.sleep(15)
        except (discord.NotFound, discord.Forbidden): pass
        except Exception as e: print(f"Error editing message on ConfirmAppealView timeout: {e}")
        await self.cleanup() # Clean up messages after timeout

# --- View for Starting Appeal (DM - Non-persistent) ---
class AppealStartView(discord.ui.View):
    """View sent in DM to blacklisted user to initiate the appeal process."""
    def __init__(self, bot_instance: TicketBot, guild: discord.Guild, reason: str):
        super().__init__(timeout=1800); self.bot = bot_instance; self.guild = guild; self.reason = reason; self.message = None

    async def ask_question(self, channel, user, embed, min_length=0, check_proof=False, timeout=600.0):
        # Helper to ask question, wait for response, track messages for deletion
        bot_msgs_to_delete = []
        user_msg = None
        ask_msg = None
        err_msg = None # To track the 'too short' message
        try:
            ask_msg = await channel.send(embed=embed); bot_msgs_to_delete.append(ask_msg)
            while True:
                # Wait for a message from the correct user in the correct channel
                msg = await self.bot.wait_for('message', check=lambda m: m.author == user and m.channel == channel, timeout=timeout)
                user_msg = msg # Store user message
                # Immediately add user message to list for deletion
                bot_msgs_to_delete.append(user_msg)

                # Clear previous error message if any before validation
                if err_msg:
                    try: await err_msg.delete(); bot_msgs_to_delete.remove(err_msg); err_msg = None
                    except: pass # Ignore delete errors

                # Validation
                if check_proof: return bot_msgs_to_delete, user_msg # Proof is just the message
                if len(msg.content) < min_length:
                     err_msg = await channel.send(embed=create_embed("Input Too Short", f"Your response must be at least {min_length} characters long. Please try again.", discord.Color.orange())); bot_msgs_to_delete.append(err_msg)
                     continue # Ask again
                # If valid, return collected messages and the user's answer message
                return bot_msgs_to_delete, user_msg
        except asyncio.TimeoutError:
            await channel.send(embed=create_embed("Timed Out", f"You took longer than {int(timeout/60)} minutes to respond. The appeal has been cancelled.", discord.Color.red()))
            # Don't delete messages here, let ConfirmAppealView handle final cleanup or timeout logic if reached
            return bot_msgs_to_delete, None # Signal timeout
        except Exception as e:
             print(f"Error in ask_question: {e}"); traceback.print_exc()
             await channel.send(embed=create_embed("Error", "An error occurred during the question process. Appeal cancelled.", discord.Color.red()))
             return bot_msgs_to_delete, None # Signal error


    @discord.ui.button(label="Start Appeal Process", style=discord.ButtonStyle.primary, emoji="📜")
    async def start_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable button immediately
        for item in self.children: item.disabled = True
        try:
            await interaction.response.edit_message(view=self) # Acknowledge and edit original message
        except discord.NotFound: print("AppealStartView: Original message not found."); return
        except Exception as e: print(f"Error editing original message in start_appeal: {e}")

        channel = interaction.channel; user = interaction.user
        # Track all messages (bot prompts + user answers) for final cleanup
        messages_to_delete = [interaction.message]; answers = {}

        # Ensure bot has instance
        current_bot = self.bot or interaction.client
        if not current_bot: print("CRITICAL ERROR: Bot instance lost."); await channel.send("Internal error."); return

        settings = current_bot.get_guild_settings(self.guild.id); appeal_channel_id = settings.get("appeal_channel")
        if not appeal_channel_id: await channel.send(embed=create_embed("Error", f"The appeal system for **{self.guild.name}** is not configured.", discord.Color.red())); return
        appeal_channel = self.guild.get_channel(appeal_channel_id)
        if not appeal_channel or not isinstance(appeal_channel, discord.TextChannel): await channel.send(embed=create_embed("Error", f"The appeal channel for **{self.guild.name}** is invalid.", discord.Color.red())); return

        # --- Ask Questions ---
        q1_embed = create_embed("Appeal Question 1/3", "Please explain why you believe your blacklist was incorrect or unfair.", discord.Color.blue()).set_footer(text="Response required (min. 5 characters). 10 minute time limit.")
        bot_msgs, answer1_msg = await self.ask_question(channel, user, q1_embed, 5, timeout=600.0); messages_to_delete.extend(bot_msgs)
        if not answer1_msg: await self.cleanup_on_fail(messages_to_delete); return # Timeout/Error during Q1
        answers['q1'] = answer1_msg.content

        q2_embed = create_embed("Appeal Question 2/3", "Why should your blacklist be removed? What assurances can you provide regarding future conduct?", discord.Color.blue()).set_footer(text="Response required (min. 5 characters). 10 minute time limit.")
        bot_msgs, answer2_msg = await self.ask_question(channel, user, q2_embed, 5, timeout=600.0); messages_to_delete.extend(bot_msgs)
        if not answer2_msg: await self.cleanup_on_fail(messages_to_delete); return # Timeout/Error during Q2
        answers['q2'] = answer2_msg.content

        q3_embed = create_embed("Appeal Question 3/3", "Please provide any supporting evidence (images, screenshots) or further statements. If none, type `N/A`.", discord.Color.blue()).set_footer(text="Optional. 10 minute time limit.")
        bot_msgs, answer3_msg = await self.ask_question(channel, user, q3_embed, 0, check_proof=True, timeout=600.0); messages_to_delete.extend(bot_msgs)
        if not answer3_msg: await self.cleanup_on_fail(messages_to_delete); return # Timeout/Error during Q3
        # Process proof message (text and attachments)
        proof_content = answer3_msg.content if answer3_msg.content else "N/A"
        if answer3_msg.attachments:
             proof_urls = "\n".join([att.url for att in answer3_msg.attachments])
             proof_content = f"{proof_content}\n{proof_urls}" if proof_content != "N/A" else proof_urls
        answers['proof'] = proof_content

        # --- Confirmation Step ---
        summary_embed = create_embed("Confirm Your Appeal Submission", "Please review your answers. Press 'Submit Appeal' to send this to the staff or 'Cancel'.", discord.Color.green())
        summary_embed.add_field(name="1. Why unfair?", value=f"```{answers['q1']}```", inline=False)
        summary_embed.add_field(name="2. Why unblacklist?", value=f"```{answers['q2']}```", inline=False)
        summary_embed.add_field(name="3. Proof/Statement", value=answers['proof'], inline=False)
        # Pass ALL messages collected so far to ConfirmAppealView for eventual deletion
        confirm_view = ConfirmAppealView(current_bot, answers, self.guild, appeal_channel, messages_to_delete)
        confirm_view.message = await channel.send(embed=summary_embed, view=confirm_view)
        # Confirm view now handles deletion of its own message and all previous messages

    async def cleanup_on_fail(self, messages: list):
        # Helper to clean up messages if a step fails before confirm view
        print("Cleaning up messages after appeal step failure (timeout/error).")
        for msg in reversed(messages): # Delete in reverse
            try: await msg.delete()
            except (discord.NotFound, discord.Forbidden): pass

    async def on_timeout(self):
        # Disables button if user doesn't click "Start Appeal"
        print("AppealStartView timed out (user did not click start).")
        for item in self.children: item.disabled = True
        try:
             if self.message: # Check message exists
                await self.message.edit(embed=create_embed(f"Blacklisted on {self.guild.name}", f"Reason:\n```{self.reason}```\nThe window to start an appeal has expired.", discord.Color.red()), view=self) # Update embed too
        except (discord.NotFound, discord.Forbidden): pass
        except Exception as e: print(f"Failed edit appeal start on timeout: {e}")

# --- TICKET PANEL VIEW ---
class TicketPanelView(discord.ui.View):
    # This is the main persistent view with the ticket creation buttons
    def __init__(self, bot: TicketBot): # Added ': TicketBot' type hint
        super().__init__(timeout=None)
        self.bot = bot # Store the bot instance

    async def send_appeal_dm(self, user: discord.Member, guild: discord.Guild, reason: str):
        # Sends the initial DM to blacklisted users
        embed = create_embed(f"Blacklisted on {guild.name}", f"You are currently blacklisted from creating tickets.\n**Reason:**\n```{reason}```\nIf you believe this is a mistake, you may submit an appeal below.", discord.Color.red())
        # Make sure bot instance is passed
        current_bot = self.bot or user.guild.me # Try getting bot from interaction user's guild if self.bot is None
        if not current_bot: print("ERROR: Cannot get bot instance for AppealStartView."); return

        view = AppealStartView(bot_instance=current_bot, guild=guild, reason=reason)
        try:
            dm_channel = await user.create_dm()
            view.message = await dm_channel.send(embed=embed, view=view) # Store message for timeout handling
        except discord.Forbidden: print(f"Cannot send appeal DM to {user.id} (DMs disabled).")
        except Exception as e: print(f"Failed to send appeal DM to {user.id}: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Runs before any button callback in this view
        current_bot = self.bot or interaction.client # Ensure bot instance
        if not current_bot:
             print("CRITICAL ERROR: Could not get bot instance in TicketPanelView interaction_check.")
             # Try to respond if possible
             try:
                 if not interaction.response.is_done():
                     await interaction.response.send_message("Internal bot error. Cannot process request.", ephemeral=True)
                 else:
                     await interaction.followup.send("Internal bot error. Cannot process request.", ephemeral=True)
             except Exception: pass # Ignore if response fails
             return False
        self.bot = current_bot # Update self.bot if it was missing

        if not interaction.guild: return False # Should not happen

        settings = self.bot.get_guild_settings(interaction.guild.id)
        blacklist = settings.get("blacklist", {}); user_id_str = str(interaction.user.id)

        # --- BLACKLIST CHECK ---
        if user_id_str in blacklist:
            reason = blacklist.get(user_id_str, "No reason provided.")
            # Use send_embed_response which handles interaction state
            await send_embed_response(interaction, "Blacklisted", "You are currently blacklisted and cannot create new tickets.", discord.Color.red(), ephemeral=True)
            await self.send_appeal_dm(interaction.user, interaction.guild, reason)
            return False # Stop button callback

        # --- SETUP CHECK ---
        required_settings = ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']
        if not all(settings.get(key) for key in required_settings):
            # Use send_embed_response which handles interaction state
            await send_embed_response(interaction, "System Offline", "The ticket system is not fully configured by an administrator.", discord.Color.red(), ephemeral=True)
            return False # Stop button callback

        return True # Allow button callback to proceed

    # --- TICKET CREATION BUTTONS ---
    @discord.ui.button(label="Standard Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="persistent_panel:standard")
    async def standard_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the creation of a standard support ticket."""
        current_bot = self.bot or interaction.client # Ensure bot instance
        if not current_bot: await interaction.response.send_message("Internal error.", ephemeral=True); return
        self.bot = current_bot

        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "ticket"; LIMIT = 3; category_id = settings.get('ticket_category')
        if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket category not configured.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT: await send_embed_response(interaction, "Limit Reached", f"You may only have {LIMIT} open standard tickets.", discord.Color.orange()); return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role:
            await interaction.followup.send(embed=create_embed("Ticket Created", f"Your ticket is ready: {channel.mention}", discord.Color.green()), ephemeral=True)
            embed = discord.Embed(title="🎫 Standard Support Ticket", description=f"Welcome, {interaction.user.mention}!\nDescribe issue. {staff_role.mention} will assist.", color=discord.Color.blue())
            # *** REMOVED view=... from here ***
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}")

    @discord.ui.button(label="Tryout Application", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="persistent_panel:tryout")
    async def tryout_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the creation and application process for a tryout ticket."""
        current_bot = self.bot or interaction.client
        if not current_bot: await interaction.response.send_message("Internal error.", ephemeral=True); return
        self.bot = current_bot

        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "tryout"; LIMIT = 1; category_id = settings.get('ticket_category')
        if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket category not configured.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT: await send_embed_response(interaction, "Limit Reached", f"Max {LIMIT} open tryout application.", discord.Color.orange()); return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if not channel or not staff_role: return

        await interaction.followup.send(embed=create_embed("Ticket Created", f"Tryout channel ready: {channel.mention}", discord.Color.green()), ephemeral=True)
        try: await channel.send(f"{interaction.user.mention} {staff_role.mention}", delete_after=1)
        except Exception as e: print(f"Warning: Could not send ping in {channel.id}: {e}")

        # --- Tryout Application Logic ---
        try:
            username_embed = create_embed("⚔️ Tryout Application - Step 1/2", "Reply with Roblox Username.", discord.Color.green()).set_footer(text="5 minute limit.")
            bot_msg_1 = await channel.send(embed=username_embed)
            def check_username(m): return m.channel == channel and m.author == interaction.user and not m.author.bot
            username_msg = await self.bot.wait_for('message', check=check_username, timeout=300.0)
            roblox_username = username_msg.content.strip()

            stats_embed = create_embed("⚔️ Tryout Application - Step 2/2", f"`{roblox_username}`\nSend stats screenshot.", discord.Color.green()).set_footer(text="5 minute limit. Must be image.")
            bot_msg_2 = await channel.send(embed=stats_embed)
            def check_stats(m): return m.channel == channel and m.author == interaction.user and not m.author.bot and m.attachments and m.attachments[0].content_type and m.attachments[0].content_type.startswith('image')
            stats_msg = await self.bot.wait_for('message', check=check_stats, timeout=300.0)
            stats_screenshot_url = stats_msg.attachments[0].url if stats_msg.attachments else None

            success_embed = create_embed("✅ Tryout Application Submitted", f"{interaction.user.mention}, {staff_role.mention} will review.", discord.Color.brand_green())
            success_embed.add_field(name="Roblox Username", value=roblox_username, inline=False)
            if stats_screenshot_url:
                try: success_embed.set_image(url=stats_screenshot_url)
                except Exception as e: print(f"Error setting image: {e}"); success_embed.add_field(name="Image Error", value="Could not embed.", inline=False)
            else: success_embed.add_field(name="Stats Screenshot", value="Not provided.", inline=False)

            # *** REMOVED view=... from here ***
            await channel.send(embed=success_embed)

        except asyncio.TimeoutError:
            timeout_embed = create_embed("Ticket Closed Automatically", "Inactivity during application.", discord.Color.red())
            try: await channel.send(embed=timeout_embed); await asyncio.sleep(10); await channel.delete(reason="Tryout timeout")
            except (discord.NotFound, discord.Forbidden): pass
            except Exception as e: print(f"Error during timeout cleanup: {e}")
        except Exception as e:
            print(f"ERROR during tryout process in {getattr(channel, 'id', 'N/A')}: {e}"); traceback.print_exc()
            try: await channel.send(embed=create_embed("Application Error", "Unexpected error. Close ticket & try again, or create standard ticket.", discord.Color.red()))
            except Exception: pass

    @discord.ui.button(label="Report a User", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="persistent_panel:report")
    async def report_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the creation of a user report ticket."""
        current_bot = self.bot or interaction.client
        if not current_bot: await interaction.response.send_message("Internal error.", ephemeral=True); return
        self.bot = current_bot

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
            # *** REMOVED view=... from here ***
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}")

# End of Part 2/4
# bot.py (Part 3/4)

    # --- TICKET CREATION BUTTONS ---
    @discord.ui.button(label="Standard Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="persistent_panel:standard")
    async def standard_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the creation of a standard support ticket."""
        # Ensure bot instance is available
        current_bot = self.bot or interaction.client
        if not current_bot: print("ERROR: Bot instance missing in standard_ticket."); await interaction.response.send_message("Internal error.", ephemeral=True); return
        self.bot = current_bot # Update self.bot if needed

        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "ticket"; LIMIT = 3; category_id = settings.get('ticket_category')
        if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket category not configured.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"You may only have {LIMIT} open standard tickets at a time.", discord.Color.orange()); return

        # Defer BEFORE channel creation
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role:
            # Send ephemeral confirmation via followup
            await interaction.followup.send(embed=create_embed("Ticket Created", f"Your ticket is ready: {channel.mention}", discord.Color.green()), ephemeral=True)
            # Send welcome message in the new channel
            embed = discord.Embed(title="🎫 Standard Support Ticket", description=f"Welcome, {interaction.user.mention}!\n\nPlease describe your question or issue in detail. A member of the {staff_role.mention} team will assist you shortly.", color=discord.Color.blue())
            # Pass bot instance to the view in the channel
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=self.bot))
        # No else needed, create_ticket_channel sends error response on failure

    @discord.ui.button(label="Tryout Application", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="persistent_panel:tryout")
    async def tryout_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the creation and application process for a tryout ticket."""
        current_bot = self.bot or interaction.client
        if not current_bot: print("ERROR: Bot instance missing in tryout_ticket."); await interaction.response.send_message("Internal error.", ephemeral=True); return
        self.bot = current_bot

        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "tryout"; LIMIT = 1; category_id = settings.get('ticket_category')
        if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket category not configured.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"You may only have {LIMIT} open tryout application at a time.", discord.Color.orange()); return

        await interaction.response.defer(ephemeral=True, thinking=True) # Defer BEFORE channel creation
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if not channel or not staff_role: return # Exit if channel/role creation failed

        await interaction.followup.send(embed=create_embed("Ticket Created", f"Your tryout application channel is ready: {channel.mention}", discord.Color.green()), ephemeral=True)
        try:
            # Send a quick ping, delete immediately
            await channel.send(f"{interaction.user.mention} {staff_role.mention}", delete_after=1)
        except Exception as e: print(f"Warning: Could not send initial ping in {channel.id}: {e}")

        # --- Tryout Application Logic (No Message Deletion) ---
        bot_msg_1 = None; username_msg = None; bot_msg_2 = None; stats_msg = None
        try:
            username_embed = create_embed("⚔️ Tryout Application - Step 1/2", "Please reply to this message with your exact **Roblox Username**.", discord.Color.green()).set_footer(text="You have 5 minutes to respond.")
            bot_msg_1 = await channel.send(embed=username_embed)
            def check_username(m): return m.channel == channel and m.author == interaction.user and not m.author.bot
            username_msg = await self.bot.wait_for('message', check=check_username, timeout=300.0) # 5 minutes
            roblox_username = username_msg.content.strip() # Remove leading/trailing whitespace

            stats_embed = create_embed("⚔️ Tryout Application - Step 2/2", f"Thank you, `{roblox_username}`.\n\nNow, please send a **single message containing a clear screenshot of your stats** from the Roblox game.", discord.Color.green()).set_footer(text="You have 5 minutes to respond. The message MUST contain an image attachment.")
            bot_msg_2 = await channel.send(embed=stats_embed)
            def check_stats(m): return m.channel == channel and m.author == interaction.user and not m.author.bot and m.attachments and m.attachments[0].content_type and m.attachments[0].content_type.startswith('image')
            stats_msg = await self.bot.wait_for('message', check=check_stats, timeout=300.0) # 5 minutes
            stats_screenshot_url = stats_msg.attachments[0].url if stats_msg.attachments else None

            # --- Final Summary Embed ---
            success_embed = create_embed("✅ Tryout Application Submitted", f"Thank you, {interaction.user.mention}! Your application details are below. A member of the {staff_role.mention} team will review it soon.", discord.Color.brand_green())
            success_embed.add_field(name="Roblox Username", value=roblox_username, inline=False)
            if stats_screenshot_url:
                try:
                    success_embed.set_image(url=stats_screenshot_url)
                except Exception as e:
                    print(f"Error setting image URL during tryout ({stats_screenshot_url}): {e}")
                    success_embed.add_field(name="Stats Image Error", value="There was an issue embedding the provided image.", inline=False)
            else:
                success_embed.add_field(name="Stats Screenshot", value="Not provided or attachment error.", inline=False)

            # Send summary and add close/delete buttons
            await channel.send(embed=success_embed, view=TicketCloseView(bot=self.bot))

        except asyncio.TimeoutError:
            timeout_embed = create_embed("Ticket Closed Automatically", "This tryout ticket has been closed due to inactivity during the application process.", discord.Color.red())
            try:
                # Check if channel still exists before sending/deleting
                await channel.send(embed=timeout_embed)
                await asyncio.sleep(10) # Give user time to see message
                await channel.delete(reason="Tryout application timeout")
            except discord.NotFound: pass # Channel already gone
            except discord.Forbidden: print(f"ERROR: Lacking permissions to delete channel {channel.id} after tryout timeout.")
            except Exception as e: print(f"Error during tryout timeout cleanup for {channel.id}: {e}")
        except Exception as e:
            print(f"ERROR during tryout process in channel {getattr(channel, 'id', 'N/A')}: {e}")
            traceback.print_exc()
            try:
                 # Check if channel exists before sending error message
                 if channel:
                     await channel.send(embed=create_embed("Application Error", "An unexpected error occurred during the application process. Please close this ticket and try again, or create a standard ticket for help.", discord.Color.red()))
            except Exception as send_error:
                 print(f"Error sending error message to tryout channel: {send_error}")

    @discord.ui.button(label="Report a User", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="persistent_panel:report")
    async def report_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles the creation of a user report ticket."""
        current_bot = self.bot or interaction.client
        if not current_bot: print("ERROR: Bot instance missing in report_ticket."); await interaction.response.send_message("Internal error.", ephemeral=True); return
        self.bot = current_bot

        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "report"; LIMIT = 10; category_id = settings.get('ticket_category')
        if not category_id: await send_embed_response(interaction, "Setup Error", "Ticket category not configured.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"You may only have {LIMIT} open report tickets at a time.", discord.Color.orange()); return

        await interaction.response.defer(ephemeral=True, thinking=True) # Defer BEFORE channel creation
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role:
            await interaction.followup.send(embed=create_embed("Ticket Created", f"Your report channel is ready: {channel.mention}", discord.Color.green()), ephemeral=True)
            embed = discord.Embed(title="🚨 User Report",
                                  description=f"Welcome, {interaction.user.mention}!\n\nPlease provide the following information:\n1. **Username** of the user you are reporting.\n2. **Reason** for the report.\n3. **Detailed description** of the incident.\n4. Any **proof** (screenshots, video links, message links).\n\nA member of the {staff_role.mention} team will review your report.",
                                  color=discord.Color.red())
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=self.bot))


# --- MODAL FOR TICKET CLOSE REASON ---
class CloseReasonModal(discord.ui.Modal, title="Close Ticket Reason"):
    """Modal popup for staff/creator to enter reason for closing ticket."""
    reason_input = discord.ui.TextInput(
        label="Reason for Closing", style=discord.TextStyle.paragraph,
        placeholder="Please provide a brief reason for closing this ticket...", required=True, min_length=5, max_length=1000
    )

    def __init__(self, bot_instance: TicketBot, target_channel: discord.TextChannel, closer: discord.Member):
        super().__init__()
        self.bot = bot_instance
        self.target_channel = target_channel
        self.closer = closer

    async def on_submit(self, interaction: discord.Interaction):
        # Defer ephemerally as logic can take time
        await interaction.response.defer(ephemeral=True, thinking=True)
        reason = self.reason_input.value
        # Instantiate the view containing the close logic
        view_instance = TicketCloseView(bot=self.bot)
        try:
            # Call the actual closing logic
            await view_instance.close_ticket_logic(self.target_channel, self.closer, reason)
            await interaction.followup.send("✅ Ticket closing process initiated.", ephemeral=True)
        except Exception as e:
            print(f"Error calling close_ticket_logic from modal: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Failed to initiate ticket closing due to an internal error.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"ERROR in CloseReasonModal: {error}"); traceback.print_exc()
        # Attempt to respond ephemerally
        try:
            if not interaction.response.is_done():
                 await interaction.response.send_message("An error occurred submitting the reason.", ephemeral=True)
            else:
                 await interaction.followup.send("An error occurred submitting the reason.", ephemeral=True)
        except Exception as e:
             print(f"Error sending on_error message in CloseReasonModal: {e}")

# --- PERSISTENT TICKET CLOSE VIEW ---
class TicketCloseView(discord.ui.View):
    """View with 'Close' and 'Delete' buttons inside a ticket channel."""
    def __init__(self, bot: TicketBot): # Added ': TicketBot' type hint
        super().__init__(timeout=None)
        self.bot = bot # Store the bot instance

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="persistent_ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Opens modal to ask for close reason after permission check."""
        current_bot = self.bot_ref or interaction.client # Get bot instance
        if not current_bot: print("CRITICAL ERROR: Bot instance missing in close_ticket."); await interaction.response.send_message("Internal error.", ephemeral=True); return
        self.bot_ref = current_bot # Update ref if needed

        settings = current_bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None

        # Ensure interaction.user is a Member for role/perm checks
        if not isinstance(interaction.user, discord.Member):
             await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return

        is_admin = interaction.user.guild_permissions.administrator
        is_staff = (staff_role and staff_role in interaction.user.roles)
        can_close = False

        # Allow original ticket creator OR staff/admin to close
        channel_topic = getattr(interaction.channel, 'topic', '') or ""
        # Check if user ID matches the one in the topic
        if f"ticket-user-{interaction.user.id}" in channel_topic:
            can_close = True # Original creator
        elif is_staff or is_admin:
            can_close = True # Staff/Admin

        if not can_close:
            await send_embed_response(interaction, "Permission Denied", "Only the ticket creator or a staff member can close this ticket.", discord.Color.red(), ephemeral=True)
            return

        # Open the modal to get the reason
        modal = CloseReasonModal(bot_instance=current_bot, target_channel=interaction.channel, closer=interaction.user)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Delete Ticket", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="persistent_ticket:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Permanently deletes ticket, staff/admin only."""
        current_bot = self.bot_ref or interaction.client
        if not current_bot: print("CRITICAL ERROR: Bot instance missing."); await interaction.response.send_message("Internal error.", ephemeral=True); return
        self.bot_ref = current_bot

        settings = current_bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Setup Error", "Staff role not configured.", discord.Color.red()); return
        staff_role = interaction.guild.get_role(staff_role_id)
        if not staff_role: await send_embed_response(interaction, "Setup Error", "Staff role configured but not found.", discord.Color.red()); return

        if not isinstance(interaction.user, discord.Member): await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return
        is_admin = interaction.user.guild_permissions.administrator
        is_staff = staff_role in interaction.user.roles

        if not is_staff and not is_admin:
            await send_embed_response(interaction, "Permission Denied", "Only staff members or administrators can permanently delete tickets.", discord.Color.red(), ephemeral=True); return

        # Respond ephemerally first to confirm the action will start
        await interaction.response.defer(ephemeral=True, thinking=True)
        embed = create_embed("🗑️ Confirm Ticket Deletion", f"This ticket will be **permanently deleted** by {interaction.user.mention} in 10 seconds.", discord.Color.dark_red())
        # Send non-ephemeral warning message
        warning_message = await interaction.channel.send(embed=embed) # Send to channel directly

        # Send ephemeral confirmation to the user who clicked
        await interaction.followup.send("Deletion initiated.", ephemeral=True)

        await asyncio.sleep(10) # 10 second countdown
        try:
            print(f"Attempting to delete channel {interaction.channel.id} (Ticket Delete)")
            await interaction.channel.delete(reason=f"Ticket permanently deleted by {interaction.user.name} ({interaction.user.id})")
            # Don't try to delete warning message, channel is gone
        except discord.NotFound: pass # Channel already gone
        except discord.Forbidden:
             print(f"ERROR: Lacking delete permissions for channel {interaction.channel.id}")
             # Cannot send followup here as channel might be gone, log is sufficient
        except Exception as e:
            print(f"ERROR deleting ticket channel {interaction.channel.id}: {e}")
            traceback.print_exc()
            # Cannot send followup here

    # --- Close Ticket Logic (Handles Archiving) ---
    async def close_ticket_logic(self, channel: discord.TextChannel, user: discord.Member, reason: str = "No reason provided"):
        """Handles transcript generation, message sending, and channel archival."""
        guild = channel.guild
        if not guild: print(f"ERROR: Cannot close ticket, no guild context for channel {channel.id}."); return

        # Ensure bot instance is available
        current_bot = self.bot_ref or channel.guild.me.bot # Try getting bot instance
        if not current_bot: print("CRITICAL ERROR: Bot instance missing in close_ticket_logic."); await channel.send("Internal error closing ticket."); return
        self.bot_ref = current_bot

        settings = current_bot.get_guild_settings(guild.id)
        archive_category_id = settings.get('archive_category')
        if not archive_category_id: await channel.send(embed=create_embed("Configuration Error", "Archive category not set.", discord.Color.red())); return
        archive_category = guild.get_channel(archive_category_id)
        if not archive_category or not isinstance(archive_category, discord.CategoryChannel): await channel.send(embed=create_embed("Configuration Error", "Archive category is invalid or not found.", discord.Color.red())); return

        # Send "Closing..." message immediately
        closing_msg = None
        try: closing_msg = await channel.send(embed=create_embed("Archiving Ticket...", f"Ticket is being closed by {user.mention} and archived. Generating transcript...", discord.Color.light_grey()))
        except discord.Forbidden: print(f"Cannot send 'Archiving' message in {channel.id}"); # Proceed anyway
        except Exception as e: print(f"Error sending 'Archiving' message: {e}")

        # Generate Transcript
        transcript_file = await generate_transcript(channel)

        # Prepare closing embed with reason
        embed = discord.Embed(title="Ticket Closed", description=f"Closed by: {user.mention}\n**Reason:**\n```{reason}```", color=discord.Color.orange())
        transcript_file.seek(0)
        transcript_message = None # To potentially remove view later
        try:
            transcript_message = await channel.send(embed=embed, file=discord.File(transcript_file, filename=f"{channel.name}-transcript.txt"))
        except discord.HTTPException as e:
            if e.code == 40005: await channel.send(embed=create_embed("Transcript Too Large", "Transcript exceeds Discord's file size limit. Archiving without transcript upload.", discord.Color.orange()))
            else: await channel.send(embed=create_embed("Error", f"Could not upload transcript (HTTP {e.code}): {e.text}", discord.Color.red()))
            try: await channel.send(embed=embed) # Still send close embed
            except Exception: pass
        except discord.Forbidden: await channel.send(embed=create_embed("Error", "Lacking permissions to send transcript file/embed.", discord.Color.red()))
        except Exception as e: print(f"ERROR sending transcript for {channel.id}: {e}"); traceback.print_exc(); await channel.send(embed=create_embed("Error", f"Transcript send error.", discord.Color.red()))

        # Clean up "Closing..." message if it was sent
        if closing_msg:
             try: await closing_msg.delete()
             except: pass

        await asyncio.sleep(3) # Short delay

        # Prepare overwrites for archived channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, view_channel=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, view_channel=True, send_messages=True) # Ensure bot can send final message
        }
        staff_role_id = settings.get('staff_role')
        if staff_role_id and (staff_role := guild.get_role(staff_role_id)):
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False, view_channel=True) # Staff read-only

        # Try to move and edit permissions
        try:
            base_name = channel.name.replace("closed-","")[:75] # Remove previous prefix, limit length
            closed_name = f"closed-{base_name}-{channel.id}"[:100] # Ensure unique name
            await channel.edit(
                name=closed_name, category=archive_category, overwrites=overwrites,
                reason=f"Ticket closed by {user.name}. Reason: {reason}"
            )

            # Attempt to remove view from the transcript message
            if transcript_message:
                 try: await transcript_message.edit(view=None)
                 except (discord.NotFound, discord.Forbidden): pass
                 except Exception as edit_err: print(f"Failed to remove view from transcript msg: {edit_err}")

            # Send final confirmation *after* move and edit
            await channel.send(embed=create_embed("Ticket Archived", f"This ticket has been moved to the {archive_category.name} category and is now read-only for staff.", discord.Color.greyple()))

        except discord.Forbidden: print(f"ERROR: Bot lacks permissions to move/edit channel {channel.id} to archive."); await channel.send(embed=create_embed("Error", "Lacking permissions to archive.", discord.Color.red()))
        except discord.NotFound: print(f"WARNING: Channel {channel.id} not found during archival.")
        except Exception as e: print(f"ERROR during archival of {channel.id}: {e}"); traceback.print_exc(); await channel.send(embed=create_embed("Error", f"Archival error.", discord.Color.red()))

# End of Part 3/4
# bot.py (Part 4/4)

# --- SLASH COMMAND GROUPS ---
# Group setup commands under /setup
setup_group = app_commands.Group(name="setup", description="Admin commands to configure the ticket bot.", guild_only=True, default_permissions=discord.Permissions(administrator=True))
# Group ticket management commands under /ticket
ticket_group = app_commands.Group(name="ticket", description="Staff commands to manage tickets.", guild_only=True) # Permissions checked within commands
# Group moderation commands under /mod
mod_group = app_commands.Group(name="mod", description="Moderation related commands.", guild_only=True)


# --- SETUP COMMANDS (Now under /setup group) ---

@setup_group.command(name="panel_channel", description="Sets the channel where the ticket creation panel is posted.")
@app_commands.describe(channel="The text channel for the panel.")
@app_commands.checks.has_permissions(administrator=True)
async def set_panel_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Sets the channel for the ticket creation panel."""
    bot.update_guild_setting(interaction.guild.id, "panel_channel", channel.id)
    await send_embed_response(interaction, "Setup Complete", f"Ticket panel channel has been set to {channel.mention}", discord.Color.green())

@setup_group.command(name="ticket_category", description="Sets the category where new tickets will be created.")
@app_commands.describe(category="The category channel for new tickets.")
@app_commands.checks.has_permissions(administrator=True)
async def set_ticket_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    """Sets the category for new tickets."""
    bot.update_guild_setting(interaction.guild.id, "ticket_category", category.id)
    await send_embed_response(interaction, "Setup Complete", f"New tickets will be created in the `{category.name}` category.", discord.Color.green())

@setup_group.command(name="archive_category", description="Sets the category where closed tickets will be moved.")
@app_commands.describe(category="The category channel for archived tickets.")
@app_commands.checks.has_permissions(administrator=True)
async def set_archive_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    """Sets the category for archived tickets."""
    bot.update_guild_setting(interaction.guild.id, "archive_category", category.id)
    await send_embed_response(interaction, "Setup Complete", f"Closed tickets will be moved to the `{category.name}` category.", discord.Color.green())

@setup_group.command(name="staff_role", description="Sets the primary staff role for ticket access and pings.")
@app_commands.describe(role="The role designated as staff.")
@app_commands.checks.has_permissions(administrator=True)
async def set_staff_role(interaction: discord.Interaction, role: discord.Role):
    """Sets the main staff role."""
    bot.update_guild_setting(interaction.guild.id, "staff_role", role.id)
    await send_embed_response(interaction, "Setup Complete", f"Staff role has been set to {role.mention}", discord.Color.green())

@setup_group.command(name="escalation_role", description="Sets the senior staff role pinged by /ticket escalate.")
@app_commands.describe(role="The role to ping for ticket escalations.")
@app_commands.checks.has_permissions(administrator=True)
async def set_escalation_role(interaction: discord.Interaction, role: discord.Role):
    """Sets the escalation role."""
    bot.update_guild_setting(interaction.guild.id, "escalation_role", role.id)
    await send_embed_response(interaction, "Setup Complete", f"Escalation role has been set to {role.mention}", discord.Color.green())

@setup_group.command(name="appeal_channel", description="Sets the channel where blacklist appeals are sent.")
@app_commands.describe(channel="The channel for staff to review appeals.")
@app_commands.checks.has_permissions(administrator=True)
async def set_appeal_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Sets the blacklist appeal channel."""
    bot.update_guild_setting(interaction.guild.id, "appeal_channel", channel.id)
    await send_embed_response(interaction, "Setup Complete", f"Blacklist appeals will be sent to {channel.mention}", discord.Color.green())

# --- PANEL CREATION COMMAND (Now under /setup group) ---
@setup_group.command(name="create_panel", description="Sends the ticket creation panel to the configured channel.")
@app_commands.checks.has_permissions(administrator=True)
async def create_panel(interaction: discord.Interaction):
    """Sends the ticket creation panel."""
    if not await check_setup(interaction): return # Verify setup first

    settings = bot.get_guild_settings(interaction.guild.id)
    panel_channel_id = settings.get('panel_channel')
    panel_channel = bot.get_channel(panel_channel_id) if panel_channel_id else None

    if not panel_channel:
        await send_embed_response(interaction, "Configuration Error", "The panel channel is not set or cannot be found.", discord.Color.red())
        return

    # Check bot permissions in panel channel
    bot_member = interaction.guild.me
    perms = panel_channel.permissions_for(bot_member)
    if not perms.send_messages or not perms.embed_links:
         await send_embed_response(interaction, "Permissions Error", f"I lack Send Messages or Embed Links permission in {panel_channel.mention}.", discord.Color.red()); return

    embed = discord.Embed(title="Support & Tryouts", description="Select an option below to create a ticket.", color=0x2b2d31)
    if interaction.guild.icon: embed.set_thumbnail(url=interaction.guild.icon.url)
    embed.add_field(name="🎫 Standard Ticket", value="For general help, questions, or issues.", inline=False)
    embed.add_field(name="⚔️ Tryout Application", value="Apply to join the clan.", inline=False)
    embed.add_field(name="🚨 Report a User", value="Report rule-breaking members (requires evidence).", inline=False)
    embed.set_footer(text=f"{interaction.guild.name} Support System")

    try:
        # Pass bot instance to the persistent view
        await panel_channel.send(embed=embed, view=TicketPanelView(bot=bot))
        await send_embed_response(interaction, "Panel Created", f"The ticket panel has been sent to {panel_channel.mention}", discord.Color.green())
    except discord.Forbidden: await send_embed_response(interaction, "Error", f"Failed to send panel to {panel_channel.mention} (Permission error).", discord.Color.red())
    except Exception as e:
        print(f"Error sending panel: {e}"); traceback.print_exc()
        await send_embed_response(interaction, "Error", f"An unexpected error occurred while sending the panel.", discord.Color.red())

# --- TICKET MANAGEMENT COMMANDS (Now under /ticket group) ---

# --- Staff Check Decorator for App Commands ---
def is_staff_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        # Re-use the async check function defined earlier
        if await is_staff_interaction(interaction):
            return True
        # is_staff_interaction already sends the "denied" message
        return False
    return app_commands.check(predicate)

# --- Ticket Channel Check Decorator for App Commands ---
def in_ticket_channel_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        settings = bot.get_guild_settings(interaction.guild.id)
        # Check if channel exists and its category matches
        if interaction.channel and interaction.channel.category_id == settings.get('ticket_category'):
            return True
        await send_embed_response(interaction, "Invalid Channel", "This command can only be used within an open ticket channel.", discord.Color.red()); return False
    return app_commands.check(predicate)


@ticket_group.command(name="add", description="Adds a user to the current ticket.")
@app_commands.describe(user="The user to add to the ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_add(interaction: discord.Interaction, user: discord.Member):
    """Adds a user to the current ticket channel."""
    try:
        await interaction.channel.set_permissions(user, read_messages=True, send_messages=True, view_channel=True)
        await send_embed_response(interaction, "User Added", f"{user.mention} has been added to this ticket by {interaction.user.mention}.", discord.Color.green(), ephemeral=False) # Non-ephemeral confirmation
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "I lack permission to modify channel permissions.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed to add user: {e}", discord.Color.red())

@ticket_group.command(name="remove", description="Removes a user from the current ticket.")
@app_commands.describe(user="The user to remove from the ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_remove(interaction: discord.Interaction, user: discord.Member):
    """Removes a user from the current ticket channel."""
    # Prevent removing the ticket creator easily? Maybe add a check later.
    try:
        await interaction.channel.set_permissions(user, overwrite=None) # Reset permissions
        await send_embed_response(interaction, "User Removed", f"{user.mention} has been removed from this ticket by {interaction.user.mention}.", discord.Color.orange(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "I lack permission to modify channel permissions.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed to remove user: {e}", discord.Color.red())

@ticket_group.command(name="rename", description="Renames the current ticket channel.")
@app_commands.describe(new_name="The new name for the ticket channel.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_rename(interaction: discord.Interaction, new_name: str):
    """Renames the current ticket channel."""
    try:
        # Sanitize name
        clean_name = "".join(c for c in new_name if c.isalnum() or c in ('-','_')).lower()[:100] or f"ticket-{interaction.channel.id}"
        await interaction.channel.edit(name=clean_name)
        await send_embed_response(interaction, "Ticket Renamed", f"Channel name changed to `{clean_name}`.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "I lack permission to rename this channel.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed to rename ticket: {e}", discord.Color.red())

@ticket_group.command(name="escalate", description="Pings the escalation role in the current ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_escalate(interaction: discord.Interaction):
    """Pings the escalation role in the ticket."""
    settings = bot.get_guild_settings(interaction.guild.id); esc_role_id = settings.get("escalation_role")
    if not esc_role_id or not (esc_role := interaction.guild.get_role(esc_role_id)):
        await send_embed_response(interaction, "Configuration Error", "Escalation role is not set up correctly.", discord.Color.red()); return

    embed = create_embed("Ticket Escalated", f"🚨 This ticket requires senior attention! Escalated by {interaction.user.mention}. {esc_role.mention}, please assist.", discord.Color.red())
    try:
        # Defer before sending non-ephemeral message
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(content=esc_role.mention, embed=embed) # Ping the role
        await interaction.followup.send("Escalation ping sent.", ephemeral=True)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "I cannot send messages or ping roles in this channel.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed to escalate ticket: {e}", discord.Color.red())

@ticket_group.command(name="claim", description="Claims the current ticket to indicate you are handling it.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_claim(interaction: discord.Interaction):
    """Claims the current ticket."""
    current_topic = interaction.channel.topic or ""
    if "claimed-by-" in current_topic:
        claimer_id_str = current_topic.split("claimed-by-")[-1].split(" ")[0]
        try: claimer_id = int(claimer_id_str); claimer = interaction.guild.get_member(claimer_id) or f"User ID: {claimer_id}"
        except ValueError: claimer = "Unknown User"
        await send_embed_response(interaction, "Already Claimed", f"This ticket is already claimed by {claimer}.", discord.Color.orange()); return

    base_topic_parts = current_topic.split(" ")
    base_topic = base_topic_parts[0]; # Assume 'ticket-user-ID type-TYPE'
    type_topic = base_topic_parts[1] if len(base_topic_parts) > 1 and base_topic_parts[1].startswith("type-") else ""
    if not base_topic.startswith("ticket-user-"): base_topic = f"ticket-user-{interaction.channel.id}" # Fallback
    new_topic = f"{base_topic} {type_topic} claimed-by-{interaction.user.id}".strip() # Add claimer ID

    try:
        await interaction.channel.edit(topic=new_topic)
        await send_embed_response(interaction, "Ticket Claimed", f"🎫 {interaction.user.mention} has claimed this ticket.", discord.Color.green(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "I cannot edit the channel topic.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed to claim ticket: {e}", discord.Color.red())

@ticket_group.command(name="unclaim", description="Releases the current ticket back to the queue.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_unclaim(interaction: discord.Interaction):
    """Unclaims the current ticket."""
    current_topic = interaction.channel.topic or ""
    if "claimed-by-" not in current_topic:
        await send_embed_response(interaction, "Not Claimed", "This ticket is not currently claimed.", discord.Color.orange()); return

    claimer_id_str = current_topic.split("claimed-by-")[-1].split(" ")[0]
    try: claimer_id = int(claimer_id_str)
    except ValueError: await send_embed_response(interaction, "Error", "Could not identify the claimer from the channel topic.", discord.Color.red()); return

    # Check if interaction user is the claimer or an admin
    is_admin = interaction.user.guild_permissions.administrator
    if interaction.user.id != claimer_id and not is_admin:
        claimer = interaction.guild.get_member(claimer_id) or f"User ID: {claimer_id}"
        await send_embed_response(interaction, "Permission Denied", f"This ticket is claimed by {claimer}. Only they or an administrator can unclaim it.", discord.Color.red()); return

    # Reconstruct original topic parts (user ID and type)
    topic_parts = current_topic.split(" ")
    base_topic = topic_parts[0] if topic_parts[0].startswith("ticket-user-") else f"ticket-user-{interaction.channel.id}"
    type_topic = topic_parts[1] if len(topic_parts) > 1 and topic_parts[1].startswith("type-") else ""
    new_topic = f"{base_topic} {type_topic}".strip() # Remove claimer ID

    try:
        await interaction.channel.edit(topic=new_topic)
        await send_embed_response(interaction, "Ticket Unclaimed", f"🔓 {interaction.user.mention} has unclaimed this ticket. It is now open for any staff member.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "I cannot edit the channel topic.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed to unclaim ticket: {e}", discord.Color.red())

@ticket_group.command(name="purge", description="Deletes a specified number of messages in the ticket (max 100).")
@app_commands.describe(amount="Number of messages to delete (1-100).")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    """Deletes messages in the current ticket channel."""
    await interaction.response.defer(ephemeral=True, thinking=True) # Defer ephemerally
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(embed=create_embed("Purged Messages", f"🗑️ Successfully deleted {len(deleted)} messages.", discord.Color.green()), ephemeral=True)
    except discord.Forbidden: await interaction.followup.send(embed=create_embed("Permissions Error", "I lack permission to delete messages.", discord.Color.red()), ephemeral=True)
    except Exception as e: await interaction.followup.send(embed=create_embed("Error", f"Failed to purge messages: {e}", discord.Color.red()), ephemeral=True)

@ticket_group.command(name="slowmode", description="Sets slowmode in the current ticket channel.")
@app_commands.describe(delay="Slowmode delay in seconds (0 to disable, max 21600).")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_slowmode(interaction: discord.Interaction, delay: app_commands.Range[int, 0, 21600]):
    """Sets slowmode delay for the current ticket channel."""
    try:
        await interaction.channel.edit(slowmode_delay=delay)
        status = f"disabled" if delay == 0 else f"set to {delay} seconds"
        await send_embed_response(interaction, "Slowmode Updated", f"⏳ Slowmode has been {status} for this channel.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "I lack permission to change slowmode.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed to set slowmode: {e}", discord.Color.red())


# --- MODERATION COMMANDS (Now under /mod group) ---

@mod_group.command(name="blacklist", description="Blacklists a user from creating tickets.")
@app_commands.describe(user="The user to blacklist.", reason="The reason for the blacklist (will be shown to user).")
@app_commands.checks.has_permissions(administrator=True) # Admin only
async def mod_blacklist(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Blacklists a user."""
    if user.id == interaction.user.id: await send_embed_response(interaction, "Error", "You cannot blacklist yourself.", discord.Color.orange()); return
    if user.bot: await send_embed_response(interaction, "Error", "You cannot blacklist bots.", discord.Color.orange()); return

    settings = bot.get_guild_settings(interaction.guild.id)
    user_id_str = str(user.id)
    blacklist_dict = settings.setdefault("blacklist", {}) # Ensure dict exists

    if user_id_str in blacklist_dict:
        await send_embed_response(interaction, "Already Blacklisted", f"{user.mention} is already blacklisted for: `{blacklist_dict[user_id_str]}`.", discord.Color.orange()); return

    blacklist_dict[user_id_str] = reason; bot.update_guild_setting(interaction.guild.id, "blacklist", blacklist_dict) # Update whole dict
    await send_embed_response(interaction, "User Blacklisted", f"{user.mention} has been **blacklisted**. Reason: `{reason}`.", discord.Color.red())

@mod_group.command(name="unblacklist", description="Removes a user from the ticket blacklist.")
@app_commands.describe(user="The user to unblacklist.")
@app_commands.checks.has_permissions(administrator=True) # Admin only
async def mod_unblacklist(interaction: discord.Interaction, user: discord.Member):
    """Unblacklists a user."""
    settings = bot.get_guild_settings(interaction.guild.id)
    user_id_str = str(user.id)
    blacklist_dict = settings.get("blacklist", {})

    if user_id_str not in blacklist_dict:
        await send_embed_response(interaction, "Not Found", f"{user.mention} is not currently blacklisted.", discord.Color.orange()); return

    del blacklist_dict[user_id_str]; bot.update_guild_setting(interaction.guild.id, "blacklist", blacklist_dict)
    await send_embed_response(interaction, "User Unblacklisted", f"{user.mention} has been **unblacklisted** and can now create tickets.", discord.Color.green())

@mod_group.command(name="announce", description="Sends an announcement (plain text or JSON embed).")
@app_commands.describe(channel="The channel to send the announcement to.", message="The text message (required if no JSON/image attached).", json_file="Attach embed JSON file (overrides message/image).", image_file="Attach an image file (sent with message).")
@is_staff_check() # Staff check
async def mod_announce(interaction: discord.Interaction, channel: discord.TextChannel, message: str = None, json_file: discord.Attachment = None, image_file: discord.Attachment = None):
    """Sends announcement (text, image, or JSON embed). JSON > Image > Text."""
    await interaction.response.defer(ephemeral=True, thinking=True) # Defer ephemerally

    embed_to_send = None
    content_to_send = message
    file_to_send = None

    # 1. Process JSON if provided (takes highest priority)
    if json_file:
        if not json_file.filename.lower().endswith('.json'):
            await interaction.followup.send(embed=create_embed("Error", "Invalid file type. Please attach a `.json` file for embeds.", discord.Color.red()), ephemeral=True); return
        try:
            json_bytes = await json_file.read()
            embed_data = json.loads(json_bytes.decode('utf-8'))
            if not isinstance(embed_data, dict): raise ValueError("JSON must be an object.")
            # Validate common embed fields if needed (optional)
            embed_to_send = discord.Embed.from_dict(embed_data)
            content_to_send = None # Ignore message if sending JSON embed
            image_file = None # Ignore image if sending JSON embed
            print(f"Loaded embed from {json_file.filename}")
        except Exception as e: await interaction.followup.send(embed=create_embed("JSON Error", f"Failed to process JSON: {e}", discord.Color.red()), ephemeral=True); return

    # 2. Process Image if provided (and no JSON)
    elif image_file:
        if not image_file.content_type or not image_file.content_type.startswith("image/"):
            await interaction.followup.send(embed=create_embed("Error", "Invalid file type. Please attach an image file.", discord.Color.red()), ephemeral=True); return
        try:
            image_bytes = await image_file.read()
            file_to_send = discord.File(io.BytesIO(image_bytes), filename=image_file.filename)
            print(f"Prepared image file: {image_file.filename}")
        except Exception as e: await interaction.followup.send(embed=create_embed("Error", f"Failed to read image: {e}", discord.Color.red()), ephemeral=True); return

    # 3. Check if there's anything to send
    if embed_to_send is None and content_to_send is None and file_to_send is None:
         await interaction.followup.send(embed=create_embed("Error", "Nothing to announce. Provide message, image, or JSON.", discord.Color.orange()), ephemeral=True); return

    # 4. Send the announcement
    try:
        await channel.send(content=content_to_send, embed=embed_to_send, file=file_to_send)
        await interaction.followup.send(embed=create_embed("Announcement Sent", f"Message delivered to {channel.mention}.", discord.Color.green()), ephemeral=True)
    except discord.Forbidden: await interaction.followup.send(embed=create_embed("Permissions Error", f"Cannot send to {channel.mention}.", discord.Color.red()), ephemeral=True)
    except discord.HTTPException as e: await interaction.followup.send(embed=create_embed("Send Error", f"Failed: {e}", discord.Color.red()), ephemeral=True)
    except Exception as e: print(f"Error in announce send: {e}"); traceback.print_exc(); await interaction.followup.send(embed=create_embed("Error", "Unexpected send error.", discord.Color.red()), ephemeral=True)


# --- UTILITY COMMANDS (Adding some useful extras) ---

@bot.tree.command(name="userinfo", description="Displays information about a server member.")
@app_commands.guild_only()
@app_commands.describe(member="The member to get information about (optional, defaults to you).")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    """Shows details about a user."""
    target = member or interaction.user # Default to self if member not provided
    embed = discord.Embed(title=f"User Information - {target.display_name}", color=target.color or discord.Color.blue())
    if target.avatar: embed.set_thumbnail(url=target.avatar.url)
    embed.add_field(name="Username", value=f"{target.name}#{target.discriminator}", inline=True)
    embed.add_field(name="User ID", value=target.id, inline=True)
    embed.add_field(name="Nickname", value=target.nick or "None", inline=True)
    embed.add_field(name="Joined Server", value=discord.utils.format_dt(target.joined_at, style='F'), inline=False) # 'F' for full date/time
    embed.add_field(name="Joined Discord", value=discord.utils.format_dt(target.created_at, style='F'), inline=False)
    roles = [role.mention for role in target.roles if role.name != "@everyone"]
    embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles) if roles else "None", inline=False)
    embed.add_field(name="Is Bot?", value="Yes" if target.bot else "No", inline=True)
    # Add highest role
    embed.add_field(name="Highest Role", value=target.top_role.mention, inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=False) # Not ephemeral

@bot.tree.command(name="serverinfo", description="Displays information about the current server.")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    """Shows details about the server."""
    guild = interaction.guild
    embed = discord.Embed(title=f"Server Information - {guild.name}", color=discord.Color.blurple())
    if guild.icon: embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Server ID", value=guild.id, inline=True)
    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True) # Mention owner
    embed.add_field(name="Created On", value=discord.utils.format_dt(guild.created_at, style='F'), inline=False)
    members = guild.member_count or "N/A" # Handle potential None
    humans = sum(1 for member in guild.members if not member.bot) if guild.members else "N/A"
    bots = sum(1 for member in guild.members if member.bot) if guild.members else "N/A"
    embed.add_field(name="Members", value=f"Total: {members}\nHumans: {humans}\nBots: {bots}", inline=True)
    embed.add_field(name="Channels", value=f"Text: {len(guild.text_channels)}\nVoice: {len(guild.voice_channels)}\nCategories: {len(guild.categories)}", inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    # embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True) # Uncomment if needed
    # embed.add_field(name="Boosts", value=guild.premium_subscription_count, inline=True) # Uncomment if needed
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
            open_tickets = len(ticket_category.text_channels) # Count text channels in category
        else:
            await interaction.followup.send(embed=create_embed("Warning", "Ticket category is invalid or not found. Open count may be inaccurate.", discord.Color.orange()), ephemeral=True)

    embed = discord.Embed(title=f"Ticket Statistics: {interaction.guild.name}", color=discord.Color.light_grey())
    embed.add_field(name="Total Tickets Created", value=f"**{total_created}**", inline=True)
    embed.add_field(name="Currently Open Tickets", value=f"**{open_tickets}**", inline=True)
    embed.set_footer(text="Counts include all ticket types.")
    await interaction.followup.send(embed=embed, ephemeral=True) # Send stats ephemerally

# Add command groups to the tree
bot.tree.add_command(setup_group)
bot.tree.add_command(ticket_group)
bot.tree.add_command(mod_group)


# --- RUN THE BOT ---
if __name__ == "__main__": # Good practice
    try:
        print("Attempting to run bot...")
        bot.run(TOKEN, log_handler=None)
    except discord.errors.LoginFailure:
        print("CRITICAL ERROR: Login Failure...")
    # ... other except blocks ...
    except Exception as e:
        print(f"CRITICAL ERROR during bot startup: {e}")
        traceback.print_exc()

