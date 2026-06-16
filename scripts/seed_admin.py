"""
Admin Account Seeding Script
Creates the admin account 'admin@mbbs.com' in Supabase Auth (if missing)
and elevates their profile row in the local DB to `is_admin = True`.
"""

import sys
import os
import re
import logging

# Ensure the root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import supabase_admin
from app.core.database import SessionLocal
from app.models.database import Profile

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Load credentials from admin_credentials.txt
ADMIN_EMAIL = "admin@mbbs.com"
ADMIN_PASSWORD = "admin@123S"

# Resolve credentials file path (support running from root or scripts/)
cred_path = "admin_credentials.txt"
if not os.path.exists(cred_path):
    parent_cred = os.path.join(os.path.dirname(__file__), "..", "admin_credentials.txt")
    if os.path.exists(parent_cred):
        cred_path = parent_cred

if os.path.exists(cred_path):
    try:
        content = open(cred_path, "r").read()
        email_match = re.search(r"Email:\s*([^\s]+)", content)
        pass_match = re.search(r"Password:\s*([^\s]+)", content)
        if email_match:
            ADMIN_EMAIL = email_match.group(1)
        if pass_match:
            ADMIN_PASSWORD = pass_match.group(1)
        logger.info("Loaded admin credentials from %s", cred_path)
    except Exception as read_err:
        logger.warning("Could not read credentials file, using defaults. Error: %s", read_err)
else:
    logger.warning("Credentials file %s not found, using default fallback credentials.", cred_path)


def seed_admin_user():
    logger.info("Initializing admin seeding protocol...")

    db = SessionLocal()
    try:
        # 1. Check if the profile already exists in DB
        admin_profile = db.query(Profile).filter(Profile.email == ADMIN_EMAIL).first()
        
        if admin_profile:
            logger.info("Admin profile node already exists in database. Verifying admin status...")
            if not admin_profile.is_admin:
                admin_profile.is_admin = True
                db.commit()
                logger.info("Admin privileges elevated successfully.")
            else:
                logger.info("Admin credentials and privileges are already active and nominal.")
            return

        # 2. If profile is missing, create user account in Supabase Auth via admin client
        logger.info("Creating administrative account in Supabase Auth...")
        try:
            auth_response = supabase_admin.auth.admin.create_user({
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
                "email_confirm": True,
                "user_metadata": {"name": "System Admin"}
            })
            
            if not auth_response or not auth_response.user:
                logger.error("Failed to seed admin: Supabase did not return a valid user object.")
                sys.exit(1)
                
            user_id = auth_response.user.id
            logger.info("Auth container registered with UUID: %s", user_id)

            # Wait/verify profile creation (handled by Supabase trigger `handle_new_user`)
            # Query profiles table again to make sure trigger executed
            admin_profile = db.query(Profile).filter(Profile.id == user_id).first()
            if not admin_profile:
                # If trigger didn't fire or ran asynchronously, manually insert
                logger.info("Trigger delayed. Creating profile row manually...")
                admin_profile = Profile(
                    id=user_id,
                    email=ADMIN_EMAIL,
                    name="System Admin",
                    is_admin=True
                )
                db.add(admin_profile)
            else:
                admin_profile.is_admin = True
            
            db.commit()
            logger.info("System Admin successfully registered and elevated to ROOT status.")

        except Exception as auth_exc:
            logger.error("Supabase Auth API creation error: %s", auth_exc)
            sys.exit(1)

    except Exception as exc:
        logger.error("Seeding operation failed: %s", exc)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed_admin_user()
