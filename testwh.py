# Create test_whatsapp.py
import pywhatkit as kit

# Try sending a message to YOUR number (replace with your number)
phone = "+8925640238"  # Your 10-digit number with +91
message = "Test from MechTrack!"

try:
    kit.sendwhatmsg_instantly(
        phone_no=phone,
        message=message,
        wait_time=15,  # Wait 15 seconds
        tab_close=True,
        close_time=3
    )
    print("✅ Message sent! Check your WhatsApp")
except Exception as e:
    print(f"❌ Failed: {e}")
    print("\nMake sure:")
    print("1. You're logged into web.whatsapp.com in your browser")
    print("2. The browser tab stays open")
    print("3. Your phone has active internet connection")