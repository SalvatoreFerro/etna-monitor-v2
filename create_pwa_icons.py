#!/usr/bin/env python3
"""
Create PWA icons for EtnaMonitor using PIL
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size, filename):
    """Create a volcano-themed icon with EtnaMonitor branding"""
    img = Image.new('RGB', (size, size), '#007aff')
    draw = ImageDraw.Draw(img)
    
    volcano_color = '#ff4444'
    base_width = int(size * 0.6)
    height = int(size * 0.5)
    
    points = [
        (size//2 - base_width//2, size - size//4),  # bottom left
        (size//2 + base_width//2, size - size//4),  # bottom right
        (size//2, size//2 - height//2)             # top
    ]
    
    draw.polygon(points, fill=volcano_color)
    
    smoke_color = '#ffffff'
    for i in range(3):
        x = size//2 + (i-1) * size//8
        y = size//2 - height//2 - size//8
        draw.ellipse([x-size//20, y-size//20, x+size//20, y+size//20], fill=smoke_color)
    
    filepath = f'app/static/icons/{filename}'
    img.save(filepath)
    print(f'✅ Created {filename} ({size}x{size})')
    return filepath

def create_screenshots():
    """Create PWA screenshot placeholders"""
    os.makedirs('app/static/screenshots', exist_ok=True)
    
    desktop = Image.new('RGB', (1280, 720), '#0a0a0a')
    draw = ImageDraw.Draw(desktop)
    
    draw.rectangle([50, 50, 1230, 150], fill='#1a1a1a', outline='#333333')
    draw.text((70, 80), 'EtnaMonitor Dashboard', fill='#ffffff')
    draw.text((70, 110), 'Real-time volcanic tremor monitoring', fill='#888888')
    
    draw.rectangle([50, 200, 800, 600], fill='#1a1a1a', outline='#333333')
    draw.text((70, 220), 'Etna Volcanic Tremor Chart', fill='#ffffff')
    
    for i in range(10):
        y = 300 + i * 20
        draw.line([70, y, 780, y + (i % 3) * 10], fill='#00ff00', width=2)
    
    desktop.save('app/static/screenshots/desktop.png')
    print('✅ Created desktop.png (1280x720)')
    
    mobile = Image.new('RGB', (390, 844), '#0a0a0a')
    draw = ImageDraw.Draw(mobile)
    
    draw.rectangle([20, 50, 370, 120], fill='#1a1a1a', outline='#333333')
    draw.text((30, 70), 'EtnaMonitor', fill='#ffffff')
    
    draw.rectangle([20, 150, 370, 400], fill='#1a1a1a', outline='#333333')
    draw.text((30, 170), 'Tremor Chart', fill='#ffffff')
    
    mobile.save('app/static/screenshots/mobile.png')
    print('✅ Created mobile.png (390x844)')

def main():
    """Create all PWA assets"""
    os.makedirs('app/static/icons', exist_ok=True)
    
    print("🌋 Creating PWA icons for EtnaMonitor...")
    
    create_icon(192, 'icon-192.png')
    create_icon(512, 'icon-512.png')
    create_icon(16, 'favicon-16x16.png')
    create_icon(32, 'favicon-32x32.png')
    create_icon(180, 'apple-touch-icon.png')
    create_icon(96, 'dashboard-96.png')
    
    print("\n📱 Creating PWA screenshots...")
    create_screenshots()
    
    print("\n🎉 All PWA assets created successfully!")
    print("Icons created in: app/static/icons/")
    print("Screenshots created in: app/static/screenshots/")

if __name__ == '__main__':
    main()
