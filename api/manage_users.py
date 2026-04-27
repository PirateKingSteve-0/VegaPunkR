#!/usr/bin/env python3
"""
User management script for VegaPunkR trading system.

Usage:
    python manage_users.py create --email EMAIL --name NAME --password PASSWORD [OPTIONS]
    python manage_users.py list
    python manage_users.py delete --email EMAIL
    python manage_users.py update --email EMAIL [OPTIONS]

Examples:
    # Create admin user
    python manage_users.py create --email admin@example.com --name "Admin" --password "secret123" --role admin

    # Create regular user with trading preferences
    python manage_users.py create --email trader@example.com --name "Trader" --password "pass123" \\
        --risk-tolerance high --account-size 10000 --max-trade-pct 0.03

    # List all users
    python manage_users.py list

    # Update user
    python manage_users.py update --email trader@example.com --account-size 15000
"""
import sys
import os
import argparse
import bcrypt
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from models import User
from database import SessionLocals
from config import Environment
SessionLocal = SessionLocals[Environment.DEV]


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def create_user(args):
    """Create a new user."""
    db = SessionLocal()
    try:
        # Check if user already exists
        existing = db.query(User).filter(User.email == args.email).first()
        if existing:
            print(f"✗ Error: User with email '{args.email}' already exists")
            return

        # Create user
        user = User(
            email=args.email,
            name=args.name,
            hashed_password=hash_password(args.password),
            role=args.role,
            risk_tolerance=args.risk_tolerance,
            account_size_usd=args.account_size,
            max_trade_percentage=args.max_trade_pct,
            timezone=args.timezone,
            is_active=True
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        print("✓ User created successfully!")
        print(f"  ID: {user.id}")
        print(f"  Email: {user.email}")
        print(f"  Name: {user.name}")
        print(f"  Role: {user.role}")
        print(f"  Risk Tolerance: {user.risk_tolerance}")
        print(f"  Account Size: ${user.account_size_usd:,.2f}")
        print(f"  Max Trade %: {user.max_trade_percentage * 100}%")
        print(f"  Timezone: {user.timezone}")

    except Exception as e:
        print(f"✗ Error creating user: {e}")
        db.rollback()
    finally:
        db.close()


def list_users(args):
    """List all users."""
    db = SessionLocal()
    try:
        users = db.query(User).all()

        if not users:
            print("No users found.")
            return

        print(f"\n{'ID':<5} {'Email':<30} {'Name':<20} {'Role':<10} {'Active':<8} {'Account $':<12}")
        print("-" * 95)

        for user in users:
            status = "Yes" if user.is_active else "No"
            print(f"{user.id:<5} {user.email:<30} {user.name:<20} {user.role:<10} {status:<8} ${user.account_size_usd:>10,.2f}")

        print(f"\nTotal users: {len(users)}")

    finally:
        db.close()


def update_user(args):
    """Update an existing user."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email).first()
        if not user:
            print(f"✗ Error: User with email '{args.email}' not found")
            return

        # Update fields if provided
        if args.name:
            user.name = args.name
        if args.password:
            user.hashed_password = hash_password(args.password)
        if args.role:
            user.role = args.role
        if args.risk_tolerance:
            user.risk_tolerance = args.risk_tolerance
        if args.account_size is not None:
            user.account_size_usd = args.account_size
        if args.max_trade_pct is not None:
            user.max_trade_percentage = args.max_trade_pct
        if args.timezone:
            user.timezone = args.timezone
        if args.active is not None:
            user.is_active = args.active

        user.updated_at = datetime.now()
        db.commit()

        print(f"✓ User '{user.email}' updated successfully!")

    except Exception as e:
        print(f"✗ Error updating user: {e}")
        db.rollback()
    finally:
        db.close()


def delete_user(args):
    """Delete a user."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email).first()
        if not user:
            print(f"✗ Error: User with email '{args.email}' not found")
            return

        if not args.force:
            response = input(f"Are you sure you want to delete user '{user.email}'? (yes/no): ")
            if response.lower() != 'yes':
                print("Aborted.")
                return

        db.delete(user)
        db.commit()
        print(f"✓ User '{args.email}' deleted successfully!")

    except Exception as e:
        print(f"✗ Error deleting user: {e}")
        db.rollback()
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description='User management for VegaPunkR trading system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Create command
    create_parser = subparsers.add_parser('create', help='Create a new user')
    create_parser.add_argument('--email', required=True, help='User email address')
    create_parser.add_argument('--name', required=True, help='User full name')
    create_parser.add_argument('--password', required=True, help='User password')
    create_parser.add_argument('--role', default='user', choices=['user', 'admin'], help='User role (default: user)')
    create_parser.add_argument('--risk-tolerance', default='medium', choices=['low', 'medium', 'high'], help='Risk tolerance (default: medium)')
    create_parser.add_argument('--account-size', type=float, default=0.0, help='Account size in USD (default: 0.0)')
    create_parser.add_argument('--max-trade-pct', type=float, default=0.02, help='Max trade percentage as decimal (default: 0.02 = 2%%)')
    create_parser.add_argument('--timezone', default='UTC', help='User timezone (default: UTC)')

    # List command
    list_parser = subparsers.add_parser('list', help='List all users')

    # Update command
    update_parser = subparsers.add_parser('update', help='Update an existing user')
    update_parser.add_argument('--email', required=True, help='User email address')
    update_parser.add_argument('--name', help='New name')
    update_parser.add_argument('--password', help='New password')
    update_parser.add_argument('--role', choices=['user', 'admin'], help='New role')
    update_parser.add_argument('--risk-tolerance', choices=['low', 'medium', 'high'], help='New risk tolerance')
    update_parser.add_argument('--account-size', type=float, help='New account size in USD')
    update_parser.add_argument('--max-trade-pct', type=float, help='New max trade percentage')
    update_parser.add_argument('--timezone', help='New timezone')
    update_parser.add_argument('--active', type=lambda x: x.lower() == 'true', help='Active status (true/false)')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a user')
    delete_parser.add_argument('--email', required=True, help='User email address')
    delete_parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Route to appropriate function
    if args.command == 'create':
        create_user(args)
    elif args.command == 'list':
        list_users(args)
    elif args.command == 'update':
        update_user(args)
    elif args.command == 'delete':
        delete_user(args)


if __name__ == "__main__":
    main()
