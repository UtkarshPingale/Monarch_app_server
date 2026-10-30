# Monarch_app_server

Monarch HR & WorkTrack Backend & Phone-Identical Web Application Server.

## Features
- **Monarch PostgreSQL Database Backend (`postgres_api_server.py`)**:
  - Employee Master and Leave Management
  - Biometric Machine Sync & Geofenced GPS punch verification
  - Indian Standard 26th-to-25th Monthly Payroll Muster calculation
  - Excel Master Import with intelligent column mapping
- **Standalone Web App (`web_app.py`)**:
  - Phone-identical web UI matching the Monarch HR mobile app (Flutter)
  - Zero-latency cached rendering and live stopwatch
  - Multi-tab support: Dashboard, Attendance History, Leaves, and Profile
