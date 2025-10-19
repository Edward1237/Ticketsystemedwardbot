# ticket_bot.py (or bot.py)

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
    with open(SETTINGS_FILE, 'r') as f:
        return json.load(f)

def save_settings(settings):
    """Saves settings to settings.json"""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)

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
intents.message_content = True  # <-- REQUIRED FOR READING MESSAGES

# --- DYNAMIC PREFIX FUNCTION ---
def get_prefix(bot_instance, message):
    """Gets the prefix for the specific guild."""
    if not message.guild:
        return commands.when_mentioned_or("!")(bot_instance, message) # Default '!' in DMs

    settings = bot_instance.settings.get(str(message.guild.id), {})
    prefix = settings.get("prefix", "!") # Default '!'
    return commands.when_mentioned_or(prefix)(bot_instance, message)

# Bot definition (using the new get_prefix function)
class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, intents=intents)
        self.settings = load_settings()
        self.persistent_views_added = False
        
        # Remove the default help command
        self.remove_command('help')

    async def setup_hook(self):
        # This is run after the bot logs in but before it's fully connected.
        if not self.persistent_views_added:
            self.add_view(TicketPanelView(bot=self))
            self.add_view(TicketCloseView(bot=self))
            self.add_view(AppealReviewView(bot=self)) # <-- For appeal buttons
            self.persistent_views_added = True
        
        # Sync slash commands
        await self.tree.sync()

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('Bot is ready and listening for commands.')
        print('------')

    def get_guild_settings(self, guild_id):
        """Gets settings for a specific guild, creating if not found."""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.settings:
            self.settings[guild_id_str] = {
                "panel_channel": None,
                "ticket_category": None,
                "archive_category": None,
                "staff_role": None,
                "escalation_role": None,
                "appeal_channel": None, 
                "prefix": "!",
                "ticket_counter": 1,
                "blacklist": {}
            }
            save_settings(self.settings)
        
        # --- Auto-update old configs ---
        if "blacklist" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["blacklist"] = {}
            save_settings(self.settings)
        if "appeal_channel" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["appeal_channel"] = None
            save_settings(self.settings)
        # --- End auto-update ---
            
        return self.settings[guild_id_str]

    def update_guild_setting(self, guild_id, key, value):
        """Updates a specific setting for a guild."""
        settings = self.get_guild_settings(guild_id)
        settings[key] = value
        save_settings(self.settings)

bot = TicketBot()

# --- GLOBAL CHECK TO IGNORE DMS ---
@bot.check
async def globally_ignore_dms(ctx):
    """Silently ignores any command sent in a DM."""
    return ctx.guild is not None

# --- HELPER FUNCTIONS ---

def create_embed(title: str, description: str, color: discord.Color) -> discord.Embed:
    """Helper function to create a standard embed."""
    return discord.Embed(title=title, description=description, color=color)

async def send_embed_response(ctx_or_interaction, title: str, description: str, color: discord.Color, ephemeral: bool = True):
    """Helper function to send embed responses for both interactions and context."""
    embed = create_embed(title, description, color)
    if isinstance(ctx_or_interaction, discord.Interaction):
        if ctx_or_interaction.response.is_done():
            await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else: # Assumes commands.Context
        await ctx_or_interaction.send(embed=embed, ephemeral=ephemeral)

# --- ERROR HANDLING ---

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await send_embed_response(ctx, "Permission Denied", f"Sorry {ctx.author.mention}, you don't have permission to use that command.", discord.Color.red())
    elif isinstance(error, commands.CheckFailure):
        pass # Already handled by the is_staff() check
    elif isinstance(error, commands.ChannelNotFound):
        await send_embed_response(ctx, "Error", "Channel not found. Please make sure you spelled it correctly and I can see it.", discord.Color.red())
    elif isinstance(error, commands.RoleNotFound):
        await send_embed_response(ctx, "Error", "Role not found. Please make sure you spelled it correctly.", discord.Color.red())
    elif isinstance(error, commands.MissingRequiredArgument):
        await send_embed_response(ctx, "Error", f"You missed an argument: `{error.param.name}`", discord.Color.orange())
    else:
        print(f"Unhandled error: {error}")
        try:
            if ctx.guild:
                await send_embed_response(ctx, "An Unexpected Error Occurred", "An unexpected error occurred. Please contact an admin.", discord.Color.dark_red())
        except Exception as e:
            print(f"Failed to send error message to context: {e}")

# --- HELPER FUNCTIONS ---

async def check_setup(ctx_or_interaction):
    """Checks if the bot is fully set up for the guild."""
    settings = bot.get_guild_settings(ctx_or_interaction.guild.id)
    if not all([settings['panel_channel'], settings['ticket_category'], settings['archive_category'], settings['staff_role']]):
        embed = discord.Embed(
            title="Bot Not Fully Setup!",
            description="An admin needs to run all setup commands first:",
            color=discord.Color.red()
        )
        embed.add_field(name="`/set_panel_channel`", value="Sets the channel for the ticket panel.", inline=False)
        embed.add_field(name="`/set_ticket_category`", value="Sets the category for new tickets.", inline=False)
        embed.add_field(name="`/set_archive_category`", value="Sets the category for closed tickets.", inline=False)
        embed.add_field(name="`/set_staff_role`", value="Sets the role to ping for new tickets.", inline=False)
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_interaction.send(embed=embed, ephemeral=True)
        return False
    return True

async def create_ticket_channel(interaction: discord.Interaction, ticket_type_name: str, settings: dict):
    """Creates a new ticket channel."""
    guild = interaction.guild
    user = interaction.user
    
    staff_role = guild.get_role(settings['staff_role'])
    if not staff_role:
        await send_embed_response(interaction, "Setup Error", "The configured Staff Role could not be found. Please have an admin reset it.", discord.Color.red())
        return None, None

    category = guild.get_channel(settings['ticket_category'])
    if not category:
        await send_embed_response(interaction, "Setup Error", "The configured Ticket Category could not be found. Please have an admin reset it.", discord.Color.red())
        return None, None
        
    for channel in category.text_channels:
        if channel.topic and channel.topic.startswith(f"ticket-user-{user.id}"):
            await send_embed_response(interaction, "Ticket Exists", f"You already have an open ticket: {channel.mention}", discord.Color.orange())
            return None, None

    ticket_num = settings['ticket_counter']
    bot.update_guild_setting(guild.id, "ticket_counter", ticket_num + 1)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
    }

    try:
        channel_name = f"{ticket_type_name}-{ticket_num}-{user.name}"
        topic = f"ticket-user-{user.id}" # Base topic
        new_channel = await category.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=topic
        )
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I don't have permissions to create channels in that category.", discord.Color.red())
        return None, None
    except Exception as e:
        await send_embed_response(interaction, "Error", f"An unknown error occurred: {e}", discord.Color.red())
        return None, None

    return new_channel, staff_role


async def generate_transcript(channel: discord.TextChannel):
    """Generates a text file transcript of the channel's messages."""
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        if not msg.author.bot:
            messages.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author.display_name}: {msg.content}")
        if msg.attachments:
            for att in msg.attachments:
                messages.append(f"[Attachment: {att.url}]")

    transcript_content = "\n".join(messages)
    if not transcript_content:
        transcript_content = "No messages were sent in this ticket."

    return io.BytesIO(transcript_content.encode('utf-8'))

# --- APPEAL REASON MODAL CLASS ---
class AppealReasonModal(discord.ui.Modal):
    def __init__(self, bot: TicketBot, action: str, original_message: discord.Message, guild: discord.Guild, appealing_user_id: int):
        super().__init__(title=f"Appeal {action} Reason")
        
        self.bot = bot
        self.action = action # "Approve" or "Reject"
        self.original_message = original_message
        self.guild = guild
        self.appealing_user_id = appealing_user_id

        self.reason_input = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            placeholder=f"Enter the reason for {action.lower()}ing this appeal...",
            required=True,
            min_length=3
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handles the modal submission."""
        await interaction.response.defer(ephemeral=True)
        
        staff_member = interaction.user
        reason = self.reason_input.value
        
        try:
            appealing_user = await self.bot.fetch_user(self.appealing_user_id)
        except discord.NotFound:
            await interaction.followup.send(embed=create_embed("Error", "Could not find the user to notify.", discord.Color.red()))
            return

        # 1. Update the original appeal embed
        original_embed = self.original_message.embeds[0]
        new_embed = original_embed.copy()
        
        # 2. DM the user and perform the action
        if self.action == "Approve":
            title = "✅ Appeal Approved"
            color = discord.Color.green()
            
            # DM the user
            try:
                dm_embed = create_embed(title, f"Your blacklist appeal for **{self.guild.name}** was approved.\n\n**Reason:**\n```{reason}```", color)
                await appealing_user.send(embed=dm_embed)
            except discord.Forbidden:
                pass # User has DMs disabled

            # Unblacklist the user
            settings = self.bot.get_guild_settings(self.guild.id)
            user_id_str = str(self.appealing_user_id)
            if user_id_str in settings["blacklist"]:
                del settings["blacklist"][user_id_str]
                save_settings(self.bot.settings)
                
        else: # Reject
            title = "❌ Appeal Rejected"
            color = discord.Color.red()
            
            # DM the user
            try:
                dm_embed = create_embed(title, f"Your blacklist appeal for **{self.guild.name}** was rejected.\n\n**Reason:**\n```{reason}```", color)
                await appealing_user.send(embed=dm_embed)
            except discord.Forbidden:
                pass # User has DMs disabled

        # 3. Edit the staff message
        new_embed.title = f"[{self.action.upper()}D] Blacklist Appeal"
        new_embed.color = color
        new_embed.add_field(name=f"{title} by {staff_member.display_name}", value=f"```{reason}```", inline=False)
        
        await self.original_message.edit(embed=new_embed, view=None) # view=None removes the buttons
        
        await interaction.followup.send(embed=create_embed("Success", f"The appeal has been {self.action.lower()}d.", color))

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Error in AppealReasonModal: {error}")
        await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

# --- PERSISTENT APPEAL REVIEW VIEW FOR STAFF ---
class AppealReviewView(discord.ui.View):
    """The Approve/Reject buttons for the appeal in the staff channel."""
    def __init__(self, bot: TicketBot = None):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.bot:
            self.bot = interaction.client
            
        # Permission check: Only staff can use these buttons
        settings = self.bot.get_guild_settings(interaction.guild.id)
        staff_role_id = settings.get('staff_role')
        if not staff_role_id:
            await send_embed_response(interaction, "Error", "Staff role is not configured.", discord.Color.red())
            return False
            
        staff_role = interaction.guild.get_role(staff_role_id)
        is_admin = interaction.user.guild_permissions.administrator
        
        if (staff_role and staff_role in interaction.user.roles) or is_admin:
            return True
        else:
            await send_embed_response(interaction, "Permission Denied", "You must be staff to review appeals.", discord.Color.red())
            return False

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅", custom_id="appeal:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text:
            await send_embed_response(interaction, "Error", "Could not find the User ID in the appeal message. This is an old appeal.", discord.Color.red())
            return
            
        user_id = int(embed.footer.text.split(": ")[1])
        modal = AppealReasonModal(
            bot=self.bot,
            action="Approve",
            original_message=interaction.message,
            guild=interaction.guild,
            appealing_user_id=user_id
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id="appeal:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text:
            await send_embed_response(interaction, "Error", "Could not find the User ID in the appeal message. This is an old appeal.", discord.Color.red())
            return
            
        user_id = int(embed.footer.text.split(": ")[1])
        modal = AppealReasonModal(
            bot=self.bot,
            action="Reject",
            original_message=interaction.message,
            guild=interaction.guild,
            appealing_user_id=user_id
        )
        await interaction.response.send_modal(modal)


# --- APPEAL CLASSES (non-persistent, sent to DMs) ---

class ConfirmAppealView(discord.ui.View):
    """The final Submit/Cancel view for an appeal."""
    def __init__(self, bot: TicketBot, answers: dict, guild: discord.Guild, appeal_channel: discord.TextChannel, messages_to_delete: list):
        super().__init__(timeout=600) # 10 mins to decide
        self.bot = bot
        self.answers = answers
        self.guild = guild
        self.appeal_channel = appeal_channel
        self.messages_to_delete = messages_to_delete
        self.message = None # To store the message object

    async def cleanup(self, interaction: discord.Interaction):
        """Deletes all messages from the appeal process."""
        self.stop()
        for msg in self.messages_to_delete:
            try:
                await msg.delete()
            except discord.NotFound:
                pass # Message was already deleted
            except discord.Forbidden:
                pass # Can't delete, oh well
        try:
            # Check if interaction is None (for on_timeout)
            if interaction:
                await interaction.message.delete() # Delete the confirmation message itself
            elif self.message:
                await self.message.delete()
        except:
            pass

    @discord.ui.button(label="Submit Appeal", style=discord.ButtonStyle.success, emoji="✅")
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        # Create the final appeal embed to send to the staff
        embed = create_embed(
            "New Blacklist Appeal",
            f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n**Server:** {self.guild.name}",
            discord.Color.gold()
        )
        embed.add_field(name="1. Why do you believe you were unfairly blacklisted?", value=f"```{self.answers['q1']}```", inline=False)
        embed.add_field(name="2. Why should you be unblacklisted?", value=f"```{self.answers['q2']}```", inline=False)
        embed.add_field(name="3. Supporting Proof", value=self.answers['proof'], inline=False)
        
        embed.set_footer(text=f"User ID: {interaction.user.id}") # Add user ID for the buttons
        view_to_send = AppealReviewView(bot=self.bot)

        try:
            await self.appeal_channel.send(embed=embed, view=view_to_send) # Attach the new view
            await interaction.followup.send(embed=create_embed("✅ Appeal Submitted", "Your appeal has been sent to the staff. You will be contacted if it is approved.", discord.Color.green()))
        except discord.Forbidden:
            await interaction.followup.send(embed=create_embed("Error", "I could not submit your appeal to the staff channel. Please contact an admin.", discord.Color.red()))

        await self.cleanup(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.followup.send(embed=create_embed("Appeal Cancelled", "Your appeal has been cancelled.", discord.Color.red()))
        await self.cleanup(interaction)

    async def on_timeout(self):
        # This function is called if the user doesn't click Submit/Cancel in time
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(embed=create_embed("Appeal Timed Out", "You took too long to respond. The appeal has been cancelled.", discord.Color.red()), view=self)
        except:
            pass
        await self.cleanup(None)

class AppealStartView(discord.ui.View):
    """The first view sent to a blacklisted user's DMs."""
    def __init__(self, bot: TicketBot, guild: discord.Guild, reason: str):
        super().__init__(timeout=1800) # 30 mins to start the appeal
        self.bot = bot
        self.guild = guild
        self.reason = reason
        self.message = None # To store the message object for on_timeout

    async def ask_question(self, channel, user, embed, min_length=0, check_proof=False, timeout=600.0):
        """Helper to ask a question and wait for a valid response."""
        bot_msgs = [await channel.send(embed=embed)]
        
        while True:
            try:
                msg = await self.bot.wait_for('message', check=lambda m: m.author == user and m.channel == channel, timeout=timeout)
            except asyncio.TimeoutError:
                await channel.send(embed=create_embed("Timed Out", "You took too long to respond. Your appeal has been cancelled.", discord.Color.red()))
                return bot_msgs, None # Signal a timeout
            
            if check_proof: # For proof, any message or attachment is fine
                return bot_msgs, msg
            
            if len(msg.content) < min_length:
                bot_msgs.append(await channel.send(embed=create_embed("Answer Too Short", f"Your answer must be at least {min_length} characters.", discord.Color.orange())))
                continue
            
            return bot_msgs, msg # Valid answer

    @discord.ui.button(label="Start Appeal", style=discord.ButtonStyle.primary, emoji="📜")
    async def start_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() # Acknowledge the button click

        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        
        channel = interaction.channel # This is the DM channel
        user = interaction.user
        messages_to_delete = [interaction.message] # Start tracking messages to delete
        answers = {}
        
        settings = self.bot.get_guild_settings(self.guild.id)
        appeal_channel_id = settings.get("appeal_channel")
        if not appeal_channel_id:
            await channel.send(embed=create_embed("Error", f"The appeal system for **{self.guild.name}** is not configured. Please contact an admin.", discord.Color.red()))
            return
            
        appeal_channel = self.guild.get_channel(appeal_channel_id)
        if not appeal_channel:
            await channel.send(embed=create_embed("Error", f"The appeal system for **{self.guild.name}** is broken (channel not found). Please contact an admin.", discord.Color.red()))
            return

        # --- Question 1 ---
        q1_embed = create_embed("Appeal: Question 1/3", "Why do you believe you were unfairly blacklisted?", discord.Color.blue())
        q1_embed.set_footer(text="You have 10 minutes to reply. Must be at least 3 characters.")
        bot_msgs, answer1_msg = await self.ask_question(channel, user, q1_embed, 3)
        messages_to_delete.extend(bot_msgs)
        if not answer1_msg: return # Timeout
        messages_to_delete.append(answer1_msg)
        answers['q1'] = answer1_msg.content

        # --- Question 2 ---
        q2_embed = create_embed("Appeal: Question 2/3", "Why should you be unblacklisted?", discord.Color.blue())
        q2_embed.set_footer(text="You have 10 minutes to reply. Must be at least 3 characters.")
        bot_msgs, answer2_msg = await self.ask_question(channel, user, q2_embed, 3)
        messages_to_delete.extend(bot_msgs)
        if not answer2_msg: return # Timeout
        messages_to_delete.append(answer2_msg)
        answers['q2'] = answer2_msg.content

        # --- Question 3 (Proof) ---
        q3_embed = create_embed("Appeal: Question 3/3", "Please provide any supporting proof (screenshots, messages, etc.). If you have no proof, just type `N/A`.", discord.Color.blue())
        q3_embed.set_footer(text="You have 10 minutes to reply.")
        bot_msgs, answer3_msg = await self.ask_question(channel, user, q3_embed, 0, check_proof=True)
        messages_to_delete.extend(bot_msgs)
        if not answer3_msg: return # Timeout
        messages_to_delete.append(answer3_msg)
        
        proof_content = answer3_msg.content if answer3_msg.content else "N/A"
        if answer3_msg.attachments:
            proof_content = answer3_msg.attachments[0].url
        answers['proof'] = proof_content

        # --- Confirmation Step ---
        summary_embed = create_embed("Confirm Your Appeal", "Please review your answers below. Press Submit to send this to the staff.", discord.Color.green())
        summary_embed.add_field(name="1. Unfairly Blacklisted?", value=f"```{answers['q1']}```", inline=False)
        summary_embed.add_field(name="2. Why Unblacklist?", value=f"```{answers['q2']}```", inline=False)
        summary_embed.add_field(name="3. Proof", value=answers['proof'], inline=False)
        
        confirm_view = ConfirmAppealView(self.bot, answers, self.guild, appeal_channel, messages_to_delete)
        confirm_view.message = await channel.send(embed=summary_embed, view=confirm_view)

    async def on_timeout(self):
        # This is for if they don't click "Start Appeal" in 30 mins
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass # Failed to edit, probably DMs closed


# --- VIEWS (BUTTONS) ---

class TicketPanelView(discord.ui.View):
    """The persistent view with buttons to create tickets."""
    def __init__(self, bot: TicketBot = None):
        super().__init__(timeout=None)
        self.bot = bot

    async def send_appeal_dm(self, user: discord.Member, guild: discord.Guild, reason: str):
        """Sends the initial appeal DM to a blacklisted user."""
        embed = create_embed(
            f"You are Blacklisted on {guild.name}",
            f"You are blacklisted from creating tickets in **{guild.name}**.\n\n**Reason:**\n```{reason}```\n\nIf you believe this is a mistake, you may submit an appeal.",
            discord.Color.red()
        )
        view = AppealStartView(bot=self.bot, guild=guild, reason=reason)
        try:
            view.message = await user.send(embed=embed, view=view)
        except discord.Forbidden:
            pass # User has DMs disabled, can't send appeal.
        except Exception as e:
            print(f"Failed to send appeal DM: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.bot:
            self.bot = interaction.client
            
        settings = self.bot.get_guild_settings(interaction.guild.id)
        
        # --- BLACKLIST CHECK ---
        blacklist = settings.get("blacklist", {})
        user_id_str = str(interaction.user.id)
        
        if user_id_str in blacklist:
            reason = blacklist[user_id_str]
            await send_embed_response(interaction, "Blacklisted", "You are blacklisted from creating tickets.", discord.Color.red())
            # Send the appeal DM
            await self.send_appeal_dm(interaction.user, interaction.guild, reason)
            return False # Stop the interaction
        # --- END BLACKLIST CHECK ---
            
        # Check if setup is complete
        if not all([settings['panel_channel'], settings['ticket_category'], settings['archive_category'], settings['staff_role']]):
            await send_embed_response(interaction, "System Offline", "The ticket system is not fully configured. Please contact an admin.", discord.Color.red())
            return False
        return True

    @discord.ui.button(label="Standard Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="panel:standard")
    async def standard_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True) # Acknowledge interaction
        
        settings = self.bot.get_guild_settings(interaction.guild.id)
        channel, staff_role = await create_ticket_channel(interaction, "ticket", settings)

        if channel:
            await send_embed_response(interaction, "Ticket Created", f"Your ticket has been created: {channel.mention}", discord.Color.green())
            
            embed = discord.Embed(
                title="🎫 Standard Ticket",
                description=f"Welcome, {interaction.user.mention}!\n\nPlease describe your issue or question in detail. A {staff_role.mention} will be with you shortly.",
                color=discord.Color.blue()
            )
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=self.bot))

    # --- UPDATED TRYOUT FUNCTION ---
    @discord.ui.button(label="Tryout", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="panel:tryout")
    async def tryout_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True) # Acknowledge interaction
        
        settings = self.bot.get_guild_settings(interaction.guild.id)
        channel, staff_role = await create_ticket_channel(interaction, "tryout", settings)
        
        if not channel: return

        await send_embed_response(interaction, "Ticket Created", f"Your tryout ticket has been created: {channel.mention}", discord.Color.green())
        await channel.send(f"{interaction.user.mention} {staff_role.mention}", delete_after=1) # Initial ping
        
        try:
            # 1. Ask for Roblox Username
            username_embed = discord.Embed(
                title="⚔️ Tryout Application - Step 1/2",
                description="Please reply to this message with your **Roblox Username**.",
                color=discord.Color.green()
            ).set_footer(text="You have 5 minutes to reply.")
            
            bot_msg_1 = await channel.send(embed=username_embed)

            def check_username(m): return m.channel == channel and m.author == interaction.user
            username_msg = await self.bot.wait_for('message', check=check_username, timeout=300.0) # 5 minutes
            roblox_username = username_msg.content

            # 2. Ask for Stats Screenshot
            stats_embed = discord.Embed(
                title="⚔️ Tryout Application - Step 2/2",
                description=f"Great, `{roblox_username}`.\n\nNow, please send a **screenshot of your stats** from Roblox.",
                color=discord.Color.green()
            ).set_footer(text="You have 5 minutes to reply. The message MUST contain an image.")
            
            bot_msg_2 = await channel.send(embed=stats_embed)

            def check_stats(m): return m.channel == channel and m.author == interaction.user and len(m.attachments) > 0 and m.attachments[0].content_type.startswith('image')
            stats_msg = await self.bot.wait_for('message', check=check_stats, timeout=300.0) # 5 minutes
            stats_screenshot_url = stats_msg.attachments[0].url

            # 3. Delete all the prompt messages
            try:
                await bot_msg_1.delete()
                await username_msg.delete()
                await bot_msg_2.delete()
                await stats_msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass # A message was already deleted or we lack perms, just continue

            # 4. Send the final, clean embed
            success_embed = discord.Embed(
                title="✅ Tryout Application Complete!",
                description=f"Thank you, {interaction.user.mention}! A {staff_role.mention} will review your application soon.",
                color=discord.Color.brand_green()
            )
            success_embed.add_field(name="Roblox Username", value=roblox_username, inline=False)
            success_embed.set_image(url=stats_screenshot_url)
            
            # This "starts" the ticket by adding the management buttons
            await channel.send(embed=success_embed, view=TicketCloseView(bot=self.bot))

        except asyncio.TimeoutError:
            timeout_embed = discord.Embed(
                title="Ticket Closed",
                description="This ticket has been automatically closed due to inactivity.",
                color=discord.Color.red()
            )
            await channel.send(embed=timeout_embed)
            await asyncio.sleep(10)
            await channel.delete(reason="Tryout ticket timeout")
    # --- END UPDATED TRYOUT FUNCTION ---

    @discord.ui.button(label="Report a User", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="panel:report")
    async def report_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True) # Acknowledge interaction
        
        settings = self.bot.get_guild_settings(interaction.guild.id)
        channel, staff_role = await create_ticket_channel(interaction, "report", settings)

        if channel:
            await send_embed_response(interaction, "Ticket Created", f"Your report has been created: {channel.mention}", discord.Color.green())
            
            embed = discord.Embed(
                title="🚨 User Report",
                description=f"Welcome, {interaction.user.mention}!\n\nPlease provide the name of the user you are reporting, the reason, and any proof (screenshots/videos).",
                color=discord.Color.red()
            )
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=self.bot))


class TicketCloseView(discord.ui.View):
    """A persistent view with ticket management buttons."""
    def __init__(self, bot: TicketBot = None):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Closes and archives the ticket with a transcript."""
        await interaction.response.defer() # Acknowledge
        if not self.bot: self.bot = interaction.client
        await self.close_ticket_logic(interaction.channel, interaction.user)

    @discord.ui.button(label="Delete Ticket", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="ticket:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Permanently deletes the ticket. Only usable by staff."""
        if not self.bot: self.bot = interaction.client
        settings = self.bot.get_guild_settings(interaction.guild.id)
        staff_role_id = settings.get('staff_role')

        if not staff_role_id:
            await send_embed_response(interaction, "Error", "Staff role is not configured for this server.", discord.Color.red())
            return
        staff_role = interaction.guild.get_role(staff_role_id)
        if not staff_role:
            await send_embed_response(interaction, "Error", "The configured staff role was not found. Please ask an admin to reset it.", discord.Color.red())
            return

        is_staff = staff_role in interaction.user.roles
        is_admin = interaction.user.guild_permissions.administrator

        if not is_staff and not is_admin:
            await send_embed_response(interaction, "Permission Denied", "You do not have permission to permanently delete this ticket.", discord.Color.red())
            return
        
        await interaction.response.defer()
        embed = discord.Embed(
            title="🗑️ Ticket Deletion",
            description=f"This ticket has been marked for deletion by {interaction.user.mention}.\n\n**This channel will be permanently deleted in 10 seconds.**",
            color=discord.Color.dark_red()
        )
        await interaction.followup.send(embed=embed)
        await asyncio.sleep(10)
        await interaction.channel.delete(reason=f"Ticket permanently deleted by {interaction.user.name}")


    async def close_ticket_logic(self, channel: discord.TextChannel, user: discord.Member):
        """The logic to close and archive a ticket."""
        guild = channel.guild
        settings = self.bot.get_guild_settings(guild.id)
        archive_category = guild.get_channel(settings['archive_category'])

        if not archive_category:
            await channel.send(embed=create_embed("Error", "Archive category not found. Please contact an admin.", discord.Color.red()))
            return

        transcript_file = await generate_transcript(channel)
        embed = discord.Embed(
            title="Ticket Closed",
            description=f"This ticket was closed by {user.mention}.",
            color=discord.Color.orange()
        )
        transcript_file.seek(0) # Reset file pointer
        await channel.send(
            embed=embed,
            file=discord.File(transcript_file, filename=f"{channel.name}-transcript.txt")
        )

        await asyncio.sleep(5)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        staff_role = guild.get_role(settings['staff_role'])
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False) # Read-only

        try:
            await channel.edit(
                name=f"closed-{channel.name}",
                category=archive_category,
                overwrites=overwrites,
                reason=f"Ticket closed by {user.name}"
            )
            
            async for msg in channel.history(limit=5):
                if msg.author == self.bot.user and msg.embeds:
                    await msg.edit(view=None)
                    break
            
            await channel.send(embed=create_embed("Archived", f"**Channel moved to {archive_category.name} and archived.**", discord.Color.greyple()))
        
        except discord.Forbidden:
            await channel.send(embed=create_embed("Error", "I lack permissions to move this channel to the archive.", discord.Color.red()))
        except Exception as e:
            await channel.send(embed=create_embed("Error", f"An error occurred during archival: {e}", discord.Color.red()))


# --- SETUP COMMANDS (Hybrid - Works as '!' and '/') ---

@bot.hybrid_command(name="set_panel_channel", description="Sets the channel for the ticket creation panel.")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="The text channel where the ticket panel will be sent.")
async def set_panel_channel(ctx: commands.Context, channel: discord.TextChannel):
    bot.update_guild_setting(ctx.guild.id, "panel_channel", channel.id)
    await send_embed_response(ctx, "Setup Success", f"✅ Ticket panel channel set to {channel.mention}", discord.Color.green())

@bot.hybrid_command(name="set_ticket_category", description="Sets the category where new tickets will be created.")
@commands.has_permissions(administrator=True)
@app_commands.describe(category="The category for new tickets.")
async def set_ticket_category(ctx: commands.Context, category: discord.CategoryChannel):
    bot.update_guild_setting(ctx.guild.id, "ticket_category", category.id)
    await send_embed_response(ctx, "Setup Success", f"✅ Ticket category set to `{category.name}`", discord.Color.green())

@bot.hybrid_command(name="set_archive_category", description="Sets the category where closed tickets will be moved.")
@commands.has_permissions(administrator=True)
@app_commands.describe(category="The category for archived tickets.")
async def set_archive_category(ctx: commands.Context, category: discord.CategoryChannel):
    bot.update_guild_setting(ctx.guild.id, "archive_category", category.id)
    await send_embed_response(ctx, "Setup Success", f"✅ Archive category set to `{category.name}`", discord.Color.green())

@bot.hybrid_command(name="set_staff_role", description="Sets the staff role to ping and give access to tickets.")
@commands.has_permissions(administrator=True)
@app_commands.describe(role="The role for your staff/support team.")
async def set_staff_role(ctx: commands.Context, role: discord.Role):
    bot.update_guild_setting(ctx.guild.id, "staff_role", role.id)
    await send_embed_response(ctx, "Setup Success", f"✅ Staff role set to {role.mention}", discord.Color.green())

@bot.hybrid_command(name="set_escalation_role", description="Sets the role to ping when a ticket is escalated.")
@commands.has_permissions(administrator=True)
@app_commands.describe(role="The senior staff/manager role.")
async def set_escalation_role(ctx: commands.Context, role: discord.Role):
    bot.update_guild_setting(ctx.guild.id, "escalation_role", role.id)
    await send_embed_response(ctx, "Setup Success", f"✅ Escalation role set to {role.mention}", discord.Color.green())

@bot.hybrid_command(name="set_prefix", description="Sets the custom prefix for this server.")
@commands.has_permissions(administrator=True)
@app_commands.describe(prefix="The new prefix (e.g., '>')")
async def set_prefix(ctx: commands.Context, prefix: str):
    bot.update_guild_setting(ctx.guild.id, "prefix", prefix)
    await send_embed_response(ctx, "Setup Success", f"✅ My prefix for this server is now `{prefix}`", discord.Color.green())

@bot.hybrid_command(name="set_appeal_channel", description="Sets the channel where blacklist appeals are sent.")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="The text channel for staff to review appeals.")
async def set_appeal_channel(ctx: commands.Context, channel: discord.TextChannel):
    bot.update_guild_setting(ctx.guild.id, "appeal_channel", channel.id)
    await send_embed_response(ctx, "Setup Success", f"✅ Blacklist appeal channel set to {channel.mention}", discord.Color.green())


# --- PANEL CREATION COMMAND ---
@bot.hybrid_command(name="create_panel", description="Sends the ticket creation panel to the set channel.")
@commands.has_permissions(administrator=True)
async def create_panel(ctx: commands.Context):
    if not await check_setup(ctx):
        return

    settings = bot.get_guild_settings(ctx.guild.id)
    panel_channel = bot.get_channel(settings['panel_channel'])
    
    if not panel_channel:
        await send_embed_response(ctx, "Error", "Panel channel not found. Please set it again with `/set_panel_channel`.", discord.Color.red())
        return

    embed = discord.Embed(
        title="Support & Tryouts",
        description="Welcome to the support panel. Please select an option below to create a ticket.",
        color=0x2b2d31 # Dark embed color
    )
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.add_field(name="🎫 Standard Ticket", value="For general questions, help, or issues.", inline=False)
    embed.add_field(name="⚔️ Tryout", value="Apply to join the clan. You will be asked for your info.", inline=False)
    embed.add_field(name="🚨 Report a User", value="Report a user for breaking rules. Please have proof ready.", inline=False)
    embed.set_footer(text=f"{ctx.guild.name} Support System")

    try:
        await panel_channel.send(embed=embed, view=TicketPanelView(bot=bot))
        await send_embed_response(ctx, "Panel Created", f"✅ Ticket panel sent to {panel_channel.mention}", discord.Color.green())
    except discord.Forbidden:
        await send_embed_response(ctx, "Error", f"I don't have permission to send messages in {panel_channel.mention}.", discord.Color.red())

# --- TICKET MANAGEMENT COMMANDS ---

# --- STAFF CHECKER ---
def is_staff():
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None: return False
        settings = bot.get_guild_settings(ctx.guild.id)
        staff_role_id = settings.get('staff_role')
        if not staff_role_id:
            await send_embed_response(ctx, "Error", "Staff role is not configured.", discord.Color.red())
            return False
        
        staff_role = ctx.guild.get_role(staff_role_id)
        if staff_role in ctx.author.roles or ctx.author.guild_permissions.administrator:
            return True
        else:
            await send_embed_response(ctx, "Permission Denied", "This command is for staff only.", discord.Color.red())
            return False
    return commands.check(predicate)

# --- SLASH COMMAND STAFF CHECKER ---
async def is_staff_interaction(interaction: discord.Interaction) -> bool:
    """A check for pure-slash commands."""
    settings = bot.get_guild_settings(interaction.guild.id)
    staff_role_id = settings.get('staff_role')
    
    if not staff_role_id:
        await send_embed_response(interaction, "Error", "Staff role is not configured.", discord.Color.red())
        return False
        
    staff_role = interaction.guild.get_role(staff_role_id)
    is_admin = interaction.user.guild_permissions.administrator
    
    if (staff_role and staff_role in interaction.user.roles) or is_admin:
        return True
    else:
        await send_embed_response(interaction, "Permission Denied", "This command is for staff only.", discord.Color.red())
        return False

# --- TICKET CHANNEL CHECK ---
def in_ticket_channel():
    async def predicate(ctx: commands.Context) -> bool:
        settings = bot.get_guild_settings(ctx.guild.id)
        if ctx.channel.category_id == settings['ticket_category']:
            return True
        await send_embed_response(ctx, "Error", "This command can only be used in an open ticket channel.", discord.Color.red())
        return False
    return commands.check(predicate)

# --- HELP COMMAND ---
@bot.command(name="help")
@commands.guild_only()
@is_staff()
async def help_command(ctx: commands.Context):
    """Shows the staff help menu for the bot."""
    settings = bot.get_guild_settings(ctx.guild.id)
    prefix = settings.get("prefix", "!")
    
    embed = discord.Embed(
        title="🛠️ Staff Help Menu",
        description=f"Here are all available commands. My prefix is `{prefix}`",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="Setup Commands (Admin Only)",
        value=(
            "`/set_panel_channel`\n"
            "`/set_ticket_category`\n"
            "`/set_archive_category`\n"
            "`/set_staff_role`\n"
            "`/set_escalation_role`\n"
            "`/set_appeal_channel` (NEW)\n"
            f"`{prefix}setprefix` or `/set_prefix`\n"
            "`/create_panel`"
        ),
        inline=False
    )
    
    embed.add_field(
        name="Ticket Commands (Staff Only)",
        value=(
            f"`{prefix}close` - Closes and archives the current ticket.\n"
            f"`{prefix}add @user` - Adds a user to the current ticket.\n"
            f"`{prefix}remove @user` - Removes a user from the current ticket.\n"
            f"`{prefix}rename <new-name>` - Renames the ticket channel.\n"
            f"`{prefix}claim` - Claim this ticket.\n"
            f"`{prefix}unclaim` - Release this ticket.\n"
            f"`{prefix}escalate` - Ping the senior staff role for help.\n"
            f"`{prefix}help` - Shows this help message."
        ),
        inline=False
    )
    
    embed.add_field(
        name="Moderation Commands (Admin Only)",
        value=(
            f"`{prefix}blacklist @user <reason>` (NEW)\n"
            f"`{prefix}unblacklist @user` (NEW)\n"
            "`/ticket_stats` - Shows server ticket stats."
        ),
        inline=False
    )
    
    embed.set_footer(text="Buttons: Staff can also use the 'Delete Ticket' button.")
    await ctx.send(embed=embed, ephemeral=True)

# --- STANDARD TICKET COMMANDS ---
@bot.command(name="close")
@commands.guild_only()
async def close(ctx: commands.Context):
    """Closes the current ticket channel."""
    settings = bot.get_guild_settings(ctx.guild.id)
    
    if ctx.channel.category_id not in [settings['ticket_category'], settings['archive_category']]:
        await send_embed_response(ctx, "Error", "This command can only be used in a ticket channel.", discord.Color.red())
        return

    if ctx.channel.category_id == settings['archive_category']:
        await send_embed_response(ctx, "Error", "This ticket is already closed.", discord.Color.red())
        return

    close_view = TicketCloseView(bot=bot)
    await ctx.send(embed=create_embed("Closing", f"Closing ticket as requested by {ctx.author.mention}...", discord.Color.orange()), ephemeral=False)
    await close_view.close_ticket_logic(ctx.channel, ctx.author)

@bot.command(name="add")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def add(ctx: commands.Context, user: discord.Member):
    """Adds a user to the current ticket channel."""
    await ctx.channel.set_permissions(user, read_messages=True, send_messages=True)
    await send_embed_response(ctx, "User Added", f"{user.mention} has been added to this ticket by {ctx.author.mention}.", discord.Color.green(), ephemeral=False)

@bot.command(name="remove")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def remove(ctx: commands.Context, user: discord.Member):
    """Removes a user from the current ticket channel."""
    await ctx.channel.set_permissions(user, read_messages=False, send_messages=False)
    await send_embed_response(ctx, "User Removed", f"{user.mention} has been removed from this ticket by {ctx.author.mention}.", discord.Color.orange(), ephemeral=False)

# --- TICKET TOOL COMMANDS ---

@bot.command(name="rename")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def rename(ctx: commands.Context, *, new_name: str):
    """Renames the current ticket channel."""
    try:
        await ctx.channel.edit(name=new_name)
        await send_embed_response(ctx, "Channel Renamed", f"Channel name changed to `{new_name}` by {ctx.author.mention}.", discord.Color.blue(), ephemeral=False)
    except Exception as e:
        await send_embed_response(ctx, "Error", f"Failed to rename channel: {e}", discord.Color.red())

@bot.command(name="escalate")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def escalate(ctx: commands.Context):
    """Escalates the ticket to senior staff."""
    settings = bot.get_guild_settings(ctx.guild.id)
    escalation_role_id = settings.get("escalation_role")
    
    if not escalation_role_id:
        await send_embed_response(ctx, "Error", "No escalation role has been set up by an admin.", discord.Color.red())
        return
        
    escalation_role = ctx.guild.get_role(escalation_role_id)
    if not escalation_role:
        await send_embed_response(ctx, "Error", "The configured escalation role could not be found. Please notify an admin.", discord.Color.red())
        return
        
    embed = create_embed("Ticket Escalated", f"🚨 This ticket has been escalated by {ctx.author.mention}. {escalation_role.mention} has been notified.", discord.Color.red())
    await ctx.send(content=escalation_role.mention, embed=embed)

@bot.command(name="claim")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def claim(ctx: commands.Context):
    """Claims the ticket."""
    if ctx.channel.topic and "claimed-by" in ctx.channel.topic:
        await send_embed_response(ctx, "Error", "This ticket has already been claimed.", discord.Color.orange())
        return
        
    base_topic = (ctx.channel.topic or "").split(" ")[0] # Get the 'ticket-user-ID' part
    new_topic = f"{base_topic} claimed-by-{ctx.author.id}"
    
    try:
        await ctx.channel.edit(topic=new_topic)
        await send_embed_response(ctx, "Ticket Claimed", f"🎫 This ticket has been claimed by {ctx.author.mention}. They will be your primary point of contact.", discord.Color.green(), ephemeral=False)
    except Exception as e:
        await send_embed_response(ctx, "Error", f"Failed to claim ticket: {e}", discord.Color.red())

@bot.command(name="unclaim")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def unclaim(ctx: commands.Context):
    """Unclaims the ticket."""
    if not ctx.channel.topic or "claimed-by" not in ctx.channel.topic:
        await send_embed_response(ctx, "Error", "This ticket is not currently claimed.", discord.Color.orange())
        return

    claimer_id = int(ctx.channel.topic.split("claimed-by-")[-1])
    is_admin = ctx.author.guild_permissions.administrator
    
    if ctx.author.id != claimer_id and not is_admin:
        claimer = ctx.guild.get_member(claimer_id) or f"User (ID: {claimer_id})"
        await send_embed_response(ctx, "Permission Denied", f"Only the user who claimed this ticket ({claimer}) or an Administrator can unclaim it.", discord.Color.red())
        return

    base_topic = ctx.channel.topic.split(" ")[0] # Get the 'ticket-user-ID' part
    
    try:
        await ctx.channel.edit(topic=base_topic)
        await send_embed_response(ctx, "Ticket Unclaimed", f"🔓 This ticket is now unclaimed and open for any staff member to assist.", discord.Color.blue(), ephemeral=False)
    except Exception as e:
        await send_embed_response(ctx, "Error", f"Failed to unclaim ticket: {e}", discord.Color.red())

# --- BLACKLIST COMMANDS ---

@bot.hybrid_command(name="blacklist", description="Blacklist a user from creating tickets.")
@commands.has_permissions(administrator=True)
@app_commands.describe(user="The user to blacklist.", reason="The reason for the blacklist.")
async def blacklist(ctx: commands.Context, user: discord.Member, *, reason: str):
    settings = bot.get_guild_settings(ctx.guild.id)
    user_id_str = str(user.id)
    
    if user_id_str in settings["blacklist"]:
        await send_embed_response(ctx, "Error", f"{user.mention} is already blacklisted.", discord.Color.orange())
        return
        
    settings["blacklist"][user_id_str] = reason
    save_settings(bot.settings) # We save the whole settings object because we're modifying a dict
    
    await send_embed_response(ctx, "User Blacklisted", f"{user.mention} has been blacklisted for: `{reason}`.", discord.Color.red())

@bot.hybrid_command(name="unblacklist", description="Unblacklist a user.")
@commands.has_permissions(administrator=True)
@app_commands.describe(user="The user to unblacklist.")
async def unblacklist(ctx: commands.Context, user: discord.Member):
    settings = bot.get_guild_settings(ctx.guild.id)
    user_id_str = str(user.id)
    
    if user_id_str not in settings["blacklist"]:
        await send_embed_response(ctx, "Error", f"{user.mention} is not blacklisted.", discord.Color.orange())
        return
        
    del settings["blacklist"][user_id_str]
    save_settings(bot.settings)
    
    await send_embed_response(ctx, "User Unblacklisted", f"{user.mention} has been unblacklisted and can now create tickets.", discord.Color.green())


# --- SLASH-ONLY COMMAND ---
@bot.tree.command(name="ticket_stats", description="Shows statistics about tickets on this server.")
async def ticket_stats(interaction: discord.Interaction):
    """Shows stats about tickets on the server."""
    if not await is_staff_interaction(interaction):
        return
        
    await interaction.response.defer(ephemeral=True)
    
    settings = bot.get_guild_settings(interaction.guild.id)
    
    total_created = settings.get("ticket_counter", 1) - 1
    
    ticket_category_id = settings.get("ticket_category")
    open_tickets = 0
    if ticket_category_id:
        ticket_category = interaction.guild.get_channel(ticket_category_id)
        if ticket_category:
            open_tickets = len(ticket_category.text_channels)
            
    embed = discord.Embed(
        title=f"Ticket Stats for {interaction.guild.name}",
        color=discord.Color.light_grey()
    )
    embed.add_field(name="Total Tickets Created", value=f"**{total_created}**", inline=True)
    embed.add_field(name="Open Tickets", value=f"**{open_tickets}**", inline=True)
    
    await interaction.followup.send(embed=embed)


# --- RUN THE BOT ---
bot.run(TOKEN)