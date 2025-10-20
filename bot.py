# bot.py

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import io
import asyncio
from dotenv import load_dotenv

# --- SETTINGS MANAGEMENT (for multi-server) ---
SETTINGS_FILE = 'settings.json'

def load_settings():
    """Loads settings from settings.json"""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r') as f:
            # Handle empty file case
            content = f.read()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        print(f"Warning: {SETTINGS_FILE} is corrupted. Starting with default settings.")
        # Optionally backup corrupted file here
        return {}
    except Exception as e:
        print(f"Error loading settings: {e}")
        return {}


def save_settings(settings):
    """Saves settings to settings.json"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")

# --- BOT SETUP ---

# Load token from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("Error: DISCORD_TOKEN not found. Please create a .env file with your bot token.")
    exit()

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
        return commands.when_mentioned_or("!")(bot_instance, message) # Default '!' in DMs

    # Ensure settings are loaded correctly
    if not isinstance(bot_instance.settings, dict):
         print("Warning: Bot settings are not a dictionary. Using default prefix.")
         bot_instance.settings = load_settings() # Attempt reload
         if not isinstance(bot_instance.settings, dict): # Still not dict after reload
              bot_instance.settings = {} # Reset to empty dict

    settings_for_guild = bot_instance.settings.get(str(message.guild.id), {})
    prefix = settings_for_guild.get("prefix", "!") # Default '!'
    return commands.when_mentioned_or(prefix)(bot_instance, message)

# Bot definition
class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, intents=intents)
        self.settings = load_settings()
        self.persistent_views_added = False
        self.remove_command('help')

    async def setup_hook(self):
        if not self.persistent_views_added:
            self.add_view(TicketPanelView(bot=self))
            self.add_view(TicketCloseView(bot=self))
            self.add_view(AppealReviewView(bot=self)) # For appeal buttons
            self.persistent_views_added = True
        try:
            await self.tree.sync()
            print("Slash commands synced.")
        except Exception as e:
            print(f"Failed to sync slash commands: {e}")


    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('Bot is ready and listening for commands.')
        print('------')

    def get_guild_settings(self, guild_id):
        """Gets settings for a specific guild, creating if not found."""
        guild_id_str = str(guild_id)

        # Ensure self.settings is a dict
        if not isinstance(self.settings, dict):
            print("Warning: self.settings is not a dict in get_guild_settings. Reloading...")
            self.settings = load_settings()
            if not isinstance(self.settings, dict): # Still not dict? Reset.
                print("Error: Could not load settings as dict. Resetting settings.")
                self.settings = {}


        if guild_id_str not in self.settings:
            self.settings[guild_id_str] = {
                "panel_channel": None, "ticket_category": None, "archive_category": None,
                "staff_role": None, "escalation_role": None, "appeal_channel": None,
                "prefix": "!", "ticket_counter": 1, "blacklist": {}
            }
            save_settings(self.settings)

        defaults = {
            "blacklist": {}, "appeal_channel": None, "escalation_role": None,
            "prefix": "!", "ticket_counter": 1
        }
        updated = False
        # Ensure guild settings is also a dict
        guild_settings = self.settings.get(guild_id_str)
        if not isinstance(guild_settings, dict):
             print(f"Warning: Settings for guild {guild_id_str} are not a dict. Resetting guild settings.")
             guild_settings = defaults # Reset to defaults
             self.settings[guild_id_str] = guild_settings
             updated = True # Mark for saving

        for key, default_value in defaults.items():
            if key not in guild_settings:
                guild_settings[key] = default_value
                updated = True
        if updated:
            save_settings(self.settings)

        return guild_settings # Return the potentially corrected guild_settings


    def update_guild_setting(self, guild_id, key, value):
        settings = self.get_guild_settings(guild_id) # This now handles potential type errors
        if isinstance(settings, dict): # Ensure settings is a dict before updating
            settings[key] = value
            save_settings(self.settings)
        else:
            print(f"Error: Could not update setting for guild {guild_id} because settings are not a dictionary.")


bot = TicketBot()

# --- GLOBAL CHECK TO IGNORE DMS ---
@bot.check
async def globally_ignore_dms(ctx):
    return ctx.guild is not None

# --- HELPER FUNCTIONS ---

def create_embed(title: str, description: str, color: discord.Color) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)

async def send_embed_response(ctx_or_interaction, title: str, description: str, color: discord.Color, ephemeral: bool = True):
    embed = create_embed(title, description, color)
    try:
        if isinstance(ctx_or_interaction, discord.Interaction):
            if ctx_or_interaction.response.is_done():
                await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        else: # Assumes commands.Context
            await ctx_or_interaction.send(embed=embed, ephemeral=ephemeral)
    except discord.errors.InteractionResponded:
         # Interaction might have been deferred or responded to elsewhere
         try:
            await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
         except Exception as e:
            print(f"Error sending followup embed response: {e}")
    except discord.NotFound:
         print(f"Error sending embed response: Interaction or context not found (possibly timed out or deleted).")
    except Exception as e:
        print(f"Error sending embed response: {e}")


# --- ERROR HANDLING ---
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await send_embed_response(ctx, "Permission Denied", f"Sorry {ctx.author.mention}, you don't have permission.", discord.Color.red())
    elif isinstance(error, commands.CheckFailure): pass # Handled by checks
    elif isinstance(error, commands.ChannelNotFound):
        await send_embed_response(ctx, "Error", "Channel not found.", discord.Color.red())
    elif isinstance(error, commands.RoleNotFound):
        await send_embed_response(ctx, "Error", "Role not found.", discord.Color.red())
    elif isinstance(error, commands.MissingRequiredArgument):
        await send_embed_response(ctx, "Error", f"Missing argument: `{error.param.name}`", discord.Color.orange())
    elif isinstance(error, commands.CommandNotFound): pass # Ignore unknown commands
    elif isinstance(error, commands.BadArgument):
         await send_embed_response(ctx, "Error", f"Invalid argument provided. Please check the command usage.", discord.Color.orange())
    else:
        print(f"Unhandled error in command '{ctx.command}': {error}")
        try:
            if ctx.guild: await send_embed_response(ctx, "Error", "An unexpected error occurred.", discord.Color.dark_red())
        except Exception as e: print(f"Failed to send error message: {e}")

# --- HELPER FUNCTIONS ---
async def check_setup(ctx_or_interaction):
    """Checks if the bot is fully set up for the guild."""
    # Add check for guild existence
    if not ctx_or_interaction.guild:
        print("check_setup called without guild context.")
        return False

    settings = bot.get_guild_settings(ctx_or_interaction.guild.id)
    required_settings = ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']
    missing = [s for s in required_settings if not settings.get(s)] # Use .get() for safety

    if missing:
        embed = discord.Embed(
            title="Bot Not Fully Setup!",
            description="An admin needs to run all setup commands first:",
            color=discord.Color.red()
        )
        embed.add_field(name="`/set_panel_channel`", value="Sets channel for panel.", inline=False)
        embed.add_field(name="`/set_ticket_category`", value="Sets category for new tickets.", inline=False)
        embed.add_field(name="`/set_archive_category`", value="Sets category for closed tickets.", inline=False)
        embed.add_field(name="`/set_staff_role`", value="Sets staff role.", inline=False)
        embed.set_footer(text=f"Missing: {', '.join(missing)}")

        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                if not ctx_or_interaction.response.is_done():
                     await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                     await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx_or_interaction.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Error sending setup warning: {e}")
        return False
    return True

# --- NEW: Helper to count user's open tickets ---
def count_user_tickets(guild: discord.Guild, user_id: int, category_id: int, ticket_type: str = None) -> int:
    """Counts open tickets for a user, optionally filtering by type."""
    category = guild.get_channel(category_id)
    if not category or not isinstance(category, discord.CategoryChannel):
        print(f"Warning: Category ID {category_id} not found or invalid for counting tickets.")
        return 0 # Return 0 if category is invalid

    count = 0
    user_id_str = str(user_id)
    for channel in category.text_channels:
        # Check if topic exists and contains user ID before checking type
        if channel.topic and f"ticket-user-{user_id_str}" in channel.topic:
            if ticket_type:
                # Check if the specific type is in the topic
                if f"type-{ticket_type}" in channel.topic:
                    count += 1
            else:
                # Count all tickets if no type specified
                count += 1
    return count

# --- UPDATED: create_ticket_channel adds type to topic ---
async def create_ticket_channel(interaction: discord.Interaction, ticket_type_name: str, settings: dict):
    """Creates a new ticket channel."""
    guild = interaction.guild
    user = interaction.user

    staff_role_id = settings.get('staff_role')
    category_id = settings.get('ticket_category')

    # Add checks for None before proceeding
    if not staff_role_id:
        await send_embed_response(interaction, "Setup Error", "Staff Role not set.", discord.Color.red())
        return None, None
    staff_role = guild.get_role(staff_role_id)
    if not staff_role:
        await send_embed_response(interaction, "Setup Error", "Staff Role not found.", discord.Color.red())
        return None, None

    if not category_id:
        await send_embed_response(interaction, "Setup Error", "Ticket Category not set.", discord.Color.red())
        return None, None
    category = guild.get_channel(category_id)
    if not category or not isinstance(category, discord.CategoryChannel):
        await send_embed_response(interaction, "Setup Error", "Ticket Category not found or invalid.", discord.Color.red())
        return None, None

    # Limit check should ideally happen before calling this, but double-check here just in case
    # This remains as a fallback
    if count_user_tickets(guild, user.id, category.id) > 10: # General hard limit to prevent abuse?
        await send_embed_response(interaction, "Limit Reached", "You have too many open tickets.", discord.Color.orange())
        return None, None


    ticket_num = settings.get('ticket_counter', 1) # Use .get() for safety
    bot.update_guild_setting(guild.id, "ticket_counter", ticket_num + 1)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, view_channel=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, view_channel=True), # Added view_channel
        staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, view_channel=True) # Added view_channel
    }

    try:
        safe_user_name = "".join(c for c in user.name if c.isalnum() or c in ('-', '_')).lower() or "user"
        channel_name = f"{ticket_type_name}-{ticket_num}-{safe_user_name}"[:100] # Max length 100
        topic = f"ticket-user-{user.id} type-{ticket_type_name}" # Added type
        new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites, topic=topic)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I lack permissions to create channels in that category.", discord.Color.red())
        return None, None
    except Exception as e:
        await send_embed_response(interaction, "Error", f"An unknown error occurred while creating the channel: {e}", discord.Color.red())
        return None, None

    return new_channel, staff_role


async def generate_transcript(channel: discord.TextChannel):
    # (generate_transcript remains the same)
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
        if not msg.author.bot:
            messages.append(f"[{timestamp}] {msg.author.display_name} ({msg.author.id}): {msg.content}")
        if msg.attachments:
            for att in msg.attachments:
                messages.append(f"[{timestamp}] [Attachment from {msg.author.display_name}: {att.url}]")

    transcript_content = "\n".join(messages)
    if not transcript_content:
        transcript_content = "No messages were sent in this ticket."

    return io.BytesIO(transcript_content.encode('utf-8'))

# --- APPEAL/MODAL CLASSES ---
# (AppealReasonModal, AppealReviewView, ConfirmAppealView, AppealStartView remain the same)
# ... [These lengthy classes are omitted for brevity but are identical to the previous version] ...
# Make sure to copy them from the previous complete script if needed.

# --- TICKET PANEL VIEW ---
class TicketPanelView(discord.ui.View):
    def __init__(self, bot: TicketBot = None): super().__init__(timeout=None); self.bot = bot
    # (send_appeal_dm remains the same)
    async def send_appeal_dm(self, user: discord.Member, guild: discord.Guild, reason: str):
        embed = create_embed(f"Blacklisted on {guild.name}", f"Reason:\n```{reason}```\nSubmit an appeal?", discord.Color.red())
        view = AppealStartView(bot=self.bot, guild=guild, reason=reason)
        try: view.message = await user.send(embed=embed, view=view)
        except discord.Forbidden: pass
        except Exception as e: print(f"Failed to send appeal DM: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.bot: self.bot = interaction.client
        if not interaction.guild: return False # Should not happen with guild buttons

        settings = self.bot.get_guild_settings(interaction.guild.id) # Use get_guild_settings

        # --- BLACKLIST CHECK ---
        blacklist = settings.get("blacklist", {}); user_id_str = str(interaction.user.id)
        if user_id_str in blacklist:
            reason = blacklist.get(user_id_str, "No reason provided.") # Use .get()
            # Ensure response hasn't already happened
            if not interaction.response.is_done():
                 await send_embed_response(interaction, "Blacklisted", "", discord.Color.red())
            else: # If already deferred (e.g., another check failed first), use followup
                 await interaction.followup.send(embed=create_embed("Blacklisted", "", discord.Color.red()), ephemeral=True)

            await self.send_appeal_dm(interaction.user, interaction.guild, reason)
            return False
        # --- Check setup ---
        if not all(settings.get(key) for key in ['panel_channel', 'ticket_category', 'archive_category', 'staff_role']):
            # Need to handle response state again
            response_message = "System Offline: Not fully configured."
            if not interaction.response.is_done():
                await send_embed_response(interaction, "System Offline", "Not configured.", discord.Color.red())
            else:
                 await interaction.followup.send(embed=create_embed("System Offline", "Not configured.", discord.Color.red()), ephemeral=True)
            return False
        return True


    # --- UPDATED BUTTONS WITH LIMIT CHECKS ---
    @discord.ui.button(label="Standard Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="panel:standard")
    async def standard_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "ticket"
        LIMIT = 3
        category_id = settings.get('ticket_category')
        if not category_id:
            await send_embed_response(interaction, "Error", "Ticket category not set.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"Max {LIMIT} open standard tickets.", discord.Color.orange())
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role: # Ensure staff_role is valid too
            await send_embed_response(interaction, "Ticket Created", f"{channel.mention}", discord.Color.green())
            embed = discord.Embed(title="🎫 Standard Ticket", description=f"Welcome, {interaction.user.mention}!\nPlease describe your issue. {staff_role.mention} will assist.", color=discord.Color.blue())
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=self.bot))

    @discord.ui.button(label="Tryout", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="panel:tryout")
    async def tryout_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "tryout"
        LIMIT = 1
        category_id = settings.get('ticket_category')
        if not category_id:
             await send_embed_response(interaction, "Error", "Ticket category not set.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"Max {LIMIT} open tryout ticket.", discord.Color.orange())
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if not channel or not staff_role: return # Exit if channel/role creation failed

        await send_embed_response(interaction, "Ticket Created", f"{channel.mention}", discord.Color.green())
        try: await channel.send(f"{interaction.user.mention} {staff_role.mention}", delete_after=1)
        except Exception: pass

        try: # --- Tryout Application Logic (No Deletion) ---
            username_embed = create_embed("⚔️ Tryout: Step 1/2", "Reply with Roblox Username.", discord.Color.green()).set_footer(text="5 min.")
            bot_msg_1 = await channel.send(embed=username_embed)
            def check_username(m): return m.channel == channel and m.author == interaction.user
            username_msg = await self.bot.wait_for('message', check=check_username, timeout=300.0)
            roblox_username = username_msg.content

            stats_embed = create_embed("⚔️ Tryout: Step 2/2", f"`{roblox_username}`\nSend stats screenshot.", discord.Color.green()).set_footer(text="5 min, must be image.")
            bot_msg_2 = await channel.send(embed=stats_embed)
            def check_stats(m): return m.channel == channel and m.author == interaction.user and m.attachments and m.attachments[0].content_type and m.attachments[0].content_type.startswith('image')
            stats_msg = await self.bot.wait_for('message', check=check_stats, timeout=300.0)

            stats_screenshot_url = stats_msg.attachments[0].url if stats_msg.attachments else None
            print(f"Stats URL: {stats_screenshot_url}") # Debugging

            success_embed = create_embed("✅ Tryout Complete!", f"{interaction.user.mention}, {staff_role.mention} will review.", discord.Color.brand_green())
            success_embed.add_field(name="Roblox Username", value=roblox_username, inline=False)
            if stats_screenshot_url:
                try: success_embed.set_image(url=stats_screenshot_url)
                except Exception as e: print(f"Error setting image: {e}"); success_embed.add_field(name="Image Error", value="Could not embed.", inline=False)
            else: success_embed.add_field(name="Stats Image", value="Not provided/found.", inline=False)

            await channel.send(embed=success_embed, view=TicketCloseView(bot=self.bot))

        except asyncio.TimeoutError:
            timeout_embed = create_embed("Ticket Closed", "Auto-closed: Inactivity.", discord.Color.red())
            try:
                await channel.send(embed=timeout_embed); await asyncio.sleep(10)
                await channel.delete(reason="Tryout timeout")
            except (discord.NotFound, discord.Forbidden): pass
            except Exception as e: print(f"Error during timeout cleanup: {e}")
        except Exception as e:
            print(f"Error in tryout ({channel.id}): {e}")
            try: await channel.send(embed=create_embed("Error", "Unexpected error.", discord.Color.red()))
            except Exception: pass

    @discord.ui.button(label="Report a User", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="panel:report")
    async def report_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "report"
        LIMIT = 10
        category_id = settings.get('ticket_category')
        if not category_id:
             await send_embed_response(interaction, "Error", "Ticket category not set.", discord.Color.red()); return

        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, category_id, TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"Max {LIMIT} open report tickets.", discord.Color.orange())
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel and staff_role:
            await send_embed_response(interaction, "Ticket Created", f"{channel.mention}", discord.Color.green())
            embed = discord.Embed(title="🚨 User Report", description=f"{interaction.user.mention}, provide user, reason, proof. {staff_role.mention} will assist.", color=discord.Color.red())
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=self.bot))

# --- NEW CLOSE REASON MODAL ---
class CloseReasonModal(discord.ui.Modal, title="Close Ticket Reason"):
    reason_input = discord.ui.TextInput(
        label="Reason for Closing", style=discord.TextStyle.paragraph,
        placeholder="Enter the reason...", required=True, min_length=3
    )

    def __init__(self, bot_instance: TicketBot, target_channel: discord.TextChannel, closer: discord.Member):
        super().__init__()
        self.bot = bot_instance
        self.target_channel = target_channel
        self.closer = closer

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Acknowledge modal submission
        reason = self.reason_input.value
        # Need to instantiate the view to call its method
        view_instance = TicketCloseView(bot=self.bot)
        await view_instance.close_ticket_logic(self.target_channel, self.closer, reason)
        await interaction.followup.send("Closing ticket...", ephemeral=True) # Give feedback

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Error in CloseReasonModal: {error}")
        await interaction.followup.send("An error occurred submitting the reason.", ephemeral=True)

# --- UPDATED TICKET CLOSE VIEW ---
class TicketCloseView(discord.ui.View):
    def __init__(self, bot: TicketBot = None): super().__init__(timeout=None); self.bot = bot

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Opens modal to ask for close reason."""
        if not self.bot: self.bot = interaction.client
        modal = CloseReasonModal(bot_instance=self.bot, target_channel=interaction.channel, closer=interaction.user)
        await interaction.response.send_modal(modal)

    # (delete_ticket logic remains the same)
    @discord.ui.button(label="Delete Ticket", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="ticket:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.bot: self.bot = interaction.client
        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Error", "Staff role not configured.", discord.Color.red()); return
        staff_role = interaction.guild.get_role(staff_role_id)
        if not staff_role: await send_embed_response(interaction, "Error", "Staff role not found.", discord.Color.red()); return
        is_staff = staff_role in interaction.user.roles; is_admin = interaction.user.guild_permissions.administrator
        if not is_staff and not is_admin: await send_embed_response(interaction, "Permission Denied", "", discord.Color.red()); return
        await interaction.response.defer()
        embed = create_embed("🗑️ Ticket Deletion", f"Marked by {interaction.user.mention}.\n**Deleting in 10s.**", discord.Color.dark_red())
        await interaction.followup.send(embed=embed, ephemeral=False)
        await asyncio.sleep(10)
        try: await interaction.channel.delete(reason=f"Deleted by {interaction.user.name}")
        except discord.NotFound: pass
        except discord.Forbidden:
             try: await interaction.followup.send(embed=create_embed("Error", "Lacking delete permissions.", discord.Color.red()), ephemeral=True)
             except Exception: pass
        except Exception as e: print(f"Error deleting ticket: {e}")

    # (close_ticket_logic updated to accept reason)
    async def close_ticket_logic(self, channel: discord.TextChannel, user: discord.Member, reason: str = "No reason provided"):
        guild = channel.guild
        settings = self.bot.get_guild_settings(guild.id)
        archive_category_id = settings.get('archive_category')
        if not archive_category_id:
            await channel.send(embed=create_embed("Error", "Archive category not set.", discord.Color.red())); return
        archive_category = guild.get_channel(archive_category_id)
        if not archive_category or not isinstance(archive_category, discord.CategoryChannel):
            await channel.send(embed=create_embed("Error", "Archive category invalid.", discord.Color.red())); return

        transcript_file = await generate_transcript(channel)
        embed = discord.Embed(title="Ticket Closed", description=f"Closed by: {user.mention}\n**Reason:**\n```{reason}```", color=discord.Color.orange())
        transcript_file.seek(0)
        try:
            await channel.send(embed=embed, file=discord.File(transcript_file, filename=f"{channel.name}-transcript.txt"))
        except discord.HTTPException as e:
            if e.code == 40005: await channel.send(embed=create_embed("Transcript Too Large", "", discord.Color.orange()))
            else: await channel.send(embed=create_embed("Error", f"Upload failed: {e}", discord.Color.red()))
        except Exception as e: await channel.send(embed=create_embed("Error", f"Transcript send error: {e}", discord.Color.red()))

        await asyncio.sleep(5)
        overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), guild.me: discord.PermissionOverwrite(read_messages=True)}
        staff_role_id = settings.get('staff_role')
        if staff_role_id:
             staff_role = guild.get_role(staff_role_id)
             if staff_role: overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
        try:
            closed_name = f"closed-{channel.name[:80]}-{channel.id}"[:100]
            await channel.edit(name=closed_name, category=archive_category, overwrites=overwrites, reason=f"Closed by {user.name}. Reason: {reason}")
            async for msg in channel.history(limit=5):
                if msg.author == self.bot.user and msg.embeds:
                    try: await msg.edit(view=None)
                    except Exception: pass; break
            await channel.send(embed=create_embed("Archived", f"Moved to {archive_category.name}.", discord.Color.greyple()))
        except discord.Forbidden: await channel.send(embed=create_embed("Error", "Lacking permissions.", discord.Color.red()))
        except Exception as e: await channel.send(embed=create_embed("Error", f"Archival error: {e}", discord.Color.red()))

# --- SETUP COMMANDS (Hybrid - Works as '!' and '/') ---

@bot.hybrid_command(name="set_panel_channel", description="Sets channel for the ticket panel.")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="Channel for the ticket panel.")
async def set_panel_channel(ctx: commands.Context, channel: discord.TextChannel):
    bot.update_guild_setting(ctx.guild.id, "panel_channel", channel.id)
    await send_embed_response(ctx, "Setup", f"Panel channel: {channel.mention}", discord.Color.green())

@bot.hybrid_command(name="set_ticket_category", description="Sets category for new tickets.")
@commands.has_permissions(administrator=True)
@app_commands.describe(category="Category for new tickets.")
async def set_ticket_category(ctx: commands.Context, category: discord.CategoryChannel):
    bot.update_guild_setting(ctx.guild.id, "ticket_category", category.id)
    await send_embed_response(ctx, "Setup", f"Ticket category: `{category.name}`", discord.Color.green())

@bot.hybrid_command(name="set_archive_category", description="Sets category for closed tickets.")
@commands.has_permissions(administrator=True)
@app_commands.describe(category="Category for archived tickets.")
async def set_archive_category(ctx: commands.Context, category: discord.CategoryChannel):
    bot.update_guild_setting(ctx.guild.id, "archive_category", category.id)
    await send_embed_response(ctx, "Setup", f"Archive category: `{category.name}`", discord.Color.green())

@bot.hybrid_command(name="set_staff_role", description="Sets the main staff role.")
@commands.has_permissions(administrator=True)
@app_commands.describe(role="Your staff/support role.")
async def set_staff_role(ctx: commands.Context, role: discord.Role):
    bot.update_guild_setting(ctx.guild.id, "staff_role", role.id)
    await send_embed_response(ctx, "Setup", f"Staff role: {role.mention}", discord.Color.green())

@bot.hybrid_command(name="set_escalation_role", description="Sets role for !escalate.")
@commands.has_permissions(administrator=True)
@app_commands.describe(role="Senior staff/manager role.")
async def set_escalation_role(ctx: commands.Context, role: discord.Role):
    bot.update_guild_setting(ctx.guild.id, "escalation_role", role.id)
    await send_embed_response(ctx, "Setup", f"Escalation role: {role.mention}", discord.Color.green())

@bot.hybrid_command(name="set_prefix", description="Sets bot prefix for this server.")
@commands.has_permissions(administrator=True)
@app_commands.describe(prefix="New prefix (max 5 chars).")
async def set_prefix(ctx: commands.Context, prefix: str):
    if len(prefix) > 5:
        await send_embed_response(ctx, "Error", "Prefix max 5 chars.", discord.Color.red())
        return
    bot.update_guild_setting(ctx.guild.id, "prefix", prefix)
    await send_embed_response(ctx, "Setup", f"Prefix: `{prefix}`", discord.Color.green())

@bot.hybrid_command(name="set_appeal_channel", description="Sets channel for blacklist appeals.")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="Channel for appeal reviews.")
async def set_appeal_channel(ctx: commands.Context, channel: discord.TextChannel):
    bot.update_guild_setting(ctx.guild.id, "appeal_channel", channel.id)
    await send_embed_response(ctx, "Setup", f"Appeal channel: {channel.mention}", discord.Color.green())

# --- PANEL CREATION COMMAND ---
@bot.hybrid_command(name="create_panel", description="Sends the ticket panel.")
@commands.has_permissions(administrator=True)
async def create_panel(ctx: commands.Context):
    if not await check_setup(ctx): return
    settings = bot.get_guild_settings(ctx.guild.id); panel_channel_id = settings.get('panel_channel')
    if not panel_channel_id: await send_embed_response(ctx, "Error", "Panel channel not set.", discord.Color.red()); return
    panel_channel = bot.get_channel(panel_channel_id)
    if not panel_channel: await send_embed_response(ctx, "Error", "Panel channel not found.", discord.Color.red()); return
    embed = discord.Embed(title="Support & Tryouts", description="Select an option below.", color=0x2b2d31)
    if ctx.guild.icon: embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.add_field(name="🎫 Standard Ticket", value="General help.", inline=False); embed.add_field(name="⚔️ Tryout", value="Apply to join.", inline=False); embed.add_field(name="🚨 Report a User", value="Report rule breakers.", inline=False)
    embed.set_footer(text=f"{ctx.guild.name}")
    try:
        await panel_channel.send(embed=embed, view=TicketPanelView(bot=bot))
        await send_embed_response(ctx, "Panel Created", f"Sent to {panel_channel.mention}", discord.Color.green())
    except discord.Forbidden: await send_embed_response(ctx, "Error", f"No permission in {panel_channel.mention}.", discord.Color.red())

# --- TICKET MANAGEMENT COMMANDS ---

# --- STAFF CHECKERS ---
def is_staff():
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None: return False
        settings = bot.get_guild_settings(ctx.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(ctx, "Error", "Staff role not set.", discord.Color.red()); return False
        staff_role = ctx.guild.get_role(staff_role_id)
        if not isinstance(ctx.author, discord.Member): return False
        if (staff_role and staff_role in ctx.author.roles) or ctx.author.guild_permissions.administrator: return True
        else: await send_embed_response(ctx, "Permission Denied", "Staff only.", discord.Color.red()); return False
    return commands.check(predicate)

async def is_staff_interaction(interaction: discord.Interaction) -> bool:
    settings = bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
    if not staff_role_id: await send_embed_response(interaction, "Error", "Staff role not set.", discord.Color.red()); return False
    staff_role = interaction.guild.get_role(staff_role_id); is_admin = interaction.user.guild_permissions.administrator
    if (staff_role and staff_role in interaction.user.roles) or is_admin: return True
    else: await send_embed_response(interaction, "Permission Denied", "Staff only.", discord.Color.red()); return False

# --- TICKET CHANNEL CHECK ---
def in_ticket_channel():
    async def predicate(ctx: commands.Context) -> bool:
        settings = bot.get_guild_settings(ctx.guild.id)
        if ctx.channel.category_id == settings.get('ticket_category'): return True # Use .get()
        await send_embed_response(ctx, "Error", "Only in open tickets.", discord.Color.red()); return False
    return commands.check(predicate)

# --- HELP COMMAND ---
# --- HELP COMMAND ---
@bot.command(name="help")
@commands.guild_only() # <<< 4 SPACES
@is_staff() # <<< 4 SPACES
async def help_command(ctx: commands.Context): # <<< 4 SPACES
    """Shows the staff help menu for the bot."""
    settings = bot.get_guild_settings(ctx.guild.id) # <<< 8 SPACES
    prefix = settings.get("prefix", "!") # <<< 8 SPACES

    embed = discord.Embed( # <<< 8 SPACES
        title="🛠️ Staff Help",
        description=f"Prefix: `{prefix}`",
        color=discord.Color.blue()
    )

    embed.add_field( # <<< 8 SPACES
        name="Setup (Admin)",
        value=(
            "`/set_panel_channel`\n"
            "`/set_ticket_category`\n"
            "`/set_archive_category`\n"
            "`/set_staff_role`\n"
            "`/set_escalation_role`\n"
            "`/set_appeal_channel`\n"
            f"`{prefix}setprefix` or `/set_prefix`\n"
            "`/create_panel`"
        ),
        inline=False
    )

    embed.add_field( # <<< 8 SPACES
        name="Tickets (Staff)",
        value=(
            f"`{prefix}close` (Use button)\n"
            f"`{prefix}add @user`\n"
            f"`{prefix}remove @user`\n"
            f"`{prefix}rename <name>`\n"
            f"`{prefix}claim`\n"
            f"`{prefix}unclaim`\n"
            f"`{prefix}escalate`\n"
            f"`{prefix}purge <amount>`\n"
            f"`{prefix}help`"
        ),
        inline=False
    )

    embed.add_field( # <<< 8 SPACES
        name="Moderation (Admin)",
        value=(
            f"`{prefix}blacklist @user <reason>`\n"
            f"`{prefix}unblacklist @user`\n"
            "`/announce <#channel> <message>`\n"
            "`/ticket_stats`"
        ),
        inline=False
    )

    embed.set_footer(text="Use buttons too (Close/Delete/Approve/Reject)") # <<< 8 SPACES
    await ctx.send(embed=embed, ephemeral=True) # <<< 8 SPACES

# --- STANDARD TICKET COMMANDS ---
@bot.command(name="close")
@commands.guild_only() # No staff check needed, button handles it. Modal is now primary method.
async def close(ctx: commands.Context):
    settings = bot.get_guild_settings(ctx.guild.id)
    category_id = settings.get('ticket_category')
    archive_id = settings.get('archive_category')
    if ctx.channel.category_id not in [category_id, archive_id]:
        await send_embed_response(ctx, "Error", "Only in ticket channels.", discord.Color.red()); return
    if ctx.channel.category_id == archive_id:
        await send_embed_response(ctx, "Error", "Already closed.", discord.Color.red()); return
    # Direct users to use the button which opens the modal
    await send_embed_response(ctx, "Use Button", "Please use the 'Close Ticket' button to provide a reason.", discord.Color.blue(), ephemeral=True)


@bot.command(name="add")
@commands.guild_only() # <<< 4 SPACES
@is_staff() # <<< 4 SPACES
@in_ticket_channel() # <<< 4 SPACES
async def add(ctx: commands.Context, user: discord.Member): # <<< 4 SPACES
    """Adds a user to the current ticket channel."""
    await ctx.channel.set_permissions(user, read_messages=True, send_messages=True, view_channel=True) # <<< 8 SPACES
    await send_embed_response(ctx, "User Added", f"{user.mention} added by {ctx.author.mention}.", discord.Color.green(), ephemeral=False) # <<< 8 SPACES

@bot.command(name="remove")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def remove(ctx: commands.Context, user: discord.Member):
    await ctx.channel.set_permissions(user, overwrite=None) # Reset perms
    await send_embed_response(ctx, "User Removed", f"{user.mention} removed by {ctx.author.mention}.", discord.Color.orange(), ephemeral=False)

# --- TICKET TOOL COMMANDS ---
@bot.command(name="rename")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def rename(ctx: commands.Context, *, new_name: str):
    try:
        clean_name = new_name.replace(" ", "-").lower()[:100]
        await ctx.channel.edit(name=clean_name)
        await send_embed_response(ctx, "Renamed", f"Now `{clean_name}`.", discord.Color.blue(), ephemeral=False)
    except Exception as e: await send_embed_response(ctx, "Error", f"Rename failed: {e}", discord.Color.red())

@bot.command(name="escalate")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def escalate(ctx: commands.Context):
    settings = bot.get_guild_settings(ctx.guild.id); esc_role_id = settings.get("escalation_role")
    if not esc_role_id: await send_embed_response(ctx, "Error", "Escalation role not set.", discord.Color.red()); return
    esc_role = ctx.guild.get_role(esc_role_id)
    if not esc_role: await send_embed_response(ctx, "Error", "Escalation role not found.", discord.Color.red()); return
    embed = create_embed("Ticket Escalated", f"🚨 By {ctx.author.mention}. {esc_role.mention} notified.", discord.Color.red())
    await ctx.send(content=esc_role.mention, embed=embed)

@bot.command(name="claim")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def claim(ctx: commands.Context):
    if ctx.channel.topic and "claimed-by" in ctx.channel.topic:
        claimer_id = int(ctx.channel.topic.split("claimed-by-")[-1]); claimer = ctx.guild.get_member(claimer_id) or f"ID: {claimer_id}"
        await send_embed_response(ctx, "Error", f"Claimed by {claimer}.", discord.Color.orange()); return
    base_topic = (ctx.channel.topic or f"ticket-user-{ctx.channel.id}").split(" ")[0]
    if not base_topic.startswith("ticket-user-"): base_topic = f"ticket-user-{ctx.channel.id}" # Fallback
    new_topic = f"{base_topic} claimed-by-{ctx.author.id}"
    try:
        await ctx.channel.edit(topic=new_topic)
        await send_embed_response(ctx, "Ticket Claimed", f"🎫 Claimed by {ctx.author.mention}.", discord.Color.green(), ephemeral=False)
    except Exception as e: await send_embed_response(ctx, "Error", f"Failed claim: {e}", discord.Color.red())

@bot.command(name="unclaim")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def unclaim(ctx: commands.Context):
    if not ctx.channel.topic or "claimed-by" not in ctx.channel.topic: await send_embed_response(ctx, "Error", "Not claimed.", discord.Color.orange()); return
    claimer_id = int(ctx.channel.topic.split("claimed-by-")[-1]); is_admin = ctx.author.guild_permissions.administrator
    if ctx.author.id != claimer_id and not is_admin:
        claimer = ctx.guild.get_member(claimer_id) or f"ID: {claimer_id}"
        await send_embed_response(ctx, "Permission Denied", f"Claimed by {claimer}.", discord.Color.red()); return
    base_topic = ctx.channel.topic.split(" ")[0]
    if not base_topic.startswith("ticket-user-"): base_topic = f"ticket-user-{ctx.channel.id}" # Fallback
    try:
        await ctx.channel.edit(topic=base_topic)
        await send_embed_response(ctx, "Ticket Unclaimed", "🔓 Unclaimed.", discord.Color.blue(), ephemeral=False)
    except Exception as e: await send_embed_response(ctx, "Error", f"Failed unclaim: {e}", discord.Color.red())

# --- CORRECTED PURGE COMMAND ---
@bot.command(name="purge")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def purge(ctx: commands.Context, amount: int):
    """Deletes a specified number of messages in the current ticket channel."""
    if amount <= 0:
        await send_embed_response(ctx, "Error", "Amount must be positive.", discord.Color.orange())
        return
    if amount > 100:
         await send_embed_response(ctx, "Error", "Max 100 messages.", discord.Color.orange())
         return

    try:
        deleted = await ctx.channel.purge(limit=amount + 1) # +1 for command msg
        # Send ephemeral confirmation
        await send_embed_response(ctx, "Purged", f"🗑️ Deleted {len(deleted) - 1} messages.", discord.Color.green(), ephemeral=True)
    except discord.Forbidden:
        await send_embed_response(ctx, "Error", "No permission to delete.", discord.Color.red())
    except Exception as e:
        await send_embed_response(ctx, "Error", f"Purge failed: {e}", discord.Color.red())
# --- END CORRECTED PURGE COMMAND ---


# --- BLACKLIST COMMANDS ---
@bot.hybrid_command(name="blacklist", description="Blacklist a user.")
@commands.has_permissions(administrator=True) @app_commands.describe(user="User.", reason="Reason.")
async def blacklist(ctx: commands.Context, user: discord.Member, *, reason: str):
    settings = bot.get_guild_settings(ctx.guild.id); user_id_str = str(user.id)
    if user.id == ctx.author.id: await send_embed_response(ctx, "Error", "Cannot blacklist self.", discord.Color.orange()); return
    if user.bot: await send_embed_response(ctx, "Error", "Cannot blacklist bots.", discord.Color.orange()); return
    if user_id_str in settings.get("blacklist", {}): await send_embed_response(ctx, "Error", "Already blacklisted.", discord.Color.orange()); return # Use .get()
    # Ensure blacklist key exists before assigning
    if "blacklist" not in settings: settings["blacklist"] = {}
    settings["blacklist"][user_id_str] = reason; save_settings(bot.settings)
    await send_embed_response(ctx, "User Blacklisted", f"{user.mention} blacklisted: `{reason}`.", discord.Color.red())

@bot.hybrid_command(name="unblacklist", description="Unblacklist a user.")
@commands.has_permissions(administrator=True) @app_commands.describe(user="User.")
async def unblacklist(ctx: commands.Context, user: discord.Member):
    settings = bot.get_guild_settings(ctx.guild.id); user_id_str = str(user.id)
    blacklist_dict = settings.get("blacklist", {}) # Use .get()
    if user_id_str not in blacklist_dict: await send_embed_response(ctx, "Error", "Not blacklisted.", discord.Color.orange()); return
    del blacklist_dict[user_id_str]; save_settings(bot.settings) # Modify the dict obtained via .get()
    await send_embed_response(ctx, "User Unblacklisted", f"{user.mention} unblacklisted.", discord.Color.green())

# --- NEW ANNOUNCE COMMAND ---
@bot.hybrid_command(name="announce", description="Send an announcement.")
@is_staff() @app_commands.describe(channel="Channel.", message="Message.")
async def announce(ctx: commands.Context, channel: discord.TextChannel, *, message: str):
    """Sends an announcement embed."""
    embed = discord.Embed(title="📢 Announcement", description=message, color=discord.Color.blue())
    if isinstance(ctx.author, discord.Member): # Check if author is member before accessing display_name
         embed.set_footer(text=f"By {ctx.author.display_name}")
    else: # Fallback if context is weird
         embed.set_footer(text=f"By {ctx.author.name}")

    # Check for attachments in the command message
    attachment_url = None
    if ctx.message and ctx.message.attachments:
        # Use the first attachment's URL
        attachment = ctx.message.attachments[0]
        # Check if it's an image before trying to set it
        if attachment.content_type and attachment.content_type.startswith("image/"):
            attachment_url = attachment.url
            embed.set_image(url=attachment_url)
        else:
             embed.add_field(name="Attachment", value=f"[Link]({attachment.url})", inline=False)


    try:
        await channel.send(embed=embed)
        await send_embed_response(ctx, "Sent", f"To {channel.mention}.", discord.Color.green(), ephemeral=True)
    except discord.Forbidden: await send_embed_response(ctx, "Error", f"No permission in {channel.mention}.", discord.Color.red(), ephemeral=True)
    except Exception as e: await send_embed_response(ctx, "Error", f"Send failed: {e}", discord.Color.red(), ephemeral=True)


# --- SLASH-ONLY COMMAND ---
@bot.tree.command(name="ticket_stats", description="Shows server ticket stats.")
async def ticket_stats(interaction: discord.Interaction):
    if not await is_staff_interaction(interaction): return
    await interaction.response.defer(ephemeral=True)
    settings = bot.get_guild_settings(interaction.guild.id)
    total_created = settings.get("ticket_counter", 1) - 1
    ticket_category_id = settings.get("ticket_category")
    open_tickets = 0
    if ticket_category_id:
        ticket_category = interaction.guild.get_channel(ticket_category_id)
        if ticket_category and isinstance(ticket_category, discord.CategoryChannel): open_tickets = len(ticket_category.text_channels)
        else: await interaction.followup.send(embed=create_embed("Warning", "Ticket category invalid.", discord.Color.orange()), ephemeral=True)
    embed = discord.Embed(title=f"Ticket Stats: {interaction.guild.name}", color=discord.Color.light_grey())
    embed.add_field(name="Total Created", value=f"**{total_created}**", inline=True); embed.add_field(name="Open Tickets", value=f"**{open_tickets}**", inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


# --- RUN THE BOT ---
try:
    bot.run(TOKEN)
except discord.errors.LoginFailure: print("Login Failure: Improper token.")
except discord.errors.PrivilegedIntentsRequired: print("Privileged Intents Required.")
except Exception as e: print(f"Error during bot startup: {e}")