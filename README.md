#TrekManager V2 — Setup & Run Guide

A full-stack Trekking Management Application:
Flask (REST API) + SQLAlchemy/SQLite (database) + Redis (cache) +
Celery (background jobs) + Vue 3 via CDN + Bootstrap 5.

This app needs 5 terminals running at the same time: Redis, the Flask
API, a Celery worker, Celery Beat, and the frontend's static file server.


0. Prerequisites


Python 3.10+
Redis installed locally


Install Redis if you don't have it:

bash# macOS
brew install redis

# Ubuntu / Debian
sudo apt install redis-server

# or via Docker, if you'd rather not install it directly
docker run -p 6379:6379 redis


1. Backend setup (one-time)

bashcd backend
python -m venv venv

Activate the virtual environment:

bash# macOS / Linux
source venv/bin/activate

# Windows (Command Prompt)
venv\Scripts\activate.bat

# Windows (PowerShell)
venv\Scripts\Activate.ps1

Install dependencies:

bashpip install -r requirements.txt


⚠️ Important: every command below that mentions python app.py or
celery ... must be run from inside the backend/ folder, with the
venv active. Running them from the project root will fail with
ModuleNotFoundError because app.py / tasks.py live in backend/.




2. Start everything (4 backend terminals)

Open 4 separate terminal tabs/windows. In each one, cd into backend/
and activate the venv first (source venv/bin/activate), then run one of
these:

Terminal 1 — Redis:

bashredis-server

Terminal 2 — Flask API:

bashpython app.py

On the very first run, this creates all SQLite tables and seeds one Admin
account:


Email: admin@trekmanager.com
Password: Admin@123


The API is now live at http://localhost:5000.

Terminal 3 — Celery worker:

bashcelery -A tasks:celery_app worker --loglevel=info --pool=solo

(--pool=solo is the simplest, most reliable option on macOS/Windows. On
Linux you can drop it and use Celery's default pool if you prefer.)

Terminal 4 — Celery Beat (the scheduler):

bashcelery -A tasks:celery_app beat --loglevel=info

This fires two automatic jobs: daily trek reminders (07:00 UTC) and a
monthly activity report (1st of the month, 06:00 UTC). You don't have to
wait for the schedule to see them work — both can also be triggered
on-demand from the Admin dashboard's Reports tab.


3. Start the frontend (1 more terminal)

No venv needed for this one — it's just static files.

bashcd frontend
python -m http.server 8080

Open your browser to:

http://localhost:8080

That's the actual app. (Visiting http://localhost:5000 directly will show
a {"error": "Resource not found"} JSON message — that's expected, since
port 5000 is the API only, not a webpage.)


4. Log in

RoleHow to get inAdminUse the seeded account: admin@trekmanager.com / Admin@123StaffLog in as Admin first → Add Staff tab → create a staff account, then log in with those credentialsTrekkerClick Register on the login page — anyone can self-register as a trekker


5. Quick end-to-end test


Log in as Admin → Add Staff → create a staff account.
Log out, log in as that Staff account → Create Trek → submit a
trek with a start date within the next few days.
Log back in as Admin → Pending Approvals → Approve it.
Log back in as Staff → My Treks → Open it for booking.
Register a new Trekker account → Browse Treks → book a slot.
Log back in as Admin → Reports → Send Now (daily reminders) —
check the Celery worker terminal for the simulated notification log.



Troubleshooting


command not found: redis-server / celery — the tool isn't
installed, or your venv isn't activated, or you're not in backend/.
Run which celery after activating the venv to confirm it resolves to
something inside backend/venv/.
ModuleNotFoundError: No module named 'tasks' (or 'app') — you ran
the command from the wrong directory. cd backend first.
{"error": "Resource not found"} in the browser — you're looking at
localhost:5000 (the API). The actual UI is localhost:8080.
Report/reminder jobs fail or hang — make sure all 4 backend terminals
are running, and that you fully restarted the Celery worker (Ctrl+C, then
rerun) after any code change — Python doesn't hot-reload Celery workers.# Trekking-Management-app
