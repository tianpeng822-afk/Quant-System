import smtplib

try:
    server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15)
    server.login('270215122@qq.com', 'fnheckfxjrjebhfd')
    print("Login successful")
    server.quit()
except Exception as e:
    print(f"Error: {e}")
