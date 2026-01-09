"""
CloudVault Email Service
Uses Resend API for sending emails (works on Render free tier)
https://resend.com
"""
import os
import requests


class EmailService:
    """Handles sending emails via Resend API."""
    
    def __init__(self):
        self.api_key = os.getenv("RESEND_API_KEY", "")
        # Use Resend test domain if no custom domain configured
        self.from_email = os.getenv("RESEND_FROM_EMAIL", "CloudVault <onboarding@resend.dev>")
        self.api_url = "https://api.resend.com/emails"
        
        if not self.api_key:
            print("[EMAIL] Warning: RESEND_API_KEY not set. Emails will be logged to console only.")
            self.enabled = False
        else:
            self.enabled = True
            print(f"[EMAIL] Resend API configured with sender: {self.from_email}")
    
    def send_email(self, to_email, subject, html_content, text_content=None):
        """
        Send an email via Resend API.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML body content
            text_content: Plain text fallback (optional)
        
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.enabled:
            # Fallback: log to console
            print(f"\n{'='*50}")
            print(f"[EMAIL LOG] To: {to_email}")
            print(f"[EMAIL LOG] Subject: {subject}")
            print(f"[EMAIL LOG] Content: {(text_content or html_content)[:200]}...")
            print(f"{'='*50}\n")
            return True
        
        # Send email in background thread to not block the request
        import threading
        
        def _send():
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "from": self.from_email,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_content
                }
                
                if text_content:
                    payload["text"] = text_content
                
                response = requests.post(self.api_url, json=payload, headers=headers, timeout=10)
                
                if response.status_code in [200, 201, 202]:
                    print(f"[EMAIL] Sent to {to_email}: {subject}")
                else:
                    print(f"[EMAIL] Failed to send to {to_email}: {response.status_code} - {response.text}")
                    
            except Exception as e:
                print(f"[EMAIL] Error sending to {to_email}: {e}")
        
        # Start background thread
        thread = threading.Thread(target=_send, daemon=True)
        thread.start()
        
        return True  # Return immediately, email sends in background
    
    def send_password_reset(self, to_email, reset_link):
        """Send a password reset email."""
        subject = "Reset Your CloudVault Password"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 500px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ font-size: 24px; font-weight: bold; color: #6366f1; }}
                .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px; 
                          text-decoration: none; border-radius: 8px; font-weight: 500; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #888; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">☁️ CloudVault</div>
                </div>
                <p>Hi there,</p>
                <p>We received a request to reset your password. Click the button below to create a new password:</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" class="button">Reset Password</a>
                </p>
                <p>Or copy and paste this link in your browser:</p>
                <p style="word-break: break-all; font-size: 14px; color: #666;">{reset_link}</p>
                <p>If you didn't request this, you can safely ignore this email.</p>
                <div class="footer">
                    This link expires in 1 hour.<br>
                    &copy; CloudVault - Secure Cloud Storage
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
CloudVault Password Reset

Hi there,

We received a request to reset your password. 
Click this link to create a new password:

{reset_link}

If you didn't request this, you can safely ignore this email.
This link expires in 1 hour.
        """
        
        return self.send_email(to_email, subject, html_content, text_content)
    
    def send_verification_code(self, to_email, code, purpose="verification"):
        """Send a verification code email."""
        subject = f"Your CloudVault Verification Code: {code}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 500px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ font-size: 24px; font-weight: bold; color: #6366f1; }}
                .code {{ font-size: 32px; font-weight: bold; letter-spacing: 8px; text-align: center;
                        background: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #888; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">☁️ CloudVault</div>
                </div>
                <p>Hi there,</p>
                <p>Your {purpose} code is:</p>
                <div class="code">{code}</div>
                <p>Enter this code in CloudVault to continue. This code expires in 10 minutes.</p>
                <p>If you didn't request this, please ignore this email.</p>
                <div class="footer">
                    &copy; CloudVault - Secure Cloud Storage
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
CloudVault Verification Code

Your {purpose} code is: {code}

Enter this code in CloudVault to continue.
This code expires in 10 minutes.

If you didn't request this, please ignore this email.
        """
        
        return self.send_email(to_email, subject, html_content, text_content)


# Global instance
email_service = EmailService()
