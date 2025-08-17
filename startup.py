#!/usr/bin/env python3
"""
Startup script for Render deployment that ensures database migration runs
"""
import os
import sys
import subprocess

def run_migration():
    """Run database migration"""
    try:
        print("🔄 Running database migration...")
        result = subprocess.run([sys.executable, 'migrations/add_billing_fields.py'], 
                              capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            print("✅ Database migration completed successfully")
            print(result.stdout)
        else:
            print("⚠️  Migration had issues but continuing...")
            print(result.stdout)
            print(result.stderr)
    except Exception as e:
        print(f"⚠️  Migration failed: {e}")
        print("Continuing with app startup...")

def main():
    """Main startup function"""
    print("🚀 Starting EtnaMonitor deployment...")
    
    data_dir = os.getenv('DATA_DIR', '/var/tmp')
    log_dir = os.getenv('LOG_DIR', '/var/tmp/log')
    
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    print(f"📁 Data directories created: {data_dir}, {log_dir}")
    
    run_migration()
    
    port = os.environ.get('PORT', '5000')
    workers = os.environ.get('WEB_CONCURRENCY', '2')
    
    cmd = [
        'gunicorn',
        '-w', str(workers),
        '-k', 'gthread',
        '-b', f'0.0.0.0:{port}',
        'app:app'
    ]
    
    print(f"🌐 Starting gunicorn: {' '.join(cmd)}")
    os.execvp('gunicorn', cmd)

if __name__ == '__main__':
    main()
