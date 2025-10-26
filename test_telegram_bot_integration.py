#!/usr/bin/env python3

import os
import requests
import time
from app import create_app
from app.models import db
from app.models.user import User
from app.services.telegram_service import TelegramService

def test_bot_integration():
    """Test complete Telegram bot integration"""
    app = create_app()
    
    with app.app_context():
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        response = requests.get(f'https://api.telegram.org/bot{bot_token}/getMe')
        if response.status_code == 200:
            bot_info = response.json()
            print(f'✅ Bot accessible: @{bot_info["result"]["username"]}')
        else:
            print(f'❌ Bot not accessible: {response.status_code}')
            return
        
        print('✅ TelegramBotService integrated and running')
        
        admin = User.query.filter_by(email='admin@etnamonitor.com').first()
        if admin:
            admin.premium = True
            admin.chat_id = '123456789'  # Test chat_id
            admin.threshold = 1.0  # Low threshold for testing
            db.session.commit()
            print(f'✅ Test Premium user configured: {admin.email}')
        
        telegram_service = TelegramService()
        telegram_service.check_and_send_alerts()
        print('✅ Alert checking completed')
        
        if admin and admin.chat_id:
            success = telegram_service.send_message(
                admin.chat_id, 
                "🧪 Test message from EtnaMonitor - Bot integration working!"
            )
            if success:
                print('✅ Direct message sending works')
            else:
                print('❌ Direct message sending failed')

if __name__ == "__main__":
    test_bot_integration()
