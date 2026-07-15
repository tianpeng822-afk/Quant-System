import smtplib

try:
    server = smtplib.SMTP('smtp.qq.com', 587, timeout=15)
    server.starttls()
    server.login('270215122@qq.com', 'fnheckfxjrjebhfd')
    print("Login 587 successful")
    server.quit()
except Exception as e:
    print(f"Error 587: {e}")

try:
    server = smtplib.SMTP('smtp.qq.com', 25, timeout=15)
    server.login('270215122@qq.com', 'fnheckfxjrjebhfd')
    print("Login 25 successful")
    server.quit()
except Exception as e:
    print(f"Error 25: {e}")

