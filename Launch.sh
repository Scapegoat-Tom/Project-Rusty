#!/bin/bash
printf "\e]0;Project Rusty\a"
# Navigate to the bot directory
cd /home/nas/destiny2-discord-bot/ || { echo "Directory not found"; exit 1; }

# Activate the virtual environment
source venv/bin/activate || { echo "Failed to activate virtual environment"; exit 1; }
echo "VIRTUAL_ENV=$VIRTUAL_ENV"
which python
python --version

# Set the bot token
export BOT_TOKEN=" "

# Start the bot with auto-restart on file changes
watchmedo auto-restart --pattern="*.py" --recursive python3 bot.py
