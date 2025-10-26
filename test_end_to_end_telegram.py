#!/usr/bin/env python3

import pandas as pd
import os
from datetime import datetime
from app import create_app
from app.models import db
from app.models.user import User
from app.models.event import Event
from app.services.telegram_service import TelegramService

def test_end_to_end_flow():
    """Test complete end-to-end Premium Telegram notification flow"""
    app = create_app()
    
    with app.app_context():
        data_dir = os.getenv("DATA_DIR", "data")
        curva_file = os.path.join(data_dir, "curva.csv")
        
        test_data = []
        base_time = datetime.now()
        for i in range(10):
            test_data.append({
                'timestamp': base_time.strftime('%Y-%m-%d %H:%M:%S'),
                'value': 3.5 + (i * 0.1)  # Values from 3.5 to 4.4 mV
            })
        
        df = pd.DataFrame(test_data)
        os.makedirs(data_dir, exist_ok=True)
        df.to_csv(curva_file, index=False)
        print(f'✅ Test tremor data created: {len(test_data)} points')
        
        premium_users = User.query.filter(
            User.premium == True,
            User.chat_id.isnot(None),
            User.chat_id > 0
        ).all()
        print(f'✅ Premium users with chat_id: {len(premium_users)}')
        
        telegram_service = TelegramService()
        telegram_service.check_and_send_alerts()
        
        recent_alerts = Event.query.filter_by(event_type='alert').all()
        print(f'✅ Alert events logged: {len(recent_alerts)}')
        
        for alert in recent_alerts:
            print(f'   - {alert.timestamp}: {alert.message}')

if __name__ == "__main__":
    test_end_to_end_flow()
