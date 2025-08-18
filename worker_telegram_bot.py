#!/usr/bin/env python3
"""
Telegram Bot Worker Service
Runs the Telegram bot in isolation from the main webapp to prevent polling conflicts.
"""

import os
import time
from app import create_app
from app.services.telegram_bot_service import TelegramBotService

def main():
    """Initialize and run the Telegram bot worker"""
    print("🤖 Starting Telegram Bot Worker...")
    
    app = create_app()
    
    with app.app_context():
        try:
            telegram_bot = TelegramBotService()
            telegram_bot.init_app(app)
            print("✅ Telegram bot initialized and polling started")
            
            print("🔄 Bot worker running... Press Ctrl+C to stop")
            while True:
                time.sleep(60)  # Sleep for 1 minute intervals
                print("💓 Bot worker heartbeat - still running")
                
        except KeyboardInterrupt:
            print("\n🛑 Bot worker stopped by user")
        except Exception as e:
            print(f"❌ Bot worker error: {e}")
            raise

if __name__ == "__main__":
    main()
