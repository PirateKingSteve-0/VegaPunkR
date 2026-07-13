#!/usr/bin/env python3
"""
Update account size after depositing funds.
Run this after depositing money to Tradier.
"""

import sys
sys.path.insert(0, '/Users/pirateking/Github/VegaPunkR/api')

from database import get_db
from models import User

def update_account_size(email: str, new_size: float):
    """Update user account size"""
    db = next(get_db())

    user = db.query(User).filter(User.email == email).first()

    if not user:
        print(f"❌ User {email} not found")
        return

    old_size = user.account_size_usd
    user.account_size_usd = new_size

    db.commit()

    print(f"✅ Updated account size for {email}")
    print(f"   Old: ${old_size:,.2f}")
    print(f"   New: ${new_size:,.2f}")
    print()
    print(f"Risk Calculations:")
    print(f"├─ Max $ per trade (2%): ${(new_size * 0.02):,.2f}")
    print(f"├─ Daily loss limit (5%): ${(new_size * 0.05):,.2f}")
    print(f"└─ After 3 losing trades: ${(new_size - (new_size * 0.02 * 3)):,.2f} remaining")

if __name__ == "__main__":
    # Update to $1,000
    update_account_size("kingofpirates92@gmail.com", 1000.00)
