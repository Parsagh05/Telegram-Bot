#!/bin/bash

# Navigate to your bot directory (Update this path based on your hosting)
cd /home/myfirstb/mybot

# Check if bot.py is already running
if pgrep -f "python3 bot.py" > /dev/null
then
    echo "Bot is already running."
else
    echo "Bot not found. Starting bot..."
    # Run the bot in the background and save logs to bot_log.txt
    nohup python3 bot.py > bot_log.txt 2>&1 &
fi