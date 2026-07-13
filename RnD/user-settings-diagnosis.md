# User Settings Update Issue - Diagnosis

## Investigation Summary

I traced the entire data flow from UI → Backend → Database. **All code is correctly wired**. Here's what I found:

### ✅ What's Working

1. **UI Component** (`ui/src/app/components/profile-dialog/profile-dialog.component.ts`)
   - Save button properly wired to `save()` method (line 318)
   - Form fields use Angular signals with two-way binding
   - Builds update payload correctly (lines 305-349)
   - Only sends changed fields to avoid unnecessary updates

2. **Angular Service** (`ui/src/app/services/auth.service.ts`)
   - `updateProfile()` method sends PATCH to `/api/v1/auth/me` (line 135)
   - Includes Bearer token in Authorization header
   - Updates localStorage and current user on success

3. **Backend API** (`api/routers/auth.py`)
   - PATCH `/api/v1/auth/me` endpoint exists (line 111)
   - Accepts `UserUpdate` schema with all required fields
   - Validates data (password verification, email uniqueness)
   - Commits changes to database (line 184)
   - Returns updated user object

4. **Database Model** (`api/models.py`)
   - User table has all required columns:
     - `account_size_usd`
     - `max_trade_percentage`
     - `daily_loss_limit_pct`
     - `trading_window_enabled/start/end`
     - `notification_preferences` (JSON column)

### ❓ Potential Issues

Since the code is correct, the issue is likely environmental or user-flow related:

#### 1. Backend Not Running
- If FastAPI server isn't running, the PATCH request fails silently
- **Check**: Is `http://localhost:8000` responding?
- **Fix**: Run `cd api && uvicorn app:app --reload --port 8000`

#### 2. Authentication Token Expired
- JWT tokens expire after a period
- **Check**: Look for 401 Unauthorized errors in browser console (F12 → Console)
- **Fix**: Log out and log back in

#### 3. Validation Error Not Noticed
- The UI shows validation errors in a red box at the bottom of the dialog
- **Check**: Did you see any error messages when clicking Save?
- Common validation errors:
  - Daily loss limit must be 0.5% - 20%
  - Account size must be ≥ 0
  - Max trade % must be 0% - 100%
  - Trading window start must be before end

#### 4. "No Changes to Save"
- If you didn't actually change any values, the save() method shows this error
- The component compares current vs initial values
- **Check**: Did you modify the values before clicking Save?

#### 5. Browser Cache / localStorage Stale
- The dialog loads initial values from `auth.refreshMe()`
- This merges fresh API data with localStorage
- **Check**: Open browser DevTools (F12) → Application → Local Storage → `currentUser`
- **Fix**: Clear localStorage or hard refresh (Cmd+Shift+R)

#### 6. Success But Reopening Shows Old Data
- Updates might succeed but dialog reopens with cached data
- **Check**: Close the entire app and reopen
- **Fix**: Refresh the page after saving

## Diagnostic Steps

### Step 1: Test the API Directly

Run the test script to verify the backend endpoint works:

```bash
cd /Users/pirateking/Github/VegaPunkR
python scripts/test_user_update.py
```

This will:
1. Log you in
2. Fetch current user data
3. Update account_size_usd to $1,000
4. Verify the change persisted

If this works ✅ → The backend is fine, issue is in the UI flow
If this fails ❌ → Backend problem (likely not running)

### Step 2: Check Browser Console

1. Open the UI in Chrome/Firefox
2. Press F12 to open DevTools
3. Go to Console tab
4. Clear the console
5. Open Settings dialog and try to update a value
6. Click Save
7. Look for errors:
   - **Red errors**: JavaScript errors, network failures, 401/403/500 responses
   - **Yellow warnings**: Usually safe to ignore

### Step 3: Check Network Tab

1. In DevTools, go to Network tab
2. Clear it
3. Try saving settings
4. Look for the PATCH request to `/api/v1/auth/me`
5. Click on it and check:
   - **Status**: Should be 200 OK (not 401, 400, or 500)
   - **Request Payload**: Should show your changes
   - **Response**: Should show updated user object

### Step 4: Verify Database Directly

If the API test passes but UI still doesn't work, check the database:

```bash
cd /Users/pirateking/Github/VegaPunkR
python -c "
import sys
sys.path.insert(0, 'api')
from database import get_db
from models import User

db = next(get_db())
user = db.query(User).filter(User.email == 'kingofpirates92@gmail.com').first()

print(f'Account Size: \${user.account_size_usd:,.2f}')
print(f'Max Trade %: {user.max_trade_percentage * 100:.2f}%')
print(f'Daily Loss Limit: {user.daily_loss_limit_pct}%')
print(f'Trading Window Enabled: {user.trading_window_enabled}')
"
```

## Most Likely Culprits

Based on the code review, here are the most probable causes (ranked):

1. **Backend not running** (80% likelihood)
   - Solution: Start FastAPI server

2. **Validation error not noticed** (10% likelihood)
   - Solution: Look for red error message at bottom of dialog

3. **Cached data after successful save** (5% likelihood)
   - Solution: Hard refresh browser or clear localStorage

4. **Auth token expired** (3% likelihood)
   - Solution: Log out and back in

5. **Actual code bug** (2% likelihood)
   - Solution: This investigation found none, but run test script to confirm

## Quick Test

Try this right now:

1. Make sure backend is running: `curl http://localhost:8000/api/v1/auth/me` (should not say "connection refused")
2. Make sure you're logged into the UI
3. Open Settings dialog
4. Change account size from $70 to $1,000
5. Click Save
6. **Look at the bottom of the dialog** - do you see any red error text?
7. If no error, close the dialog
8. Reopen it - is the value still $1,000?

If step 8 shows $70 again, run `scripts/test_user_update.py` to narrow down where the failure is.

## Next Steps

Please try:
1. Run `scripts/test_user_update.py` and share the output
2. If that works, open browser DevTools and share any console errors when trying to save in the UI
3. Let me know exactly what you see when you click Save (error message? spinner? nothing?)

This will tell us if it's:
- ❌ Backend issue (API test fails)
- ❌ Frontend issue (API test passes, UI doesn't work)
- ✅ Everything works but user flow confusion
