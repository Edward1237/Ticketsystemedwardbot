# bot.py (Part 1/4)

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

# --- SETTINGS MANAGEMENT ---
SETTINGS_FILE = 'settings.json'

def load_settings():
    """Loads settings from settings.json, creating/handling errors."""
    if not os.path.exists(SETTINGS_FILE):
        print(f"Info: {SETTINGS_FILE} not found. Creating.")
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: json.dump({}, f)
        return {}
    try:
        if os.path.getsize(SETTINGS_FILE) == 0: return {} # Handle empty file
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except json.JSONDecodeError: print(f"ERROR: {SETTINGS_FILE} corrupted. Fix/delete it."); return {}
    except Exception as e: print(f"ERROR loading settings: {e}"); traceback.print_exc(); return {}

def save_settings(settings):
    """Saves settings to settings.json"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: json.dump(settings, f, indent=4)
    except Exception as e: print(f"ERROR saving settings: {e}"); traceback.print_exc()

# --- BOT SETUP ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN: print("CRITICAL ERROR: DISCORD_TOKEN missing."); exit(1)

intents = discord.Intents.default()
intents.messages = True; intents.guilds = True; intents.members = True; intents.message_content = True

class TicketBot(commands.Bot):
    def __init__(self):
        # No prefix needed for slash-only bot, mentions still work
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = load_settings()
        self.persistent_views_added = False

    async def setup_hook(self):
        # Register persistent views ONCE before bot connects fully
        if not self.persistent_views_added:
            # Pass self (the bot instance) to the views
            self.add_view(TicketPanelView(self))
            self.add_view(TicketCloseView(self))
            self.add_view(AppealReviewView(self))
            self.persistent_views_added = True
            print("Persistent views registered.")
        # Sync slash commands
        try:
            print("Syncing slash commands...")
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands.")
        except Exception as e: print(f"ERROR syncing slash commands: {e}"); traceback.print_exc()

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print(f'discord.py version: {discord.__version__}')
        print('Bot is ready.')
        try:
            await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for tickets"))
            print("Presence set.")
        except Exception as e: print(f"Error setting presence: {e}")
        print('------')

    def get_guild_settings(self, guild_id: int):
        """Gets settings for a specific guild, ensuring defaults."""
        guild_id_str = str(guild_id)
        if not isinstance(self.settings, dict): self.settings = load_settings(); # Reload if needed
        if not isinstance(self.settings, dict): self.settings = {}; print("CRITICAL ERROR: Settings corrupted, reset.") # Reset if reload fails

        defaults = {
            "panel_channel": None, "ticket_category": None, "archive_category": None,
            "staff_role": None, "escalation_role": None, "appeal_channel": None,
            "ticket_counter": 1, "blacklist": {}
            # Removed prefix setting as bot is slash-only now
        }
        guild_settings = self.settings.get(guild_id_str)
        updated = False
        if not isinstance(guild_settings, dict):
             print(f"WARNING: Settings for guild {guild_id_str} invalid. Resetting."); guild_settings = defaults.copy(); updated = True
        for key, default_value in defaults.items():
            if key not in guild_settings: guild_settings[key] = default_value; updated = True
        if updated: self.settings[guild_id_str] = guild_settings; save_settings(self.settings) # Ensure update is saved
        return guild_settings

    def update_guild_setting(self, guild_id: int, key: str, value):
        settings = self.get_guild_settings(guild_id)
        if isinstance(settings, dict): settings[key] = value; save_settings(self.settings)
        else: print(f"CRITICAL ERROR: Cannot update setting '{key}' for guild {guild_id}.")

bot = TicketBot()

# --- HELPER FUNCTIONS ---
def create_embed(title: str = discord.Embed.Empty, description: str = discord.Embed.Empty, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
    # Allows omitting title/description, defaults color
    return discord.Embed(title=title, description=str(description) if description is not discord.Embed.Empty else description, color=color)

async def send_embed_response(interaction: discord.Interaction, title: str = discord.Embed.Empty, description: str = discord.Embed.Empty, color: discord.Color = discord.Color.blurple(), ephemeral: bool = True):
    # Sends embed responses for interactions, handles state
    embed = create_embed(title, description, color)
    try:
        # Use defer() first if lengthy operation might follow, otherwise send directly
        # For simplicity, we just try to send/followup
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except discord.NotFound: print(f"WARNING: Interaction not found sending '{title}'.")
    except discord.Forbidden: print(f"ERROR: Bot lacks permissions for embed response in {interaction.channel_id}.")
    except Exception as e: print(f"ERROR sending embed response: {type(e).__name__} - {e}"); traceback.print_exc()


# --- SLASH COMMAND GLOBAL ERROR HANDLER ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Global error handler for slash commands."""
    original_error = getattr(error, 'original', error) # Get original error if wrapped
    error_message = "An unexpected error occurred." # Default message

    if isinstance(error, app_commands.errors.MissingPermissions):
        error_message = "You lack the required permissions to use this command."
        await send_embed_response(interaction, "Permission Denied", error_message, discord.Color.red())
    elif isinstance(error, app_commands.errors.CheckFailure):
        # Our custom checks (is_staff, in_ticket) send their own messages. Log it here.
        print(f"Check failure handled for command '{interaction.command.name}' by {interaction.user.name}.")
        # No need to send another message if the check already did
        if not interaction.response.is_done():
             # If check failed *before* sending a response (e.g., internal error in check)
             await send_embed_response(interaction, "Check Failed", "Could not verify permissions.", discord.Color.orange())
        return # Stop further processing for check failures
    elif isinstance(error, app_commands.CommandNotFound):
         # Should ideally not happen with synced commands, but handle just in case
         error_message = "This command seems to be invalid or outdated."
         await send_embed_response(interaction, "Command Not Found", error_message, discord.Color.orange())
    elif isinstance(original_error, discord.Forbidden):
        # Permissions error *during* command execution
        print(f"ERROR: Bot lacks permissions during execution of '{interaction.command.name}': {original_error.text}")
        error_message = f"I lack permissions to perform this action. Missing: `{original_error.missing_perms}`" if hasattr(original_error, 'missing_perms') else "I lack the necessary permissions."
        await send_embed_response(interaction, "Permissions Error", error_message, discord.Color.red())
    elif isinstance(error, app_commands.errors.CommandInvokeError):
        # Generic error within the command code
        print(f"ERROR during command execution ({interaction.command.name}):")
        traceback.print_exception(type(original_error), original_error, original_error.__traceback__)
        error_message = "An error occurred while running this command."
        await send_embed_response(interaction, "Command Runtime Error", error_message, discord.Color.dark_red())
    else:
        # Log other unexpected errors
        print(f"UNHANDLED SLASH COMMAND ERROR ({type(error)}) in '{interaction.command.name}': {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_embed_response(interaction, "Error", error_message, discord.Color.dark_red())


# --- HELPER FUNCTIONS CONTINUED ---
async def check_setup(interaction: discord.Interaction):
    """Checks if the bot is fully set up for the guild."""
    # Simplified check_setup
    try: settings = bot.get_guild_settings(interaction.guild.id)
    except Exception as e: print(f"Error getting settings in check_setup: {e}"); await send_embed_response(interaction, "Error", "Could not load settings.", discord.Color.red()); return False
    required = ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']
    if not all(settings.get(key) for key in required):
        missing_str = ", ".join([s.replace("_", " ").title() for s in required if not settings.get(s)])
        desc = f"Admin needs to configure: `{missing_str}` using `/setup` commands."
        await send_embed_response(interaction, "Bot Not Configured", desc, discord.Color.red())
        return False
    return True

# Helper to count user's open tickets
def count_user_tickets(guild: discord.Guild, user_id: int, category_id: int, ticket_type: str = None) -> int:
    category = guild.get_channel(category_id)
    if not category or not isinstance(category, discord.CategoryChannel): return 0
    count = 0; user_id_str = str(user_id)
    for channel in category.text_channels:
        if channel.topic and f"ticket-user-{user_id_str}" in channel.topic:
            if ticket_type:
                if f"type-{ticket_type}" in channel.topic: count += 1
            else: count += 1
    return count

# create_ticket_channel helper function
async def create_ticket_channel(interaction: discord.Interaction, ticket_type_name: str, settings: dict):
    guild = interaction.guild; user = interaction.user
    staff_role_id = settings.get('staff_role'); category_id = settings.get('ticket_category')

    if not staff_role_id or not (staff_role := guild.get_role(staff_role_id)):
        await send_embed_response(interaction, "Configuration Error", "Staff Role invalid.", discord.Color.red()); return None, None
    if not category_id or not (category := guild.get_channel(category_id)) or not isinstance(category, discord.CategoryChannel):
        await send_embed_response(interaction, "Configuration Error", "Ticket Category invalid.", discord.Color.red()); return None, None

    # General hard limit
    if count_user_tickets(guild, user.id, category.id) > 15:
        await send_embed_response(interaction, "Limit Reached", "Too many open tickets.", discord.Color.orange()); return None, None

    ticket_num = settings.get('ticket_counter', 1)
    bot.update_guild_setting(guild.id, "ticket_counter", ticket_num + 1)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False), # Deny view for @everyone
        user: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True, embed_links=True, attach_files=True, manage_channels=True, manage_permissions=True, manage_messages=True),
        staff_role: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True, manage_messages=True)
    }

    try:
        safe_user_name = "".join(c for c in user.display_name if c.isalnum() or c in ('-', '_')).lower() or "user" # Use display_name
        channel_name = f"{ticket_type_name}-{ticket_num}-{safe_user_name}"[:100]
        # More descriptive topic, keep user ID marker clear
        topic = f"Ticket #{ticket_num} ({ticket_type_name.capitalize()}) for {user.name}. UserID marker: [ticket-user-{user.id} type-{ticket_type_name}]"[:1024] # Max topic length

        print(f"Attempting create channel '{channel_name}' in '{category.name}'")
        new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites, topic=topic, reason=f"Ticket created by {user.name}")
        print(f"Channel created: {new_channel.mention}")
    except discord.Forbidden: print(f"ERROR: Forbidden creating channel in {category.id}"); await send_embed_response(interaction, "Permissions Error", "Cannot create channel/set perms.", discord.Color.red()); return None, None
    except Exception as e: print(f"ERROR creating channel: {e}"); traceback.print_exc(); await send_embed_response(interaction, "Error", "Error creating channel.", discord.Color.red()); return None, None
    return new_channel, staff_role

# generate_transcript helper function
async def generate_transcript(channel: discord.TextChannel):
    # (Same as previous version, ensures clean output and size limits)
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
        clean_content = discord.utils.remove_markdown(discord.utils.escape_mentions(msg.content))
        author_display = f"{msg.author.display_name} ({msg.author.id})"
        if not msg.author.bot: messages.append(f"[{timestamp}] {author_display}: {clean_content}")
        if msg.attachments:
            for att in msg.attachments: messages.append(f"[{timestamp}] [Attachment from {author_display}: {att.url}]")
    transcript_content = "\n".join(messages) or "No messages sent."
    encoded_content = transcript_content.encode('utf-8'); max_size = 7 * 1024 * 1024 + 512 * 1024
    if len(encoded_content) > max_size:
        print(f"Transcript for {channel.name} too large, truncating."); truncated_content = encoded_content[:max_size - 200]
        try: transcript_content = truncated_content.decode('utf-8', errors='ignore') + "\n\n--- TRUNCATED ---"; encoded_content = transcript_content.encode('utf-8')
        except: return io.BytesIO(b"Transcript too large and could not be truncated.")
    return io.BytesIO(encoded_content)

# End of Part 1/4
# bot.py (Part 2/4)

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
            required=True, min_length=5, max_length=500 # Added length limits
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Processes the reason, updates appeal, notifies user."""
        await interaction.response.defer(ephemeral=True); staff_member = interaction.user; reason = self.reason_input.value
        try: appealing_user = await self.bot.fetch_user(self.appealing_user_id)
        except discord.NotFound: await interaction.followup.send(embed=create_embed("Error", "Could not find the appealing user to notify.", discord.Color.red())); return

        if not self.original_message or not self.original_message.embeds: # Check original message exists
            await interaction.followup.send(embed=create_embed("Error", "Could not find the original appeal message embed.", discord.Color.red())); return
        original_embed = self.original_message.embeds[0]; new_embed = original_embed.copy()

        if self.action == "Approve":
            title = "✅ Blacklist Appeal Approved"; color = discord.Color.green()
            dm_desc = f"Your blacklist appeal for **{self.guild.name}** has been approved by staff.\n\n**Reason Provided:**\n```{reason}```\nYou should now be able to create tickets again."
            # Unblacklist the user
            settings = self.bot.get_guild_settings(self.guild.id); user_id_str = str(self.appealing_user_id)
            if user_id_str in settings.get("blacklist", {}): # Use get() for safety
                del settings["blacklist"][user_id_str]; self.bot.update_guild_setting(self.guild.id, "blacklist", settings["blacklist"]) # Update via method
                print(f"User {user_id_str} unblacklisted via appeal approval by {staff_member.name}.")
        else: # Reject
            title = "❌ Blacklist Appeal Rejected"; color = discord.Color.red()
            dm_desc = f"Your blacklist appeal for **{self.guild.name}** has been rejected by staff.\n\n**Reason Provided:**\n```{reason}```"

        # Try to DM the user
        try:
            dm_embed = create_embed(title, dm_desc, color)
            await appealing_user.send(embed=dm_embed)
        except discord.Forbidden: print(f"Could not DM user {appealing_user.id} (appeal {self.action.lower()}d - DMs likely disabled)")
        except Exception as e: print(f"Error sending appeal result DM to {appealing_user.id}: {e}")

        # Edit the staff message
        new_embed.title = f"[{self.action.upper()}D by {staff_member.name}] Blacklist Appeal" # Add user who actioned
        new_embed.color = color
        # Replace fields or add new one? Add new one is safer.
        new_embed.add_field(name=f"{self.action.capitalize()}d by {staff_member.display_name}", value=f"```{reason}```", inline=False)
        try:
            await self.original_message.edit(embed=new_embed, view=None) # Remove buttons after action
        except discord.NotFound: print("Original appeal message not found during edit.")
        except discord.Forbidden: print("Lacking permissions to edit original appeal message.")

        await interaction.followup.send(embed=create_embed("Action Complete", f"The appeal has been **{self.action.lower()}d**. User notified (if DMs enabled).", color), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"ERROR in AppealReasonModal: {error}"); traceback.print_exc()
        # Attempt to respond ephemerally if possible
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred processing the reason.", ephemeral=True)
            else:
                await interaction.followup.send("An error occurred processing the reason.", ephemeral=True)
        except Exception as e:
             print(f"Error sending on_error message in AppealReasonModal: {e}")

# --- Persistent View for Appeal Review Buttons in Staff Channel ---
class AppealReviewView(discord.ui.View):
    """Persistent view with Approve/Reject buttons for staff appeal channel."""
    # Pass bot instance during init for persistent views
    def __init__(self, bot_instance: TicketBot):
        super().__init__(timeout=None)
        self.bot = bot_instance # Store bot instance directly

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Check permissions dynamically on button press
        # Use the stored bot instance
        if not self.bot:
             print("CRITICAL ERROR: Bot instance missing in AppealReviewView.")
             # Try to send an ephemeral message if possible
             try: await interaction.response.send_message("Internal bot error.", ephemeral=True)
             except Exception: pass
             return False

        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Setup Error", "Staff role not configured.", discord.Color.red()); return False
        staff_role = interaction.guild.get_role(staff_role_id)
        # Ensure user is a Member before checking roles/perms
        if not isinstance(interaction.user, discord.Member):
             await send_embed_response(interaction, "Error", "Could not verify permissions.", discord.Color.red()); return False
        is_admin = interaction.user.guild_permissions.administrator
        if (staff_role and staff_role in interaction.user.roles) or is_admin: return True
        else: await send_embed_response(interaction, "Permission Denied", "Only staff members can review appeals.", discord.Color.red()); return False

    @discord.ui.button(label="Approve Appeal", style=discord.ButtonStyle.success, emoji="✅", custom_id="persistent_appeal:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Cannot find appeal information.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "Cannot identify user from appeal.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        # Pass the stored bot instance to the modal
        modal = AppealReasonModal(bot_instance=self.bot, action="Approve", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Reject Appeal", style=discord.ButtonStyle.danger, emoji="❌", custom_id="persistent_appeal:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Cannot find appeal information.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "Cannot identify user from appeal.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        # Pass the stored bot instance to the modal
        modal = AppealReasonModal(bot_instance=self.bot, action="Reject", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
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
        for msg in reversed(self.messages_to_delete): # Reverse order
            try: await msg.delete()
            except (discord.NotFound, discord.Forbidden): pass
        try:
            target_message = interaction.message if interaction else self.message
            if target_message: await target_message.delete()
        except (discord.NotFound, discord.Forbidden): pass
        except Exception as e: print(f"Error cleaning up final appeal message: {e}")

    @discord.ui.button(label="Submit Appeal", style=discord.ButtonStyle.success, emoji="✅")
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True) # Defer ephemerally while sending to staff
        embed = create_embed("New Blacklist Appeal", f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n**Server:** {self.guild.name}", discord.Color.gold())
        embed.add_field(name="1. Reason for appeal (Why unfair?)", value=f"```{self.answers.get('q1','Not Provided')}```", inline=False)
        embed.add_field(name="2. Justification for unblacklist", value=f"```{self.answers.get('q2','Not Provided')}```", inline=False)
        embed.add_field(name="3. Supporting Proof/Statement", value=self.answers.get('proof','N/A'), inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}") # For review buttons
        # Pass bot instance to the persistent review view
        view_to_send = AppealReviewView(bot_instance=self.bot)

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
        await interaction.response.defer(ephemeral=True) # Defer ephemerally
        await interaction.followup.send(embed=create_embed("Appeal Cancelled", "Your appeal submission has been cancelled.", discord.Color.red()), ephemeral=True)
        await self.cleanup(interaction)

    async def on_timeout(self):
        # Disable buttons visually and clean up
        print("ConfirmAppealView timed out.")
        for item in self.children: item.disabled = True
        try:
            if self.message: # Check message exists
                 await self.message.edit(embed=create_embed("Appeal Timed Out", "You did not confirm the submission in time. The appeal has been cancelled.", discord.Color.red()), view=self)
                 await asyncio.sleep(15) # Allow user to see message before cleanup
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
        bot_msgs_to_delete = []; user_msg = None; ask_msg = None; err_msg = None
        try:
            ask_msg = await channel.send(embed=embed); bot_msgs_to_delete.append(ask_msg)
            while True:
                msg = await self.bot.wait_for('message', check=lambda m: m.author == user and m.channel == channel, timeout=timeout)
                user_msg = msg; bot_msgs_to_delete.append(user_msg)
                if err_msg:
                    try: await err_msg.delete(); bot_msgs_to_delete.remove(err_msg); err_msg = None
                    except: pass
                if check_proof: return bot_msgs_to_delete, user_msg
                # Add strip() to remove leading/trailing whitespace before length check
                if len(msg.content.strip()) < min_length:
                     err_msg = await channel.send(embed=create_embed("Input Too Short", f"Response must be at least {min_length} characters.", discord.Color.orange())); bot_msgs_to_delete.append(err_msg)
                     continue
                return bot_msgs_to_delete, user_msg
        except asyncio.TimeoutError:
            await channel.send(embed=create_embed("Timed Out", f"No response received within {int(timeout/60)} minutes. Appeal cancelled.", discord.Color.red()))
            # Don't delete intermediate messages here, let main flow handle cleanup if confirm times out or step fails
            return bot_msgs_to_delete, None # Signal timeout
        except Exception as e:
             print(f"Error in ask_question: {e}"); traceback.print_exc()
             await channel.send(embed=create_embed("Error", "An error occurred. Appeal cancelled.", discord.Color.red()))
             return bot_msgs_to_delete, None # Signal error


    @discord.ui.button(label="Start Appeal Process", style=discord.ButtonStyle.primary, emoji="📜")
    async def start_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable button immediately
        for item in self.children: item.disabled = True
        try: await interaction.response.edit_message(view=self) # Acknowledge and edit original message
        except discord.NotFound: print("AppealStartView: Original message not found."); return
        except Exception as e: print(f"Error editing original message in start_appeal: {e}")

        channel = interaction.channel; user = interaction.user
        messages_to_delete = [interaction.message]; answers = {}

        # Ensure bot instance is available
        current_bot = self.bot or interaction.client
        if not current_bot: print("CRITICAL ERROR: Bot instance lost."); await channel.send("Internal error."); return

        settings = current_bot.get_guild_settings(self.guild.id); appeal_channel_id = settings.get("appeal_channel")
        if not appeal_channel_id: await channel.send(embed=create_embed("Setup Error", f"Appeal system for **{self.guild.name}** not configured.", discord.Color.red())); return
        appeal_channel = self.guild.get_channel(appeal_channel_id)
        if not appeal_channel or not isinstance(appeal_channel, discord.TextChannel): await channel.send(embed=create_embed("Setup Error", f"Appeal channel for **{self.guild.name}** is invalid.", discord.Color.red())); return

        # --- Ask Questions with updated prompts ---
        q1_embed = create_embed("Appeal Question 1/3", "**Why do you believe your blacklist was incorrect or unfair?** Please provide specific details.", discord.Color.blue()).set_footer(text="Response required (min. 5 characters). 10 minute time limit.")
        bot_msgs, answer1_msg = await self.ask_question(channel, user, q1_embed, 5, timeout=600.0); messages_to_delete.extend(bot_msgs)
        if not answer1_msg: await self.cleanup_on_fail(messages_to_delete); return
        answers['q1'] = answer1_msg.content.strip() # Store stripped answer

        q2_embed = create_embed("Appeal Question 2/3", "**Why should your blacklist be removed?** What assurances can you provide regarding future conduct, if relevant?", discord.Color.blue()).set_footer(text="Response required (min. 5 characters). 10 minute time limit.")
        bot_msgs, answer2_msg = await self.ask_question(channel, user, q2_embed, 5, timeout=600.0); messages_to_delete.extend(bot_msgs)
        if not answer2_msg: await self.cleanup_on_fail(messages_to_delete); return
        answers['q2'] = answer2_msg.content.strip()

        q3_embed = create_embed("Appeal Question 3/3", "**Please provide any supporting evidence** (e.g., screenshots, message links) or any additional statements you wish to make. If you have no evidence, please type `N/A`.", discord.Color.blue()).set_footer(text="Optional response. 10 minute time limit.")
        bot_msgs, answer3_msg = await self.ask_question(channel, user, q3_embed, 0, check_proof=True, timeout=600.0); messages_to_delete.extend(bot_msgs)
        if not answer3_msg: await self.cleanup_on_fail(messages_to_delete); return
        # Process proof message (text and attachments)
        proof_content = answer3_msg.content.strip() if answer3_msg.content else "N/A" # Use stripped content
        if answer3_msg.attachments:
             proof_urls = "\n".join([att.url for att in answer3_msg.attachments])
             proof_content = f"{proof_content}\n{proof_urls}" if proof_content != "N/A" else proof_urls
        answers['proof'] = proof_content

        # --- Confirmation Step ---
        summary_embed = create_embed("Confirm Appeal Submission", "Please review your answers. Press 'Submit Appeal' to send this to the staff or 'Cancel'.", discord.Color.green())
        summary_embed.add_field(name="1. Reason for appeal (Why unfair?)", value=f"```{answers['q1']}```", inline=False)
        summary_embed.add_field(name="2. Justification for unblacklist", value=f"```{answers['q2']}```", inline=False)
        summary_embed.add_field(name="3. Supporting Proof/Statement", value=answers['proof'], inline=False)
        # Pass ALL messages collected so far to ConfirmAppealView for eventual deletion
        confirm_view = ConfirmAppealView(current_bot, answers, self.guild, appeal_channel, messages_to_delete)
        confirm_view.message = await channel.send(embed=summary_embed, view=confirm_view)

    async def cleanup_on_fail(self, messages: list):
        """Cleans up messages if a step fails before confirm view"""
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
                await self.message.edit(embed=create_embed(f"Blacklisted on {self.guild.name}", f"Reason:\n```{self.reason}```\nThe window to start an appeal has expired (30 minutes).", discord.Color.red()), view=self) # Update embed
        except (discord.NotFound, discord.Forbidden): pass
        except Exception as e: print(f"Failed edit appeal start on timeout: {e}")

# bot.py (Part 3/4)

# bot.py (Part 3/4 - Continued)

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
        except discord.Forbidden: print(f"Cannot send appeal DM to {user.id} (DMs disabled).")
        except Exception as e: print(f"Failed to send appeal DM to {user.id}: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Checks blacklist and setup status before allowing button press."""
        # Ensure bot instance is available
        if not self.bot:
             print("CRITICAL ERROR: Bot instance missing in TicketPanelView interaction_check.")
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
            await self.send_appeal_dm(interaction.user, interaction.guild, reason)
            return False # Stop button callback

        # --- SETUP CHECK ---
        required = ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']
        if not all(settings.get(key) for key in required):
            # Use send_embed_response which handles interaction state
            await send_embed_response(interaction, "System Offline", "The ticket system is not fully configured by an administrator.", discord.Color.red(), ephemeral=True)
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
            # Pass bot instance to the view in the channel
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(self.bot))

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
        except Exception as e: print(f"Warning: Could not send ping in {channel.id}: {e}")

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
                except Exception as e: print(f"Error setting image: {e}"); success_embed.add_field(name="Image Error", value="Could not embed.", inline=False)
            else: success_embed.add_field(name="Stats Screenshot", value="Not provided.", inline=False)

            await channel.send(embed=success_embed, view=TicketCloseView(self.bot)) # Pass bot instance

        except asyncio.TimeoutError:
            timeout_embed = create_embed("Ticket Closed Automatically", "Inactivity during application.", discord.Color.red())
            try: await channel.send(embed=timeout_embed); await asyncio.sleep(10); await channel.delete(reason="Tryout timeout")
            except (discord.NotFound, discord.Forbidden): pass
            except Exception as e: print(f"Error during timeout cleanup: {e}")
        except Exception as e:
            print(f"ERROR during tryout process in {getattr(channel, 'id', 'N/A')}: {e}"); traceback.print_exc()
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
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(self.bot)) # Pass bot instance


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
        warning_message = await interaction.channel.send(embed=embed) # Send non-ephemeral warning
        await interaction.followup.send("Deletion initiated.", ephemeral=True) # Confirm to user
        await asyncio.sleep(10)
        try: await interaction.channel.delete(reason=f"Deleted by {interaction.user.name} ({interaction.user.id})")
        except discord.NotFound: pass # Already gone
        except discord.Forbidden: print(f"ERROR: Lacking delete permissions for {interaction.channel.id}") # Log error
        except Exception as e: print(f"ERROR deleting ticket {interaction.channel.id}: {e}"); traceback.print_exc()

    async def close_ticket_logic(self, channel: discord.TextChannel, user: discord.Member, reason: str = "No reason provided"):
        """Handles transcript generation, message sending, and channel archival."""
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

# End of Part 3/4

# End of Part 3/4
# bot.py (Part 4/4)

# --- SLASH COMMAND GROUPS ---
# Group setup commands under /setup
# default_permissions apply to all commands within the group unless overridden
setup_group = app_commands.Group(
    name="setup",
    description="Admin commands to configure the ticket bot.",
    guild_only=True,
    default_permissions=discord.Permissions(administrator=True) # Only Admins can use /setup commands
)
# Group ticket management commands under /ticket
# Permissions for ticket commands are checked within each command using is_staff_check()
ticket_group = app_commands.Group(
    name="ticket",
    description="Staff commands to manage tickets.",
    guild_only=True
)
# Group moderation commands under /mod
mod_group = app_commands.Group(
    name="mod",
    description="Moderation related commands (blacklist, announce).",
    guild_only=True
)


# --- SETUP COMMANDS (Now under /setup group) ---

@setup_group.command(name="panel_channel", description="Sets the channel where the ticket creation panel is posted.")
@app_commands.describe(channel="The text channel for the panel.")
async def set_panel_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Sets the channel for the ticket creation panel."""
    # Admin check is handled by group default_permissions
    bot.update_guild_setting(interaction.guild.id, "panel_channel", channel.id)
    await send_embed_response(interaction, "Setup Complete", f"Ticket panel channel has been set to {channel.mention}", discord.Color.green())

@setup_group.command(name="ticket_category", description="Sets the category where new tickets will be created.")
@app_commands.describe(category="The category channel for new tickets.")
async def set_ticket_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    """Sets the category for new tickets."""
    bot.update_guild_setting(interaction.guild.id, "ticket_category", category.id)
    await send_embed_response(interaction, "Setup Complete", f"New tickets will be created in the `{category.name}` category.", discord.Color.green())

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
    await send_embed_response(interaction, "Setup Complete", f"Staff role has been set to {role.mention}", discord.Color.green())

@setup_group.command(name="escalation_role", description="Sets the senior staff role pinged by /ticket escalate.")
@app_commands.describe(role="The role to ping for ticket escalations.")
async def set_escalation_role(interaction: discord.Interaction, role: discord.Role):
    """Sets the escalation role."""
    bot.update_guild_setting(interaction.guild.id, "escalation_role", role.id)
    await send_embed_response(interaction, "Setup Complete", f"Escalation role has been set to {role.mention}", discord.Color.green())

@setup_group.command(name="appeal_channel", description="Sets the channel where blacklist appeals are sent.")
@app_commands.describe(channel="The channel for staff to review appeals.")
async def set_appeal_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Sets the blacklist appeal channel."""
    bot.update_guild_setting(interaction.guild.id, "appeal_channel", channel.id)
    await send_embed_response(interaction, "Setup Complete", f"Blacklist appeals will be sent to {channel.mention}", discord.Color.green())

# --- PANEL CREATION COMMAND (Now under /setup group) ---
@setup_group.command(name="create_panel", description="Sends the ticket creation panel to the configured channel.")
async def create_panel(interaction: discord.Interaction):
    """Sends the ticket creation panel."""
    # Admin check handled by group
    if not await check_setup(interaction): return # Verify setup first

    settings = bot.get_guild_settings(interaction.guild.id)
    panel_channel_id = settings.get('panel_channel')
    panel_channel = bot.get_channel(panel_channel_id) if panel_channel_id else None

    if not panel_channel or not isinstance(panel_channel, discord.TextChannel):
        await send_embed_response(interaction, "Configuration Error", "Panel channel invalid or not found.", discord.Color.red()); return

    bot_member = interaction.guild.me; perms = panel_channel.permissions_for(bot_member)
    if not perms.send_messages or not perms.embed_links:
         await send_embed_response(interaction, "Permissions Error", f"Cannot send panel to {panel_channel.mention}.", discord.Color.red()); return

    embed = discord.Embed(title="Support & Tryouts", description="Select an option below to create a ticket.", color=0x2b2d31)
    if interaction.guild.icon: embed.set_thumbnail(url=interaction.guild.icon.url)
    embed.add_field(name="🎫 Standard Ticket", value="General help, questions, issues.", inline=False)
    embed.add_field(name="⚔️ Tryout Application", value="Apply to join the clan.", inline=False)
    embed.add_field(name="🚨 Report a User", value="Report rule breakers (requires evidence).", inline=False)
    embed.set_footer(text=f"{interaction.guild.name} Support System")
    try:
        # Pass bot instance to the persistent view
        await panel_channel.send(embed=embed, view=TicketPanelView(bot))
        await send_embed_response(interaction, "Panel Created", f"Panel sent to {panel_channel.mention}", discord.Color.green())
    except Exception as e: print(f"Error sending panel: {e}"); traceback.print_exc(); await send_embed_response(interaction, "Error", "Could not send panel.", discord.Color.red())

# --- TICKET MANAGEMENT COMMANDS (Now under /ticket group) ---

# --- Staff Check Decorator for App Commands ---
def is_staff_check():
    """Decorator check if interaction user is staff or admin."""
    async def predicate(interaction: discord.Interaction) -> bool:
        # Uses the async check function defined earlier
        if await is_staff_interaction(interaction): return True
        # is_staff_interaction sends the "denied" message
        return False
    return app_commands.check(predicate)

# --- Ticket Channel Check Decorator for App Commands ---
def in_ticket_channel_check():
    """Decorator check if command is used in an open ticket channel."""
    async def predicate(interaction: discord.Interaction) -> bool:
        settings = bot.get_guild_settings(interaction.guild.id)
        # Check channel category against configured ticket category
        if interaction.channel and interaction.channel.category_id == settings.get('ticket_category'): return True
        await send_embed_response(interaction, "Invalid Channel", "Only usable in open tickets.", discord.Color.red()); return False
    return app_commands.check(predicate)


@ticket_group.command(name="add", description="Adds a user to the current ticket.")
@app_commands.describe(user="The user to add to the ticket.")
@is_staff_check() # Check if command user is staff
@in_ticket_channel_check() # Check if used in a ticket channel
async def ticket_add(interaction: discord.Interaction, user: discord.Member):
    """Adds a user to the current ticket channel."""
    try:
        # Grant permissions to the specified user
        await interaction.channel.set_permissions(user, read_messages=True, send_messages=True, view_channel=True)
        # Send confirmation (not ephemeral)
        await send_embed_response(interaction, "User Added", f"{user.mention} added by {interaction.user.mention}.", discord.Color.green(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "Cannot modify permissions.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed: {e}", discord.Color.red())

@ticket_group.command(name="remove", description="Removes a user from the current ticket.")
@app_commands.describe(user="The user to remove from the ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_remove(interaction: discord.Interaction, user: discord.Member):
    """Removes a user from the current ticket channel."""
    try:
        # Reset permissions (effectively removing them)
        await interaction.channel.set_permissions(user, overwrite=None)
        await send_embed_response(interaction, "User Removed", f"{user.mention} removed by {interaction.user.mention}.", discord.Color.orange(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "Cannot modify permissions.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed: {e}", discord.Color.red())

@ticket_group.command(name="rename", description="Renames the current ticket channel.")
@app_commands.describe(new_name="The new name for the ticket channel (spaces become hyphens).")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_rename(interaction: discord.Interaction, new_name: str):
    """Renames the current ticket channel."""
    try:
        # Sanitize name
        clean_name = "".join(c for c in new_name if c.isalnum() or c in ('-','_ ')).replace(' ','-').lower()[:100] or f"ticket-{interaction.channel.id}"
        await interaction.channel.edit(name=clean_name, reason=f"Renamed by {interaction.user.name}")
        await send_embed_response(interaction, "Ticket Renamed", f"Channel renamed to `{clean_name}`.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "Cannot rename channel.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed: {e}", discord.Color.red())

@ticket_group.command(name="escalate", description="Pings the escalation role in the current ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_escalate(interaction: discord.Interaction):
    """Pings the escalation role in the ticket."""
    settings = bot.get_guild_settings(interaction.guild.id); esc_role_id = settings.get("escalation_role")
    if not esc_role_id or not (esc_role := interaction.guild.get_role(esc_role_id)):
        await send_embed_response(interaction, "Configuration Error", "Escalation role invalid.", discord.Color.red()); return

    embed = create_embed("Ticket Escalated", f"🚨 Requires senior attention! Escalated by {interaction.user.mention}. {esc_role.mention}, please assist.", discord.Color.red())
    try:
        await interaction.response.defer(ephemeral=True) # Defer before sending non-ephemeral
        await interaction.channel.send(content=esc_role.mention, embed=embed) # Ping role
        await interaction.followup.send("Escalation ping sent.", ephemeral=True)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "Cannot send/ping.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed: {e}", discord.Color.red())

@ticket_group.command(name="claim", description="Claims the current ticket.")
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
             claimer = claimer_member.mention if claimer_member else f"User ID: {claimer_id}"
        await send_embed_response(interaction, "Already Claimed", f"Claimed by {claimer}.", discord.Color.orange()); return

    # Reconstruct topic preserving essential parts
    topic_parts = current_topic.split(" ")
    base_topic = next((part for part in topic_parts if part.startswith("ticket-user-")), f"ticket-user-{interaction.channel.id}")
    type_topic = next((part for part in topic_parts if part.startswith("type-")), "")
    new_topic = f"{base_topic} {type_topic} claimed-by-{interaction.user.id}".strip()[:1024]

    try:
        await interaction.channel.edit(topic=new_topic, reason=f"Claimed by {interaction.user.name}")
        await send_embed_response(interaction, "Ticket Claimed", f"🎫 {interaction.user.mention} claimed this ticket.", discord.Color.green(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "Cannot edit topic.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed: {e}", discord.Color.red())

@ticket_group.command(name="unclaim", description="Releases the current ticket.")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_unclaim(interaction: discord.Interaction):
    """Unclaims the current ticket."""
    current_topic = interaction.channel.topic or ""
    if "claimed-by-" not in current_topic: await send_embed_response(interaction, "Not Claimed", "", discord.Color.orange()); return

    parts = current_topic.split(" ")
    claimer_part = next((part for part in parts if part.startswith("claimed-by-")), None)
    claimer_id_str = claimer_part.split("-")[-1] if claimer_part else None
    claimer_id = None
    if claimer_id_str and claimer_id_str.isdigit(): claimer_id = int(claimer_id_str)

    if not claimer_id: await send_embed_response(interaction, "Error", "Cannot identify claimer.", discord.Color.red()); return

    is_admin = interaction.user.guild_permissions.administrator
    if interaction.user.id != claimer_id and not is_admin:
        claimer = interaction.guild.get_member(claimer_id) or f"User ID: {claimer_id}"
        await send_embed_response(interaction, "Permission Denied", f"Claimed by {claimer}.", discord.Color.red()); return

    # Reconstruct topic without claimer part
    base_topic = next((part for part in parts if part.startswith("ticket-user-")), f"ticket-user-{interaction.channel.id}")
    type_topic = next((part for part in parts if part.startswith("type-")), "")
    new_topic = f"{base_topic} {type_topic}".strip()[:1024]

    try:
        await interaction.channel.edit(topic=new_topic, reason=f"Unclaimed by {interaction.user.name}")
        await send_embed_response(interaction, "Ticket Unclaimed", f"🔓 {interaction.user.mention} unclaimed.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "Cannot edit topic.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed: {e}", discord.Color.red())

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
        await interaction.followup.send(embed=create_embed("Purged Messages", f"🗑️ Successfully deleted {len(deleted)} messages.", discord.Color.green()), ephemeral=True)
    except discord.Forbidden: await interaction.followup.send(embed=create_embed("Permissions Error", "Lacking delete permission.", discord.Color.red()), ephemeral=True)
    except Exception as e: await interaction.followup.send(embed=create_embed("Error", f"Purge failed: {e}", discord.Color.red()), ephemeral=True)

@ticket_group.command(name="slowmode", description="Sets slowmode in the current ticket.")
@app_commands.describe(delay="Delay in seconds (0 to disable, max 21600).")
@is_staff_check()
@in_ticket_channel_check()
async def ticket_slowmode(interaction: discord.Interaction, delay: app_commands.Range[int, 0, 21600]):
    """Sets slowmode delay for the current ticket channel."""
    try:
        await interaction.channel.edit(slowmode_delay=delay, reason=f"Slowmode set by {interaction.user.name}")
        status = f"disabled" if delay == 0 else f"set to {delay} seconds"
        # Send non-ephemeral confirmation
        await send_embed_response(interaction, "Slowmode Updated", f"⏳ Slowmode {status}.", discord.Color.blue(), ephemeral=False)
    except discord.Forbidden: await send_embed_response(interaction, "Permissions Error", "Cannot change slowmode.", discord.Color.red())
    except Exception as e: await send_embed_response(interaction, "Error", f"Failed: {e}", discord.Color.red())

# --- MODERATION COMMANDS (Now under /mod group) ---

# Create the command group
mod_group = app_commands.Group(name="mod", description="Moderation commands (blacklist, announce).", guild_only=True)

@mod_group.command(name="blacklist", description="Blacklists a user from creating tickets.")
@app_commands.describe(user="The user to blacklist.", reason="Reason for blacklist (shown to user).")
@app_commands.checks.has_permissions(administrator=True) # Admin only
async def mod_blacklist(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Blacklists a user."""
    if user.id == interaction.user.id: await send_embed_response(interaction, "Error", "Cannot blacklist self.", discord.Color.orange()); return
    if user.bot: await send_embed_response(interaction, "Error", "Cannot blacklist bots.", discord.Color.orange()); return
    settings = bot.get_guild_settings(interaction.guild.id); user_id_str = str(user.id)
    blacklist_dict = settings.setdefault("blacklist", {})
    if user_id_str in blacklist_dict: await send_embed_response(interaction, "Already Blacklisted", f"{user.mention} is already blacklisted.", discord.Color.orange()); return
    blacklist_dict[user_id_str] = reason; bot.update_guild_setting(interaction.guild.id, "blacklist", blacklist_dict)
    await send_embed_response(interaction, "User Blacklisted", f"{user.mention} blacklisted: `{reason}`.", discord.Color.red())

@mod_group.command(name="unblacklist", description="Removes a user from the ticket blacklist.")
@app_commands.describe(user="The user to unblacklist.")
@app_commands.checks.has_permissions(administrator=True) # Admin only
async def mod_unblacklist(interaction: discord.Interaction, user: discord.Member):
    """Unblacklists a user."""
    settings = bot.get_guild_settings(interaction.guild.id); user_id_str = str(user.id)
    blacklist_dict = settings.get("blacklist", {})
    if user_id_str not in blacklist_dict: await send_embed_response(interaction, "Not Found", f"{user.mention} is not blacklisted.", discord.Color.orange()); return
    del blacklist_dict[user_id_str]; bot.update_guild_setting(interaction.guild.id, "blacklist", blacklist_dict)
    await send_embed_response(interaction, "User Unblacklisted", f"{user.mention} unblacklisted.", discord.Color.green())

@mod_group.command(name="announce", description="Sends an announcement (plain text, image, or JSON embed).")
@app_commands.describe(channel="Channel to announce in.", message="Text message (if not using JSON/image).", json_file="Attach embed JSON file (overrides others).", image_file="Attach image file (sent with text).")
@is_staff_check() # Staff check
async def mod_announce(interaction: discord.Interaction, channel: discord.TextChannel, message: str = None, json_file: discord.Attachment = None, image_file: discord.Attachment = None):
    """Sends announcement. JSON > Image > Text priority."""
    await interaction.response.defer(ephemeral=True, thinking=True) # Defer ephemerally

    embed_to_send = None; content_to_send = message; file_to_send = None

    if json_file: # JSON highest priority
        if not json_file.filename.lower().endswith('.json'): await interaction.followup.send(embed=create_embed("Error", "Invalid JSON file type.", discord.Color.red()), ephemeral=True); return
        try:
            json_bytes = await json_file.read(); embed_data = json.loads(json_bytes.decode('utf-8'))
            if not isinstance(embed_data, dict): raise ValueError("JSON must be object.")
            embed_to_send = discord.Embed.from_dict(embed_data)
            content_to_send = None; image_file = None # Ignore others if JSON used
        except Exception as e: await interaction.followup.send(embed=create_embed("JSON Error", f"Failed: {e}", discord.Color.red()), ephemeral=True); return
    elif image_file: # Image second priority
        if not image_file.content_type or not image_file.content_type.startswith("image/"): await interaction.followup.send(embed=create_embed("Error", "Invalid image file type.", discord.Color.red()), ephemeral=True); return
        try: image_bytes = await image_file.read(); file_to_send = discord.File(io.BytesIO(image_bytes), filename=image_file.filename)
        except Exception as e: await interaction.followup.send(embed=create_embed("Error", f"Failed reading image: {e}", discord.Color.red()), ephemeral=True); return

    if embed_to_send is None and content_to_send is None and file_to_send is None:
         await interaction.followup.send(embed=create_embed("Error", "Nothing to announce.", discord.Color.orange()), ephemeral=True); return

    try:
        await channel.send(content=content_to_send, embed=embed_to_send, file=file_to_send)
        await interaction.followup.send(embed=create_embed("Sent", f"To {channel.mention}.", discord.Color.green()), ephemeral=True)
    except discord.Forbidden: await interaction.followup.send(embed=create_embed("Permissions Error", f"Cannot send to {channel.mention}.", discord.Color.red()), ephemeral=True)
    except discord.HTTPException as e: await interaction.followup.send(embed=create_embed("Send Error", f"Failed: {e}", discord.Color.red()), ephemeral=True)
    except Exception as e: print(f"Error announce send: {e}"); traceback.print_exc(); await interaction.followup.send(embed=create_embed("Error", "Unexpected send error.", discord.Color.red()), ephemeral=True)


# --- UTILITY COMMANDS ---

@bot.tree.command(name="userinfo", description="Displays information about a server member.")
@app_commands.guild_only()
@app_commands.describe(member="The member to get info about (defaults to you).")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    """Shows details about a user."""
    target = member or interaction.user # Target is Member type
    embed = discord.Embed(title=f"User Information", description=f"Details for {target.mention}", color=target.color or discord.Color.blue(), timestamp=discord.utils.utcnow())
    if target.avatar: embed.set_thumbnail(url=target.avatar.url)
    if target.display_avatar: embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    else: embed.set_author(name=target.display_name) # Fallback if no display avatar

    embed.add_field(name="Username", value=f"`{target.name}#{target.discriminator}`", inline=True)
    embed.add_field(name="User ID", value=f"`{target.id}`", inline=True)
    embed.add_field(name="Nickname", value=f"`{target.nick}`" if target.nick else "None", inline=True)
    embed.add_field(name="Joined Server", value=discord.utils.format_dt(target.joined_at, style='R'), inline=True) # Relative time
    embed.add_field(name="Joined Discord", value=discord.utils.format_dt(target.created_at, style='R'), inline=True)
    embed.add_field(name="Is Bot?", value="Yes" if target.bot else "No", inline=True)
    roles = [role.mention for role in reversed(target.roles) if role.name != "@everyone"] # Reverse for hierarchy?
    role_str = ", ".join(roles) if roles else "None"
    # Truncate role list if too long
    if len(role_str) > 1020: role_str = role_str[:1020] + "..."
    embed.add_field(name=f"Roles ({len(roles)})", value=role_str or "None", inline=False)
    embed.add_field(name="Highest Role", value=target.top_role.mention if target.top_role.name != "@everyone" else "None", inline=True)
    embed.add_field(name="Status", value=str(target.status).capitalize(), inline=True)
    # Add activity if present
    if target.activity: embed.add_field(name="Activity", value=f"{target.activity.type.name.capitalize() if target.activity.type else ''} {target.activity.name or ''}", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=False) # Not ephemeral

@bot.tree.command(name="serverinfo", description="Displays information about the current server.")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    """Shows details about the server."""
    guild = interaction.guild
    embed = discord.Embed(title=f"Server Information", description=f"Details for **{guild.name}**", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
    if guild.icon: embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Server ID", value=f"`{guild.id}`", inline=True)
    # Fetch owner if not cached? Or just display ID if owner is None
    owner_mention = guild.owner.mention if guild.owner else (await bot.fetch_user(guild.owner_id)).mention if guild.owner_id else "Unknown"
    embed.add_field(name="Owner", value=owner_mention, inline=True)
    embed.add_field(name="Created On", value=discord.utils.format_dt(guild.created_at, style='F'), inline=False)
    # Member counts (ensure members intent is enabled and bot has cache)
    members = guild.member_count or len(guild.members) # Use member_count if available
    humans = sum(1 for m in guild.members if not m.bot) if guild.members else "N/A (Cache?)"
    bots = sum(1 for m in guild.members if m.bot) if guild.members else "N/A (Cache?)"
    embed.add_field(name="Members", value=f"Total: {members}\nHumans: {humans}\nBots: {bots}", inline=True)
    embed.add_field(name="Channels", value=f"Text: {len(guild.text_channels)}\nVoice: {len(guild.voice_channels)}\nCategories: {len(guild.categories)}", inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)
    embed.add_field(name="Boosts", value=guild.premium_subscription_count or 0, inline=True)
    # Add verification level
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
    embed.set_footer(text="Counts include all ticket types.")
    await interaction.followup.send(embed=embed, ephemeral=True) # Send stats ephemerally

# Add command groups to the tree AFTER defining them
bot.tree.add_command(setup_group)
bot.tree.add_command(ticket_group)
bot.tree.add_command(mod_group)


# --- RUN THE BOT ---
if __name__ == "__main__": # Good practice
    try:
        # Use discord.py's default logging or configure your own
        # handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w') # Example file logger
        bot.run(TOKEN) #, log_handler=handler, log_level=logging.DEBUG) # Optional logging args
    except discord.errors.LoginFailure: print("CRITICAL ERROR: Login Failure - Improper token.")
    except discord.errors.PrivilegedIntentsRequired: print("CRITICAL ERROR: Privileged Intents Required - Check Developer Portal.")
    except Exception as e: print(f"CRITICAL ERROR during bot startup: {e}"); traceback.print_exc()

# End of Part 4/4