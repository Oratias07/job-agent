import smtplib
import os

password = os.environ.get('GMAIL_APP_PASSWORD')
if not password:
    print("Error: GMAIL_APP_PASSWORD not set")
    exit(1)

print(f"Testing with password: {password[:4]}...{password[-4:]}")

try:
    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login('chamyproject@gmail.com', password)
    print('✓ Login successful')
    server.quit()
except Exception as e:
    print(f'✗ Failed: {e}')
