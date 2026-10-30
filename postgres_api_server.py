#!/usr/bin/env python3
"""
PostgreSQL API Server for WorkTrack / GPS Tracker & Monarch HR
Connected to:
  • Monarch DB ('Monarch') for:
      users (1000+ employee directory, authentication, profile, roles & designations),
      devicelogs_M_YYYY (biometric machine punch logs)
  • Indian_Railway DB ('Indian_Railway') for:
      attendance, holidays, leaves, leave_balances, work_entries, app_versions, PMS tables
"""

import os
import sys
import re
import math
import datetime
import logging
import hashlib
import random
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict
from functools import wraps
import json
import csv
import io
import openpyxl
from flask import Flask, request, jsonify, render_template_string, Response, make_response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import jwt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MonarchAPIServer")

# ─── Configuration ────────────────────────────────────────────────────────────
MONARCH_DB_URI = os.getenv(
    "MONARCH_DB_URI",
    "postgresql://postgres:Monarch%40123@192.168.1.149:5432/Monarch"
)
IR_DB_URI = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@192.168.1.156:5432/Indian_Railway"
)
DB_URI = MONARCH_DB_URI
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret_jwt_key_12345")
PORT = int(os.getenv("PORT", 3001))

# ─── SMTP Email Configuration for OTP ─────────────────────────────────────────
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = 465
SMTP_EMAIL = "monarchtbc04@gmail.com"
SMTP_PASSWORD = "dkizoxoaqiuqvzaz"

# In-memory tracking of consumed tokens to prevent replay / brute force attacks
USED_OTP_NONCES = set()

app = Flask(__name__)
CORS(app)


# ─── IST Timezone Configuration ───────────────────────────────────────────────
# Indian Standard Time (UTC+05:30)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

def get_ist_now():
    return datetime.datetime.now(IST)

def get_ist_today():
    return datetime.datetime.now(IST).date()

def get_ist_time():
    return datetime.datetime.now(IST).time().replace(microsecond=0)

def get_payroll_cycle(ref_date=None):
    """Calculates company standard 26th-to-25th payroll cycle (start_date, end_date) for a given reference date."""
    if not ref_date:
        ref_date = get_ist_today()
    if ref_date.day >= 26:
        start_year = ref_date.year
        start_month = ref_date.month
        end_year = start_year + 1 if start_month == 12 else start_year
        end_month = 1 if start_month == 12 else start_month + 1
    else:
        end_year = ref_date.year
        end_month = ref_date.month
        start_year = end_year - 1 if end_month == 1 else end_year
        start_month = 12 if end_month == 1 else end_month - 1
    return datetime.date(start_year, start_month, 26), datetime.date(end_year, end_month, 25)

def get_available_payroll_cycles(num_cycles=8):
    """Generates consecutive 26th-to-25th payroll cycle ranges starting from current active cycle backwards."""
    today = get_ist_today()
    curr_start, curr_end = get_payroll_cycle(today)
    cycles = []
    s_year, s_month = curr_start.year, curr_start.month
    for i in range(num_cycles):
        e_year = s_year + 1 if s_month == 12 else s_year
        e_month = 1 if s_month == 12 else s_month + 1
        c_start = datetime.date(s_year, s_month, 26)
        c_end = datetime.date(e_year, e_month, 25)
        label = f"26 {c_start.strftime('%b %Y')} – 25 {c_end.strftime('%b %Y')}"
        if i == 0:
            label += " (Current Cycle)"
        cycles.append({
            'start_date': c_start.isoformat(),
            'end_date': c_end.isoformat(),
            'label': label,
            'is_current': (i == 0)
        })
        if s_month == 1:
            s_month = 12
            s_year -= 1
        else:
            s_month -= 1
    return cycles


# ─── Database Connection Helpers ──────────────────────────────────────────────
def get_db_connection():
    """Returns a new psycopg2 connection to Monarch PostgreSQL DB (defaulting to schema: data)."""
    return psycopg2.connect(MONARCH_DB_URI, options='-c search_path=data,public', cursor_factory=RealDictCursor)

def get_monarch_connection():
    """Returns a new psycopg2 connection to Monarch PostgreSQL DB (defaulting to schema: data)."""
    return psycopg2.connect(MONARCH_DB_URI, options='-c search_path=data,public', cursor_factory=RealDictCursor)

def get_ir_connection():
    """Returns a new psycopg2 connection to Indian_Railway PostgreSQL DB (schema: topology, public, team_site)."""
    return psycopg2.connect(IR_DB_URI, options='-c search_path=topology,public,team_site', cursor_factory=RealDictCursor)


DEFAULT_HOLIDAYS_2026 = [
    ("New Year", "2026-01-01", "Thursday"),
    ("Republic Day", "2026-01-26", "Monday"),
    ("Holi (Dhulivandan)", "2026-03-03", "Tuesday"),
    ("Gudhi Padwa", "2026-03-19", "Thursday"),
    ("Maharashtra Day", "2026-05-01", "Friday"),
    ("Independence Day", "2026-08-15", "Saturday"),
    ("Ganesh Chaturthi", "2026-09-14", "Monday"),
    ("Anant Chaturdashi", "2026-09-25", "Friday"),
    ("Gandhi Jayanti", "2026-10-02", "Friday"),
    ("Dussehra", "2026-10-20", "Tuesday"),
    ("Diwali (Narak Chaturdashi / Laxmi Pujan)", "2026-11-08", "Sunday"),
    ("Diwali", "2026-11-09", "Monday"),
    ("Diwali (Bali Pratipada / Padwa)", "2026-11-10", "Tuesday"),
    ("Diwali (Bhaubij)", "2026-11-11", "Wednesday"),
]


COMPANY_BUILDINGS = [
    {"name": "Monarch House (HQ)", "lat": 18.522998417472472, "lng": 73.90693699954727},
    {"name": "KK Empire", "lat": 18.523534, "lng": 73.906659},
    {"name": "Morya Palace", "lat": 18.523928384376653, "lng": 73.90561320811979},
]
GEOFENCE_RADIUS_METERS = 40.0

# ── Unified Company Geofence Square (Enclosing All 3 Office Locations) ───────
# Bounding square encompassing Morya Palace, KK Empire, and Monarch House (HQ)
COMPANY_GEOFENCE_SQUARE = {
    "name": "Monarch Office Campus Unified Geofence Zone",
    "description": "Unified perimeter square enclosing Morya Palace, KK Empire, and Monarch House HQ",
    "min_lat": 18.522450,
    "max_lat": 18.524450,
    "min_lng": 73.905150,
    "max_lng": 73.907450,
    "center_lat": 18.523450,
    "center_lng": 73.906300,
    "radius_equivalent_meters": 125.0
}


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    """Calculates great-circle distance between two points on Earth in meters."""
    try:
        R = 6371000.0  # Earth radius in meters
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        delta_phi = math.radians(float(lat2) - float(lat1))
        delta_lambda = math.radians(float(lon2) - float(lon1))
        a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c
    except Exception:
        return 999999.0


def is_in_company_geofence_square(lat, lng):
    """Returns True if (lat, lng) falls within the unified office campus square boundary."""
    try:
        f_lat = float(lat)
        f_lng = float(lng)
        return (
            COMPANY_GEOFENCE_SQUARE["min_lat"] <= f_lat <= COMPANY_GEOFENCE_SQUARE["max_lat"] and
            COMPANY_GEOFENCE_SQUARE["min_lng"] <= f_lng <= COMPANY_GEOFENCE_SQUARE["max_lng"]
        )
    except (ValueError, TypeError):
        return False


def check_geofence(lat, lng):
    """
    Checks if coordinates fall within the unified office campus square geofence
    encompassing Morya Palace, KK Empire, and Monarch House (HQ).
    """
    if lat is None or lng is None:
        return {"in_geofence": False, "nearest_building": "Unknown", "distance_meters": None, "in_square": False}
    try:
        f_lat = float(lat)
        f_lng = float(lng)
    except (ValueError, TypeError):
        return {"in_geofence": False, "nearest_building": "Unknown", "distance_meters": None, "in_square": False}

    in_square = is_in_company_geofence_square(f_lat, f_lng)

    min_dist = float('inf')
    nearest = "Monarch House (HQ)"
    for b in COMPANY_BUILDINGS:
        d = calculate_distance_meters(f_lat, f_lng, b['lat'], b['lng'])
        if d < min_dist:
            min_dist = d
            nearest = b['name']

    # In geofence if inside the unified square boundary OR within 40m building perimeter fallback
    in_geofence = in_square or (min_dist <= GEOFENCE_RADIUS_METERS)
    effective_dist = 0.0 if in_square else round(min_dist, 1)

    return {
        "in_geofence": in_geofence,
        "nearest_building": nearest,
        "distance_meters": effective_dist,
        "in_square": in_square
    }


# ─── Role & Department Helpers ────────────────────────────────────────────────
def normalize_role(role_str):
    """
    Normalizes roles to one of: 'admin', 'manager', 'seniorteamleader', 'teamleader', 'employee'.
    Supports roles and designations such as: Admin, SuperAdmin, Manager, Project Manager, Director, HR,
    Senior Team Leader, Senior Team Lead, Sr Team Leader, Sr TL, Sinor Team Leader,
    Team Leader, Team Lead, Sub Team Lead, TL, Lead, Engineer, Junior Engineer, Intern, Employee, etc.
    """
    if not role_str:
        return 'employee'
    r = str(role_str).strip().lower().replace('_', '').replace(' ', '').replace('-', '').replace('.', '')
    if 'admin' in r or 'owner' in r:
        return 'admin'
    if 'manager' in r or 'director' in r or 'hr' in r or 'vp' in r or 'president' in r or 'hod' in r:
        return 'manager'
    # Check senior team leader before team leader
    if ('senior' in r or 'sr' in r or 'sinor' in r or 'snr' in r) and ('lead' in r or 'tl' in r or 'leader' in r or 'head' in r or 'manager' in r):
        return 'seniorteamleader'
    if 'lead' in r or 'tl' in r or 'head' in r or 'leader' in r:
        return 'teamleader'
    return 'employee'


DEPT_ALIASES = {
    'finance': {'finance', 'account', 'accounts', 'accounting', 'accountancy', 'financial', 'audit', 'taxation', 'billing'},
    'it': {'it', 'information technology', 'tech', 'technology', 'infrastructure', 'software', 'hardware', 'network', 'system', 'developer', 'development', 'engineering'},
    'hr': {'hr', 'human resources', 'admin', 'administration', 'personnel', 'recruitment', 'talent'},
    'operations': {'operations', 'ops', 'logistics', 'supply', 'facility'},
    'sales': {'sales', 'marketing', 'bd', 'business development', 'growth'},
}


def normalize_department_name(d):
    """Normalizes department names for fuzzy/family comparison."""
    if not d:
        return ''
    s = str(d).strip().lower()
    s = s.replace('&', ' and ').replace('/', ' and ').replace(',', ' and ').replace('+', ' and ')
    s = re.sub(r'\b(department|dept|division|team|branch|unit|group)\b', '', s)
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    s = re.sub(r'\b(financial)\b', 'finance', s)
    s = re.sub(r'\b(accounts|accounting|accountancy)\b', 'account', s)
    s = re.sub(r'\b(operations|ops)\b', 'operation', s)
    s = re.sub(r'\b(administration|administrative)\b', 'admin', s)
    s = ' '.join(s.split())
    return s


def are_departments_matching(dept1, dept2):
    """Returns True if dept1 and dept2 match or belong to the same department family."""
    if not dept1 or not dept2:
        return True
    d1 = str(dept1).strip()
    d2 = str(dept2).strip()
    if not d1 or not d2 or d1.lower() in ('all', 'general', '') or d2.lower() in ('all', 'general', ''):
        return True
    if d1.lower() == d2.lower():
        return True

    n1 = normalize_department_name(d1)
    n2 = normalize_department_name(d2)
    if not n1 or not n2:
        return True
    if n1 == n2:
        return True

    tokens1 = set(w for w in n1.split() if w not in ('and', 'the', 'of', 'in', 'for'))
    tokens2 = set(w for w in n2.split() if w not in ('and', 'the', 'of', 'in', 'for'))

    if not tokens1 or not tokens2:
        return True
    if tokens1 == tokens2:
        return True
    if tokens1.issubset(tokens2) or tokens2.issubset(tokens1):
        return True
    if tokens1.intersection(tokens2):
        return True

    for fam_name, fam_tokens in DEPT_ALIASES.items():
        has_t1 = bool(tokens1 & fam_tokens or any(fam in n1 for fam in fam_tokens))
        has_t2 = bool(tokens2 & fam_tokens or any(fam in n2 for fam in fam_tokens))
        if has_t1 and has_t2:
            return True

    return False


def check_dept_has_leader(all_users_list, target_dept, role_type):
    """Checks if there is any active user in all_users_list with normalized_role == role_type whose department matches target_dept."""
    for u in all_users_list:
        u_role = normalize_role(u.get('role') if isinstance(u, dict) else u['role'])
        u_dept = (u.get('department') if isinstance(u, dict) else u['department']) or ''
        if u_role == role_type and are_departments_matching(u_dept, target_dept):
            return True
    return False


def normalize_person_name(name_str):
    """Normalizes person names for robust comparison."""
    if not name_str:
        return ''
    s = str(name_str).strip().lower()
    s = re.sub(r'\b(mr|mrs|ms|dr|shri|smt)\b\.?', '', s)
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    return ' '.join(s.split())


def is_direct_reporting_manager(caller, subordinate):
    """
    Checks if `caller` is the direct 1-on-1 reporting manager of `subordinate`.
    Matches by:
      1. Exact or normalized name match (e.g. 'Vishwas Damodar Kulal' vs 'Vishwas Damodar Kulal')
      2. Multi-token name match (e.g. 'Vishwas Kulal' matching 'Vishwas Damodar Kulal')
      3. Caller employee_no / emp_id matching subordinate's reporting_manager if stored as ID.
    """
    if not caller or not subordinate:
        return False

    caller_name = normalize_person_name(caller.get('name') or caller.get('full_name'))
    caller_eid = str(caller.get('employee_no') or caller.get('emp_id') or '').strip()

    rep_mgr = normalize_person_name(subordinate.get('reporting_manager'))
    rep_raw = str(subordinate.get('reporting_manager') or '').strip()

    if not rep_mgr and not rep_raw:
        return False

    # 1. Exact ID or string match
    if caller_eid and (rep_raw == caller_eid or rep_raw.lstrip('0') == caller_eid.lstrip('0')):
        return True
    if caller_name and caller_name == rep_mgr:
        return True

    # 2. Multi-word token matching (first name and last name match)
    tokens_caller = set(caller_name.split())
    tokens_mgr = set(rep_mgr.split())
    if len(tokens_caller) >= 2 and len(tokens_mgr) >= 2:
        if tokens_caller.issubset(tokens_mgr) or tokens_mgr.issubset(tokens_caller):
            return True
        c_list = caller_name.split()
        m_list = rep_mgr.split()
        if c_list[0] == m_list[0] and c_list[-1] == m_list[-1]:
            return True

    return False



# ─── Monarch User Helpers ─────────────────────────────────────────────────────
def format_monarch_user(r):
    """
    Standardizes a row from Monarch database 'users' table into a unified format
    compatible with all API endpoints and frontend expectations.
    """
    if not r:
        return None
    row = dict(r)
    eid = str(row.get('employee_no') or row.get('emp_id') or row.get('id') or '').strip()
    u_name = row.get('name') or row.get('full_name') or row.get('username') or f"Employee {eid}"
    desig = row.get('designation') or ''
    dept = row.get('department') or ''
    explicit_role = row.get('role')
    effective_role = explicit_role if (explicit_role and explicit_role.strip()) else normalize_role(desig)
    phone = row.get('mobile_number') or row.get('phone_number') or ''
    email = row.get('personal_email') or row.get('email') or ''
    doj = row.get('date_of_joining')
    doj_iso = doj.isoformat() if doj and hasattr(doj, 'isoformat') else (str(doj) if doj else '')

    return {
        'id': row.get('id'),
        'employee_no': row.get('employee_no'),
        'emp_id': eid,
        'name': u_name,
        'full_name': u_name,
        'username': row.get('username') or eid,
        'role': effective_role,
        'normalized_role': normalize_role(effective_role),
        'department': dept,
        'designation': desig,
        'phone_number': phone,
        'mobile_number': phone,
        'email': email,
        'personal_email': email,
        'date_of_joining': doj_iso,
        'joining_date': doj_iso,
        'gender': row.get('gender') or '',
        'reporting_manager': row.get('reporting_manager') or '',
        'location': row.get('location') or '',
        'company_name': row.get('company_name') or '',
        'shift_timing': row.get('shift_timing') or '',
        'password': row.get('password'),
        'password_hash': row.get('password_hash'),
        'is_location_bound': row.get('is_location_bound') if row.get('is_location_bound') is not None else True,
        'is_time_bound': row.get('is_time_bound') if row.get('is_time_bound') is not None else True,
    }


def get_user_by_identifier(cur, identifier):
    """
    Finds a user from the Monarch DB 'users' table by:
    1. employee_no (e.g. 1009, 1237, 2178)
    2. username (e.g. 'SUMIT')
    3. personal_email
    4. integer id (fallback)
    """
    if not identifier:
        return None
    ident_str = str(identifier).strip()
    clean_eid = ident_str.lstrip('0') or ident_str

    conn = None
    should_close = False
    if cur is None:
        conn = get_monarch_connection()
        cur = conn.cursor()
        should_close = True

    try:
        cur.execute("""
            SELECT id, employee_no, name, date_of_joining, gender, designation, department,
                   reporting_manager, location, company_name, mobile_number, personal_email,
                   shift_timing, password, created_at, role, username, password_hash,
                   is_location_bound, is_time_bound
            FROM users
            WHERE employee_no::text = %s 
               OR employee_no::text = %s 
               OR LOWER(username) = %s 
               OR UPPER(username) = %s
               OR LOWER(personal_email) = %s
               OR id::text = %s
            ORDER BY CASE
                WHEN employee_no::text = %s THEN 1
                WHEN employee_no::text = %s THEN 2
                WHEN LOWER(username) = %s THEN 3
                WHEN LOWER(personal_email) = %s THEN 4
                ELSE 5
            END
            LIMIT 1;
        """, (
            ident_str, clean_eid, ident_str.lower(), ident_str.upper(), ident_str.lower(), ident_str,
            ident_str, clean_eid, ident_str.lower(), ident_str.lower()
        ))
        raw = cur.fetchone()
        return format_monarch_user(raw)
    finally:
        if should_close:
            cur.close()
            if conn:
                conn.close()


def load_monarch_users_map():
    """Loads all 1000+ users from Monarch database into an in-memory lookup dictionary."""
    users_map = {}
    conn = None
    try:
        conn = get_monarch_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, employee_no, name, date_of_joining, gender, designation, department,
                   reporting_manager, location, company_name, mobile_number, personal_email,
                   shift_timing, password, created_at, role, username, password_hash,
                   is_location_bound, is_time_bound
            FROM users
            ORDER BY id ASC;
        """)
        rows = cur.fetchall()
        cur.close()

        for r in rows:
            u = format_monarch_user(r)
            eid = str(u.get('employee_no') or u.get('emp_id') or '').strip()
            if eid:
                users_map[eid] = u
                users_map[eid.lstrip('0')] = u
                users_map[eid.lower()] = u
                users_map[eid.upper()] = u
            if u.get('username'):
                users_map[u['username'].lower()] = u
            if u.get('personal_email'):
                users_map[u['personal_email'].lower()] = u
            if u.get('id'):
                users_map[f"uid_{u['id']}"] = u
            if u.get('name'):
                users_map[u['name'].lower().strip()] = u
                users_map[f"norm_{normalize_person_name(u['name'])}"] = u

        return users_map
    except Exception as e:
        logger.error(f"Error loading Monarch users map: {e}")
        return {}
    finally:
        if conn:
            conn.close()


def load_all_monarch_users():
    """Returns a full list of all formatted users from Monarch database."""
    conn = None
    try:
        conn = get_monarch_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, employee_no, name, date_of_joining, gender, designation, department,
                   reporting_manager, location, company_name, mobile_number, personal_email,
                   shift_timing, created_at, role, username
            FROM users
            ORDER BY employee_no ASC, name ASC;
        """)
        rows = cur.fetchall()
        cur.close()
        return [format_monarch_user(r) for r in rows]
    except Exception as e:
        logger.error(f"Error loading all Monarch users: {e}")
        return []
    finally:
        if conn:
            conn.close()


# ─── Database Initialization ──────────────────────────────────────────────────
def init_db():
    """
    Sets up schemas and tables:
      1. Monarch DB: Ensures users, attendance, shifts, holidays, leaves, leave_balances, app_versions in schema 'data'.
      2. Indian_Railway DB: Only connects for work_entries and daily_work (topology schema).
    """
    print(f"[INFO] Initializing Monarch DB (Schema: data) at {MONARCH_DB_URI} ...")
    try:
        conn_m = get_monarch_connection()
        cur_m = conn_m.cursor()
        
        # 1. Ensure 'data' schema exists
        cur_m.execute("CREATE SCHEMA IF NOT EXISTS data;")

        # 2. Ensure data.users table exists
        cur_m.execute("""
            CREATE TABLE IF NOT EXISTS data.users (
                id SERIAL PRIMARY KEY,
                employee_no INT,
                name VARCHAR(255),
                date_of_joining DATE,
                gender VARCHAR(50),
                designation VARCHAR(100),
                department VARCHAR(100),
                reporting_manager VARCHAR(255),
                location VARCHAR(255),
                company_name VARCHAR(255),
                mobile_number VARCHAR(50),
                personal_email VARCHAR(255),
                shift_timing VARCHAR(100),
                password VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                role VARCHAR(50),
                username VARCHAR(100),
                password_hash VARCHAR(255)
            );
        """)

        # 3. Copy/Sync all users from public.users into data.users
        try:
            cur_m.execute("""
                INSERT INTO data.users (
                    id, employee_no, name, date_of_joining, gender, designation, department,
                    reporting_manager, location, company_name, mobile_number, personal_email,
                    shift_timing, password, created_at, role, username, password_hash
                )
                SELECT 
                    id, employee_no, name, date_of_joining, gender, designation, department,
                    reporting_manager, location, company_name, mobile_number, personal_email,
                    shift_timing, password, created_at, role, username, password_hash
                FROM public.users
                ON CONFLICT (id) DO UPDATE SET
                    employee_no = EXCLUDED.employee_no,
                    name = EXCLUDED.name,
                    designation = EXCLUDED.designation,
                    department = EXCLUDED.department,
                    reporting_manager = EXCLUDED.reporting_manager,
                    location = EXCLUDED.location,
                    company_name = EXCLUDED.company_name,
                    mobile_number = EXCLUDED.mobile_number,
                    personal_email = EXCLUDED.personal_email,
                    shift_timing = EXCLUDED.shift_timing,
                    role = COALESCE(data.users.role, EXCLUDED.role),
                    username = COALESCE(data.users.username, EXCLUDED.username),
                    password_hash = COALESCE(data.users.password_hash, EXCLUDED.password_hash);
            """)
        except Exception as e_copy:
            conn_m.rollback()
            logger.warning(f"Notice while copying public.users to data.users: {e_copy}")

        # 4. Ensure admin user SUMIT / SUMIT05 exists in data.users
        cur_m.execute("SELECT id FROM data.users WHERE employee_no = 1009 OR UPPER(username) = 'SUMIT';")
        existing_sumit = cur_m.fetchone()
        hashed_pw = bcrypt.hashpw(b'SUMIT05', bcrypt.gensalt()).decode('utf-8')

        if existing_sumit:
            cur_m.execute("""
                UPDATE data.users 
                SET role = 'admin', 
                    username = 'SUMIT', 
                    password_hash = %s 
                WHERE id = %s;
            """, (hashed_pw, existing_sumit['id']))
        else:
            cur_m.execute("""
                INSERT INTO data.users (
                    employee_no, name, designation, department, reporting_manager,
                    location, company_name, mobile_number, personal_email,
                    role, username, password, password_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                1009, 'Sumit Sopan Somwanshi', 'Engineer', 'IT Department', 'Vishwas Damodar Kulal',
                'Pune', 'Monarch Surveyors & Engineering Consultants Limited', '7249023106', 'somwanshisumit5@gmail.com',
                'admin', 'SUMIT', hashed_pw, hashed_pw
            ))

        # 4b. Ensure admin user UTKARSH (1951) exists in data.users as admin
        cur_m.execute("SELECT id FROM data.users WHERE employee_no = 1951 OR personal_email = 'utkarshpingale11@gmail.com';")
        existing_utkarsh = cur_m.fetchone()
        hashed_utkarsh = bcrypt.hashpw(b'Utkarsh1951', bcrypt.gensalt()).decode('utf-8')
        if existing_utkarsh:
            cur_m.execute("""
                UPDATE data.users
                SET role = 'admin',
                    username = COALESCE(username, '1951'),
                    password = COALESCE(password, %s),
                    password_hash = COALESCE(password_hash, %s)
                WHERE id = %s;
            """, (hashed_utkarsh, hashed_utkarsh, existing_utkarsh['id']))

        # 4c. Ensure admin user SUMEDH (1228) exists in data.users as admin
        cur_m.execute("SELECT id FROM data.users WHERE employee_no = 1228;")
        existing_1228 = cur_m.fetchone()
        hashed_1228 = bcrypt.hashpw(b'Sumedh1228', bcrypt.gensalt()).decode('utf-8')
        if existing_1228:
            cur_m.execute("""
                UPDATE data.users
                SET role = 'admin',
                    username = COALESCE(username, '1228'),
                    password = %s,
                    password_hash = %s
                WHERE id = %s;
            """, (hashed_1228, hashed_1228, existing_1228['id']))

        # Ensure active/employment/shift columns exist in data.users
        cur_m.execute("""
            ALTER TABLE data.users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
            ALTER TABLE data.users ADD COLUMN IF NOT EXISTS employment_status VARCHAR(50) DEFAULT 'Active';
            ALTER TABLE data.users ADD COLUMN IF NOT EXISTS weekly_off VARCHAR(50) DEFAULT 'Sunday';
            ALTER TABLE data.users ADD COLUMN IF NOT EXISTS shift_id INT;
        """)

        # 5. Ensure Application Tables exist in data schema
        cur_m.execute("""
            CREATE TABLE IF NOT EXISTS data.shifts (
                id SERIAL PRIMARY KEY,
                shift_name VARCHAR(100) NOT NULL UNIQUE,
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                grace_period_mins INT DEFAULT 15,
                half_day_hours NUMERIC(4,2) DEFAULT 4.5,
                full_day_hours NUMERIC(4,2) DEFAULT 8.5,
                min_overtime_mins INT DEFAULT 30,
                is_night_shift BOOLEAN DEFAULT FALSE,
                working_days VARCHAR(100) DEFAULT 'Mon,Tue,Wed,Thu,Fri,Sat',
                description VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO data.shifts (shift_name, start_time, end_time, grace_period_mins, half_day_hours, full_day_hours, is_night_shift, description)
            VALUES 
                ('General Shift', '09:30:00', '18:30:00', 15, 4.5, 8.5, FALSE, 'Standard office shift (09:30 AM - 06:30 PM)'),
                ('Morning Shift', '07:00:00', '15:30:00', 15, 4.0, 8.0, FALSE, 'Early morning operations (07:00 AM - 03:30 PM)'),
                ('Evening Shift', '14:00:00', '22:30:00', 15, 4.0, 8.0, FALSE, 'Afternoon/Evening shift (02:00 PM - 10:30 PM)'),
                ('Night Shift', '22:00:00', '06:30:00', 15, 4.0, 8.0, TRUE, 'Overnight operations (10:00 PM - 06:30 AM)')
            ON CONFLICT (shift_name) DO NOTHING;

            CREATE TABLE IF NOT EXISTS data.leave_types (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                code VARCHAR(20) NOT NULL UNIQUE,
                annual_days NUMERIC(5,2) DEFAULT 12.0,
                carry_forward_max NUMERIC(5,2) DEFAULT 5.0,
                is_paid BOOLEAN DEFAULT TRUE,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO data.leave_types (name, code, annual_days, carry_forward_max, is_paid, description)
            VALUES
                ('Casual Leave', 'CL', 12.0, 3.0, TRUE, 'For personal and unforeseen matters'),
                ('Sick Leave', 'SL', 10.0, 5.0, TRUE, 'Medical illness with doctor advice'),
                ('Earned / Privilege Leave', 'EL', 15.0, 30.0, TRUE, 'Annual vacation and accrued leaves'),
                ('Leave Without Pay', 'LWP', 0.0, 0.0, FALSE, 'Unpaid absence approved by management'),
                ('Compensatory Off', 'COMP', 0.0, 0.0, TRUE, 'Credit for working on weekend or holiday')
            ON CONFLICT (code) DO NOTHING;

            CREATE TABLE IF NOT EXISTS data.attendance_corrections (
                id SERIAL PRIMARY KEY,
                attendance_id INT,
                employee_id VARCHAR(100) NOT NULL,
                employee_name VARCHAR(255),
                attendance_date DATE NOT NULL,
                requested_sign_in TIME,
                requested_sign_out TIME,
                reason TEXT NOT NULL,
                status VARCHAR(50) DEFAULT 'Pending Review',
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_by VARCHAR(100),
                reviewed_at TIMESTAMP,
                reviewer_comments TEXT
            );

            CREATE TABLE IF NOT EXISTS data.audit_logs (
                id SERIAL PRIMARY KEY,
                actor_id VARCHAR(100) NOT NULL,
                actor_name VARCHAR(255),
                action VARCHAR(100) NOT NULL,
                target_type VARCHAR(50) NOT NULL,
                target_id VARCHAR(100),
                reason TEXT,
                before_value JSONB,
                after_value JSONB,
                ip_address VARCHAR(50),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS data.employee_location_trail (
                id SERIAL PRIMARY KEY,
                employee_id VARCHAR(100) NOT NULL,
                employee_name VARCHAR(255),
                latitude NUMERIC(10, 6) NOT NULL,
                longitude NUMERIC(10, 6) NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                speed NUMERIC(6, 2),
                battery_level INT,
                nearest_building VARCHAR(100),
                distance_meters NUMERIC(10, 2),
                in_geofence BOOLEAN DEFAULT FALSE
            );
            CREATE INDEX IF NOT EXISTS idx_trail_emp_date ON data.employee_location_trail(employee_id, recorded_at);
        """)

        cur_m.execute("""
            CREATE TABLE IF NOT EXISTS data.holidays (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                date DATE NOT NULL,
                weekday VARCHAR(50)
            );

            CREATE TABLE IF NOT EXISTS data.leaves (
                id SERIAL PRIMARY KEY,
                employee_id VARCHAR(100) NOT NULL,
                employee_name VARCHAR(255),
                title VARCHAR(255) NOT NULL,
                leave_type VARCHAR(100) DEFAULT 'Annual',
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                days_count NUMERIC(5,2) DEFAULT 1.0,
                status VARCHAR(50) DEFAULT 'Pending Review',
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                note TEXT,
                department VARCHAR(100),
                reviewed_by VARCHAR(100),
                reviewed_at TIMESTAMP,
                rejection_reason TEXT
            );

            ALTER TABLE data.leaves ADD COLUMN IF NOT EXISTS is_half_day BOOLEAN DEFAULT FALSE;
            ALTER TABLE data.leaves ADD COLUMN IF NOT EXISTS session VARCHAR(50);
            ALTER TABLE data.leaves ADD COLUMN IF NOT EXISTS from_session VARCHAR(50);
            ALTER TABLE data.leaves ADD COLUMN IF NOT EXISTS to_session VARCHAR(50);


            CREATE TABLE IF NOT EXISTS data.leave_balances (
                id SERIAL PRIMARY KEY,
                employee_id VARCHAR(100) UNIQUE NOT NULL,
                total_allotted NUMERIC(5,2) DEFAULT 6.0,
                used_days NUMERIC(5,2) DEFAULT 0.0,
                remaining_days NUMERIC(5,2) DEFAULT 6.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS data.app_versions (
                id SERIAL PRIMARY KEY,
                platform VARCHAR(20) DEFAULT 'android',
                version_name VARCHAR(50) NOT NULL,
                version_code INT NOT NULL,
                min_supported_version VARCHAR(50) DEFAULT '1.0.0',
                is_force_update BOOLEAN DEFAULT FALSE,
                download_url TEXT,
                release_notes TEXT,
                title VARCHAR(255) DEFAULT 'Monarch HR Update Available!',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ALTER TABLE data.app_versions ADD COLUMN IF NOT EXISTS platform VARCHAR(20) DEFAULT 'android';

            CREATE TABLE IF NOT EXISTS data.attendance (
                id SERIAL PRIMARY KEY,
                employee_id VARCHAR(100) NOT NULL,
                employee_name VARCHAR(255),
                date DATE NOT NULL,
                sign_in TIME,
                sign_out TIME,
                location VARCHAR(255),
                in_geofence BOOLEAN DEFAULT TRUE,
                nearest_building VARCHAR(100),
                distance_meters NUMERIC(10, 2),
                clock_in_lat NUMERIC(10, 6),
                clock_in_lng NUMERIC(10, 6),
                clock_out_lat NUMERIC(10, 6),
                clock_out_lng NUMERIC(10, 6),
                clock_out_in_geofence BOOLEAN DEFAULT TRUE,
                clock_out_distance_meters NUMERIC(10, 2),
                department VARCHAR(100),
                role VARCHAR(100),
                approval_status VARCHAR(50) DEFAULT 'Approved',
                reviewed_by VARCHAR(100),
                reviewed_at TIMESTAMP,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT unique_employee_date UNIQUE (employee_id, date)
            );
            ALTER TABLE data.attendance ADD COLUMN IF NOT EXISTS is_manually_corrected BOOLEAN DEFAULT FALSE;
        """)

        # 6. Seed initial app versions in data.app_versions for Android (1.0.5+9) and Apple iOS (1.0.5+11)
        cur_m.execute("SELECT id FROM data.app_versions WHERE LOWER(platform) = 'android' LIMIT 1;")
        if not cur_m.fetchone():
            cur_m.execute("""
                INSERT INTO data.app_versions (
                    platform, version_name, version_code, min_supported_version,
                    is_force_update, download_url, release_notes, title
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                'android',
                '1.0.5',
                9,
                '1.0.0',
                False,
                'https://play.google.com/store/apps/details?id=com.monarchconsultants.monarchhr',
                '• Attendance Regularization & Leave options\n• Half Day punch-in/out tracking\n• Dark/Light mode theme sync',
                'Monarch HR Android Update Available!'
            ))

        cur_m.execute("SELECT id FROM data.app_versions WHERE LOWER(platform) IN ('ios', 'apple') LIMIT 1;")
        if not cur_m.fetchone():
            cur_m.execute("""
                INSERT INTO data.app_versions (
                    platform, version_name, version_code, min_supported_version,
                    is_force_update, download_url, release_notes, title
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                'ios',
                '1.0.5',
                11,
                '1.0.0',
                False,
                'https://apps.apple.com/app/monarch-hr/id6470000000',
                '• Attendance Regularization & Leave options\n• Apple iOS biometric touchpoints\n• Dark/Light mode theme sync',
                'Monarch HR iOS Update Available!'
            ))

        # 7. Seed default 2026 holidays in data.holidays
        for title, h_date, weekday in DEFAULT_HOLIDAYS_2026:
            cur_m.execute("SELECT id FROM data.holidays WHERE date = %s;", (h_date,))
            if not cur_m.fetchone():
                cur_m.execute("""
                    INSERT INTO data.holidays (title, date, weekday)
                    VALUES (%s, %s, %s);
                """, (title, h_date, weekday))

        # 8. Seed default leave balance for SUMIT / 1009 in data.leave_balances
        cur_m.execute("""
            INSERT INTO data.leave_balances (employee_id, total_allotted, used_days, remaining_days)
            VALUES ('1009', 6.0, 0.0, 6.0)
            ON CONFLICT (employee_id) DO NOTHING;
        """)
        cur_m.execute("""
            INSERT INTO data.leave_balances (employee_id, total_allotted, used_days, remaining_days)
            VALUES ('SUMIT', 6.0, 0.0, 6.0)
            ON CONFLICT (employee_id) DO NOTHING;
        """)

        conn_m.commit()
        cur_m.close()
        conn_m.close()
        print("[SUCCESS] Connected to Monarch database (All users copied to data.users; Users, Attendance, Holidays, Leaves in schema 'data').")
    except Exception as e:
        print(f"[WARN] Monarch DB check failed: {e}")

    # Ensure topology schema & work_entries table exist in Indian_Railway DB
    print(f"[INFO] Initializing Indian_Railway DB (Only for work_entries table) at {IR_DB_URI} ...")
    try:
        conn_ir = get_ir_connection()
        cur_ir = conn_ir.cursor()
        cur_ir.execute("CREATE SCHEMA IF NOT EXISTS topology;")
        cur_ir.execute("""
            CREATE TABLE IF NOT EXISTS topology.work_entries (
                id SERIAL PRIMARY KEY,
                user_id INT,
                employee_id VARCHAR(50),
                employee_name VARCHAR(100),
                work_date DATE NOT NULL,
                project_id VARCHAR(50),
                project_name VARCHAR(255),
                department VARCHAR(100),
                task VARCHAR(255),
                subtask VARCHAR(255),
                quantity NUMERIC(10, 2) DEFAULT 0,
                unit VARCHAR(50) DEFAULT 'KM',
                hours INT DEFAULT 0,
                minutes INT DEFAULT 0,
                total_hours NUMERIC(5, 2) DEFAULT 0.0,
                revision VARCHAR(100) DEFAULT 'Rev 0',
                remarks TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS public.work_entries (
                id SERIAL PRIMARY KEY,
                user_id INT,
                employee_id VARCHAR(50),
                employee_name VARCHAR(100),
                work_date DATE NOT NULL,
                project_id VARCHAR(50),
                project_name VARCHAR(255),
                department VARCHAR(100),
                task VARCHAR(255),
                subtask VARCHAR(255),
                quantity NUMERIC(10, 2) DEFAULT 0,
                unit VARCHAR(50) DEFAULT 'KM',
                hours INT DEFAULT 0,
                minutes INT DEFAULT 0,
                total_hours NUMERIC(5, 2) DEFAULT 0.0,
                revision VARCHAR(100) DEFAULT 'Rev 0',
                remarks TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn_ir.commit()
        cur_ir.close()
        conn_ir.close()
        print("[SUCCESS] Indian_Railway DB connected & ready for work_entries.")
    except Exception as e:
        print(f"[WARN] Indian_Railway DB work_entries init notice: {e}")


# ─── Helper Functions ─────────────────────────────────────────────────────────
def parse_lat_lng(location_str):
    if not location_str:
        return None, None
    try:
        parts = location_str.split(',')
        return float(parts[0].strip()), float(parts[1].strip())
    except Exception:
        return None, None


def format_attendance_record(r):
    row = dict(r)
    d = row.get('date')
    s_in = row.get('sign_in')
    s_out = row.get('sign_out')

    if s_out and (s_out == datetime.time(0, 0, 0) or str(s_out).startswith('00:00:00') or str(s_out) == '00:00'):
        s_out = None
    if s_in and (s_in == datetime.time(0, 0, 0) and (not s_out or s_out == datetime.time(0, 0, 0))):
        s_in = None

    if s_in and hasattr(s_in, 'replace'):
        s_in = s_in.replace(microsecond=0)
    if s_out and hasattr(s_out, 'replace'):
        s_out = s_out.replace(microsecond=0)

    clock_in_iso = None
    clock_out_iso = None
    total_minutes = None

    if d and s_in:
        dt_in = datetime.datetime.combine(d, s_in).replace(tzinfo=IST)
        clock_in_iso = dt_in.isoformat()

        if s_out:
            dt_out = datetime.datetime.combine(d, s_out).replace(tzinfo=IST)
            if dt_out < dt_in:
                dt_out += datetime.timedelta(days=1)
            clock_out_iso = dt_out.isoformat()
            total_minutes = max(0, int((dt_out - dt_in).total_seconds() / 60))
    elif row.get('clock_in'):
        cin = row.get('clock_in')
        if isinstance(cin, datetime.datetime):
            if cin.tzinfo is None:
                cin = cin.replace(tzinfo=datetime.timezone.utc).astimezone(IST)
            clock_in_iso = cin.isoformat()
        else:
            clock_in_iso = str(cin)
        cout = row.get('clock_out')
        if cout:
            if isinstance(cout, datetime.datetime):
                if cout.tzinfo is None:
                    cout = cout.replace(tzinfo=datetime.timezone.utc).astimezone(IST)
                clock_out_iso = cout.isoformat()
            else:
                clock_out_iso = str(cout)

    lat, lng = parse_lat_lng(row.get('location'))
    d_m = float(row['distance_meters']) if row.get('distance_meters') is not None else None
    out_d_m = float(row['clock_out_distance_meters']) if row.get('clock_out_distance_meters') is not None else None
    rev_at = row['reviewed_at'].isoformat() if row.get('reviewed_at') and hasattr(row['reviewed_at'], 'isoformat') else (str(row.get('reviewed_at')) if row.get('reviewed_at') else None)
    emp_name = row.get('employee_name') or row.get('name') or row.get('full_name') or 'Employee'

    loc_raw = row.get('location') or ''
    in_device_str = None
    out_device_str = None

    if 'In #' in loc_raw:
        m_in = re.search(r'In #(\d+)', loc_raw)
        if m_in:
            if m_in.group(1) == '99':
                bldg_name = row.get('nearest_building')
                in_device_str = f"Mobile Phone (GPS) • {bldg_name}" if bldg_name else "Mobile Phone (GPS)"
            else:
                in_device_str = f"Biometric Machine #{m_in.group(1)}"
    elif loc_raw.startswith('Biometric Machine') and not row.get('clock_in_lat'):
        in_device_str = 'Biometric Machine'
    elif row.get('clock_in_lat'):
        bldg_name = row.get('nearest_building')
        in_device_str = f"Mobile Phone (GPS) • {bldg_name}" if bldg_name else "Mobile Phone (GPS)"

    if 'Out #' in loc_raw:
        m_out = re.search(r'Out #(\d+)', loc_raw)
        if m_out:
            if m_out.group(1) == '99':
                bldg_name = row.get('nearest_building')
                out_device_str = f"Mobile Phone (GPS) • {bldg_name}" if bldg_name else "Mobile Phone (GPS)"
            else:
                out_device_str = f"Biometric Machine #{m_out.group(1)}"
    elif 'Biometric Machine' in loc_raw and not row.get('clock_out_lat') and 'In #' not in loc_raw:
        out_device_str = 'Biometric Machine'
    elif row.get('clock_out_lat') or (row.get('sign_out') and 'Out #' not in loc_raw):
        bldg_name = row.get('nearest_building')
        out_device_str = f"Mobile Phone (GPS) • {bldg_name}" if bldg_name else "Mobile Phone (GPS)"

    if not in_device_str:
        in_device_str = "Mobile Phone (GPS)"
    if not out_device_str:
        out_device_str = "Mobile Phone (GPS)"

    return {
        '_id': str(row.get('id')),
        'id': row.get('id'),
        'user_id': row.get('employee_id'),
        'employee_id': row.get('employee_id'),
        'name': emp_name,
        'employee_name': emp_name,
        'clock_in': clock_in_iso,
        'clock_out': clock_out_iso,
        'clock_in_lat': row.get('clock_in_lat') or lat,
        'clock_in_lng': row.get('clock_in_lng') or lng,
        'clock_out_lat': row.get('clock_out_lat') or (lat if clock_out_iso else None),
        'clock_out_lng': row.get('clock_out_lng') or (lng if clock_out_iso else None),
        'total_minutes': total_minutes,
        'location': loc_raw,
        'clock_in_location': in_device_str,
        'clock_out_location': out_device_str,
        'punch_in_location': in_device_str,
        'punch_out_location': out_device_str,
        'date': d.isoformat() if d and hasattr(d, 'isoformat') else str(d) if d else None,
        'sign_in': str(s_in) if s_in else None,
        'sign_out': str(s_out) if s_out else None,
        'in_geofence': row.get('in_geofence') if row.get('in_geofence') is not None else True,
        'nearest_building': row.get('nearest_building') or 'Monarch House (HQ)',
        'distance_meters': d_m,
        'clock_out_in_geofence': row.get('clock_out_in_geofence') if row.get('clock_out_in_geofence') is not None else True,
        'clock_out_distance_meters': out_d_m,
        'department': row.get('department'),
        'role': row.get('role'),
        'approval_status': row.get('approval_status') or 'Approved',
        'reviewed_by': row.get('reviewed_by'),
        'reviewed_at': rev_at,
        'rejection_reason': row.get('rejection_reason'),
    }


# ─── Auth Middleware ──────────────────────────────────────────────────────────
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]

        if not token:
            return jsonify({'error': 'Token is missing'}), 401

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            request.user = payload
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(request, 'user'):
            return jsonify({'error': 'Unauthorized'}), 401
        role = str(request.user.get('role') or '').lower().replace('_', '').replace(' ', '')
        emp_id = str(request.user.get('employee_no') or request.user.get('emp_id') or '').strip()
        if role in ['admin', 'superadmin', 'manager', 'hr', 'hrmanager', 'seniorteamleader'] or emp_id in ['1009', '1951', '1228', '965', '1844', '10001', '10003']:
            return f(*args, **kwargs)
        return jsonify({'error': 'Forbidden: Admin or HR access required'}), 403

    return decorated


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    try:
        # Check Monarch DB
        conn_m = get_monarch_connection()
        cur_m = conn_m.cursor()
        cur_m.execute("SELECT COUNT(*) FROM users;")
        user_count = cur_m.fetchone()['count']
        cur_m.close()
        conn_m.close()

        # Check Indian_Railway DB
        conn_ir = get_db_connection()
        cur_ir = conn_ir.cursor()
        cur_ir.execute("SELECT COUNT(*) FROM attendance;")
        attendance_count = cur_ir.fetchone()['count']
        cur_ir.close()
        conn_ir.close()

        return jsonify({
            'status': 'ok',
            'monarch_database': 'connected',
            'indian_railway_database': 'connected',
            'users_count': user_count,
            'attendance_count': attendance_count
        })
    except Exception as e:
        return jsonify({'status': 'degraded', 'error': str(e)}), 500


@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    full_name = data.get('full_name') or data.get('name')
    username = (data.get('username') or data.get('email') or '').strip().lower()
    password = data.get('password')
    emp_id = data.get('emp_id') or data.get('employee_no') or username
    department = data.get('department', '')
    designation = data.get('designation', '')
    role = data.get('role', 'employee')

    if not full_name or not username or not password:
        return jsonify({'error': 'Missing name, username/email, or password'}), 400

    try:
        conn_m = get_monarch_connection()
        cur_m = conn_m.cursor()

        # Check existing in Monarch DB
        try:
            numeric_eid = int(emp_id) if str(emp_id).isdigit() else None
        except Exception:
            numeric_eid = None

        cur_m.execute("""
            SELECT id FROM users 
            WHERE LOWER(username) = %s 
               OR (employee_no IS NOT NULL AND %s IS NOT NULL AND employee_no = %s);
        """, (username, numeric_eid, numeric_eid))

        if cur_m.fetchone():
            cur_m.close()
            conn_m.close()
            return jsonify({'error': 'Username or Employee ID already registered in Monarch DB'}), 400

        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        cur_m.execute("""
            INSERT INTO users (
                employee_no, name, designation, department,
                role, username, password, password_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, employee_no, name, username, role, department, designation;
        """, (
            numeric_eid or 9000, full_name, designation, department,
            role, username, hashed_pw, hashed_pw
        ))
        user = cur_m.fetchone()
        conn_m.commit()
        cur_m.close()
        conn_m.close()

        # Seed leave balance in Indian_Railway DB
        try:
            conn_ir = get_db_connection()
            cur_ir = conn_ir.cursor()
            cur_ir.execute("""
                INSERT INTO leave_balances (employee_id, total_allotted, used_days, remaining_days)
                VALUES (%s, 6.0, 0.0, 6.0)
                ON CONFLICT (employee_id) DO NOTHING;
            """, (str(user['employee_no']),))
            conn_ir.commit()
            cur_ir.close()
            conn_ir.close()
        except Exception as e_lb:
            print(f"Leave balance seed error: {e_lb}")

        return jsonify({
            'id': user['id'],
            'name': user['name'],
            'email': user['username'],
            'emp_id': str(user['employee_no']),
            'employee_no': user['employee_no'],
            'role': user['role']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def verify_user_password(user, password):
    """Verifies submitted password against Monarch DB credentials, hash, and known schemes."""
    if not user or not password:
        return False

    # 1. Check against password_hash (bcrypt)
    if user.get('password_hash'):
        try:
            if bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                return True
        except Exception:
            pass

    # 2. Check against password (bcrypt)
    if user.get('password'):
        try:
            if bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
                return True
        except Exception:
            pass

    # 3. Check case-insensitive / FirstName+EmpId variants (e.g. Vedant1237 vs VEDANT1237)
    if user.get('password'):
        u_name = user.get('name') or ''
        first_name = u_name.split()[0] if u_name else ''
        eno_str = str(user.get('employee_no') or '')

        candidates = [
            f"{first_name.capitalize()}{eno_str}",
            f"{first_name.upper()}{eno_str}",
            f"{first_name.lower()}{eno_str}",
            f"Monarch@{eno_str}",
            f"Monarch{eno_str}",
            eno_str,
            "123456"
        ]

        for cand in candidates:
            if password.lower() == cand.lower():
                try:
                    if bcrypt.checkpw(cand.encode('utf-8'), user['password'].encode('utf-8')):
                        return True
                except Exception:
                    pass

    # 4. Check plaintext password match (if unhashed in legacy DB)
    if user.get('password') and user.get('password') == password:
        return True

    return False


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    emp_id = (data.get('identifier') or data.get('emp_id') or data.get('email') or data.get('username') or '').strip()
    password = str(data.get('password') or '').strip()

    if not emp_id or not password:
        return jsonify({'error': 'Employee ID / Username and password required'}), 400

    try:
        user = get_user_by_identifier(None, emp_id)

        if not user:
            return jsonify({'error': 'Invalid Employee ID or password'}), 401

        # Verify password against Monarch DB credentials
        if not verify_user_password(user, password):
            return jsonify({'error': 'Invalid Employee ID or password'}), 401

        clean_eid = str(user.get('employee_no') or user.get('emp_id') or emp_id).strip()
        user_role = user.get('role') or normalize_role(user.get('designation'))

        # Admin / HR accounts with elevated privileges (backend admin + mobile/web app)
        if clean_eid in ['965', '1844', '1951', '1009', '1228', '10001', '10003']:
            user_role = 'admin'
        token_payload = {
            'id': str(user['id']),
            'emp_id': user['emp_id'],
            'employee_no': user.get('employee_no'),
            'name': user['name'],
            'role': user_role,
            'department': user.get('department') or '',
            'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
        }
        token = jwt.encode(token_payload, JWT_SECRET, algorithm='HS256')

        doj_iso = user['date_of_joining'] or ''

        return jsonify({
            'token': token,
            'user': {
                'id': str(user['id']),
                'emp_id': user['emp_id'],
                'employee_no': user.get('employee_no'),
                'name': user['name'],
                'full_name': user['name'],
                'role': user_role,
                'phone_number': user.get('mobile_number') or '',
                'mobile_number': user.get('mobile_number') or '',
                'date_of_joining': doj_iso,
                'joining_date': doj_iso,
                'email': user.get('personal_email') or '',
                'personal_email': user.get('personal_email') or '',
                'department': user.get('department') or '',
                'designation': user.get('designation') or '',
                'reporting_manager': user.get('reporting_manager') or ''
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/profile', methods=['GET'])
@token_required
def get_user_profile():
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    try:
        user = get_user_by_identifier(None, emp_id)

        if not user:
            return jsonify({'error': 'User not found'}), 404

        return jsonify({
            'id': str(user['id']),
            'emp_id': user['emp_id'],
            'employee_no': user.get('employee_no'),
            'name': user['name'],
            'full_name': user['name'],
            'role': user.get('role') or normalize_role(user.get('designation')),
            'phone_number': user.get('mobile_number') or '',
            'mobile_number': user.get('mobile_number') or '',
            'date_of_joining': user.get('date_of_joining') or '',
            'joining_date': user.get('date_of_joining') or '',
            'email': user.get('personal_email') or '',
            'personal_email': user.get('personal_email') or '',
            'department': user.get('department') or '',
            'designation': user.get('designation') or '',
            'reporting_manager': user.get('reporting_manager') or ''
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@app.route('/api/user/profile', methods=['PUT'])
@token_required
def update_user_profile():
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    data = request.get_json() or {}

    raw_phone = data.get('phone_number') or data.get('mobile_number')
    phone_number = None
    if raw_phone:
        digits = re.sub(r'\D', '', str(raw_phone))
        if len(digits) == 12 and digits.startswith('91'):
            phone_number = digits[2:]
        elif len(digits) == 11 and digits.startswith('0'):
            phone_number = digits[1:]
        elif len(digits) > 10:
            phone_number = digits[-10:]
        else:
            phone_number = digits

    joining_date_str = data.get('date_of_joining') or data.get('joining_date')
    email = data.get('email') or data.get('personal_email')
    if email:
        email = str(email).strip()
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({'error': 'Invalid email format. Please provide a valid email address (e.g. employee@monarch.com).'}), 400

    full_name = data.get('full_name') or data.get('name')
    department = data.get('department')
    designation = data.get('designation')

    date_of_joining = None
    if joining_date_str:
        try:
            date_of_joining = datetime.date.fromisoformat(str(joining_date_str).split('T')[0])
        except Exception:
            date_of_joining = None

    try:
        conn_m = get_monarch_connection()
        cur_m = conn_m.cursor()

        target_user = get_user_by_identifier(cur_m, emp_id)
        if not target_user:
            cur_m.close()
            conn_m.close()
            return jsonify({'error': 'User not found to update'}), 404

        cur_m.execute("""
            UPDATE users
            SET mobile_number = COALESCE(%s, mobile_number),
                date_of_joining = COALESCE(%s, date_of_joining),
                personal_email = COALESCE(%s, personal_email),
                name = COALESCE(%s, name),
                department = COALESCE(%s, department),
                designation = COALESCE(%s, designation)
            WHERE id = %s
            RETURNING id, employee_no, name, date_of_joining, gender, designation, department,
                      reporting_manager, location, company_name, mobile_number, personal_email,
                      shift_timing, created_at, role, username;
        """, (phone_number, date_of_joining, email, full_name, department, designation, target_user['id']))
        updated_raw = cur_m.fetchone()
        conn_m.commit()
        cur_m.close()
        conn_m.close()

        updated_user = format_monarch_user(updated_raw)

        return jsonify({
            'id': str(updated_user['id']),
            'emp_id': updated_user['emp_id'],
            'employee_no': updated_user.get('employee_no'),
            'name': updated_user['name'],
            'full_name': updated_user['name'],
            'role': updated_user['role'],
            'phone_number': updated_user.get('mobile_number') or '',
            'mobile_number': updated_user.get('mobile_number') or '',
            'date_of_joining': updated_user.get('date_of_joining') or '',
            'joining_date': updated_user.get('date_of_joining') or '',
            'email': updated_user.get('personal_email') or '',
            'personal_email': updated_user.get('personal_email') or '',
            'department': updated_user.get('department') or '',
            'designation': updated_user.get('designation') or ''
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def mask_email(email_str):
    if not email_str or '@' not in email_str:
        return 'your registered email'
    user_part, domain = email_str.split('@', 1)
    if len(user_part) <= 2:
        masked_user = user_part[0] + '*'
    else:
        masked_user = user_part[0] + '*' * (len(user_part) - 2) + user_part[-1]
    return f"{masked_user}@{domain}"


def send_otp_email(to_email, otp_code, employee_name="Employee"):
    """Sends OTP email from monarchtbc04@gmail.com to employee email via SMTP."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Monarch HR — Verification Code: {otp_code}"
        msg["From"] = f"Monarch HR Security <{SMTP_EMAIL}>"
        msg["To"] = to_email

        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; }
                .container { max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
                .header { background: linear-gradient(135deg, #1E293B, #0F172A); padding: 30px 20px; text-align: center; color: #ffffff; }
                .content { padding: 30px 25px; color: #334155; line-height: 1.6; }
                .otp-box { background: #FFF7ED; border: 2px dashed #F59E0B; border-radius: 12px; text-align: center; padding: 18px; margin: 25px 0; font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #B45309; }
                .footer { background: #F8FAFC; padding: 15px 25px; text-align: center; font-size: 12px; color: #94A3B8; border-top: 1px solid #E2E8F0; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin:0; font-size: 20px; letter-spacing: 1px;">MONARCH HR</h2>
                    <p style="margin:5px 0 0 0; font-size: 13px; opacity: 0.85;">Account Security & Verification</p>
                </div>
                <div class="content">
                    <p style="font-size: 15px; margin-top: 0;">Hello <strong>__EMP_NAME__</strong>,</p>
                    <p style="font-size: 14px; color: #475569;">You have requested a verification code to update your Monarch HR account password. Please use the One-Time Password (OTP) below to complete this action:</p>
                    
                    <div class="otp-box">__OTP_CODE__</div>
                    
                    <p style="font-size: 13px; color: #64748B;">⏱️ This verification code is valid for <strong>10 minutes</strong>. If you did not request this password change, please ignore this email or contact the HR department immediately.</p>
                </div>
                <div class="footer">
                    &copy; 2026 Monarch Surveyors & Engineering Consultants Ltd. • Automated Security Alert
                </div>
            </div>
        </body>
        </html>
        """.replace("__EMP_NAME__", str(employee_name)).replace("__OTP_CODE__", str(otp_code))
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP_SSL(SMTP_SERVER, 465, timeout=12) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"[SUCCESS] Password reset OTP sent to {to_email} via {SMTP_EMAIL}")
        return True, None
    except Exception as e:
        logger.error(f"[ERROR] Failed to send email via SMTP ({SMTP_EMAIL}): {e}")
        return False, str(e)


@app.route('/api/auth/send-password-otp', methods=['POST'])
@token_required
def send_password_otp():
    """Generates a secure 6-digit OTP, creates a signed JWT otp_token, and sends an email via monarchtbc04@gmail.com."""
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    try:
        user = get_user_by_identifier(None, emp_id)
        if not user:
            return jsonify({'error': 'Employee profile not found'}), 404

        target_email = (user.get('personal_email') or user.get('username') or '').strip()
        if not target_email or '@' not in target_email:
            return jsonify({
                'error': 'No valid email address linked with your profile. Please save your email address in Profile first.'
            }), 400

        # Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        otp_hash = hashlib.sha256(f"{otp_code}:{JWT_SECRET}".encode('utf-8')).hexdigest()
        nonce = str(uuid.uuid4())

        # Generate token with 10-minute expiry
        exp_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
        otp_token = jwt.encode({
            'emp_id': user['emp_id'],
            'user_id': str(user['id']),
            'email': target_email,
            'otp_hash': otp_hash,
            'nonce': nonce,
            'purpose': 'password_change',
            'exp': exp_time
        }, JWT_SECRET, algorithm='HS256')

        # Send Email
        emp_name = user.get('name') or 'Employee'
        success, err = send_otp_email(target_email, otp_code, emp_name)
        if not success:
            logger.error(f"SMTP send failed: {err}")
            return jsonify({
                'error': f'Failed to send email to {mask_email(target_email)}. Please provide the 16-character Google App Password for {SMTP_EMAIL}. Details: {err}'
            }), 500

        return jsonify({
            'success': True,
            'message': f'Verification OTP sent to {mask_email(target_email)}',
            'masked_email': mask_email(target_email),
            'otp_token': otp_token
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/verify-password-otp-change', methods=['POST'])
def verify_password_otp_change():
    """Verifies OTP against the cryptographic otp_token and updates password in Monarch DB."""
    data = request.get_json() or {}
    otp = str(data.get('otp') or '').strip()
    otp_token = data.get('otp_token') or ''
    new_password = str(data.get('new_password') or '').strip()

    if not otp or not otp_token or not new_password:
        return jsonify({'error': 'OTP, verification token, and new password are required.'}), 400

    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters long.'}), 400

    try:
        payload = jwt.decode(otp_token, JWT_SECRET, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Verification OTP has expired (valid for 10 mins). Please request a new OTP.'}), 400
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid or corrupted security token. Please request a new OTP.'}), 400

    if payload.get('purpose') != 'password_change':
        return jsonify({'error': 'Invalid security token purpose.'}), 400

    nonce = payload.get('nonce')
    if nonce in USED_OTP_NONCES:
        return jsonify({'error': 'This OTP has already been used. Please request a fresh OTP.'}), 400

    # Verify OTP match
    expected_hash = payload.get('otp_hash')
    submitted_hash = hashlib.sha256(f"{otp}:{JWT_SECRET}".encode('utf-8')).hexdigest()

    if submitted_hash != expected_hash:
        return jsonify({'error': 'Incorrect OTP entered. Please check and try again.'}), 400

    # Mark nonce as consumed
    USED_OTP_NONCES.add(nonce)

    emp_id = payload.get('emp_id')
    user_id = payload.get('user_id')

    # Hash new password with bcrypt
    hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    try:
        conn_m = get_monarch_connection()
        cur_m = conn_m.cursor()

        # Update in users table
        cur_m.execute("""
            UPDATE users
            SET password = %s,
                password_hash = %s
            WHERE id::text = %s OR employee_no::text = %s OR LOWER(username) = LOWER(%s);
        """, (hashed_pw, hashed_pw, str(user_id), str(emp_id), str(emp_id)))

        conn_m.commit()
        cur_m.close()
        conn_m.close()

        logger.info(f"[SUCCESS] Password updated successfully for employee ID {emp_id}")
        return jsonify({
            'success': True,
            'message': 'Password changed successfully! You can now log in with your new password.'
        })
    except Exception as e:
        logger.error(f"Error updating password in database: {e}")
        return jsonify({'error': f'Failed to update password: {str(e)}'}), 500


@app.route('/api/auth/change-password', methods=['POST'])
@token_required
def change_password():
    """Allows an authenticated user to change their password using their current password."""
    data = request.get_json() or {}
    old_password = str(data.get('old_password') or '').strip()
    new_password = str(data.get('new_password') or '').strip()

    if not old_password or not new_password:
        return jsonify({'error': 'Current password and new password are required.'}), 400

    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters long.'}), 400

    emp_id = str(request.user.get('emp_id') or request.user.get('id') or request.user.get('employee_no') or '').strip()
    try:
        user = get_user_by_identifier(None, emp_id)
        if not user:
            return jsonify({'error': 'User account not found.'}), 404

        if not verify_user_password(user, old_password):
            return jsonify({'error': 'Incorrect current password. Please try again.'}), 400

        # Hash new password with bcrypt
        hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        conn_m = get_monarch_connection()
        cur_m = conn_m.cursor()
        clean_eid = str(user.get('employee_no') or user.get('emp_id') or emp_id).strip()
        cur_m.execute("""
            UPDATE users
            SET password = %s,
                password_hash = %s
            WHERE id::text = %s OR employee_no::text = %s OR LOWER(username) = LOWER(%s);
        """, (hashed_pw, hashed_pw, str(user['id']), clean_eid, clean_eid))

        conn_m.commit()
        cur_m.close()
        conn_m.close()

        logger.info(f"[SUCCESS] Password updated successfully for employee ID {clean_eid}")
        return jsonify({
            'success': True,
            'message': 'Password updated successfully!'
        })
    except Exception as e:
        logger.error(f"Error updating password in change_password: {e}", exc_info=True)
        return jsonify({'error': f'Failed to update password: {str(e)}'}), 500



def insert_phone_punch_log(conn, emp_id, punch_dt, direction, lat=None, lng=None, nearest_bldg=None, dist_m=None, in_geofence=True):
    """
    Inserts a raw punch record into data.devicelogs_M_YYYY (and public.devicelogs_M_YYYY)
    so mobile punches become part of the immutable raw punch logs ledger.
    """
    try:
        month = punch_dt.month
        year = punch_dt.year
        table_name = f"devicelogs_{month}_{year}"
        cur = conn.cursor()

        # Ensure data schema table exists
        cur.execute("CREATE SCHEMA IF NOT EXISTS data;")
        cur.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '{table_name}') THEN
                    CREATE TABLE IF NOT EXISTS data."{table_name}" (LIKE public."{table_name}" INCLUDING ALL);
                ELSE
                    CREATE TABLE IF NOT EXISTS data."{table_name}" (
                        devicelogid INTEGER PRIMARY KEY,
                        downloaddate TIMESTAMP WITHOUT TIME ZONE,
                        deviceid INTEGER,
                        userid TEXT,
                        logdate TIMESTAMP WITHOUT TIME ZONE,
                        direction TEXT,
                        attdirection TEXT,
                        alternateattdirection TEXT,
                        statuscode TEXT,
                        workcode TEXT,
                        duration INTEGER,
                        remarks TEXT,
                        smsflag INTEGER,
                        verificationmode TEXT,
                        isapproved INTEGER,
                        logrecordlocation TEXT,
                        managerremarks TEXT,
                        attmarkandroidimeino TEXT,
                        attenndancemarkingtype TEXT,
                        lattitude TEXT,
                        longitude TEXT,
                        networklattitude TEXT,
                        networklongitude TEXT,
                        networklocation TEXT,
                        approvedby TEXT,
                        logsapprovedeclinedatetime TIMESTAMP WITHOUT TIME ZONE,
                        temperature DOUBLE PRECISION,
                        temperaturestate INTEGER,
                        geofencelocationid INTEGER,
                        issuccessapi INTEGER,
                        apiresponsetext TEXT,
                        siomode TEXT
                    );
                END IF;
            END $$;
        """)

        # Get next unique devicelogid in high range (>= 90000000) so it never collides with biometric machine IDs
        cur.execute(f"""
            SELECT COALESCE(
                (SELECT MAX(devicelogid) FROM data."{table_name}" WHERE devicelogid >= 90000000),
                90000000
            ) + 1 AS next_id;
        """)
        next_id_row = cur.fetchone()
        next_id = next_id_row['next_id'] if next_id_row else 90000001

        lat_str = str(lat) if lat is not None else ''
        lng_str = str(lng) if lng is not None else ''
        bldg_str = nearest_bldg or 'Mobile App (GPS)'
        is_appr = 1 if (in_geofence or str(emp_id).strip().lstrip('0') == '1228') else 0
        dir_str = 'in' if direction == 'in' else 'out'
        rem_str = f"Distance: {dist_m}m" if dist_m is not None else None

        cur.execute(f"""
            INSERT INTO data."{table_name}" (
                devicelogid, downloaddate, deviceid, userid, logdate, direction,
                verificationmode, isapproved, logrecordlocation, attenndancemarkingtype,
                lattitude, longitude, managerremarks
            )
            VALUES (
                %s, %s, 99, %s, %s, %s,
                'GPS', %s, %s, 'Mobile GPS',
                %s, %s, %s
            )
            ON CONFLICT (devicelogid) DO NOTHING;
        """, (
            next_id, punch_dt, str(emp_id), punch_dt, dir_str,
            is_appr, bldg_str,
            lat_str, lng_str, rem_str
        ))

        cur.close()
    except Exception as e:
        logger.error(f"Error inserting phone punch to devicelogs: {e}")


@app.route('/api/attendance/clock-in', methods=['POST'])
@token_required
def clock_in():
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    emp_name = request.user.get('name', 'Employee')
    user_dept = request.user.get('department', '')
    raw_role = request.user.get('role', 'employee')
    user_role = normalize_role(raw_role)

    data = request.get_json() or {}
    lat = data.get('lat')
    lng = data.get('lng')

    loc_str = f"{lat},{lng}" if (lat is not None and lng is not None) else None
    geo_res = check_geofence(lat, lng)
    in_geofence = geo_res['in_geofence']
    nearest_bldg = geo_res['nearest_building']
    dist_m = geo_res['distance_meters']

    client_time_str = data.get('client_time')
    if client_time_str:
        try:
            client_dt = datetime.datetime.fromisoformat(str(client_time_str).replace('Z', '+00:00'))
            if client_dt.tzinfo is not None:
                client_dt = client_dt.astimezone(IST)
            today = client_dt.date()
            now_dt = client_dt.replace(tzinfo=None)
            now_time = client_dt.time().replace(microsecond=0)
        except Exception:
            today = get_ist_today()
            now_dt = get_ist_now().replace(tzinfo=None)
            now_time = get_ist_time()
    else:
        today = get_ist_today()
        now_dt = get_ist_now().replace(tzinfo=None)
        now_time = get_ist_time()

    try:
        # Fetch fresh user details from Monarch DB to guarantee accurate department and role
        u_info = get_user_by_identifier(None, emp_id)
        if u_info:
            emp_name = u_info.get('name') or emp_name
            user_dept = u_info.get('department') or user_dept
            raw_role = u_info.get('role') or raw_role
            user_role = normalize_role(raw_role)

        is_exempt_from_geofence = (
            str(emp_id).strip().lstrip('0') == '1228' 
            or (u_info and u_info.get('is_location_bound') is False)
        )

        if (lat is None or lng is None) and not is_exempt_from_geofence:
            return jsonify({
                'error': 'Location is required. Please turn ON your device GPS / Location before checking in.'
            }), 400

        if in_geofence or is_exempt_from_geofence:
            approval_status = 'Approved'
        elif user_role == 'teamleader':
            approval_status = 'Pending Manager Approval'
        elif user_role in ['seniorteamleader', 'manager', 'admin']:
            approval_status = 'Pending Manager Approval'
        else:
            approval_status = 'Pending TL Approval'

        conn = get_db_connection()
        cur = conn.cursor()

        # Check if already active in today's attendance
        cur.execute("""
            SELECT id, sign_in, sign_out 
            FROM attendance 
            WHERE (employee_id = %s OR employee_id = %s) AND date = %s
            ORDER BY id DESC LIMIT 1;
        """, (emp_id, emp_id.lstrip('0'), today))
        existing_att = cur.fetchone()

        if existing_att and existing_att.get('sign_in') and not existing_att.get('sign_out'):
            s_in_str = str(existing_att['sign_in'])
            cur.close()
            conn.close()
            return jsonify({
                'error': f'You are already clocked in (shift started at {s_in_str}). Please punch out before checking in again.',
                'session_id': existing_att['id']
            }), 400

        if existing_att and existing_att.get('sign_out'):
            s_out_str = str(existing_att['sign_out'])
            cur.close()
            conn.close()
            return jsonify({
                'error': f'You have already completed your punch out for today at {s_out_str}. Today\'s shift is completed.',
                'session_id': existing_att['id']
            }), 400

        location_str = nearest_bldg or 'Mobile App (GPS)'

        if existing_att:
            cur.execute("""
                UPDATE attendance
                SET sign_in = %s,
                    location = %s,
                    in_geofence = %s,
                    nearest_building = %s,
                    distance_meters = %s,
                    clock_in_lat = %s,
                    clock_in_lng = %s,
                    department = %s,
                    role = %s,
                    approval_status = %s
                WHERE id = %s
                RETURNING id;
            """, (
                now_time, location_str, in_geofence, nearest_bldg, dist_m,
                lat, lng, user_dept, user_role, approval_status, existing_att['id']
            ))
            att_row = cur.fetchone()
        else:
            cur.execute("""
                INSERT INTO attendance (
                    employee_id, employee_name, date, sign_in, location,
                    in_geofence, nearest_building, distance_meters,
                    clock_in_lat, clock_in_lng, department, role, approval_status
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                RETURNING id;
            """, (
                emp_id, emp_name, today, now_time, location_str,
                in_geofence, nearest_bldg, dist_m,
                lat, lng, user_dept, user_role, approval_status
            ))
            att_row = cur.fetchone()

        # Record raw punch in data.devicelogs_M_YYYY
        insert_phone_punch_log(conn, emp_id, now_dt, 'in', lat=lat, lng=lng, nearest_bldg=nearest_bldg, dist_m=dist_m, in_geofence=in_geofence)

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'session_id': att_row['id'],
            'in_geofence': in_geofence,
            'nearest_building': nearest_bldg,
            'distance_meters': dist_m,
            'approval_status': approval_status,
            'table_stored': 'attendance'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance/clock-out', methods=['POST'])
@token_required
def clock_out():
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    raw_role = request.user.get('role', 'employee')
    user_role = normalize_role(raw_role)

    u_info = get_user_by_identifier(None, emp_id)
    if u_info:
        raw_role = u_info.get('role') or raw_role
        user_role = normalize_role(raw_role)

    data = request.get_json() or {}
    lat = data.get('lat')
    lng = data.get('lng')

    geo_res = check_geofence(lat, lng)
    out_in_geofence = geo_res['in_geofence']
    out_nearest_bldg = geo_res['nearest_building']
    out_dist_m = geo_res['distance_meters']

    client_time_str = data.get('client_time')
    if client_time_str:
        try:
            client_dt = datetime.datetime.fromisoformat(str(client_time_str).replace('Z', '+00:00'))
            if client_dt.tzinfo is not None:
                client_dt = client_dt.astimezone(IST)
            today = client_dt.date()
            now_dt = client_dt.replace(tzinfo=None)
            now_time = client_dt.time().replace(microsecond=0)
        except Exception:
            today = get_ist_today()
            now_dt = get_ist_now().replace(tzinfo=None)
            now_time = get_ist_time()
    else:
        today = get_ist_today()
        now_dt = get_ist_now().replace(tzinfo=None)
        now_time = get_ist_time()

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Check active shift today in attendance table
        cur.execute("""
            SELECT id, sign_in, sign_out 
            FROM attendance 
            WHERE (employee_id = %s OR employee_id = %s) AND date = %s
            ORDER BY id DESC LIMIT 1;
        """, (emp_id, emp_id.lstrip('0'), today))
        active_record = cur.fetchone()

        if not active_record or not active_record.get('sign_in'):
            cur.close()
            conn.close()
            return jsonify({'error': 'No active clocked-in shift found. Please check in first.'}), 400

        s_out = active_record.get('sign_out')
        if s_out and (s_out == datetime.time(0, 0, 0) or str(s_out).startswith('00:00:00') or str(s_out) == '00:00'):
            s_out = None

        if s_out:
            s_out_str = str(s_out)
            cur.close()
            conn.close()
            return jsonify({
                'error': f'You have already completed your punch out for today at {s_out_str}. No active shift is running.'
            }), 400

        is_exempt_from_geofence = (
            str(emp_id).strip().lstrip('0') == '1228' 
            or (u_info and u_info.get('is_location_bound') is False)
        )

        if (lat is None or lng is None) and not is_exempt_from_geofence:
            cur.close()
            conn.close()
            return jsonify({
                'error': 'Location is required. Please turn ON your device GPS / Location before checking out.'
            }), 400

        if out_in_geofence or is_exempt_from_geofence:
            out_approval = 'Approved'
        elif user_role == 'teamleader':
            out_approval = 'Pending Manager Approval'
        elif user_role in ['seniorteamleader', 'manager', 'admin']:
            out_approval = 'Pending Manager Approval'
        else:
            out_approval = 'Pending TL Approval'

        cur.execute("""
            UPDATE attendance
            SET sign_out = %s,
                clock_out_lat = %s,
                clock_out_lng = %s,
                clock_out_in_geofence = %s,
                clock_out_distance_meters = %s,
                approval_status = %s
            WHERE id = %s
            RETURNING id;
        """, (now_time, lat, lng, out_in_geofence, out_dist_m, out_approval, active_record['id']))
        updated_row = cur.fetchone()

        # Record raw punch in data.devicelogs_M_YYYY
        insert_phone_punch_log(conn, emp_id, now_dt, 'out', lat=lat, lng=lng, nearest_bldg=out_nearest_bldg, dist_m=out_dist_m, in_geofence=out_in_geofence)

        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'session_id': updated_row['id'],
            'clock_out_in_geofence': out_in_geofence,
            'nearest_building': out_nearest_bldg,
            'distance_meters': out_dist_m,
            'approval_status': out_approval,
            'table_stored': 'attendance'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance/me', methods=['GET'])
@token_required
def get_my_attendance():
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, employee_id, employee_name, date, sign_in, sign_out, location,
                   in_geofence, nearest_building, distance_meters, clock_in_lat, clock_in_lng,
                   clock_out_lat, clock_out_lng, clock_out_in_geofence, clock_out_distance_meters,
                   department, role, approval_status, reviewed_by, reviewed_at, rejection_reason
            FROM attendance
            WHERE employee_id = %s OR employee_id = %s OR employee_id = %s
            ORDER BY date DESC, sign_in DESC;
        """, (emp_id, emp_id.lower(), emp_id.lstrip('0')))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        formatted_rows = [format_attendance_record(r) for r in rows]
        return jsonify(formatted_rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/team/punch-requests', methods=['GET'])
@token_required
def get_team_punch_requests():
    """
    Returns pending out-of-range punch requests:
    - TeamLeader: pending punches from employees in their department requiring TL approval ('Pending TL Approval')
    - SeniorTeamLeader / Manager / Admin: pending punches within their oversight
    """
    caller_emp_id = str(request.user.get('emp_id') or request.user.get('id'))

    try:
        caller = get_user_by_identifier(None, caller_emp_id)
        if not caller:
            user_role = normalize_role(request.user.get('role'))
            user_dept = (request.user.get('department') or '').strip()
        else:
            user_role = normalize_role(caller.get('role') or request.user.get('role'))
            user_dept = (caller.get('department') or request.user.get('department') or '').strip()

        if user_role not in ['teamleader', 'seniorteamleader', 'manager', 'admin']:
            return jsonify({'punch_requests': [], 'count': 0})

        # Load users map from Monarch DB
        users_map = load_monarch_users_map()
        all_users = list(users_map.values())

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, employee_id, employee_name, date, sign_in, sign_out, location,
                   in_geofence, nearest_building, distance_meters, clock_in_lat, clock_in_lng,
                   clock_out_lat, clock_out_lng, clock_out_in_geofence, clock_out_distance_meters,
                   department, role, approval_status, reviewed_by, reviewed_at, rejection_reason
            FROM attendance
            WHERE approval_status IN ('Pending TL Approval', 'Pending Approval', 'Pending Sr TL Approval', 'Pending Manager Approval')
              AND employee_id != %s
              AND LOWER(employee_id) != LOWER(%s)
            ORDER BY 
              CASE 
                WHEN approval_status = 'Pending Manager Approval' THEN 1
                WHEN approval_status IN ('Pending Sr TL Approval', 'Pending TL Approval', 'Pending Approval') THEN 2
                ELSE 3
              END,
              date DESC, sign_in DESC;
        """, (caller_emp_id, caller_emp_id))
        raw_rows = cur.fetchall()
        cur.close()
        conn.close()

        filtered_rows = []
        for r in raw_rows:
            e_id = str(r['employee_id']).strip()
            u_info = (
                users_map.get(e_id) or 
                users_map.get(e_id.lstrip('0')) or 
                users_map.get(str(r.get('employee_name') or '').lower().strip()) or 
                users_map.get(f"norm_{normalize_person_name(r.get('employee_name'))}") or 
                {}
            )
            
            # Enrich row with live Monarch user metadata
            r_dept = (r.get('department') or u_info.get('department') or '').strip()
            r_name = r.get('employee_name') or u_info.get('name') or f"Employee {e_id}"
            r_role = r.get('role') or u_info.get('role') or 'Employee'
            r['department'] = r_dept
            r['employee_name'] = r_name
            r['role'] = r_role

            is_direct_sub = is_direct_reporting_manager(caller, u_info)
            emp_has_mgr = bool(u_info.get('reporting_manager') and str(u_info.get('reporting_manager')).strip())

            # 1. Direct 1-on-1 Reporting Manager match:
            if is_direct_sub:
                filtered_rows.append(r)
            # 2. SuperAdmin top-level oversight:
            elif user_role == 'admin':
                filtered_rows.append(r)
            # 3. Department Team Leader / Senior Team Leader:
            elif user_role in ['teamleader', 'seniorteamleader'] and (are_departments_matching(r_dept, user_dept) or not user_dept):
                filtered_rows.append(r)
            # 4. If employee has an assigned reporting manager who is someone else, route to that manager:
            elif emp_has_mgr:
                continue
            # 5. Department Manager fallback:
            elif user_role == 'manager':
                if are_departments_matching(r_dept, user_dept) or not user_dept:
                    filtered_rows.append(r)

        formatted = [format_attendance_record(r) for r in filtered_rows]
        return jsonify({'punch_requests': formatted, 'count': len(formatted)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/team/punch-requests/<int:attendance_id>/action', methods=['POST'])
@token_required
def take_punch_action(attendance_id):
    """Approve or Reject a pending punch request with direct 1-on-1 manager routing and team leader oversight."""
    caller_emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    reviewer_name = request.user.get('name') or request.user.get('full_name') or 'Supervisor'

    data = request.get_json() or {}
    action = (data.get('action') or '').lower().strip()
    reason = data.get('reason', '')

    if action not in ['approve', 'reject']:
        return jsonify({'error': 'Invalid action. Must be approve or reject.'}), 400

    now_ts = get_ist_now().replace(tzinfo=None)

    try:
        caller = get_user_by_identifier(None, caller_emp_id)
        user_role = normalize_role(caller.get('role') if caller else request.user.get('role'))
        user_dept = ((caller.get('department') if caller else request.user.get('department')) or '').strip()

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT * FROM attendance WHERE id = %s;", (attendance_id,))
        current_att = cur.fetchone()
        if not current_att:
            cur.close()
            conn.close()
            return jsonify({'error': 'Punch record not found'}), 404

        target_emp_id = str(current_att.get('employee_id') or '').strip()
        users_map = load_monarch_users_map()
        target_user = (
            users_map.get(target_emp_id) or 
            users_map.get(target_emp_id.lstrip('0')) or 
            users_map.get(str(current_att.get('employee_name') or '').lower().strip()) or 
            users_map.get(f"norm_{normalize_person_name(current_att.get('employee_name'))}") or 
            {}
        )

        is_direct_mgr = is_direct_reporting_manager(caller, target_user)
        emp_has_mgr = bool(target_user.get('reporting_manager') and str(target_user.get('reporting_manager')).strip())

        # Authorized if: Admin, Direct 1-on-1 reporting manager, or unassigned fallback in matching department
        is_authorized = (
            user_role == 'admin' or
            is_direct_mgr or
            (user_role in ['manager', 'seniorteamleader', 'teamleader'] and (are_departments_matching(user_dept, current_att.get('department')) or not user_dept))
        )

        if not is_authorized:
            cur.close()
            conn.close()
            return jsonify({'error': 'Forbidden: Only the assigned Direct Reporting Manager, Team Leader, or Administrator can review this punch request.'}), 403

        role_label = 'Mgr' if (is_direct_mgr or user_role == 'manager') else ('Sr TL' if user_role == 'seniorteamleader' else ('TL' if user_role == 'teamleader' else 'Admin'))
        
        if action == 'reject':
            new_status = 'Rejected'
            reviewed_by = f"{role_label}: {reviewer_name}"
        else:
            new_status = 'Approved'
            tl_rev = current_att.get('reviewed_by') or ''
            if tl_rev and role_label not in tl_rev:
                reviewed_by = f"{tl_rev} | {role_label}: {reviewer_name}"
            else:
                reviewed_by = f"{role_label}: {reviewer_name}"

        cur.execute("""
            UPDATE attendance
            SET approval_status = %s,
                reviewed_by = %s,
                reviewed_at = %s,
                rejection_reason = %s
            WHERE id = %s
            RETURNING id, employee_id, employee_name, date, sign_in, sign_out, location,
                      in_geofence, nearest_building, distance_meters, clock_in_lat, clock_in_lng,
                      clock_out_lat, clock_out_lng, clock_out_in_geofence, clock_out_distance_meters,
                      department, role, approval_status, reviewed_by, reviewed_at, rejection_reason;
        """, (new_status, reviewed_by, now_ts, reason if action == 'reject' else None, attendance_id))
        updated = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not updated:
            return jsonify({'error': 'Failed to update punch record'}), 500

        msg = (
            f'Punch request {action}ed successfully'
            if action == 'reject'
            else f'Punch request approved successfully by {role_label}: {reviewer_name}'
        )

        return jsonify({
            'success': True,
            'message': msg,
            'approval_status': new_status,
            'record': format_attendance_record(updated)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance/regularize', methods=['POST'])
@token_required
def regularize_attendance():
    """
    Option 1: Employee submits a Missed Punch / Attendance Regularization request.
    Payload: {
        "date": "2026-10-03",
        "sign_in": "09:30:00",
        "sign_out": "18:30:00",
        "reason": "Forgot to punch out on biometric machine"
    }
    """
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    emp_name = str(request.user.get('name') or request.user.get('full_name') or 'Employee')
    user_dept = str(request.user.get('department') or 'General')
    user_role = str(request.user.get('role') or 'Employee')

    data = request.get_json() or {}
    req_date = data.get('date')
    sign_in = data.get('sign_in')
    sign_out = data.get('sign_out')
    reason = (data.get('reason') or '').strip()

    if not req_date:
        return jsonify({'error': 'date is required (YYYY-MM-DD)'}), 400
    if not sign_in and not sign_out:
        return jsonify({'error': 'At least one of sign_in or sign_out is required'}), 400
    if not reason:
        return jsonify({'error': 'Reason for regularization is mandatory'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, sign_in, sign_out FROM attendance
            WHERE (employee_id = %s OR employee_id = %s) AND date = %s
            LIMIT 1;
        """, (emp_id, emp_id.lstrip('0'), req_date))
        existing = cur.fetchone()

        loc_str = f"Regularization Request: {reason}"

        if existing:
            att_id = existing['id']
            cur.execute("""
                UPDATE attendance
                SET sign_in = COALESCE(%s, sign_in),
                    sign_out = COALESCE(%s, sign_out),
                    approval_status = 'Pending TL Approval',
                    location = %s,
                    rejection_reason = NULL
                WHERE id = %s
                RETURNING *;
            """, (sign_in or None, sign_out or None, loc_str, att_id))
            rec = cur.fetchone()
        else:
            cur.execute("""
                INSERT INTO attendance (
                    employee_id, employee_name, date, sign_in, sign_out,
                    location, in_geofence, department, role, approval_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s, 'Pending TL Approval')
                RETURNING *;
            """, (emp_id, emp_name, req_date, sign_in or None, sign_out or None, loc_str, user_dept, user_role))
            rec = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Regularization request submitted to your Team Leader for approval.',
            'record': format_attendance_record(rec)
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/attendance/override', methods=['POST'])
@token_required
@admin_required
def admin_override_attendance():
    """
    Option 2: Admin or HR directly updates / inserts an attendance record for any employee and date.
    Payload: {
        "employee_id": "1009",
        "date": "2026-10-03",
        "sign_in": "09:30:00",
        "sign_out": "18:30:00",
        "status": "Approved",
        "note": "HR Direct Manual Punch Correction"
    }
    """
    admin_name = str(request.user.get('name') or request.user.get('full_name') or 'Admin')
    data = request.get_json() or {}
    emp_id = str(data.get('employee_id') or '').strip()
    req_date_str = data.get('date')
    sign_in = data.get('sign_in')
    sign_out = data.get('sign_out')
    approval_status = data.get('status', 'Approved')
    note = (data.get('note') or 'Admin Direct Correction').strip()

    if not emp_id or not req_date_str:
        return jsonify({'error': 'employee_id and date required'}), 400

    try:
        user_info = get_user_by_identifier(None, emp_id)
        emp_name = user_info.get('name') if user_info else f"Employee {emp_id}"
        dept = user_info.get('department') if user_info else 'General'
        role = user_info.get('role') if user_info else 'Employee'

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id FROM attendance
            WHERE (employee_id = %s OR employee_id = %s) AND date = %s
            LIMIT 1;
        """, (emp_id, emp_id.lstrip('0'), req_date_str))
        existing = cur.fetchone()

        now_ts = get_ist_now().replace(tzinfo=None)
        loc_str = f"Admin Manual Correction ({note})"

        if existing:
            cur.execute("""
                UPDATE attendance
                SET sign_in = COALESCE(%s, sign_in),
                    sign_out = COALESCE(%s, sign_out),
                    approval_status = %s,
                    reviewed_by = %s,
                    reviewed_at = %s,
                    location = %s
                WHERE id = %s
                RETURNING *;
            """, (sign_in or None, sign_out or None, approval_status, f"Admin: {admin_name}", now_ts, loc_str, existing['id']))
            rec = cur.fetchone()
        else:
            cur.execute("""
                INSERT INTO attendance (
                    employee_id, employee_name, date, sign_in, sign_out,
                    location, in_geofence, department, role, approval_status,
                    reviewed_by, reviewed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s, %s)
                RETURNING *;
            """, (emp_id, emp_name, req_date_str, sign_in or None, sign_out or None, loc_str, dept, role, approval_status, f"Admin: {admin_name}", now_ts))
            rec = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Attendance for {emp_name} on {req_date_str} successfully updated.',
            'record': format_attendance_record(rec)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/location', methods=['POST'])
@token_required
def update_location():
    data = request.get_json() or {}
    session_id = data.get('session_id')
    lat = data.get('lat')
    lng = data.get('lng')

    if not session_id or lat is None or lng is None:
        return jsonify({'error': 'Missing session_id or coordinates'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM attendance WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Session not found'}), 404

        cur.close()
        conn.close()
        return jsonify({'success': True, 'session_id': session_id, 'lat': lat, 'lng': lng})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance/history', methods=['GET'])
@token_required
def get_attendance_history():
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, employee_id, employee_name, date, sign_in, sign_out, location,
                   in_geofence, nearest_building, distance_meters, clock_in_lat, clock_in_lng,
                   clock_out_lat, clock_out_lng, clock_out_in_geofence, clock_out_distance_meters,
                   department, role, approval_status, reviewed_by, reviewed_at, rejection_reason
            FROM attendance
            WHERE employee_id = %s OR employee_id = %s OR employee_id = %s
            ORDER BY date DESC, sign_in DESC
            LIMIT 100;
        """, (emp_id, emp_id.lower(), emp_id.lstrip('0')))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([format_attendance_record(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/today-attendance', methods=['GET'])
@app.route('/api/team/hierarchy', methods=['GET'])
@app.route('/api/team/overview', methods=['GET'])
@token_required
def get_admin_today_attendance():
    """
    Returns live today attendance overview for employees in Monarch directory.
    Scopes output dynamically by caller role: Team Leader, Senior Team Leader, Manager, Admin.
    Supports 1-on-1 direct reporting manager subordinates mapping.
    """
    caller_emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    today = get_ist_today()

    try:
        caller = get_user_by_identifier(None, caller_emp_id)
        if not caller:
            return jsonify({'error': 'Caller not found in Monarch user directory'}), 404

        caller_role = normalize_role(caller.get('role'))
        caller_dept = caller.get('department') or ''

        # 1. Fetch all users from Monarch DB
        all_monarch_users = load_all_monarch_users()

        # 2. Fetch today's attendance records from Monarch DB (data.attendance)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, employee_id, employee_name, date, sign_in, sign_out, location,
                   in_geofence, nearest_building, distance_meters, department, role, approval_status
            FROM attendance
            WHERE date = %s;
        """, (today,))
        att_rows = cur.fetchall()
        today_att_map = {}
        for ar in att_rows:
            eid = str(ar['employee_id']).strip()
            today_att_map[eid] = ar
            today_att_map[eid.lstrip('0')] = ar

        # 3. Fetch pending leaves from Indian_Railway DB
        cur.execute("""
            SELECT id, employee_id, department, status
            FROM leaves
            WHERE LOWER(status) LIKE '%pending%';
        """)
        pending_leaves = cur.fetchall()
        cur.close()
        conn.close()

        # Build today members list
        formatted_all = []
        for u in all_monarch_users:
            eid = u['emp_id']
            att = today_att_map.get(eid) or today_att_map.get(eid.lstrip('0'))
            s_in = str(att['sign_in']) if att and att.get('sign_in') else None
            s_out = str(att['sign_out']) if att and att.get('sign_out') else None
            status = 'Not Clocked In'
            if s_in:
                status = 'Clocked Out' if s_out else 'Clocked In'

            formatted_all.append({
                'id': str(u['id']),
                'emp_id': eid,
                'employee_no': u.get('employee_no'),
                'name': u['name'],
                'role': u['role'] or 'Employee',
                'normalized_role': normalize_role(u['role']),
                'department': u['department'] or 'General',
                'designation': u['designation'] or '',
                'phone_number': u.get('mobile_number') or '',
                'reporting_manager': u.get('reporting_manager') or '',
                'today_status': status,
                'sign_in': s_in,
                'sign_out': s_out,
                'location': att.get('location') if att else None,
            })

        # 1. Direct 1-on-1 Subordinates of caller:
        direct_subordinates = [
            m for m in formatted_all
            if is_direct_reporting_manager(caller, m) and m['emp_id'].lower() != caller_emp_id.lower()
        ]

        # 2. Team Leader Scope:
        if caller_role == 'teamleader':
            if direct_subordinates:
                dept_members = direct_subordinates
            else:
                dept_members = [
                    m for m in formatted_all
                    if are_departments_matching(m['department'], caller_dept)
                    and m['emp_id'].lower() != caller_emp_id.lower()
                ]

            dept_ids = {m['emp_id'].lower() for m in dept_members}
            tl_pending_count = 0
            for pr in pending_leaves:
                p_emp = str(pr.get('employee_id') or '').strip().lower()
                if p_emp != caller_emp_id.lower() and (p_emp in dept_ids or p_emp.lstrip('0') in dept_ids):
                    tl_pending_count += 1

            return jsonify({
                'level': 'teamleader',
                'caller_role': caller.get('role'),
                'department': caller_dept,
                'members_count': len(dept_members),
                'members': dept_members,
                'all_members': dept_members,
                'direct_subordinates': direct_subordinates,
                'pending_approvals_count': tl_pending_count,
            })

        # 3. Senior Team Leader Scope:
        if caller_role == 'seniorteamleader':
            if direct_subordinates:
                dept_members = direct_subordinates
            else:
                dept_members = [
                    m for m in formatted_all
                    if are_departments_matching(m['department'], caller_dept)
                    and m['emp_id'].lower() != caller_emp_id.lower()
                ]

            dept_ids = {m['emp_id'].lower() for m in dept_members}
            senior_tl_pending_count = 0
            for pr in pending_leaves:
                p_emp = str(pr.get('employee_id') or '').strip().lower()
                if p_emp != caller_emp_id.lower() and (p_emp in dept_ids or p_emp.lstrip('0') in dept_ids):
                    senior_tl_pending_count += 1

            team_leaders = [
                m for m in dept_members
                if m['normalized_role'] == 'teamleader'
            ]

            return jsonify({
                'level': 'seniorteamleader',
                'caller_role': caller.get('role'),
                'department': caller_dept,
                'team_leaders_count': len(team_leaders),
                'members_count': len(dept_members),
                'members': dept_members,
                'team_leaders': team_leaders,
                'pending_approvals_count': senior_tl_pending_count,
                'all_members': dept_members,
                'direct_subordinates': direct_subordinates,
            })

        # 4. Manager / Admin / Employee Scope:
        if caller_role == 'manager':
            # Manager sees their direct 1-on-1 reporting subordinates
            if direct_subordinates:
                my_team_members = direct_subordinates
            else:
                my_team_members = [
                    m for m in formatted_all
                    if are_departments_matching(m['department'], caller_dept)
                    and m['emp_id'].lower() != caller_emp_id.lower()
                ]
        elif caller_role == 'admin':
            # Admin sees all employees
            my_team_members = [m for m in formatted_all if m['emp_id'].lower() != caller_emp_id.lower()]
        else:
            # Regular employee (not admin, manager, or team leader)
            if direct_subordinates:
                my_team_members = direct_subordinates
            else:
                return jsonify({
                    'level': 'employee',
                    'caller_role': caller.get('role') or 'employee',
                    'department': caller_dept,
                    'senior_team_leaders_count': 0,
                    'team_leaders_count': 0,
                    'employees_count': 0,
                    'pending_approvals_count': 0,
                    'members_count': 0,
                    'senior_team_leaders': [],
                    'team_leaders': [],
                    'departments': [],
                    'members': [],
                    'all_members': [],
                    'direct_subordinates': []
                })

        senior_team_leaders = [
            m for m in my_team_members
            if m['normalized_role'] == 'seniorteamleader'
        ]
        team_leaders = [
            m for m in my_team_members
            if m['normalized_role'] == 'teamleader'
        ]
        employees = [
            m for m in my_team_members
            if m['normalized_role'] == 'employee'
        ]

        # Department breakdown
        dept_map = {}
        for m in my_team_members:
            d = m['department'] or 'General'
            if d not in dept_map:
                dept_map[d] = {'department': d, 'senior_team_leaders': [], 'team_leaders': [], 'employees': [], 'total_count': 0, 'present_count': 0}
            dept_map[d]['total_count'] += 1
            if m['today_status'] in ['Clocked In', 'Clocked Out']:
                dept_map[d]['present_count'] += 1
            if m['normalized_role'] == 'seniorteamleader':
                dept_map[d]['senior_team_leaders'].append(m)
            elif m['normalized_role'] == 'teamleader':
                dept_map[d]['team_leaders'].append(m)
            elif m['normalized_role'] == 'employee':
                dept_map[d]['employees'].append(m)

        team_emp_ids = {m['emp_id'].lower() for m in my_team_members}
        manager_pending_count = 0
        for pr in pending_leaves:
            p_emp = str(pr.get('employee_id') or '').strip().lower()
            if caller_role == 'admin' or p_emp in team_emp_ids or p_emp.lstrip('0') in team_emp_ids:
                manager_pending_count += 1

        return jsonify({
            'level': 'manager' if caller_role == 'manager' else 'admin',
            'caller_role': caller.get('role'),
            'department': caller_dept,
            'senior_team_leaders_count': len(senior_team_leaders),
            'team_leaders_count': len(team_leaders),
            'employees_count': len(employees),
            'pending_approvals_count': manager_pending_count,
            'senior_team_leaders': senior_team_leaders,
            'team_leaders': team_leaders,
            'departments': list(dept_map.values()),
            'members': my_team_members,
            'all_members': my_team_members,
            'direct_subordinates': direct_subordinates,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/team/leaves', methods=['GET'])
@token_required
def get_team_leaves():
    caller_emp_id = str(request.user.get('emp_id') or request.user.get('id'))

    try:
        caller = get_user_by_identifier(None, caller_emp_id)
        if not caller:
            return jsonify({'error': 'Caller not found in Monarch user directory'}), 404

        caller_role = normalize_role(caller.get('role'))
        caller_dept = caller.get('department') or ''

        users_map = load_monarch_users_map()
        all_users = list(users_map.values())

        # Regular employee with no direct subordinates manages no one
        if caller_role == 'employee':
            direct_subs = [u for u in all_users if is_direct_reporting_manager(caller, u)]
            if not direct_subs:
                return jsonify([])

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, employee_id, employee_name, department AS leave_dept,
                   title, leave_type, start_date, end_date, days_count,
                   is_half_day, from_session, to_session,
                   status, applied_at, note, reviewed_by, reviewed_at, rejection_reason
            FROM leaves
            ORDER BY CASE WHEN LOWER(status) LIKE '%pending%' THEN 1 ELSE 2 END, applied_at DESC;
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        formatted_leaves = []
        for r in rows:
            emp_id = str(r.get('employee_id') or '').strip()
            if emp_id.lower() == caller_emp_id.lower() or emp_id.lstrip('0') == caller_emp_id.lstrip('0'):
                continue

            u_info = users_map.get(emp_id) or users_map.get(emp_id.lstrip('0'))
            if not u_info and r.get('employee_name'):
                raw_name = str(r['employee_name']).strip()
                u_info = users_map.get(raw_name.lower()) or users_map.get(f"norm_{normalize_person_name(raw_name)}")
            u_info = u_info or {}
            u_role = normalize_role(u_info.get('role'))
            dept = r.get('leave_dept') or u_info.get('department') or ''
            emp_name = r.get('employee_name') or u_info.get('name') or f"Employee {emp_id}"

            has_tl_in_dept = check_dept_has_leader(all_users, dept, 'teamleader')
            is_direct_sub = is_direct_reporting_manager(caller, u_info)
            emp_has_mgr = bool(u_info.get('reporting_manager') and str(u_info.get('reporting_manager')).strip())

            # 1. Direct 1-on-1 Reporting Manager:
            if is_direct_sub:
                pass
            # 2. SuperAdmin top-level oversight:
            elif caller_role == 'admin':
                pass
            # 3. Department Team Leader / Senior Team Leader:
            elif caller_role in ['teamleader', 'seniorteamleader'] and (are_departments_matching(dept, caller_dept) or not caller_dept):
                pass
            # 4. If employee has an assigned reporting manager who is someone else, strictly route to that manager:
            elif emp_has_mgr:
                continue
            # 4. Fallback for unassigned employees:
            elif caller_role == 'manager':
                if u_role in ['admin']:
                    continue
                if not are_departments_matching(dept, caller_dept):
                    continue
            elif caller_role == 'seniorteamleader':
                if u_role not in ['teamleader', 'employee']:
                    continue
                is_dept_match = are_departments_matching(dept, caller_dept)
                is_tl_fallback = (u_role == 'employee' and not has_tl_in_dept)
                if not (is_dept_match or is_tl_fallback):
                    continue
            elif caller_role == 'teamleader':
                if u_role != 'employee':
                    continue
                if caller_dept and not are_departments_matching(dept, caller_dept):
                    continue
            else:
                continue

            item = {
                'id': r['id'],
                'employee_id': emp_id,
                'employee_name': emp_name,
                'role': u_info.get('role') or 'Employee',
                'normalized_role': u_role,
                'department': dept or caller_dept or 'General',
                'designation': u_info.get('designation') or '',
                'title': r['title'],
                'leave_type': r['leave_type'],
                'start_date': r['start_date'].isoformat() if r.get('start_date') and hasattr(r['start_date'], 'isoformat') else str(r.get('start_date') or ''),
                'end_date': r['end_date'].isoformat() if r.get('end_date') and hasattr(r['end_date'], 'isoformat') else str(r.get('end_date') or ''),
                'days_count': float(r['days_count']) if r.get('days_count') is not None else 1.0,
                'is_half_day': bool(r.get('is_half_day') or (float(r.get('days_count') or 1.0) == 0.5)),
                'from_session': r.get('from_session') or 'Session 1',
                'to_session': r.get('to_session') or 'Session 2',
                'status': r['status'] or 'Pending Review',
                'applied_at': r['applied_at'].isoformat() if r.get('applied_at') and hasattr(r['applied_at'], 'isoformat') else str(r.get('applied_at') or ''),
                'note': r.get('note') or '',
                'reviewed_by': r.get('reviewed_by') or '',
                'reviewed_at': r['reviewed_at'].isoformat() if r.get('reviewed_at') and hasattr(r['reviewed_at'], 'isoformat') else str(r.get('reviewed_at') or ''),
                'rejection_reason': r.get('rejection_reason') or '',
            }
            formatted_leaves.append(item)

        return jsonify(formatted_leaves)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/team/leaves/<int:leave_id>/action', methods=['POST'])
@token_required
def review_team_leave(leave_id):
    caller_emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    data = request.get_json() or {}
    action = (data.get('action') or '').strip().lower()  # 'approve' or 'reject'
    note = data.get('note', '')

    if action not in ['approve', 'reject']:
        return jsonify({'error': 'Invalid action. Must be approve or reject.'}), 400

    new_status = 'Approved' if action == 'approve' else 'Rejected'
    now_ts = get_ist_now().replace(tzinfo=None)

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT * FROM leaves WHERE id = %s;", (leave_id,))
        leave_row = cur.fetchone()

        if not leave_row:
            cur.close()
            conn.close()
            return jsonify({'error': 'Leave request not found'}), 404

        caller = get_user_by_identifier(None, caller_emp_id)
        caller_role = normalize_role(caller.get('role') if caller else request.user.get('role'))
        caller_dept = ((caller.get('department') if caller else request.user.get('department')) or '').strip()

        users_map = load_monarch_users_map()
        target_emp_id = str(leave_row.get('employee_id') or '').strip()
        target_user = users_map.get(target_emp_id) or users_map.get(target_emp_id.lstrip('0'))
        if not target_user and leave_row.get('employee_name'):
            raw_name = str(leave_row['employee_name']).strip()
            target_user = users_map.get(raw_name.lower()) or users_map.get(f"norm_{normalize_person_name(raw_name)}")
        target_user = target_user or {}

        is_direct_mgr = is_direct_reporting_manager(caller, target_user)
        emp_has_mgr = bool(target_user.get('reporting_manager') and str(target_user.get('reporting_manager')).strip())

        is_authorized = (
            is_direct_mgr or
            (caller_role in ['teamleader', 'seniorteamleader', 'manager'] and (are_departments_matching(caller_dept, leave_row.get('department')) or not caller_dept))
        )

        if not is_authorized:
            cur.close()
            conn.close()
            return jsonify({'error': 'Forbidden: Only the assigned Direct Reporting Manager has approval authority for leave requests. Admin/HR cannot approve.'}), 403


        cur.execute("""
            UPDATE leaves
            SET status = %s,
                reviewed_by = %s,
                reviewed_at = %s,
                rejection_reason = %s
            WHERE id = %s
            RETURNING *;
        """, (new_status, caller_emp_id, now_ts, note if action == 'reject' else None, leave_id))
        updated_leave = cur.fetchone()

        # If approved and not Loss Of Pay, adjust leave balance
        if action == 'approve' and leave_row.get('leave_type') not in ['Loss Of Pay', 'Loss of Pay', 'LOP', 'Regularization', 'Attendance Regularization', 'Work From Home']:
            days = float(leave_row.get('days_count') or 1.0)
            target_emp = str(leave_row['employee_id'])
            cur.execute("""
                UPDATE leave_balances
                SET used_days = used_days + %s,
                    remaining_days = GREATEST(0.0, remaining_days - %s),
                    updated_at = NOW()
                WHERE employee_id = %s OR employee_id = %s;
            """, (days, days, target_emp, target_emp.lstrip('0')))

        conn.commit()
        cur.close()
        conn.close()

        if updated_leave.get('start_date') and hasattr(updated_leave['start_date'], 'isoformat'): updated_leave['start_date'] = updated_leave['start_date'].isoformat()
        if updated_leave.get('end_date') and hasattr(updated_leave['end_date'], 'isoformat'): updated_leave['end_date'] = updated_leave['end_date'].isoformat()
        if updated_leave.get('applied_at') and hasattr(updated_leave['applied_at'], 'isoformat'): updated_leave['applied_at'] = updated_leave['applied_at'].isoformat()
        if updated_leave.get('reviewed_at') and hasattr(updated_leave['reviewed_at'], 'isoformat'): updated_leave['reviewed_at'] = updated_leave['reviewed_at'].isoformat()

        return jsonify({
            'success': True,
            'status': new_status,
            'leave': dict(updated_leave)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/leaves', methods=['GET', 'POST'])
@app.route('/api/leaves/me', methods=['GET'])
@token_required
def handle_my_leaves():
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    emp_name = request.user.get('name') or 'Employee'
    user_dept = request.user.get('department') or ''

    if request.method == 'GET':
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                SELECT id, employee_id, employee_name, title, leave_type, start_date, end_date,
                       days_count, is_half_day, from_session, to_session,
                       status, applied_at, note, department, reviewed_by, reviewed_at, rejection_reason
                FROM leaves
                WHERE employee_id = %s OR employee_id = %s
                ORDER BY applied_at DESC;
            """, (emp_id, emp_id.lstrip('0')))
            leaves = cur.fetchall()

            cur.execute("""
                SELECT total_allotted, used_days, remaining_days
                FROM leave_balances
                WHERE employee_id = %s OR employee_id = %s OR employee_id = %s
                LIMIT 1;
            """, (emp_id, emp_id.lstrip('0'), f"E{emp_id.lstrip('0').zfill(4)}"))
            balance = cur.fetchone()

            cur.close()
            conn.close()

            if not balance:
                balance = {'total_allotted': 6.0, 'used_days': 0.0, 'remaining_days': 6.0}

            formatted_leaves = []
            for r in leaves:
                formatted_leaves.append({
                    'id': r['id'],
                    'title': r['title'],
                    'leave_type': r['leave_type'],
                    'start_date': r['start_date'].isoformat() if r.get('start_date') and hasattr(r['start_date'], 'isoformat') else str(r.get('start_date') or ''),
                    'end_date': r['end_date'].isoformat() if r.get('end_date') and hasattr(r['end_date'], 'isoformat') else str(r.get('end_date') or ''),
                    'days_count': float(r['days_count'] or 1.0),
                    'is_half_day': bool(r.get('is_half_day') or float(r.get('days_count') or 1.0) == 0.5),
                    'from_session': r.get('from_session') or '',
                    'to_session': r.get('to_session') or '',
                    'status': r['status'],
                    'applied_at': r['applied_at'].isoformat() if r.get('applied_at') and hasattr(r['applied_at'], 'isoformat') else str(r.get('applied_at') or ''),
                    'note': r.get('note') or '',
                    'department': r.get('department') or '',
                    'reviewed_by': r.get('reviewed_by') or '',
                    'reviewed_at': r['reviewed_at'].isoformat() if r.get('reviewed_at') and hasattr(r['reviewed_at'], 'isoformat') else str(r.get('reviewed_at') or ''),
                    'rejection_reason': r.get('rejection_reason') or '',
                })

            tot = float(balance['total_allotted']) if balance and balance.get('total_allotted') is not None else 6.0
            used = float(balance['used_days']) if balance and balance.get('used_days') is not None else 0.0
            rem = max(0.0, round(tot - used, 2))

            bal_obj = {
                'total_allotted': tot,
                'used_days': used,
                'remaining_days': rem,
            }
            return jsonify({
                'balance': bal_obj,
                'total_allotted': tot,
                'used_days': used,
                'remaining_days': rem,
                'leaves': formatted_leaves
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        data = request.get_json() or {}
        title = data.get('title')
        leave_type = data.get('leave_type', 'Earned Leave')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        from_session = data.get('from_session') or data.get('session') or 'Session 1'
        to_session = data.get('to_session') or 'Session 2'
        try:
            days_count = float(data.get('days_count') or 1.0)
        except (ValueError, TypeError):
            days_count = 1.0
        is_half_day = bool(data.get('is_half_day') or leave_type == 'Half Day Leave' or days_count == 0.5)
        note = data.get('note', '')

        if not title or not start_date or not end_date:
            return jsonify({'error': 'Title, start_date, and end_date are required'}), 400

        try:
            users_map = load_monarch_users_map()
            u_info = users_map.get(emp_id) or users_map.get(emp_id.lstrip('0')) or {}
            final_name = u_info.get('name') or emp_name
            final_dept = u_info.get('department') or user_dept

            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO leaves (
                    employee_id, employee_name, title, leave_type,
                    start_date, end_date, days_count, is_half_day, from_session, to_session,
                    status, note, department, applied_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending Review', %s, %s, NOW())
                RETURNING *;
            """, (emp_id, final_name, title, leave_type, start_date, end_date, days_count, is_half_day, from_session, to_session, note, final_dept))
            new_leave = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            if new_leave.get('start_date') and hasattr(new_leave['start_date'], 'isoformat'): new_leave['start_date'] = new_leave['start_date'].isoformat()
            if new_leave.get('end_date') and hasattr(new_leave['end_date'], 'isoformat'): new_leave['end_date'] = new_leave['end_date'].isoformat()
            if new_leave.get('applied_at') and hasattr(new_leave['applied_at'], 'isoformat'): new_leave['applied_at'] = new_leave['applied_at'].isoformat()

            return jsonify(dict(new_leave)), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500



@app.route('/api/leaves/summary', methods=['GET'])
@token_required
def get_leave_summary():
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT total_allotted, used_days, remaining_days
            FROM leave_balances
            WHERE employee_id = %s OR employee_id = %s OR employee_id = %s
            LIMIT 1;
        """, (emp_id, emp_id.lstrip('0'), f"E{emp_id.lstrip('0').zfill(4)}"))
        balance = cur.fetchone()
        cur.close()
        conn.close()

        if not balance:
            balance = {'total_allotted': 6.0, 'used_days': 0.0, 'remaining_days': 6.0}

        bal_obj = {
            'total_allotted': float(balance['total_allotted']),
            'used_days': float(balance['used_days']),
            'remaining_days': float(balance['remaining_days']),
        }
        return jsonify({
            'balance': bal_obj,
            'total_allotted': bal_obj['total_allotted'],
            'used_days': bal_obj['used_days'],
            'remaining_days': bal_obj['remaining_days'],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/team/attendance', methods=['GET'])
@token_required
def get_team_attendance():
    caller_emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    emp_id_filter = request.args.get('employee_id')

    try:
        caller = get_user_by_identifier(None, caller_emp_id)
        caller_role = normalize_role(caller.get('role') if caller else request.user.get('role'))
        caller_dept = (caller.get('department') if caller else request.user.get('department')) or ''

        conn = get_db_connection()
        cur = conn.cursor()

        if emp_id_filter:
            cur.execute("""
                SELECT id, employee_id, employee_name, date, sign_in, sign_out, location,
                       in_geofence, nearest_building, distance_meters, clock_in_lat, clock_in_lng,
                       clock_out_lat, clock_out_lng, clock_out_in_geofence, clock_out_distance_meters,
                       department, role, approval_status, reviewed_by, reviewed_at, rejection_reason
                FROM attendance
                WHERE employee_id = %s OR employee_id = %s
                ORDER BY date DESC, sign_in DESC
                LIMIT 50;
            """, (emp_id_filter, emp_id_filter.lstrip('0')))
            rows = cur.fetchall()
        else:
            users_map = load_monarch_users_map()
            direct_sub_ids = set()
            for u in users_map.values():
                if is_direct_reporting_manager(caller, u):
                    eid = str(u.get('employee_no') or u.get('emp_id') or '').strip()
                    if eid:
                        direct_sub_ids.add(eid)
                        direct_sub_ids.add(eid.lstrip('0'))

            cur.execute("""
                SELECT id, employee_id, employee_name, date, sign_in, sign_out, location,
                       in_geofence, nearest_building, distance_meters, clock_in_lat, clock_in_lng,
                       clock_out_lat, clock_out_lng, clock_out_in_geofence, clock_out_distance_meters,
                       department, role, approval_status, reviewed_by, reviewed_at, rejection_reason
                FROM attendance
                ORDER BY date DESC, sign_in DESC
                LIMIT 300;
            """)
            raw_rows = cur.fetchall()

            if direct_sub_ids:
                rows = [r for r in raw_rows if str(r.get('employee_id')).strip() in direct_sub_ids]
            elif caller_role in ['teamleader', 'seniorteamleader']:
                rows = [r for r in raw_rows if are_departments_matching(r.get('department'), caller_dept)]
            else:
                rows = raw_rows[:100]

        cur.close()
        conn.close()


        return jsonify([format_attendance_record(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Holidays & Admin API ──────────────────────────────────────────────────────

@app.route('/api/holidays', methods=['GET'])
def get_holidays():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, title, date, weekday FROM holidays ORDER BY date ASC;")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        for r in rows:
            if r.get('date') and hasattr(r['date'], 'isoformat'):
                r['date'] = r['date'].isoformat()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users', methods=['GET'])
@token_required
@admin_required
def admin_users():
    """Returns all employees from the Monarch database directory."""
    try:
        users = load_all_monarch_users()
        return jsonify(users)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/<int:user_id>', methods=['PUT', 'PATCH'])
@app.route('/api/admin/users/<string:user_id_str>', methods=['PUT', 'PATCH'])
@token_required
@admin_required
def update_user(user_id=None, user_id_str=None):
    """Updates user information in Monarch database."""
    data = request.get_json() or {}
    ident = user_id if user_id is not None else user_id_str
    full_name = data.get('full_name') or data.get('name')
    department = data.get('department')
    designation = data.get('designation')
    reporting_manager = data.get('reporting_manager') or data.get('manager')
    location = data.get('location')
    email = data.get('personal_email') or data.get('email')
    shift_timing = data.get('shift_timing') or data.get('shift')
    raw_phone = data.get('phone_number') or data.get('mobile_number')
    phone_number = None
    if raw_phone:
        digits = re.sub(r'\D', '', str(raw_phone))
        if len(digits) == 12 and digits.startswith('91'):
            phone_number = digits[2:]
        elif len(digits) == 11 and digits.startswith('0'):
            phone_number = digits[1:]
        elif len(digits) > 10:
            phone_number = digits[-10:]
        else:
            phone_number = digits
    role = data.get('role')
    employment_status = data.get('employment_status') or data.get('status')
    is_active = data.get('is_active')
    if is_active is None and employment_status:
        is_active = (str(employment_status).lower() == 'active')

    conn_m = None
    try:
        conn_m = get_monarch_connection()
        cur_m = conn_m.cursor()

        # Check by id or employee_no
        cur_m.execute("""
            SELECT id FROM data.users 
            WHERE id = %s OR employee_no = %s
            LIMIT 1;
        """, (int(ident) if str(ident).isdigit() else -1, int(ident) if str(ident).isdigit() else -1))
        existing = cur_m.fetchone()
        if not existing:
            return jsonify({'error': f'User not found for identifier: {ident}'}), 404

        actual_id = existing['id']

        cur_m.execute("""
            UPDATE data.users
            SET name = COALESCE(%s, name),
                department = COALESCE(%s, department),
                designation = COALESCE(%s, designation),
                reporting_manager = COALESCE(%s, reporting_manager),
                mobile_number = COALESCE(%s, mobile_number),
                personal_email = COALESCE(%s, personal_email),
                location = COALESCE(%s, location),
                shift_timing = COALESCE(%s, shift_timing),
                role = COALESCE(%s, role),
                employment_status = COALESCE(%s, employment_status),
                is_active = COALESCE(%s, is_active)
            WHERE id = %s
            RETURNING id, employee_no, name, username, department, designation, reporting_manager, mobile_number, personal_email, location, shift_timing, role, employment_status, is_active;
        """, (full_name, department, designation, reporting_manager, phone_number, email, location, shift_timing, role, employment_status, is_active, actual_id))
        updated = cur_m.fetchone()
        conn_m.commit()
        return jsonify(format_monarch_user(updated))
    except Exception as e:
        if conn_m:
            conn_m.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn_m:
            cur_m.close()
            conn_m.close()


@app.route('/api/admin/attendance/<employee_id>', methods=['GET'])
@token_required
@admin_required
def admin_get_user_attendance(employee_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, employee_id, employee_name, date, sign_in, sign_out, location,
                   in_geofence, nearest_building, distance_meters, clock_in_lat, clock_in_lng,
                   clock_out_lat, clock_out_lng, clock_out_in_geofence, clock_out_distance_meters,
                   department, role, approval_status, reviewed_by, reviewed_at, rejection_reason
            FROM attendance
            WHERE employee_id = %s OR employee_id = %s
            ORDER BY date DESC, sign_in DESC
            LIMIT 50;
        """, (employee_id, employee_id.lstrip('0')))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([format_attendance_record(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/leave-balance/<employee_id>', methods=['GET', 'PUT'])
@token_required
@admin_required
def admin_manage_leave_balance(employee_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if request.method == 'GET':
            cur.execute("""
                SELECT total_allotted, used_days, remaining_days
                FROM leave_balances
                WHERE employee_id = %s OR employee_id = %s OR employee_id = %s
                LIMIT 1;
            """, (employee_id, employee_id.lstrip('0'), f"E{employee_id.lstrip('0').zfill(4)}"))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row:
                row = {'total_allotted': 6.0, 'used_days': 0.0, 'remaining_days': 6.0}
            return jsonify({
                'employee_id': employee_id,
                'total_allotted': float(row['total_allotted']),
                'used_days': float(row['used_days']),
                'remaining_days': float(row['remaining_days']),
            })

        elif request.method == 'PUT':
            data = request.get_json() or {}
            total = float(data.get('total_allotted', 6.0))
            used = float(data.get('used_days', 0.0))
            remaining = float(data.get('remaining_days', total - used))

            cur.execute("""
                INSERT INTO leave_balances (employee_id, total_allotted, used_days, remaining_days, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (employee_id) DO UPDATE
                SET total_allotted = EXCLUDED.total_allotted,
                    used_days = EXCLUDED.used_days,
                    remaining_days = EXCLUDED.remaining_days,
                    updated_at = NOW()
                RETURNING total_allotted, used_days, remaining_days;
            """, (employee_id, total, used, remaining))
            updated = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            return jsonify({
                'employee_id': employee_id,
                'total_allotted': float(updated['total_allotted']),
                'used_days': float(updated['used_days']),
                'remaining_days': float(updated['remaining_days']),
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/leaves', methods=['GET'])
@token_required
@admin_required
def admin_get_all_leaves():
    try:
        users_map = load_monarch_users_map()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, employee_id, employee_name, department, title, leave_type,
                   start_date, end_date, days_count, status, applied_at, note,
                   reviewed_by, reviewed_at, rejection_reason
            FROM leaves
            ORDER BY applied_at DESC;
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        formatted = []
        for r in rows:
            emp_id = str(r['employee_id']).strip()
            u_info = users_map.get(emp_id) or users_map.get(emp_id.lstrip('0')) or {}
            emp_name = r.get('employee_name') or u_info.get('name') or f"Employee {emp_id}"
            dept = r.get('department') or u_info.get('department') or ''

            formatted.append({
                'id': r['id'],
                'employee_id': emp_id,
                'employee_name': emp_name,
                'department': dept,
                'title': r['title'],
                'leave_type': r['leave_type'],
                'start_date': r['start_date'].isoformat() if r.get('start_date') and hasattr(r['start_date'], 'isoformat') else str(r.get('start_date') or ''),
                'end_date': r['end_date'].isoformat() if r.get('end_date') and hasattr(r['end_date'], 'isoformat') else str(r.get('end_date') or ''),
                'days_count': float(r['days_count'] or 1.0),
                'status': r['status'],
                'applied_at': r['applied_at'].isoformat() if r.get('applied_at') and hasattr(r['applied_at'], 'isoformat') else str(r.get('applied_at') or ''),
                'note': r.get('note') or '',
                'reviewed_by': r.get('reviewed_by') or '',
                'reviewed_at': r['reviewed_at'].isoformat() if r.get('reviewed_at') and hasattr(r['reviewed_at'], 'isoformat') else str(r.get('reviewed_at') or ''),
                'rejection_reason': r.get('rejection_reason') or '',
            })

        return jsonify(formatted)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/attendance/edit', methods=['POST'])
@token_required
@admin_required
def admin_edit_attendance():
    """Allows Admin / SUMIT to edit check-in and check-out times of an attendance record."""
    data = request.get_json() or {}
    record_id = data.get('id')
    sign_in = data.get('sign_in')
    sign_out = data.get('sign_out')
    approval_status = data.get('approval_status')

    if not record_id:
        return jsonify({'error': 'Record ID is required'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE attendance
            SET sign_in = COALESCE(%s::time, sign_in),
                sign_out = COALESCE(%s::time, sign_out),
                approval_status = COALESCE(%s, approval_status)
            WHERE id = %s
            RETURNING *;
        """, (sign_in, sign_out, approval_status, record_id))
        updated = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not updated:
            return jsonify({'error': 'Attendance record not found'}), 404

        return jsonify(format_attendance_record(updated))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/holidays', methods=['POST'])
@token_required
@admin_required
def add_holiday():
    data = request.get_json() or {}
    title = data.get('title')
    h_date = data.get('date')
    weekday = data.get('weekday')

    if not title or not h_date:
        return jsonify({'error': 'Title and date required'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM holidays;")
        next_id = cur.fetchone()['next_id']
        cur.execute("""
            INSERT INTO holidays (id, title, date, weekday)
            VALUES (%s, %s, %s, %s)
            RETURNING *;
        """, (next_id, title, h_date, weekday))
        holiday = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if holiday and holiday.get('date') and hasattr(holiday['date'], 'isoformat'):
            holiday['date'] = holiday['date'].isoformat()
        return jsonify(holiday)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Work Entry & Task Timesheet API ──────────────────────────────────────────
@app.route('/api/work-entries/form-options', methods=['GET'])
def get_work_entry_form_options():
    """Fetches real project list, departments, tasks, and subtasks matching FOR_AKSHADA.py from Indian_Railway database."""
    projects = []
    departments = []
    tasks_by_dept = defaultdict(list)
    subtasks_by_task = defaultdict(list)

    try:
        conn_ir = get_ir_connection()
        cur_ir = conn_ir.cursor()

        # 1. Projects from team_site.project_master (matching FOR_AKSHADA.py)
        try:
            cur_ir.execute("""
                SELECT DISTINCT project_no 
                FROM team_site.project_master 
                WHERE project_no IS NOT NULL 
                  AND project_no != ''
                  AND project_no NOT LIKE '$%'
                  AND project_no NOT ILIKE '%RECYCLE%'
                  AND project_no NOT ILIKE '%REFERENCE PLEASE%'
                  AND project_no NOT ILIKE '%DO NOT TOUCH%'
                ORDER BY project_no;
            """)
            for r in cur_ir.fetchall():
                p_str = r['project_no'].strip()
                projects.append({'id': p_str, 'name': p_str})
        except Exception as e_p:
            logger.error(f"Error fetching projects from team_site.project_master: {e_p}")
            conn_ir.rollback()

        # 2. Departments from topology.department_master (matching FOR_AKSHADA.py)
        try:
            cur_ir.execute("""
                SELECT
                    dm.department AS dept,
                    COALESCE(sdm.department, mdm.department, 'Engineering') AS main_dept
                FROM topology.department_master dm
                LEFT JOIN topology.sub_department_master sdm
                       ON UPPER(TRIM(sdm.sub_department)) = UPPER(TRIM(dm.department))
                LEFT JOIN topology.main_department_master mdm
                       ON UPPER(TRIM(mdm.department)) = UPPER(TRIM(dm.department))
                WHERE UPPER(dm.department) NOT LIKE 'TEAM_%'
                ORDER BY main_dept, dept;
            """)
            for r in cur_ir.fetchall():
                d = r['dept'].strip()
                if d and d not in departments:
                    departments.append(d)
        except Exception as e_d:
            logger.error(f"Error fetching departments from topology.department_master: {e_d}")
            conn_ir.rollback()

        # 3. Tasks & Subtasks from topology.task_master & subtask_master (matching FOR_AKSHADA.py)
        try:
            cur_ir.execute("""
                SELECT t.id AS task_id, t.task, t.department, s.id AS subtask_id, s.subtask
                FROM topology.task_master t
                LEFT JOIN topology.subtask_master s ON s.task_id = t.id
                WHERE t.task IS NOT NULL AND t.task != ''
                ORDER BY t.department, t.task, s.subtask;
            """)
            for r in cur_ir.fetchall():
                dept = (r.get('department') or '').strip() or 'Engineering'
                tsk = (r.get('task') or '').strip()
                sub = (r.get('subtask') or '').strip() if r.get('subtask') else ''

                if tsk and tsk not in tasks_by_dept[dept]:
                    tasks_by_dept[dept].append(tsk)
                if tsk and sub and sub not in subtasks_by_task[tsk]:
                    subtasks_by_task[tsk].append(sub)
        except Exception as e_t:
            logger.error(f"Error fetching tasks/subtasks from topology: {e_t}")
            conn_ir.rollback()

        # 4. Check PMS user status if Authorization token is provided
        is_pms_user = True
        pms_error = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(' ')[1]
                payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
                user_eid = str(payload.get('employee_no') or payload.get('emp_id') or payload.get('id') or '').strip()
                clean_eid = user_eid.lstrip('0') or '0'
                cur_ir.execute("""
                    SELECT id FROM topology.users
                    WHERE emp_id = %s OR (emp_id IS NOT NULL AND LTRIM(emp_id, '0') = %s)
                    LIMIT 1;
                """, (user_eid, clean_eid))
                if not cur_ir.fetchone():
                    is_pms_user = False
                    pms_error = f"Employee ID #{user_eid} does not exist in PMS user directory. Work entry cannot be submitted."
            except Exception as e_tok:
                logger.debug(f"Optional token check in form-options: {e_tok}")

        cur_ir.close()
        conn_ir.close()
    except Exception as e:
        logger.error(f"Indian_Railway DB connection error in form options: {e}")

    # Ensure all departments from tasks are included
    for d in tasks_by_dept.keys():
        if d not in departments:
            departments.append(d)

    departments.sort()

    units = ['KM', 'M', 'Nos', 'Ton', 'SqM', 'CuM', 'Hrs', 'Points', 'Sheets', 'Km/Hr', 'Days']
    revisions = [
        'New',
        'R1',
        'R2',
        'R3',
        'Rework',
        'Trials',
        'Rev 0 — Initial Working Execution',
        'Rev 1 — Client Feedback Iteration',
        'Final',
    ]

    return jsonify({
        'projects': projects,
        'departments': departments,
        'tasks_by_dept': dict(tasks_by_dept),
        'subtasks_by_task': dict(subtasks_by_task),
        'units': units,
        'revisions': revisions,
        'is_pms_user': is_pms_user,
        'pms_error': pms_error,
    })


@app.route('/api/work-entries', methods=['GET'])
@token_required
def get_work_entries():
    """
    Get work entries exclusively from Indian_Railway DB (topology.daily_work & topology.work_entries).
    Supports filtering by ?date=YYYY-MM-DD or ?month=YYYY-MM or ?emp_id=...
    """
    emp_id = str(request.user.get('emp_id') or request.user.get('id'))
    role = request.user.get('role', 'employee')
    date_filter = request.args.get('date')
    month_filter = request.args.get('month')
    filter_emp_id = request.args.get('emp_id')

    try:
        rows = []
        params = []
        where_clauses = ["1=1"]

        if role not in ['admin', 'manager', 'hr', 'projectmanager', 'teamleader', 'seniorteamlead', 'subteamlead'] or not filter_emp_id:
            where_clauses.append("(employee_id = %s OR employee_id ILIKE %s)")
            params.extend([emp_id, emp_id])
        elif filter_emp_id:
            where_clauses.append("(employee_id = %s OR employee_id ILIKE %s)")
            params.extend([filter_emp_id, filter_emp_id])

        if date_filter:
            where_clauses.append("work_date = %s")
            params.append(date_filter)
        elif month_filter:
            where_clauses.append("TO_CHAR(work_date, 'YYYY-MM') = %s")
            params.append(month_filter)

        where_sql = " AND ".join(where_clauses)

        try:
            conn_ir = get_ir_connection()
            cur_ir = conn_ir.cursor()
            
            # Read from topology.daily_work (matching FOR_AKSHADA.py)
            cur_ir.execute(f"""
                SELECT id, employee_id, employee_name, work_date,
                       project_id, department, task, subtask,
                       quantity, qty_type, hours, minutes, revision,
                       remarks, status, created_at
                FROM topology.daily_work
                WHERE {where_sql}
                ORDER BY work_date DESC, created_at DESC LIMIT 100;
            """, tuple(params))
            rows = cur_ir.fetchall()
            cur_ir.close()
            conn_ir.close()
        except Exception as e_ir:
            logger.error(f"Indian_Railway DB daily_work read error: {e_ir}")

        result = []
        for r in rows:
            hrs = int(r.get('hours') or 0)
            mins = int(r.get('minutes') or 0)
            tot_hrs = round(hrs + (mins / 60.0), 2)
            result.append({
                'id': r['id'],
                'employee_id': r.get('employee_id'),
                'employee_name': r.get('employee_name'),
                'work_date': r['work_date'].isoformat() if r.get('work_date') and hasattr(r['work_date'], 'isoformat') else str(r.get('work_date') or ''),
                'project_id': str(r.get('project_id') or ''),
                'project_name': str(r.get('project_id') or ''),
                'department': r.get('department') or '',
                'task': r.get('task') or '',
                'subtask': r.get('subtask') or '',
                'quantity': float(r.get('quantity') or 0.0),
                'unit': r.get('qty_type') or 'KM',
                'hours': hrs,
                'minutes': mins,
                'total_hours': tot_hrs,
                'revision': r.get('revision') or 'New',
                'remarks': r.get('remarks') or '',
                'status': r.get('status') or 'Pending',
                'created_at': r['created_at'].isoformat() if r.get('created_at') and hasattr(r['created_at'], 'isoformat') else str(r.get('created_at') or '')
            })

        return jsonify({'work_entries': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/work-entries', methods=['POST'])
@token_required
def create_work_entry():
    """Submits a new Work Entry record strictly into Indian_Railway DB (topology.daily_work & topology.work_entries)."""
    data = request.get_json() or {}
    emp_id = str(data.get('employee_id') or data.get('emp_id') or request.user.get('employee_no') or request.user.get('emp_id') or request.user.get('id') or '').strip()
    emp_name = str(data.get('employee_name') or request.user.get('name') or request.user.get('full_name') or request.user.get('username') or '').strip()
    role = str(request.user.get('role', 'employee'))
    user_dept = str(request.user.get('department') or 'Engineering')
    user_db_id = request.user.get('id')

    work_date = data.get('work_date') or datetime.datetime.now(IST).strftime('%Y-%m-%d')
    project_id = (data.get('project_id') or data.get('project_name') or '').strip()
    project_name = (data.get('project_name') or data.get('project_id') or '').strip()
    department = (data.get('department') or user_dept).strip()
    task = (data.get('task') or '').strip()
    subtask = (data.get('subtask') or '').strip()
    remarks = (data.get('remarks') or '').strip()

    if not remarks:
        return jsonify({'error': 'Remarks are mandatory. Please enter work details / notes.'}), 400

    if not project_id and not project_name:
        return jsonify({'error': 'Project is required'}), 400

    try:
        quantity = float(data.get('quantity') or 0.0)
    except (ValueError, TypeError):
        quantity = 0.0

    unit = (data.get('unit') or 'KM').strip()

    try:
        hours = int(data.get('hours') or 0)
    except (ValueError, TypeError):
        hours = 0

    try:
        minutes = int(data.get('minutes') or 0)
    except (ValueError, TypeError):
        minutes = 0

    total_hours = round(hours + (minutes / 60.0), 2)
    revision = (data.get('revision') or 'New').strip()

    new_row = None

    try:
        conn_ir = get_ir_connection()
        cur_ir = conn_ir.cursor()

        # Check if employee exists in PMS user directory (topology.users)
        clean_eid = emp_id.lstrip('0') or '0'
        cur_ir.execute("""
            SELECT id, emp_id, full_name, department, role
            FROM topology.users
            WHERE emp_id = %s
               OR (emp_id IS NOT NULL AND LTRIM(emp_id, '0') = %s)
            LIMIT 1;
        """, (emp_id, clean_eid))
        pms_user = cur_ir.fetchone()

        if not pms_user:
            cur_ir.close()
            conn_ir.close()
            logger.warning(f"[PMS VALIDATION FAILED] Employee #{emp_id} ('{emp_name}') does not exist in topology.users. Rejecting work entry.")
            return jsonify({
                'success': False,
                'error': f"Employee ID #{emp_id} does not exist in PMS user directory. Work entry cannot be submitted."
            }), 403

        if pms_user.get('emp_id'):
            emp_id = str(pms_user['emp_id']).strip()
        if pms_user.get('full_name') and (not emp_name or emp_name.lower().startswith('employee')):
            emp_name = str(pms_user['full_name']).strip()

        # 1. Insert into topology.daily_work (as in FOR_AKSHADA.py)
        try:
            cur_ir.execute("""
                INSERT INTO topology.daily_work (
                    employee_id, employee_name,
                    work_date, department,
                    project_id,
                    task, subtask,
                    qty_type, quantity,
                    hours, minutes,
                    revision, remarks,
                    status,
                    created_by, created_role,
                    emp_team_dept,
                    created_at
                ) VALUES (
                    %s, %s,
                    %s, %s,
                    %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    'Pending',
                    %s, %s,
                    %s,
                    NOW()
                ) RETURNING *;
            """, (
                emp_id, emp_name,
                work_date, department,
                project_id,
                task, subtask,
                unit, quantity,
                hours, minutes,
                revision, remarks,
                emp_id, role,
                user_dept
            ))
            new_row = cur_ir.fetchone()
        except Exception as e_dw:
            logger.warning(f"daily_work insert warning: {e_dw}")
            conn_ir.rollback()

        # 2. Insert into topology.work_entries (as secondary/fallback)
        try:
            cur_ir.execute("""
                INSERT INTO topology.work_entries (
                    user_id, employee_id, employee_name, work_date,
                    project_id, project_name, department, task, subtask,
                    quantity, unit, hours, minutes, total_hours,
                    revision, remarks
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
            """, (
                user_db_id, emp_id, emp_name, work_date,
                project_id, project_name, department, task, subtask,
                quantity, unit, hours, minutes, total_hours,
                revision, remarks
            ))
            if not new_row:
                new_row = cur_ir.fetchone()
        except Exception as e_we:
            logger.warning(f"work_entries insert warning: {e_we}")
            conn_ir.rollback()

        conn_ir.commit()
        cur_ir.close()
        conn_ir.close()
    except Exception as e_ir:
        logger.error(f"Indian_Railway DB insert error: {e_ir}")
        return jsonify({'error': f"Failed to insert work entry: {e_ir}"}), 500

    serialized_row = {'status': 'saved'}
    if new_row:
        serialized_row = {}
        for k, v in dict(new_row).items():
            if hasattr(v, 'isoformat'):
                serialized_row[k] = v.isoformat()
            elif isinstance(v, (int, float, bool, str)) or v is None:
                serialized_row[k] = v
            else:
                serialized_row[k] = str(v)

    return jsonify({'success': True, 'work_entry': serialized_row}), 201


# ─── App Version & In-App Update API ──────────────────────────────────────────
@app.route('/api/app/version', methods=['GET'])
def get_latest_app_version():
    try:
        platform_param = (request.args.get('platform') or '').strip().lower()

        conn = get_db_connection()
        cur = conn.cursor()

        row = None
        if platform_param in ['ios', 'apple']:
            cur.execute("""
                SELECT *
                FROM app_versions
                WHERE LOWER(COALESCE(platform, 'android')) IN ('ios', 'apple')
                ORDER BY id DESC LIMIT 1;
            """)
            row = cur.fetchone()
        elif platform_param in ['android', 'google']:
            cur.execute("""
                SELECT *
                FROM app_versions
                WHERE LOWER(COALESCE(platform, 'android')) IN ('android', 'google')
                ORDER BY id DESC LIMIT 1;
            """)
            row = cur.fetchone()

        if not row:
            cur.execute("""
                SELECT *
                FROM app_versions
                ORDER BY id DESC LIMIT 1;
            """)
            row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            is_ios = platform_param in ['ios', 'apple']
            return jsonify({
                'platform': 'ios' if is_ios else 'android',
                'version_name': '1.0.5',
                'version_code': 11 if is_ios else 9,
                'min_supported_version': '1.0.0',
                'is_force_update': False,
                'download_url': 'https://apps.apple.com/app/monarch-hr/id6470000000' if is_ios else 'https://play.google.com/store/apps/details?id=com.monarchconsultants.monarchhr',
                'play_store_url': 'https://play.google.com/store/apps/details?id=com.monarchconsultants.monarchhr',
                'app_store_url': 'https://apps.apple.com/app/monarch-hr/id6470000000',
                'release_notes': '• Attendance Regularization & Leave options\n• Biometric machine & touchpoint flow sync\n• Dark / Light mode theme options',
                'title': 'Monarch HR iOS Update Available!' if is_ios else 'Monarch HR Android Update Available!'
            })

        return jsonify({
            'platform': row.get('platform') or ('ios' if platform_param in ['ios', 'apple'] else 'android'),
            'version_name': row['version_name'],
            'version_code': int(row['version_code']),
            'min_supported_version': row.get('min_supported_version') or '1.0.0',
            'is_force_update': bool(row.get('is_force_update', False)),
            'download_url': row.get('download_url') or (row.get('app_store_url') if row.get('platform') == 'ios' else row.get('play_store_url')) or 'https://play.google.com/store/apps/details?id=com.monarchconsultants.monarchhr',
            'play_store_url': row.get('play_store_url') or 'https://play.google.com/store/apps/details?id=com.monarchconsultants.monarchhr',
            'app_store_url': row.get('app_store_url') or 'https://apps.apple.com/app/monarch-hr/id6470000000',
            'release_notes': row.get('release_notes') or '• Performance improvements and bug fixes',
            'title': row.get('title') or 'Monarch HR Update Available!',
            'updated_at': row['updated_at'].isoformat() if row.get('updated_at') and hasattr(row['updated_at'], 'isoformat') else str(row.get('updated_at') or '')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/app-version', methods=['POST'])
@token_required
@admin_required
def publish_app_version():
    data = request.get_json() or {}
    platform = (data.get('platform') or 'android').strip().lower()
    version_name = (data.get('version_name') or data.get('version') or '').strip()
    version_code = data.get('version_code')
    min_supported_version = data.get('min_supported_version', '1.0.0')
    is_force_update = bool(data.get('is_force_update', False))
    download_url = data.get('download_url') or ('https://apps.apple.com/app/monarch-hr/id6470000000' if platform in ['ios', 'apple'] else 'https://play.google.com/store/apps/details?id=com.monarchconsultants.monarchhr')
    play_store_url = data.get('play_store_url') or 'https://play.google.com/store/apps/details?id=com.monarchconsultants.monarchhr'
    app_store_url = data.get('app_store_url') or 'https://apps.apple.com/app/monarch-hr/id6470000000'
    release_notes = data.get('release_notes', '• Performance improvements and bug fixes')
    title = data.get('title') or ('Monarch HR iOS Update Available!' if platform in ['ios', 'apple'] else 'Monarch HR Android Update Available!')

    if not version_name or version_code is None:
        return jsonify({'error': 'version_name and version_code (integer) required'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO app_versions (
                platform, version_name, version_code, min_supported_version,
                is_force_update, download_url, play_store_url, app_store_url, release_notes, title
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *;
        """, (platform, version_name, int(version_code), min_supported_version, is_force_update, download_url, play_store_url, app_store_url, release_notes, title))
        new_v = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if new_v and new_v.get('updated_at') and hasattr(new_v['updated_at'], 'isoformat'):
            new_v['updated_at'] = new_v['updated_at'].isoformat()
        return jsonify({'success': True, 'app_version': new_v})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/app/download-apk', methods=['GET'])
def download_apk():
    apk_candidates = [
        os.path.join(os.path.dirname(__file__), 'worktrack_app', 'build', 'app', 'outputs', 'flutter-apk', 'app-release.apk'),
        os.path.join(os.path.dirname(__file__), 'app-release.apk'),
        os.path.join(os.path.dirname(__file__), 'MonarchHR.apk'),
    ]
    for apk_path in apk_candidates:
        if os.path.exists(apk_path):
            from flask import send_file
            return send_file(apk_path, as_attachment=True, download_name='MonarchHR.apk', mimetype='application/vnd.android.package-archive')
    return jsonify({
        'error': 'APK file not currently stored on server. Please use the direct download link provided in /api/app/version.'
    }), 404


# ─── Enterprise Admin & HR Management Dashboard Module (Embedded) ─────────────
def log_audit_event(get_monarch_conn_func, actor_id, actor_name, action, target_type, target_id=None, reason=None, before_val=None, after_val=None, ip_address=None):
    """Immutable audit logging for all administrative modifications."""
    try:
        conn = get_monarch_conn_func()
        cur = conn.cursor()
        ip = ip_address or (request.remote_addr if request else '127.0.0.1')
        b_json = json.dumps(before_val, default=str) if before_val else None
        a_json = json.dumps(after_val, default=str) if after_val else None
        cur.execute("""
            INSERT INTO data.audit_logs (actor_id, actor_name, action, target_type, target_id, reason, before_value, after_value, ip_address, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW());
        """, (str(actor_id or 'ADMIN'), str(actor_name or 'Admin'), action, target_type, str(target_id or ''), reason, b_json, a_json, ip))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[AUDIT LOG ERROR] Failed to record audit log: {e}")


def calculate_attendance_metrics(sign_in, sign_out, shift_start='09:30:00', shift_end='18:30:00', grace_mins=15, date=None, is_regularized=False):
    """Calculates work_hours, late_minutes, early_minutes, overtime_hours, and status."""
    work_hours = 0.0
    if sign_in and sign_out:
        try:
            t_in = datetime.datetime.combine(datetime.date.today(), sign_in) if isinstance(sign_in, datetime.time) else datetime.datetime.strptime(str(sign_in)[:8], "%H:%M:%S")
            t_out = datetime.datetime.combine(datetime.date.today(), sign_out) if isinstance(sign_out, datetime.time) else datetime.datetime.strptime(str(sign_out)[:8], "%H:%M:%S")
            if t_out < t_in:
                t_out += datetime.timedelta(days=1)
            diff_secs = (t_out - t_in).total_seconds()
            work_hours = round(diff_secs / 3600.0, 2)
        except Exception:
            work_hours = 0.0

    late_mins = 0
    if sign_in:
        try:
            s_in = sign_in if isinstance(sign_in, datetime.time) else datetime.datetime.strptime(str(sign_in)[:8], "%H:%M:%S").time()
            s_target = datetime.datetime.strptime(str(shift_start)[:8], "%H:%M:%S").time()
            in_secs = s_in.hour * 3600 + s_in.minute * 60 + s_in.second
            target_secs = s_target.hour * 3600 + s_target.minute * 60 + s_target.second + (grace_mins * 60)
            if in_secs > target_secs:
                late_mins = int((in_secs - target_secs) / 60)
        except Exception:
            late_mins = 0

    early_mins = 0
    if sign_out:
        try:
            s_out = sign_out if isinstance(sign_out, datetime.time) else datetime.datetime.strptime(str(sign_out)[:8], "%H:%M:%S").time()
            s_end = datetime.datetime.strptime(str(shift_end)[:8], "%H:%M:%S").time()
            out_secs = s_out.hour * 3600 + s_out.minute * 60 + s_out.second
            end_secs = s_end.hour * 3600 + s_end.minute * 60 + s_end.second
            if out_secs < end_secs:
                early_mins = int((end_secs - out_secs) / 60)
        except Exception:
            early_mins = 0

    overtime_hrs = 0.0
    if work_hours > 8.5:
        overtime_hrs = round(work_hours - 8.5, 2)

    status = 'Present'
    if not sign_in and not sign_out:
        status = 'Absent'
    else:
        # Check missed punch on past date
        d_obj = None
        if date:
            if isinstance(date, datetime.date):
                d_obj = date
            else:
                try:
                    d_obj = datetime.datetime.strptime(str(date)[:10], "%Y-%m-%d").date()
                except Exception:
                    d_obj = None

        today = get_ist_today()
        is_past = bool(d_obj and d_obj < today)
        has_in = bool(sign_in)
        has_out = bool(sign_out)
        is_missed = is_past and ((has_in and not has_out) or (not has_in and has_out))

        if is_missed:
            if is_regularized:
                status = 'Present'
            else:
                status = 'Absent'
        elif work_hours > 0 and work_hours < 8.83:
            # 530 mins (8h 50m) is full day threshold with grace buffer. 3.0h to 8.83h is Half Day.
            if work_hours >= 3.0:
                status = 'Half Day'
            else:
                status = 'Short Attendance'
        elif overtime_hrs > 0:
            status = 'Present (OT)'
        elif late_mins > 0:
            status = 'Late'
        else:
            status = 'Present'

    return {
        'work_hours': work_hours,
        'late_mins': late_mins,
        'early_mins': early_mins,
        'overtime_hrs': overtime_hrs,
        'status': status
    }


def determine_half_day_code(punch=None, leave=None):
    """
    Determines session-specific half-day code for attendance muster:
      - 'A:P' : Absent in 1st Session (morning), Present in 2nd Session (afternoon).
                User took half day in the FIRST half (arrived late/afternoon e.g. >= 11:30 AM and worked evening).
      - 'P:A' : Present in 1st Session (morning), Absent in 2nd Session (afternoon).
                User took half day in the SECOND half (arrived morning and left early e.g. < 5:00 PM).
    """
    # 1. Check leave session specification if leave is provided
    if leave:
        sess = str(leave.get('session') or leave.get('from_session') or leave.get('to_session') or leave.get('note') or leave.get('title') or '').lower()
        if any(w in sess for w in ['session 1', 'session-1', 'session1', 'first session', '1st session', 'morning', 'first half', '1st half']):
            return 'A:P', 'Absent 1st Session (Session 1 Leave)'
        if any(w in sess for w in ['session 2', 'session-2', 'session2', 'second session', '2nd session', 'afternoon', 'second half', '2nd half']):
            return 'P:A', 'Absent 2nd Session (Session 2 Leave)'

    # 2. Check punch sign_in / sign_out times
    if punch:
        in_val = punch.get('sign_in')
        out_val = punch.get('sign_out')
        in_hour = None
        out_hour = None
        if in_val:
            try:
                if isinstance(in_val, (datetime.time, datetime.datetime)):
                    in_hour = in_val.hour + (in_val.minute / 60.0)
                else:
                    parts = str(in_val).strip().split(':')
                    in_hour = int(parts[0]) + (int(parts[1]) / 60.0 if len(parts) > 1 else 0.0)
            except Exception:
                in_hour = None

        if out_val:
            try:
                if isinstance(out_val, (datetime.time, datetime.datetime)):
                    out_hour = out_val.hour + (out_val.minute / 60.0)
                else:
                    parts = str(out_val).strip().split(':')
                    out_hour = int(parts[0]) + (int(parts[1]) / 60.0 if len(parts) > 1 else 0.0)
            except Exception:
                out_hour = None

        # Arrived late / afternoon (>= 11:30 AM / 12:00 PM) -> Absent in Session 1, worked Session 2 -> A:P
        if in_hour is not None and in_hour >= 11.5:
            return 'A:P', 'Absent 1st Session (Arrived afternoon)'
        # Arrived in morning (< 11:30 AM) and left early (< 5:00 PM) -> worked Session 1, Absent in Session 2 -> P:A
        elif out_hour is not None and out_hour < 17.0:
            return 'P:A', 'Absent 2nd Session (Left early)'
        elif in_hour is not None and in_hour < 11.5:
            return 'P:A', 'Absent 2nd Session (Left early)'

    # 3. Fallback: check session string for digit 1 or 2
    if leave:
        sess = str(leave.get('session') or leave.get('from_session') or '').lower()
        if '1' in sess:
            return 'A:P', 'Absent 1st Session (Session 1 Leave)'
        if '2' in sess:
            return 'P:A', 'Absent 2nd Session (Session 2 Leave)'

    return 'P:A', 'Absent 2nd Session (Left early)'


def resolve_leave_code(leave_info):
    """
    Resolves standard 2-letter HR muster code for approved leaves:
    - Earned Leave / Privilege Leave -> EL
    - Casual Leave -> CL
    - Sick Leave / Medical Leave -> SL
    - Compensatory Off -> CO
    - Leave Without Pay / Loss Of Pay -> LWP
    - Maternity Leave -> ML
    - Paternity Leave -> PL
    - Regularization -> REG
    - Default fallback -> EL if generic leave/annual, else L
    """
    if not leave_info:
        return 'EL'
    if isinstance(leave_info, dict):
        raw = str(leave_info.get('leave_type') or leave_info.get('title') or '').strip()
    else:
        raw = str(leave_info).strip()
    if not raw:
        return 'EL'
    u = raw.upper()
    if u in ['EL', 'CL', 'SL', 'CO', 'COMP', 'LWP', 'LOP', 'ML', 'PL', 'REG', 'OD']:
        return 'CO' if u == 'COMP' else u
    low = raw.lower()
    if 'earned' in low or 'privilege' in low:
        return 'EL'
    if 'casual' in low:
        return 'CL'
    if 'sick' in low or 'medical' in low:
        return 'SL'
    if 'comp' in low:
        return 'CO'
    if 'without pay' in low or 'loss of pay' in low or 'lwp' in low or 'lop' in low:
        return 'LWP'
    if 'maternity' in low:
        return 'ML'
    if 'paternity' in low:
        return 'PL'
    if 'regula' in low:
        return 'REG'
    if 'annual' in low:
        return 'EL'
    return 'EL'


def register_admin_dashboard(app, get_monarch_connection, get_db_connection, token_required, admin_required, format_monarch_user, load_monarch_users_map, get_ist_today, get_ist_now, jwt_secret):
    """Registers all enterprise Admin & HR dashboard APIs and web interface onto the Flask application."""

    # ─── 1. Dashboard Overview & Real-time KPIs ─────────────────────────────────
    @app.route('/api/admin/dashboard-stats', methods=['GET'])
    @token_required
    @admin_required
    def get_dashboard_stats():
        period = request.args.get('period', 'today').lower()
        today_date = get_ist_today()
        today_str = today_date.isoformat()

        if period == 'week':
            start_date = (today_date - datetime.timedelta(days=6)).isoformat()
            end_date = today_str
            days_in_period = 7
        elif period == 'month':
            start_date = (today_date - datetime.timedelta(days=29)).isoformat()
            end_date = today_str
            days_in_period = 30
        elif period == 'custom':
            start_date = request.args.get('start_date', today_str)
            end_date = request.args.get('end_date', today_str)
            try:
                days_in_period = max(1, (datetime.date.fromisoformat(end_date) - datetime.date.fromisoformat(start_date)).days + 1)
            except Exception:
                days_in_period = 1
        else:
            period = 'today'
            start_date = today_str
            end_date = today_str
            days_in_period = 1

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # Total active staff
            cur.execute("SELECT COUNT(*) AS total FROM data.users WHERE is_active IS NOT FALSE;")
            total_employees = cur.fetchone()['total'] or 0

            # Employees present in period
            if period == 'today':
                cur.execute("""
                    SELECT COUNT(DISTINCT employee_id) AS present
                    FROM data.attendance
                    WHERE date = %s AND sign_in IS NOT NULL;
                """, (today_str,))
            else:
                cur.execute("""
                    SELECT COUNT(DISTINCT employee_id) AS present
                    FROM data.attendance
                    WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL;
                """, (start_date, end_date))
            present_count = cur.fetchone()['present'] or 0

            # Employees on approved leave in period
            if period == 'today':
                cur.execute("""
                    SELECT COUNT(DISTINCT employee_id) AS on_leave
                    FROM data.leaves
                    WHERE %s BETWEEN start_date AND end_date
                      AND status ILIKE '%%approved%%';
                """, (today_str,))
            else:
                cur.execute("""
                    SELECT COUNT(DISTINCT employee_id) AS on_leave
                    FROM data.leaves
                    WHERE start_date <= %s AND end_date >= %s
                      AND status ILIKE '%%approved%%';
                """, (end_date, start_date))
            on_leave_count = cur.fetchone()['on_leave'] or 0

            # Absent / Inactive count
            absent_count = max(0, total_employees - present_count - on_leave_count)

            # Currently checked in (real-time active shifts in progress today)
            cur.execute("""
                SELECT COUNT(*) AS active_now
                FROM data.attendance
                WHERE date = %s AND sign_in IS NOT NULL AND sign_out IS NULL;
            """, (today_str,))
            checked_in_active = cur.fetchone()['active_now'] or 0

            # Late arrivals in period
            if period == 'today':
                cur.execute("""
                    SELECT COUNT(*) AS late_count
                    FROM data.attendance
                    WHERE date = %s AND sign_in > '09:45:00';
                """, (today_str,))
            else:
                cur.execute("""
                    SELECT COUNT(*) AS late_count
                    FROM data.attendance
                    WHERE date BETWEEN %s AND %s AND sign_in > '09:45:00';
                """, (start_date, end_date))
            late_arrivals = cur.fetchone()['late_count'] or 0

            # Unclosed shifts in period
            if period == 'today':
                cur.execute("""
                    SELECT COUNT(*) AS unclosed
                    FROM data.attendance
                    WHERE date = %s AND sign_in IS NOT NULL AND sign_out IS NULL;
                """, (today_str,))
            else:
                cur.execute("""
                    SELECT COUNT(*) AS unclosed
                    FROM data.attendance
                    WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL AND sign_out IS NULL;
                """, (start_date, end_date))
            unclosed_shifts = cur.fetchone()['unclosed'] or 0

            # Pending leave requests
            cur.execute("SELECT COUNT(*) AS pending FROM data.leaves WHERE status ILIKE '%%pending%%';")
            pending_leaves = cur.fetchone()['pending'] or 0

            # Pending attendance correction requests
            cur.execute("SELECT COUNT(*) AS pending FROM data.attendance_corrections WHERE status ILIKE '%%pending%%';")
            pending_corrections = cur.fetchone()['pending'] or 0

            # Attendance percentage
            attendance_percentage = round((present_count / max(1, total_employees)) * 100, 1)

            # Total work hours for period
            cur.execute("""
                SELECT sign_in, sign_out
                FROM data.attendance
                WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL AND sign_out IS NOT NULL;
            """, (start_date, end_date))
            all_punches = cur.fetchall()
            total_work_hours = 0.0
            for p in all_punches:
                m = calculate_attendance_metrics(p['sign_in'], p['sign_out'])
                total_work_hours += m['work_hours']
            total_work_hours = round(total_work_hours, 1)

            # Attendance Trend Chart (Daily points based on period)
            if period == 'month':
                trend_dates = [today_date - datetime.timedelta(days=i) for i in range(29, -1, -1)]
                date_fmt = '%d %b'
            else:
                trend_dates = [today_date - datetime.timedelta(days=i) for i in range(6, -1, -1)]
                date_fmt = '%a %d %b'

            trend_data = []
            for d in trend_dates:
                d_str = d.isoformat()
                cur.execute("""
                    SELECT 
                        COUNT(DISTINCT employee_id) AS present,
                        COUNT(CASE WHEN sign_in > '09:45:00' THEN 1 END) AS late
                    FROM data.attendance
                    WHERE date = %s AND sign_in IS NOT NULL;
                """, (d_str,))
                row_t = cur.fetchone()
                pres = row_t['present'] or 0
                lt = row_t['late'] or 0
                ab = max(0, total_employees - pres)
                trend_data.append({
                    'date': d_str,
                    'label': d.strftime(date_fmt),
                    'present': pres,
                    'late': lt,
                    'absent': ab
                })

            # Department employee headcount distribution
            cur.execute("""
                SELECT COALESCE(NULLIF(department, ''), 'Unassigned') AS dept, COUNT(*) AS count
                FROM data.users
                WHERE is_active IS NOT FALSE
                GROUP BY dept
                ORDER BY count DESC
                LIMIT 8;
            """)
            dept_stats = [{'department': r['dept'], 'count': r['count']} for r in cur.fetchall()]

            # Recent punches in period (last 10 events)
            cur.execute("""
                SELECT id, employee_id, employee_name, date, sign_in, sign_out, location,
                       in_geofence, nearest_building, distance_meters, department
                FROM data.attendance
                WHERE date BETWEEN %s AND %s
                ORDER BY date DESC, id DESC
                LIMIT 10;
            """, (start_date, end_date))
            recent_activity = []
            for r in cur.fetchall():
                recent_activity.append({
                    'id': r['id'],
                    'employee_id': r['employee_id'],
                    'employee_name': r.get('employee_name') or f"Employee {r['employee_id']}",
                    'department': r.get('department') or 'Operations',
                    'date': r['date'].isoformat() if hasattr(r['date'], 'isoformat') else str(r['date']),
                    'sign_in': str(r['sign_in'])[:8] if r.get('sign_in') else None,
                    'sign_out': str(r['sign_out'])[:8] if r.get('sign_out') else None,
                    'location': r.get('location') or 'Biometric / Mobile',
                    'in_geofence': bool(r.get('in_geofence', True)),
                    'nearest_building': r.get('nearest_building') or 'Monarch House (HQ)'
                })

            # Labels and titles tailored to period
            if period == 'week':
                period_title = "Enterprise Operations (This Week)"
                period_sub = f"Aggregated workforce KPIs for the past 7 days ({datetime.date.fromisoformat(start_date).strftime('%d %b')} – {today_date.strftime('%d %b %Y')})."
                present_label = "Active Staff (Week)"
                absent_label = "Inactive Staff (Week)"
                on_leave_label = "On Leave (Week)"
                late_label = "Total Late Arrivals"
                unclosed_label = "Total Unclosed Shifts"
                rate_label = "Weekly Participation Rate"
                hours_label = "Total Hours Logged (Week)"
                trend_title = "Attendance Trend (Last 7 Days)"
            elif period == 'month':
                period_title = "Enterprise Operations (This Month)"
                period_sub = f"Aggregated workforce KPIs for the past 30 days ({datetime.date.fromisoformat(start_date).strftime('%d %b')} – {today_date.strftime('%d %b %Y')})."
                present_label = "Active Staff (Month)"
                absent_label = "Inactive Staff (Month)"
                on_leave_label = "On Leave (Month)"
                late_label = "Total Late Arrivals"
                unclosed_label = "Total Unclosed Shifts"
                rate_label = "Monthly Participation Rate"
                hours_label = "Total Hours Logged (Month)"
                trend_title = "Attendance Trend (Last 30 Days)"
            else:
                period_title = "Enterprise Operations Today"
                period_sub = f"Real-time aggregated KPIs from biometric terminals and mobile GPS punches ({today_date.strftime('%d %b %Y')})."
                present_label = "Present Today"
                absent_label = "Absent Today"
                on_leave_label = "On Leave"
                late_label = "Late Arrivals"
                unclosed_label = "Unclosed Shifts"
                rate_label = "Attendance Rate"
                hours_label = "Total Hours Logged"
                trend_title = "Attendance Trend (Last 7 Days)"

            period_info = {
                'mode': period,
                'start_date': start_date,
                'end_date': end_date,
                'title': period_title,
                'subtitle': period_sub,
                'present_label': present_label,
                'absent_label': absent_label,
                'on_leave_label': on_leave_label,
                'late_label': late_label,
                'unclosed_label': unclosed_label,
                'rate_label': rate_label,
                'hours_label': hours_label,
                'trend_title': trend_title
            }

            return jsonify({
                'kpis': {
                    'total_employees': total_employees,
                    'present_today': present_count,
                    'absent_today': absent_count,
                    'on_leave_today': on_leave_count,
                    'checked_in_active': checked_in_active,
                    'late_arrivals': late_arrivals,
                    'unclosed_shifts': unclosed_shifts,
                    'pending_leaves': pending_leaves,
                    'pending_corrections': pending_corrections,
                    'attendance_percentage': attendance_percentage,
                    'total_work_hours': total_work_hours
                },
                'period': {
                    'mode': period,
                    'start_date': start_date,
                    'end_date': end_date
                },
                'period_info': period_info,
                'charts': {
                    'attendance_trend': trend_data,
                    'department_stats': dept_stats
                },
                'recent_activity': recent_activity
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 2. Employee Management Module ──────────────────────────────────────────
    @app.route('/api/admin/employees', methods=['GET'])
    @token_required
    @admin_required
    def get_admin_employees():
        search = (request.args.get('search') or '').strip()
        dept = (request.args.get('department') or '').strip()
        status = request.args.get('status', 'all').lower()
        page = max(1, int(request.args.get('page', 1)))
        limit = max(1, min(100, int(request.args.get('limit', 25))))
        offset = (page - 1) * limit

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            conditions = ["1=1"]
            params = []
            order_clause = "employee_no ASC, name ASC"
            order_params = []

            if search:
                clean_search = search.strip()
                id_candidate = re.sub(r'^(emp|employee|id|no)?[#\s\-_:]*', '', clean_search, flags=re.I).strip()

                if id_candidate.isdigit() and len(id_candidate) < 7:
                    emp_num = int(id_candidate) if int(id_candidate) <= 2147483647 else None
                    if emp_num is not None:
                        conditions.append("""(
                            employee_no = %s 
                            OR CAST(employee_no AS TEXT) LIKE %s 
                            OR LOWER(name) LIKE %s
                        )""")
                        params.extend([emp_num, f"{id_candidate}%", f"%{clean_search.lower()}%"])
                        order_clause = """
                            CASE 
                                WHEN employee_no = %s THEN 1
                                WHEN CAST(employee_no AS TEXT) LIKE %s THEN 2
                                WHEN LOWER(name) LIKE %s THEN 3
                                ELSE 4
                            END, employee_no ASC, name ASC
                        """
                        order_params = [emp_num, f"{id_candidate}%", f"%{clean_search.lower()}%"]
                    else:
                        conditions.append("(CAST(employee_no AS TEXT) LIKE %s OR LOWER(name) LIKE %s)")
                        params.extend([f"{id_candidate}%", f"%{clean_search.lower()}%"])
                        order_clause = "employee_no ASC, name ASC"
                elif id_candidate.isdigit() and len(id_candidate) >= 7:
                    emp_num = int(id_candidate) if int(id_candidate) <= 2147483647 else None
                    if emp_num is not None:
                        conditions.append("""(
                            mobile_number LIKE %s 
                            OR employee_no = %s 
                            OR CAST(employee_no AS TEXT) LIKE %s 
                            OR LOWER(personal_email) LIKE %s 
                            OR LOWER(name) LIKE %s
                        )""")
                        params.extend([f"%{id_candidate}%", emp_num, f"{id_candidate}%", f"%{clean_search.lower()}%", f"%{clean_search.lower()}%"])
                    else:
                        conditions.append("""(
                            mobile_number LIKE %s 
                            OR CAST(employee_no AS TEXT) LIKE %s 
                            OR LOWER(personal_email) LIKE %s 
                            OR LOWER(name) LIKE %s
                        )""")
                        params.extend([f"%{id_candidate}%", f"{id_candidate}%", f"%{clean_search.lower()}%", f"%{clean_search.lower()}%"])
                    order_clause = """
                        CASE 
                            WHEN mobile_number LIKE %s THEN 1
                            WHEN CAST(employee_no AS TEXT) = %s THEN 2
                            ELSE 3
                        END, employee_no ASC, name ASC
                    """
                    order_params = [f"%{id_candidate}%", id_candidate]
                else:
                    words = [w.lower() for w in clean_search.split() if w]
                    if len(words) > 1:
                        word_conds = []
                        for w in words:
                            word_conds.append("LOWER(CONCAT_WS(' ', name, department, designation, personal_email, mobile_number, CAST(employee_no AS TEXT))) LIKE %s")
                            params.append(f"%{w}%")
                        conditions.append(f"({' AND '.join(word_conds)})")
                        order_clause = """
                            CASE 
                                WHEN LOWER(name) = %s THEN 1
                                WHEN LOWER(name) LIKE %s THEN 2
                                WHEN LOWER(name) LIKE %s THEN 3
                                ELSE 4
                            END, employee_no ASC, name ASC
                        """
                        order_params = [clean_search.lower(), f"{clean_search.lower()}%", f"%{words[0]}%{words[-1]}%"]
                    else:
                        single_word = clean_search.lower()
                        conditions.append("""(
                            LOWER(name) LIKE %s 
                            OR LOWER(personal_email) LIKE %s 
                            OR LOWER(mobile_number) LIKE %s 
                            OR LOWER(department) LIKE %s 
                            OR LOWER(designation) LIKE %s 
                            OR CAST(employee_no AS TEXT) LIKE %s
                        )""")
                        like_w = f"%{single_word}%"
                        params.extend([like_w, like_w, like_w, like_w, like_w, f"{id_candidate if id_candidate else single_word}%"])
                        order_clause = """
                            CASE 
                                WHEN LOWER(name) = %s THEN 1
                                WHEN LOWER(name) LIKE %s THEN 2
                                WHEN LOWER(name) LIKE %s THEN 3
                                WHEN CAST(employee_no AS TEXT) LIKE %s THEN 4
                                ELSE 5
                            END, employee_no ASC, name ASC
                        """
                        order_params = [single_word, f"{single_word}%", f"%{single_word}%", f"{single_word}%"]

            if dept:
                conditions.append("department = %s")
                params.append(dept)

            if status == 'active':
                conditions.append("is_active IS NOT FALSE")
            elif status == 'inactive':
                conditions.append("is_active IS FALSE")

            where_clause = " AND ".join(conditions)

            # Count total
            cur.execute(f"SELECT COUNT(*) AS total FROM data.users WHERE {where_clause};", tuple(params))
            total_count = cur.fetchone()['total'] or 0

            # Fetch rows
            cur.execute(f"""
                SELECT id, employee_no, name, date_of_joining, gender, designation, department,
                       reporting_manager, location, company_name, mobile_number, personal_email,
                       shift_timing, shift_id, weekly_off, is_active, employment_status, role, username
                FROM data.users
                WHERE {where_clause}
                ORDER BY {order_clause}
                LIMIT %s OFFSET %s;
            """, tuple(params + order_params + [limit, offset]))
            rows = cur.fetchall()

            employees = []
            for r in rows:
                doj = r['date_of_joining'].isoformat() if r.get('date_of_joining') and hasattr(r['date_of_joining'], 'isoformat') else str(r.get('date_of_joining') or '')
                employees.append({
                    'id': r['id'],
                    'employee_no': r['employee_no'],
                    'name': r['name'],
                    'personal_email': r.get('personal_email') or '',
                    'mobile_number': r.get('mobile_number') or '',
                    'department': r.get('department') or 'General',
                    'designation': r.get('designation') or 'Employee',
                    'reporting_manager': r.get('reporting_manager') or 'Direct Management',
                    'location': r.get('location') or 'Monarch House HQ',
                    'company_name': r.get('company_name') or 'Monarch Surveyors & Engineering Consultants',
                    'date_of_joining': doj,
                    'gender': r.get('gender') or '',
                    'role': r.get('role') or 'employee',
                    'shift_timing': r.get('shift_timing') or '09:30 AM - 06:30 PM',
                    'shift_id': r.get('shift_id') or 1,
                    'weekly_off': r.get('weekly_off') or 'Sunday',
                    'is_active': bool(r.get('is_active', True)),
                    'employment_status': r.get('employment_status') or ('Active' if r.get('is_active', True) else 'Inactive')
                })

            return jsonify({
                'employees': employees,
                'total': total_count,
                'page': page,
                'limit': limit,
                'pages': math.ceil(total_count / limit) if total_count > 0 else 1
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/employees', methods=['POST'])
    @token_required
    @admin_required
    def create_admin_employee():
        data = request.get_json() or {}
        emp_no = data.get('employee_no')
        name = (data.get('name') or '').strip()
        email = (data.get('personal_email') or '').strip()
        phone = (data.get('mobile_number') or '').strip()
        dept = (data.get('department') or '').strip()
        designation = (data.get('designation') or '').strip()
        manager = (data.get('reporting_manager') or '').strip()
        location = data.get('location') or 'Pune'
        doj = data.get('date_of_joining') or get_ist_today().isoformat()
        shift = data.get('shift_timing') or '09:30 AM - 06:30 PM'
        weekly_off = data.get('weekly_off') or 'Sunday'
        role = data.get('role') or 'employee'
        password = data.get('password') or f"{name.split()[0].capitalize() if name else 'Monarch'}{emp_no}"

        if not emp_no or not name:
            return jsonify({'error': 'Employee number and full name are required'}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # Unique Employee Number check
            cur.execute("SELECT id FROM data.users WHERE employee_no = %s;", (emp_no,))
            if cur.fetchone():
                return jsonify({'error': f'Employee ID #{emp_no} already exists in directory'}), 400

            # Unique Email check if provided
            if email:
                cur.execute("SELECT id FROM data.users WHERE LOWER(personal_email) = LOWER(%s);", (email,))
                if cur.fetchone():
                    return jsonify({'error': f'Email address {email} is already in use by another staff member'}), 400

            hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            cur.execute("""
                INSERT INTO data.users (
                    employee_no, name, personal_email, mobile_number, department, designation,
                    reporting_manager, location, company_name, date_of_joining, shift_timing,
                    weekly_off, role, username, password, password_hash, is_active, employment_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, 'Active')
                RETURNING id, employee_no, name, personal_email, department, designation, role;
            """, (
                emp_no, name, email, phone, dept, designation, manager, location,
                'Monarch Surveyors & Engineering Consultants Limited', doj, shift,
                weekly_off, role, str(emp_no), hashed_pw, hashed_pw
            ))
            new_user = cur.fetchone()

            # Initialize leave balance
            cur.execute("""
                INSERT INTO data.leave_balances (employee_id, total_allotted, used_days, remaining_days)
                VALUES (%s, 6.0, 0.0, 6.0)
                ON CONFLICT (employee_id) DO NOTHING;
            """, (str(emp_no),))

            conn.commit()

            # Log audit
            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='EMPLOYEE_CREATE',
                target_type='user',
                target_id=str(new_user['id']),
                reason=f"Created employee profile #{emp_no} ({name})",
                after_val=dict(new_user)
            )

            return jsonify({'success': True, 'employee': dict(new_user)}), 201

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
    @app.route('/api/admin/reporting-managers', methods=['GET'])
    @token_required
    def get_admin_reporting_managers():
        """Returns sorted list of all active reporting managers across the company."""
        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # 1. Distinct managers currently assigned in data.users
            cur.execute("""
                SELECT DISTINCT TRIM(reporting_manager) AS name
                FROM data.users
                WHERE reporting_manager IS NOT NULL AND TRIM(reporting_manager) != '';
            """)
            assigned_mgrs = set(r['name'] for r in cur.fetchall() if r['name'])

            # 2. Users with leadership roles or managerial designations
            cur.execute("""
                SELECT TRIM(name) AS name, designation, department, employee_no, role
                FROM data.users
                WHERE is_active = TRUE
                  AND (
                    LOWER(role) IN ('manager', 'seniorteamleader', 'teamleader', 'admin')
                    OR designation ILIKE '%Manager%'
                    OR designation ILIKE '%Director%'
                    OR designation ILIKE '%Head%'
                    OR designation ILIKE '%Lead%'
                  );
            """)
            role_mgrs = cur.fetchall()

            mgr_dict = {}
            for r in role_mgrs:
                nm = r['name']
                if nm:
                    mgr_dict[nm] = {
                        'name': nm,
                        'department': r.get('department') or '',
                        'designation': r.get('designation') or '',
                        'employee_no': r.get('employee_no')
                    }

            for nm in assigned_mgrs:
                if nm and nm not in mgr_dict:
                    cur.execute("SELECT employee_no, department, designation FROM data.users WHERE TRIM(name) ILIKE %s LIMIT 1;", (nm,))
                    u = cur.fetchone()
                    if u:
                        mgr_dict[nm] = {
                            'name': nm,
                            'department': u.get('department') or '',
                            'designation': u.get('designation') or '',
                            'employee_no': u.get('employee_no')
                        }
                    else:
                        mgr_dict[nm] = {
                            'name': nm,
                            'department': '',
                            'designation': '',
                            'employee_no': None
                        }

            sorted_mgrs = sorted(mgr_dict.values(), key=lambda x: x['name'].lower())
            return jsonify({'success': True, 'managers': sorted_mgrs})
        except Exception as e:
            logger.error(f"Error fetching reporting managers: {e}")
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                conn.close()

    @app.route('/api/admin/employees/<int:user_id>', methods=['PUT', 'PATCH'])
    @app.route('/api/admin/employees/<string:user_id_str>', methods=['PUT', 'PATCH'])
    @token_required
    @admin_required
    def update_admin_employee(user_id=None, user_id_str=None):
        data = request.get_json() or {}
        conn = None
        ident = user_id if user_id is not None else user_id_str
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # Fetch existing by id OR employee_no
            cur.execute("""
                SELECT * FROM data.users 
                WHERE id = %s OR employee_no = %s
                LIMIT 1;
            """, (int(ident) if str(ident).isdigit() else -1, int(ident) if str(ident).isdigit() else -1))
            before = cur.fetchone()
            if not before:
                return jsonify({'error': f'Employee record not found for {ident}'}), 404

            actual_user_id = before['id']
            actual_emp_no = before['employee_no']

            name = data.get('name') if 'name' in data else before['name']
            email = data.get('personal_email') if 'personal_email' in data else (data.get('email') if 'email' in data else before.get('personal_email'))
            phone = data.get('mobile_number') if 'mobile_number' in data else (data.get('phone_number') if 'phone_number' in data else before.get('mobile_number'))
            dept = data.get('department') if 'department' in data else before.get('department')
            designation = data.get('designation') if 'designation' in data else before.get('designation')
            manager = data.get('reporting_manager') if 'reporting_manager' in data else before.get('reporting_manager')
            shift = data.get('shift_timing') if 'shift_timing' in data else before.get('shift_timing')
            weekly_off = data.get('weekly_off') if 'weekly_off' in data else before.get('weekly_off')
            role = data.get('role') if 'role' in data else before.get('role')
            gender = data.get('gender') if 'gender' in data else before.get('gender')
            location = data.get('location') if 'location' in data else before.get('location')
            company_name = data.get('company_name') if 'company_name' in data else before.get('company_name')
            doj = data.get('date_of_joining') if 'date_of_joining' in data else (data.get('doj') if 'doj' in data else before.get('date_of_joining'))
            employment_status = data.get('employment_status') if 'employment_status' in data else (data.get('status') if 'status' in data else before.get('employment_status'))

            is_active = before.get('is_active', True)
            if 'is_active' in data:
                is_active = bool(data['is_active'])
            elif employment_status:
                is_active = (str(employment_status).lower() == 'active')

            new_password = data.get('password') or data.get('new_password')
            hashed_pw = None
            if new_password and str(new_password).strip():
                hashed_pw = bcrypt.hashpw(str(new_password).strip().encode('utf-8'), bcrypt.gensalt(rounds=6)).decode('utf-8')

            reason = data.get('reason') or f"Profile updated by admin/HR {request.user.get('name')}"

            if hashed_pw:
                cur.execute("""
                    UPDATE data.users
                    SET name = %s,
                        personal_email = %s,
                        mobile_number = %s,
                        department = %s,
                        designation = %s,
                        reporting_manager = %s,
                        shift_timing = %s,
                        weekly_off = %s,
                        role = %s,
                        gender = %s,
                        location = %s,
                        company_name = %s,
                        date_of_joining = %s,
                        employment_status = %s,
                        is_active = %s,
                        password = %s,
                        password_hash = %s
                    WHERE id = %s
                    RETURNING id, employee_no, name, personal_email, mobile_number, department, designation, reporting_manager, role, location, shift_timing, employment_status, is_active;
                """, (
                    name, email, phone, dept, designation, manager, shift, weekly_off, role,
                    gender, location, company_name, doj, employment_status, is_active,
                    hashed_pw, hashed_pw, actual_user_id
                ))
            else:
                cur.execute("""
                    UPDATE data.users
                    SET name = %s,
                        personal_email = %s,
                        mobile_number = %s,
                        department = %s,
                        designation = %s,
                        reporting_manager = %s,
                        shift_timing = %s,
                        weekly_off = %s,
                        role = %s,
                        gender = %s,
                        location = %s,
                        company_name = %s,
                        date_of_joining = %s,
                        employment_status = %s,
                        is_active = %s
                    WHERE id = %s
                    RETURNING id, employee_no, name, personal_email, mobile_number, department, designation, reporting_manager, role, location, shift_timing, employment_status, is_active;
                """, (
                    name, email, phone, dept, designation, manager, shift, weekly_off, role,
                    gender, location, company_name, doj, employment_status, is_active,
                    actual_user_id
                ))
            updated = cur.fetchone()
            conn.commit()

            # Audit log
            changed_fields = []
            for field in ['name', 'department', 'designation', 'reporting_manager', 'role', 'mobile_number', 'personal_email', 'shift_timing', 'location', 'employment_status']:
                b_val = str(before.get(field) or '').strip()
                a_val = str(updated.get(field) or '').strip()
                if b_val != a_val:
                    changed_fields.append(f"{field}: '{b_val}' -> '{a_val}'")

            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='EMPLOYEE_UPDATE',
                target_type='user',
                target_id=str(actual_user_id),
                reason=reason + (f" ({', '.join(changed_fields)})" if changed_fields else ""),
                before_val={'name': before.get('name'), 'reporting_manager': before.get('reporting_manager'), 'designation': before.get('designation'), 'dept': before.get('department'), 'role': before.get('role')},
                after_val=dict(updated)
            )

            return jsonify({'success': True, 'employee': dict(updated)})

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/employees/<int:user_id>/toggle-status', methods=['POST'])
    @token_required
    @admin_required
    def toggle_employee_status(user_id):
        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, employee_no, name, is_active FROM data.users WHERE id = %s;", (user_id,))
            user = cur.fetchone()
            if not user:
                return jsonify({'error': 'Employee record not found'}), 404

            new_status = not bool(user.get('is_active', True))
            status_text = 'Active' if new_status else 'Inactive'

            cur.execute("""
                UPDATE data.users
                SET is_active = %s,
                    employment_status = %s
                WHERE id = %s
                RETURNING id, employee_no, name, is_active, employment_status;
            """, (new_status, status_text, user_id))
            updated = cur.fetchone()
            conn.commit()

            # Audit log (preserves all historical attendance, leave, and payroll records)
            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='EMPLOYEE_STATUS_CHANGE',
                target_type='user',
                target_id=str(user_id),
                reason=f"Account status changed to {status_text} (Historical logs preserved)",
                before_val={'is_active': user.get('is_active')},
                after_val={'is_active': new_status, 'status': status_text}
            )

            return jsonify({
                'success': True,
                'message': f"Employee {user['name']} account marked as {status_text}.",
                'employee': dict(updated)
            })

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/employees/<int:user_id>/detail', methods=['GET'])
    @app.route('/api/admin/employees/<string:user_id_str>/detail', methods=['GET'])
    @token_required
    @admin_required
    def get_employee_detail(user_id=None, user_id_str=None):
        conn = None
        ident = user_id if user_id is not None else user_id_str
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM data.users 
                WHERE id = %s OR employee_no = %s
                LIMIT 1;
            """, (int(ident) if str(ident).isdigit() else -1, int(ident) if str(ident).isdigit() else -1))
            user = cur.fetchone()
            if not user:
                return jsonify({'error': 'Employee not found'}), 404

            emp_id = str(user['employee_no'])

            # Attendance history last 30 records
            cur.execute("""
                SELECT id, date, sign_in, sign_out, location, in_geofence, nearest_building,
                       distance_meters, clock_in_lat, clock_in_lng, approval_status
                FROM data.attendance
                WHERE employee_id = %s OR employee_id = %s
                ORDER BY date DESC, id DESC
                LIMIT 30;
            """, (emp_id, emp_id.lstrip('0')))
            attendance_records = []
            for r in cur.fetchall():
                m = calculate_attendance_metrics(r['sign_in'], r['sign_out'])
                attendance_records.append({
                    'id': r['id'],
                    'date': r['date'].isoformat() if hasattr(r['date'], 'isoformat') else str(r['date']),
                    'sign_in': str(r['sign_in'])[:8] if r.get('sign_in') else None,
                    'sign_out': str(r['sign_out'])[:8] if r.get('sign_out') else None,
                    'work_hours': m['work_hours'],
                    'late_mins': m['late_mins'],
                    'status': m['status'],
                    'location': r.get('location') or 'HQ',
                    'in_geofence': bool(r.get('in_geofence', True)),
                    'approval_status': r.get('approval_status') or 'Approved'
                })

            # Leave balances
            cur.execute("""
                SELECT total_allotted, used_days, remaining_days
                FROM data.leave_balances
                WHERE employee_id = %s OR employee_id = %s
                LIMIT 1;
            """, (emp_id, emp_id.lstrip('0')))
            lb = cur.fetchone() or {'total_allotted': 6.0, 'used_days': 0.0, 'remaining_days': 6.0}

            # Leaves applied
            cur.execute("""
                SELECT id, title, leave_type, start_date, end_date, days_count, status, applied_at, note, reviewed_by, rejection_reason
                FROM data.leaves
                WHERE employee_id = %s OR employee_id = %s
                ORDER BY applied_at DESC
                LIMIT 20;
            """, (emp_id, emp_id.lstrip('0')))
            leaves = []
            for l in cur.fetchall():
                leaves.append({
                    'id': l['id'],
                    'title': l['title'],
                    'leave_type': l.get('leave_type') or 'Annual',
                    'start_date': l['start_date'].isoformat() if hasattr(l['start_date'], 'isoformat') else str(l['start_date']),
                    'end_date': l['end_date'].isoformat() if hasattr(l['end_date'], 'isoformat') else str(l['end_date']),
                    'days_count': float(l.get('days_count') or 1.0),
                    'status': l['status'],
                    'applied_at': l['applied_at'].isoformat() if hasattr(l['applied_at'], 'isoformat') else str(l['applied_at']),
                    'note': l.get('note') or '',
                    'rejection_reason': l.get('rejection_reason') or ''
                })

            return jsonify({
                'profile': {
                    'id': user['id'],
                    'employee_no': user['employee_no'],
                    'name': user['name'],
                    'personal_email': user.get('personal_email') or '',
                    'mobile_number': user.get('mobile_number') or '',
                    'department': user.get('department') or 'Operations',
                    'designation': user.get('designation') or 'Staff',
                    'reporting_manager': user.get('reporting_manager') or 'Direct Management',
                    'location': user.get('location') or 'Pune',
                    'gender': user.get('gender') or 'Male',
                    'company_name': user.get('company_name') or 'Monarch Surveyors & Engineering Consultants Limited',
                    'date_of_joining': user['date_of_joining'].isoformat() if hasattr(user.get('date_of_joining'), 'isoformat') else str(user.get('date_of_joining') or ''),
                    'role': user.get('role') or 'employee',
                    'shift_timing': user.get('shift_timing') or '09:30 AM - 06:30 PM',
                    'weekly_off': user.get('weekly_off') or 'Sunday',
                    'is_active': bool(user.get('is_active', True)),
                    'employment_status': user.get('employment_status') or 'Active'
                },
                'leave_balance': {
                    'total_allotted': float(lb['total_allotted']),
                    'used_days': float(lb['used_days']),
                    'remaining_days': float(lb['remaining_days'])
                },
                'recent_attendance': attendance_records,
                'leave_history': leaves
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── Employee Excel Master Upload (Preview & Confirm) ───────────────────────
    @app.route('/api/admin/employees/upload-excel/preview', methods=['POST'])
    @token_required
    @admin_required
    def preview_upload_employee_excel():
        """
        Parses weekly Employee Master Excel, identifies only brand-new employees,
        leaves existing employees completely untouched, and calculates addition counts.
        """
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded. Please select an Excel file (.xlsx or .xls).'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'Empty filename uploaded.'}), 400

        if not file.filename.lower().endswith(('.xlsx', '.xls')):
            return jsonify({'error': 'Invalid file format. Please upload an Excel (.xlsx or .xls) file.'}), 400

        try:
            file_bytes = file.read()
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet = wb.active
            rows = list(sheet.iter_rows(values_only=True))

            if not rows or len(rows) < 2:
                return jsonify({'error': 'Excel file contains no data rows.'}), 400

            header_row = rows[0]
            col_map = {}
            for idx, h in enumerate(header_row):
                if h is not None:
                    clean_h = re.sub(r'[^a-z0-9]', '', str(h).lower())
                    col_map[clean_h] = idx

            def get_col_val(r, possible_names, default=None):
                for n in possible_names:
                    if n in col_map and col_map[n] < len(r):
                        v = r[col_map[n]]
                        if v is not None:
                            s = str(v).strip()
                            if s.lower() not in ('none', 'nan', 'null', ''):
                                return s
                # Fallback: check if any column header in col_map contains 'manager' or 'reporting'
                if any('manager' in n or 'reporting' in n for n in possible_names):
                    for k, idx in col_map.items():
                        if ('manager' in k or 'reporting' in k) and idx < len(r):
                            v = r[idx]
                            if v is not None:
                                s = str(v).strip()
                                if s.lower() not in ('none', 'nan', 'null', ''):
                                    return s
                return default

            # Connect to database to get current employee numbers and count
            conn = get_monarch_connection()
            cur = conn.cursor()
            cur.execute("SELECT employee_no FROM data.users;")
            existing_emp_set = set(r['employee_no'] for r in cur.fetchall() if r.get('employee_no') is not None)
            existing_db_count = len(existing_emp_set)
            cur.close()
            conn.close()

            new_employees = []
            skipped_count = 0
            invalid_rows = 0

            for r in rows[1:]:
                emp_id_str = get_col_val(r, ['empid', 'employeeid', 'employeeno', 'empno', 'id'])
                if not emp_id_str:
                    invalid_rows += 1
                    continue

                try:
                    emp_no = int(float(emp_id_str))
                except (ValueError, TypeError):
                    invalid_rows += 1
                    continue

                if emp_no in existing_emp_set:
                    # Previous employee -> DO NOT TOUCH!
                    skipped_count += 1
                    continue

                # Brand new employee
                name = get_col_val(r, ['empname', 'employeename', 'fullname', 'name'], default='')
                doj_raw = get_col_val(r, ['doj', 'dateofjoining', 'joiningdate'])
                doj = None
                if doj_raw:
                    doj_match = re.search(r'\d{4}-\d{2}-\d{2}', str(doj_raw))
                    if doj_match:
                        doj = doj_match.group(0)
                    else:
                        try:
                            dt = datetime.datetime.strptime(str(doj_raw)[:10], '%Y-%m-%d')
                            doj = dt.strftime('%Y-%m-%d')
                        except Exception:
                            doj = str(doj_raw)[:10]

                designation = get_col_val(r, ['designation', 'desig'], default='Employee')
                department = get_col_val(r, ['department', 'dept'], default='General')
                manager = get_col_val(r, [
                    'reportingmanager', 'managername', 'reportingmanagername', 'manager',
                    'reportinghead', 'reportingto', 'reportingauthority', 'reportingperson',
                    'reportingofficer', 'rmname', 'repmanager', 'rm', 'reporting'
                ], default='Direct Management')
                gender = get_col_val(r, ['gender'], default='Male')

                phone = get_col_val(r, ['phoneno', 'phone', 'mobilenumber', 'mobile', 'contact'])
                if phone and phone.endswith('.0'):
                    phone = phone[:-2]

                email = get_col_val(r, ['emailid', 'email', 'personalemail'])
                company = get_col_val(r, ['companyname', 'company'], default='Monarch Surveyors & Engineering Consultants Limited')
                location = get_col_val(r, ['location', 'branch', 'city'], default='Pune')
                status = get_col_val(r, ['employeestatus', 'employmentstatus', 'status'], default='Active')
                shift = get_col_val(r, ['shifttiming', 'shift'], default='General- 9.30 Am To 6.30 Pm')

                new_employees.append({
                    'employee_no': emp_no,
                    'name': name,
                    'date_of_joining': doj or get_ist_today().isoformat(),
                    'designation': designation,
                    'department': department,
                    'reporting_manager': manager,
                    'gender': gender,
                    'mobile_number': phone or '',
                    'personal_email': email or '',
                    'company_name': company,
                    'location': location,
                    'employment_status': status,
                    'shift_timing': shift
                })

            new_count = len(new_employees)
            total_after_adding = existing_db_count + new_count

            return jsonify({
                'success': True,
                'filename': file.filename,
                'total_in_excel': len(rows) - 1,
                'existing_db_count': existing_db_count,
                'skipped_count': skipped_count,
                'new_count': new_count,
                'total_after_adding': total_after_adding,
                'new_employees': new_employees
            })

        except Exception as e:
            logger.error(f"Error parsing employee master Excel: {e}", exc_info=True)
            return jsonify({'error': f"Failed to parse Excel file: {str(e)}"}), 500


    @app.route('/api/admin/employees/upload-excel/confirm', methods=['POST'])
    @token_required
    @admin_required
    def confirm_upload_employee_excel():
        """
        Inserts verified new employees from Excel import into data.users,
        initializes leave balances, and logs an immutable batch audit trail.
        """
        data = request.get_json() or {}
        new_employees = data.get('new_employees', [])

        if not new_employees:
            return jsonify({'success': True, 'added_count': 0, 'message': 'No new employees to add.'})

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # Align sequence numbers before insert
            cur.execute("SELECT max(id) FROM data.users;")
            max_user_id = cur.fetchone()['max'] or 0
            cur.execute(f"SELECT setval('data.users_id_seq', {max_user_id + 1});")

            cur.execute("SELECT max(id) FROM data.leave_balances;")
            max_leave_id = cur.fetchone()['max'] or 0
            cur.execute(f"SELECT setval('data.leave_balances_id_seq', {max_leave_id + 1});")

            # Check existing to prevent any duplicates
            cur.execute("SELECT employee_no FROM data.users;")
            existing_emp_set = set(r['employee_no'] for r in cur.fetchall() if r.get('employee_no') is not None)

            added_count = 0
            added_ids = []

            for emp in new_employees:
                emp_no = int(emp.get('employee_no'))
                if emp_no in existing_emp_set:
                    continue  # Safety check: skip existing

                name = (emp.get('name') or '').strip()
                doj = emp.get('date_of_joining') or get_ist_today().isoformat()
                gender = emp.get('gender') or 'Male'
                desig = emp.get('designation') or 'Employee'
                dept = emp.get('department') or 'General'
                manager = emp.get('reporting_manager') or 'Direct Management'
                location = emp.get('location') or 'Pune'
                company = emp.get('company_name') or 'Monarch Surveyors & Engineering Consultants Limited'
                phone = (emp.get('mobile_number') or '').strip() or None
                email = (emp.get('personal_email') or '').strip() or None
                shift = emp.get('shift_timing') or 'General- 9.30 Am To 6.30 Pm'
                raw_status = str(emp.get('employment_status') or 'Active').strip()
                is_active = (raw_status.lower() in ('active', 'confirmed', 'probation', 'regular'))
                status = 'Active' if is_active else raw_status

                first_name = name.split()[0].capitalize() if name else 'Monarch'
                raw_pw = f"{first_name}{emp_no}"
                hashed_pw = bcrypt.hashpw(raw_pw.encode('utf-8'), bcrypt.gensalt(rounds=6)).decode('utf-8')

                cur.execute("""
                    INSERT INTO data.users (
                        employee_no, name, date_of_joining, gender, designation, department,
                        reporting_manager, location, company_name, mobile_number, personal_email,
                        shift_timing, password, created_at, role, username, password_hash,
                        is_active, employment_status, weekly_off, is_location_bound, is_time_bound
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, NOW(), 'employee', %s, %s,
                        %s, %s, 'Sunday', TRUE, TRUE
                    );
                """, (
                    emp_no, name, doj, gender, desig, dept,
                    manager, location, company, phone, email,
                    shift, hashed_pw, str(emp_no), hashed_pw,
                    is_active, status
                ))
                added_count += 1
                added_ids.append(emp_no)
                existing_emp_set.add(emp_no)

                # Initialize leave balance
                cur.execute("""
                    INSERT INTO data.leave_balances (employee_id, total_allotted, used_days, remaining_days)
                    VALUES (%s, 6.0, 0.0, 6.0)
                    ON CONFLICT (employee_id) DO NOTHING;
                """, (str(emp_no),))

            conn.commit()

            # Audit log
            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='EMPLOYEE_BATCH_IMPORT',
                target_type='users',
                target_id=f"batch_{added_count}",
                reason=f"Added {added_count} new employees via weekly master Excel import (Existing records preserved untouched)",
                after_val={'added_count': added_count, 'employee_ids': added_ids[:50]}
            )

            # Get final count
            cur.execute("SELECT count(*) AS total FROM data.users;")
            new_total = cur.fetchone()['total']

            return jsonify({
                'success': True,
                'added_count': added_count,
                'total_employees': new_total,
                'message': f"Successfully added {added_count} new employees! Total employees in database is now {new_total}."
            })

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error confirming employee batch import: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 3. Attendance Management Module ────────────────────────────────────────
    @app.route('/api/admin/attendance-records', methods=['GET'])
    @token_required
    @admin_required
    def get_admin_attendance_records():
        date_param = request.args.get('date')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        emp_search = (request.args.get('employee_id') or request.args.get('search') or '').strip().lower()
        dept = (request.args.get('department') or '').strip()
        status_filter = (request.args.get('status') or '').strip().lower()
        kpi_filter = (request.args.get('kpi_filter') or request.args.get('filter') or '').strip().lower()
        page = max(1, int(request.args.get('page', 1)))
        limit = max(1, min(100, int(request.args.get('limit', 25))))
        offset = (page - 1) * limit

        today_str = get_ist_today().isoformat()
        if not date_param and not start_date:
            date_param = today_str

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            conditions = ["1=1"]
            params = []

            if date_param:
                conditions.append("a.date = %s")
                params.append(date_param)
            elif start_date and end_date:
                conditions.append("a.date BETWEEN %s AND %s")
                params.extend([start_date, end_date])

            if kpi_filter in ['punches', 'total_punches']:
                conditions.append("a.sign_in IS NOT NULL")
            elif kpi_filter in ['late', 'late_arrivals']:
                conditions.append("a.sign_in > '09:45:00'")
            elif kpi_filter in ['out_of_range', 'geofence', 'out_of_geofence']:
                conditions.append("a.in_geofence = FALSE")

            if emp_search:
                clean_att = emp_search.strip()
                id_cand = re.sub(r'^(emp|employee|id|no)?[#\s\-_:]*', '', clean_att, flags=re.I).strip()
                if id_cand.isdigit() and len(id_cand) < 7:
                    conditions.append("(a.employee_id = %s OR a.employee_id = %s OR LOWER(a.employee_id) LIKE %s OR LOWER(a.employee_name) LIKE %s)")
                    params.extend([id_cand, id_cand.lstrip('0'), f"{id_cand}%", f"%{clean_att.lower()}%"])
                else:
                    words = [w.lower() for w in clean_att.split() if w]
                    if len(words) > 1:
                        word_conds = [f"LOWER(CONCAT_WS(' ', a.employee_name, a.department, a.employee_id)) LIKE %s" for _ in words]
                        conditions.append(f"({' AND '.join(word_conds)})")
                        params.extend([f"%{w}%" for w in words])
                    else:
                        conditions.append("(LOWER(a.employee_id) LIKE %s OR LOWER(a.employee_name) LIKE %s)")
                        p_s = f"%{id_cand if id_cand else clean_att.lower()}%"
                        params.extend([p_s, f"%{clean_att.lower()}%"])

            if dept:
                conditions.append("a.department = %s")
                params.append(dept)

            where_clause = " AND ".join(conditions)

            # Count total for current query
            cur.execute(f"SELECT COUNT(*) AS total FROM data.attendance a WHERE {where_clause};", tuple(params))
            total_count = cur.fetchone()['total'] or 0

            # Calculate 4 KPI metrics for the date (independent of pagination/search)
            cur.execute("SELECT COUNT(*) AS total_master FROM data.users WHERE employee_no IS NOT NULL;")
            total_master = cur.fetchone()['total_master'] or 0

            if date_param:
                cur.execute("""
                    SELECT 
                        COUNT(*) AS total_punches,
                        COUNT(DISTINCT a.employee_id) AS unique_employees,
                        COUNT(CASE WHEN a.in_geofence = FALSE THEN 1 END) AS out_of_geofence,
                        COUNT(CASE WHEN a.sign_in > '09:45:00' THEN 1 END) AS late_punches,
                        COUNT(DISTINCT CASE WHEN a.in_geofence = FALSE THEN a.employee_id END) AS unique_out_of_geofence,
                        COUNT(DISTINCT CASE WHEN a.sign_in > '09:45:00' THEN a.employee_id END) AS unique_late
                    FROM data.attendance a
                    WHERE a.date = %s;
                """, (date_param,))
            elif start_date and end_date:
                cur.execute("""
                    SELECT 
                        COUNT(*) AS total_punches,
                        COUNT(DISTINCT a.employee_id) AS unique_employees,
                        COUNT(CASE WHEN a.in_geofence = FALSE THEN 1 END) AS out_of_geofence,
                        COUNT(CASE WHEN a.sign_in > '09:45:00' THEN 1 END) AS late_punches,
                        COUNT(DISTINCT CASE WHEN a.in_geofence = FALSE THEN a.employee_id END) AS unique_out_of_geofence,
                        COUNT(DISTINCT CASE WHEN a.sign_in > '09:45:00' THEN a.employee_id END) AS unique_late
                    FROM data.attendance a
                    WHERE a.date BETWEEN %s AND %s;
                """, (start_date, end_date))
            else:
                cur.execute("""
                    SELECT 
                        COUNT(*) AS total_punches,
                        COUNT(DISTINCT a.employee_id) AS unique_employees,
                        COUNT(CASE WHEN a.in_geofence = FALSE THEN 1 END) AS out_of_geofence,
                        COUNT(CASE WHEN a.sign_in > '09:45:00' THEN 1 END) AS late_punches,
                        COUNT(DISTINCT CASE WHEN a.in_geofence = FALSE THEN a.employee_id END) AS unique_out_of_geofence,
                        COUNT(DISTINCT CASE WHEN a.sign_in > '09:45:00' THEN a.employee_id END) AS unique_late
                    FROM data.attendance a
                    WHERE a.date = %s;
                """, (today_str,))

            kpi_summary = cur.fetchone() or {}

            summary_data = {
                'total_staff': total_master,
                'total_punches': kpi_summary.get('total_punches', 0),
                'unique_employees': kpi_summary.get('unique_employees', 0),
                'late_punches': kpi_summary.get('late_punches', 0),
                'late_arrivals': kpi_summary.get('late_punches', 0),
                'unique_late': kpi_summary.get('unique_late', 0),
                'out_of_geofence': kpi_summary.get('out_of_geofence', 0),
                'out_of_range': kpi_summary.get('out_of_geofence', 0),
                'unique_out_of_geofence': kpi_summary.get('unique_out_of_geofence', 0)
            }

            # Query rows
            cur.execute(f"""
                SELECT a.id, a.employee_id, a.employee_name, a.date, a.sign_in, a.sign_out,
                       a.location, a.in_geofence, a.nearest_building, a.distance_meters,
                       a.clock_in_lat, a.clock_in_lng, a.clock_out_lat, a.clock_out_lng,
                       a.department, a.role, a.approval_status, a.reviewed_by, a.rejection_reason
                FROM data.attendance a
                WHERE {where_clause}
                ORDER BY a.date DESC, a.sign_in DESC NULLS LAST, a.id DESC
                LIMIT %s OFFSET %s;
            """, tuple(params + [limit, offset]))
            rows = cur.fetchall()

            records = []
            for r in rows:
                m = calculate_attendance_metrics(r['sign_in'], r['sign_out'])

                # Apply status filter if requested
                if status_filter and status_filter != 'all':
                    if status_filter == 'present' and 'Present' not in m['status']:
                        continue
                    if status_filter == 'late' and m['status'] != 'Late':
                        continue
                    if status_filter == 'half day' and m['status'] != 'Half Day':
                        continue
                    if status_filter == 'missing' and (r.get('sign_in') is None or r.get('sign_out') is not None):
                        continue

                records.append({
                    'id': r['id'],
                    'employee_id': r['employee_id'],
                    'employee_name': r.get('employee_name') or f"Employee {r['employee_id']}",
                    'department': r.get('department') or 'General',
                    'date': r['date'].isoformat() if hasattr(r['date'], 'isoformat') else str(r['date']),
                    'sign_in': str(r['sign_in'])[:8] if r.get('sign_in') else None,
                    'sign_out': str(r['sign_out'])[:8] if r.get('sign_out') else None,
                    'work_hours': m['work_hours'],
                    'late_mins': m['late_mins'],
                    'early_mins': m['early_mins'],
                    'overtime_hrs': m['overtime_hrs'],
                    'status': m['status'],
                    'location': r.get('location') or 'Monarch House HQ',
                    'in_geofence': bool(r.get('in_geofence', True)),
                    'nearest_building': r.get('nearest_building') or 'Monarch House (HQ)',
                    'distance_meters': float(r['distance_meters']) if r.get('distance_meters') is not None else 0.0,
                    'approval_status': r.get('approval_status') or 'Approved',
                    'clock_in_lat': float(r['clock_in_lat']) if r.get('clock_in_lat') is not None else None,
                    'clock_in_lng': float(r['clock_in_lng']) if r.get('clock_in_lng') is not None else None,
                })

            return jsonify({
                'records': records,
                'total': total_count,
                'page': page,
                'limit': limit,
                'pages': math.ceil(total_count / limit) if total_count > 0 else 1,
                'summary': summary_data,
                'kpis': summary_data,
                'filter': kpi_filter
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/attendance/monthly-cycle', methods=['GET'])
    @token_required
    @admin_required
    def get_admin_monthly_cycle_attendance():
        """Returns 26th-to-25th Monthly Attendance Muster Roll matrix for all employees."""
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        emp_search = (request.args.get('employee_id') or request.args.get('search') or '').strip().lower()
        kpi_filter = (request.args.get('filter') or request.args.get('kpi_filter') or 'all').strip().lower()
        page = max(1, int(request.args.get('page', 1)))
        limit = max(1, min(200, int(request.args.get('limit', 50))))
        offset = (page - 1) * limit

        today = get_ist_today()
        if not start_date or not end_date:
            def_start, def_end = get_payroll_cycle(today)
            start_date = def_start.isoformat()
            end_date = def_end.isoformat()

        available_cycles = get_available_payroll_cycles(8)

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
            end_dt = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()

            # Build list of date columns from 26th to 25th with Saturday indexing
            cycle_dates = []
            curr = start_dt
            while curr <= end_dt:
                sat_idx = ((curr.day - 1) // 7) + 1
                is_even_sat = (curr.weekday() == 5 and sat_idx % 2 == 0)
                is_odd_sat = (curr.weekday() == 5 and sat_idx % 2 != 0)
                is_sun = (curr.weekday() == 6)
                is_weekend = is_sun or is_even_sat

                cycle_dates.append({
                    'date': curr.isoformat(),
                    'day': curr.day,
                    'day_name': curr.strftime('%a'),
                    'is_weekend': is_weekend,
                    'is_sunday': is_sun,
                    'is_even_saturday': is_even_sat,
                    'is_odd_saturday': is_odd_sat,
                    'sat_index': sat_idx if curr.weekday() == 5 else None,
                    'month': curr.month,
                    'year': curr.year
                })
                curr += datetime.timedelta(days=1)

            # Holidays set
            holiday_dates = {h[1] for h in DEFAULT_HOLIDAYS_2026}

            # Query users with optional KPI filter and employee search
            u_conds = ["u.employee_no IS NOT NULL"]
            u_params = []
            if emp_search:
                u_conds.append("(u.employee_no::text ILIKE %s OR u.name ILIKE %s)")
                p_s = f"%{emp_search}%"
                u_params.extend([p_s, p_s])

            if kpi_filter in ['punches', 'total_punches']:
                u_conds.append("""
                    u.employee_no::text IN (
                        SELECT DISTINCT employee_id FROM data.attendance
                        WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL
                        UNION
                        SELECT DISTINCT LTRIM(employee_id, '0') FROM data.attendance
                        WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL
                    )
                """)
                u_params.extend([start_dt, end_dt, start_dt, end_dt])
            elif kpi_filter in ['late', 'late_arrivals']:
                u_conds.append("""
                    u.employee_no::text IN (
                        SELECT DISTINCT employee_id FROM data.attendance
                        WHERE date BETWEEN %s AND %s AND sign_in > '09:45:00'
                        UNION
                        SELECT DISTINCT LTRIM(employee_id, '0') FROM data.attendance
                        WHERE date BETWEEN %s AND %s AND sign_in > '09:45:00'
                    )
                """)
                u_params.extend([start_dt, end_dt, start_dt, end_dt])
            elif kpi_filter in ['out_of_range', 'geofence', 'out_of_geofence']:
                u_conds.append("""
                    u.employee_no::text IN (
                        SELECT DISTINCT employee_id FROM data.attendance
                        WHERE date BETWEEN %s AND %s AND in_geofence = FALSE
                        UNION
                        SELECT DISTINCT LTRIM(employee_id, '0') FROM data.attendance
                        WHERE date BETWEEN %s AND %s AND in_geofence = FALSE
                    )
                """)
                u_params.extend([start_dt, end_dt, start_dt, end_dt])

            u_where = " AND ".join(u_conds)

            # Total employees count
            cur.execute(f"SELECT COUNT(*) AS total FROM data.users u WHERE {u_where};", tuple(u_params))
            total_employees = cur.fetchone()['total'] or 0

            # Fetch page of employees
            cur.execute(f"""
                SELECT u.id, u.employee_no, u.name, u.weekly_off, u.department, u.designation, u.date_of_joining
                FROM data.users u
                WHERE {u_where}
                ORDER BY u.employee_no ASC
                LIMIT %s OFFSET %s;
            """, tuple(u_params + [limit, offset]))
            users = cur.fetchall()

            emp_ids = [str(u['employee_no']) for u in users]

            # Fetch all punches for these employees in this cycle
            att_map = {}
            if emp_ids:
                cur.execute("""
                    SELECT a.id, a.employee_id, a.date, a.sign_in, a.sign_out,
                           a.location, a.in_geofence, a.approval_status
                    FROM data.attendance a
                    WHERE a.date BETWEEN %s AND %s AND a.employee_id = ANY(%s)
                    ORDER BY a.date ASC, a.sign_in ASC NULLS LAST;
                """, (start_dt, end_dt, emp_ids))
                for r in cur.fetchall():
                    att_map[(str(r['employee_id']), str(r['date']))] = r

            # Fetch all leave and holiday requests for these employees overlapping this cycle
            leaves_map = {}
            if emp_ids:
                emp_id_variants = list(set(emp_ids + [e.lstrip('0') for e in emp_ids if e]))
                cur.execute("""
                    SELECT id, employee_id, leave_type, title, start_date, end_date, days_count, status, note, is_half_day, session
                    FROM data.leaves
                    WHERE employee_id = ANY(%s)
                      AND start_date <= %s AND end_date >= %s
                      AND status NOT ILIKE '%%reject%%'
                    ORDER BY CASE WHEN status ILIKE '%%approved%%' THEN 1 WHEN status ILIKE '%%pending%%' THEN 2 ELSE 3 END, id DESC;
                """, (emp_id_variants, end_dt, start_dt))
                for lr in cur.fetchall():
                    l_eid = str(lr['employee_id']).strip()
                    l_start = lr['start_date']
                    l_end = lr['end_date']
                    c_dt = max(l_start, start_dt)
                    c_max = min(l_end, end_dt)
                    while c_dt <= c_max:
                        c_str = c_dt.isoformat()
                        k1 = (l_eid, c_str)
                        k2 = (l_eid.lstrip('0'), c_str)
                        if k1 not in leaves_map:
                            leaves_map[k1] = lr
                        if k2 not in leaves_map:
                            leaves_map[k2] = lr
                        c_dt += datetime.timedelta(days=1)

            # Total staff count in master
            cur.execute("SELECT COUNT(*) AS total_master FROM data.users WHERE employee_no IS NOT NULL;")
            total_master = cur.fetchone()['total_master'] or 0

            # Cycle-wide KPI stats
            cur.execute("""
                SELECT 
                    COUNT(*) AS total_punches,
                    COUNT(DISTINCT a.employee_id) AS unique_employees,
                    COUNT(CASE WHEN a.in_geofence = FALSE THEN 1 END) AS out_of_geofence,
                    COUNT(CASE WHEN a.sign_in > '09:45:00' THEN 1 END) AS late_punches,
                    COUNT(DISTINCT CASE WHEN a.in_geofence = FALSE THEN a.employee_id END) AS unique_out_of_geofence,
                    COUNT(DISTINCT CASE WHEN a.sign_in > '09:45:00' THEN a.employee_id END) AS unique_late
                FROM data.attendance a
                WHERE a.date BETWEEN %s AND %s;
            """, (start_dt, end_dt))
            summary_row = cur.fetchone() or {}

            # Build muster rows
            cycle_month = start_dt.month
            cycle_year = start_dt.year
            muster_rows = []

            for u in users:
                eid = str(u['employee_no'])
                emp_name = u['name'] or f"Employee {eid}"
                weekly_off = (u.get('weekly_off') or 'Sunday').lower()
                doj = u.get('date_of_joining')
                if isinstance(doj, str):
                    try:
                        doj = datetime.date.fromisoformat(doj.split('T')[0])
                    except Exception:
                        doj = None
                elif isinstance(doj, datetime.datetime):
                    doj = doj.date()

                day_statuses = []
                cnt_p, cnt_a, cnt_wo, cnt_hd, cnt_h, cnt_l = 0, 0, 0, 0, 0, 0

                for d in cycle_dates:
                    d_str = d['date']
                    d_obj = datetime.datetime.strptime(d_str, '%Y-%m-%d').date()

                    # Pre-joining check: dates strictly prior to employee's date_of_joining
                    # should show blank/dash (--) and must NOT count towards Absent, Week Off, or Holiday counters.
                    if doj and d_obj < doj:
                        day_statuses.append({
                            'date': d_str,
                            'day': d['day'],
                            'day_name': d['day_name'],
                            'status': '--',
                            'details': f"Not Joined Yet (Joining Date: {doj.strftime('%d-%m-%Y')})",
                            'is_weekend': d['is_weekend'],
                            'is_sunday': d['is_sunday'],
                            'is_even_saturday': d['is_even_saturday'],
                            'is_odd_saturday': d['is_odd_saturday'],
                            'sat_index': d['sat_index'],
                            'punch_id': None,
                            'sign_in': None,
                            'sign_out': None,
                            'leave_id': None,
                            'leave_type': None,
                            'leave_status': None,
                        })
                        continue

                    punch = att_map.get((eid, d_str)) or att_map.get((eid.lstrip('0'), d_str))
                    leave = leaves_map.get((eid, d_str)) or leaves_map.get((eid.lstrip('0'), d_str))

                    is_off = (weekly_off in d['day_name'].lower()) or (d['is_sunday'] and weekly_off in ['sunday', 'sun']) or d['is_even_saturday']
                    is_holiday = (d_str in holiday_dates)
                    leave_status = str(leave.get('status') or '').strip().lower() if leave else ''
                    is_leave_pending = bool(leave and ('pending' in leave_status))
                    is_leave_approved = bool(leave and ('approved' in leave_status))

                    # Check if employee applied for or was approved for Regularization
                    is_regularized = False
                    reg_label = ''
                    if leave:
                        l_full = f"{leave.get('leave_type') or ''} {leave.get('title') or ''} {leave.get('note') or ''}".lower()
                        if 'regulariz' in l_full:
                            if 'reject' not in leave_status:
                                is_regularized = True
                                reg_label = 'Approved Regularization' if is_leave_approved else 'Pending Regularization'
                    if punch:
                        p_loc = str(punch.get('location') or '').lower()
                        p_appr = str(punch.get('approval_status') or '').lower()
                        if 'regulariz' in p_loc or 'regulariz' in p_appr:
                            if 'reject' not in p_appr:
                                is_regularized = True
                                reg_label = 'Approved Regularization' if 'approv' in p_appr else 'Pending Regularization'

                    has_in = bool(punch and punch.get('sign_in'))
                    has_out = bool(punch and punch.get('sign_out'))
                    is_missed_punch = bool(punch and (d_obj < today) and ((has_in and not has_out) or (not has_in and has_out)))

                    if punch:
                        in_t = str(punch['sign_in'])[:5] if punch.get('sign_in') else '--'
                        out_t = str(punch['sign_out'])[:5] if punch.get('sign_out') else '--'
                        m = calculate_attendance_metrics(punch.get('sign_in'), punch.get('sign_out'), date=d_obj, is_regularized=is_regularized)
                        hrs = f"{m['work_hours']}h" if m['work_hours'] > 0 else ''

                        if is_missed_punch:
                            if is_regularized:
                                # When employee puts for regularization, show Present (P)
                                status = 'P'
                                cnt_p += 1
                                details = f"Present ({reg_label or 'Regularized'}: In: {in_t} | Out: {out_t})"
                            elif is_leave_approved and (leave.get('is_half_day') or float(leave.get('days_count') or 1.0) == 0.5 or 'half' in str(leave.get('leave_type') or '').lower()):
                                hd_code, hd_desc = determine_half_day_code(punch, leave)
                                status = hd_code
                                cnt_hd += 1
                                cnt_l += 1
                                details = f"{status} - {hd_desc} (0.5 Day Punch + Approved Half Day Leave)"
                            elif is_leave_approved:
                                l_type = leave.get('leave_type') or 'Leave'
                                status = 'P'
                                cnt_p += 1
                                cnt_l += 1
                                details = f"Present (Approved Leave: {l_type} | In: {in_t} | Out: {out_t})"
                            else:
                                # Missed punch without regularization -> show Absent (A)
                                status = 'A'
                                cnt_a += 1
                                if is_leave_pending:
                                    details = f"Absent (Missed Punch: In: {in_t} | Out: {out_t} - Pending Leave: {leave.get('leave_type') or 'Leave'})"
                                elif has_in and not has_out:
                                    details = f"Absent (Missed Check-Out Punch - In: {in_t} | Out: --)"
                                else:
                                    details = f"Absent (Missed Check-In Punch - In: -- | Out: {out_t})"
                        elif 'Half Day' in m['status'] or (3.0 <= m['work_hours'] < 8.83):
                            if is_leave_approved:
                                l_type = leave.get('leave_type') or 'Leave'
                                status = 'P'
                                cnt_p += 1
                                cnt_l += 1
                                details = f"Present (0.5 Day Punch: In: {in_t} | Out: {out_t} {hrs} + 0.5 Day Approved Leave: {l_type})".strip()
                            else:
                                hd_code, hd_desc = determine_half_day_code(punch, leave)
                                status = hd_code
                                cnt_hd += 1
                                if is_leave_pending:
                                    l_type = leave.get('leave_type') or 'Leave'
                                    details = f"{status} - {hd_desc} (Pending {l_type}) | In: {in_t} | Out: {out_t} {hrs}".strip()
                                else:
                                    details = f"{status} - {hd_desc} | In: {in_t} | Out: {out_t} {hrs}".strip()
                        else:
                            status = 'P'
                            cnt_p += 1
                            if is_leave_approved:
                                cnt_l += 1
                                l_type = leave.get('leave_type') or 'Leave'
                                details = f"In: {in_t} | Out: {out_t} {hrs} (Approved Leave: {l_type})".strip()
                            else:
                                details = f"In: {in_t} | Out: {out_t} {hrs}".strip()
                    elif is_holiday:
                        status = 'H'
                        cnt_h += 1
                        details = 'Company Holiday'
                    elif is_off:
                        status = 'WO'
                        cnt_wo += 1
                        if d['is_even_saturday']:
                            sat_nth = f"{d['sat_index']}{'nd' if d['sat_index'] == 2 else 'th'}"
                            details = f"Even Saturday ({sat_nth} Sat) - Weekly Off"
                        else:
                            details = 'Weekly Off'
                    elif is_leave_pending:
                        if is_regularized:
                            status = 'P'
                            cnt_p += 1
                            details = f"Present (Regularization Request - Pending Approval)"
                        else:
                            status = 'A'
                            cnt_a += 1
                            l_type = leave.get('leave_type') or 'Holiday'
                            details = f"Absent (Request for {l_type} - Pending Approval)"
                    elif is_leave_approved:
                        cnt_l += 1
                        l_type = leave.get('leave_type') or 'Leave'
                        try:
                            d_cnt = float(leave.get('days_count') or 1.0)
                        except (ValueError, TypeError):
                            d_cnt = 1.0
                        is_half = bool(leave.get('is_half_day') or d_cnt == 0.5)
                        l_sess = str(leave.get('session') or leave.get('from_session') or '').strip()
                        sess_text = f" ({l_sess})" if l_sess else ""
                        if is_half:
                            hd_code, hd_desc = determine_half_day_code(punch, leave)
                            status = hd_code
                            cnt_hd += 1
                            details = f"{status} - {hd_desc} (Approved Leave: {l_type}{sess_text})"
                        else:
                            status = 'P'
                            cnt_p += 1
                            details = f"Present (Approved Leave: {l_type})"
                    elif d_obj > today:
                        status = '--'
                        details = 'Upcoming'
                    else:
                        status = 'A'
                        cnt_a += 1
                        if d['is_odd_saturday']:
                            sat_nth = f"{d['sat_index']}{'st' if d['sat_index'] == 1 else ('rd' if d['sat_index'] == 3 else 'th')}"
                            details = f"Absent ({sat_nth} Saturday - Working Day)"
                        else:
                            details = 'Absent'

                    punch_in_str = str(punch['sign_in'])[:8] if punch and punch.get('sign_in') else None
                    is_punch_late = bool(punch_in_str and punch_in_str > '09:45:00')
                    is_punch_out_of_range = bool(punch and punch.get('in_geofence') is False)

                    if is_punch_late and 'Late' not in details:
                        details += f" • ⚠ Late ({punch_in_str[:5]})"
                    if is_punch_out_of_range and 'Out of Range' not in details:
                        details += " • 📍 Out of Range"

                    day_statuses.append({
                        'date': d_str,
                        'day': d['day'],
                        'day_name': d['day_name'],
                        'status': status,
                        'details': details,
                        'is_weekend': d['is_weekend'],
                        'is_sunday': d['is_sunday'],
                        'is_even_saturday': d['is_even_saturday'],
                        'is_odd_saturday': d['is_odd_saturday'],
                        'sat_index': d['sat_index'],
                        'punch_id': punch['id'] if punch else None,
                        'sign_in': punch_in_str,
                        'sign_out': str(punch['sign_out'])[:8] if punch and punch.get('sign_out') else None,
                        'is_late': is_punch_late,
                        'out_of_range': is_punch_out_of_range,
                        'leave_id': leave['id'] if leave else None,
                        'leave_type': leave.get('leave_type') if leave else None,
                        'leave_status': leave.get('status') if leave else None,
                    })

                muster_rows.append({
                    'employee_number': eid,
                    'employee_name': emp_name,
                    'department': u.get('department') or '',
                    'designation': u.get('designation') or '',
                    'date_of_joining': doj.isoformat() if doj else None,
                    'month': cycle_month,
                    'year': cycle_year,
                    'days': day_statuses,
                    'summary': {
                        'present': cnt_p,
                        'absent': cnt_a,
                        'week_off': cnt_wo,
                        'half_day': cnt_hd,
                        'holiday': cnt_h,
                        'leave': cnt_l,
                        'total_worked': round(cnt_p + (cnt_hd * 0.5), 1)
                    }
                })

            cycle_label = f"26 {start_dt.strftime('%b %Y')} - 25 {end_dt.strftime('%b %Y')}"

            return jsonify({
                'cycle': {
                    'start_date': start_date,
                    'end_date': end_date,
                    'label': cycle_label
                },
                'available_cycles': available_cycles,
                'cycle_dates': cycle_dates,
                'muster': muster_rows,
                'filter': kpi_filter,
                'summary': {
                    'total_staff': total_master,
                    'total_punches': summary_row.get('total_punches', 0),
                    'unique_employees': summary_row.get('unique_employees', 0),
                    'out_of_geofence': summary_row.get('out_of_geofence', 0),
                    'late_punches': summary_row.get('late_punches', 0),
                    'unique_out_of_geofence': summary_row.get('unique_out_of_geofence', 0),
                    'unique_late': summary_row.get('unique_late', 0)
                },
                'total': total_employees,
                'total_all_staff': total_master,
                'page': page,
                'limit': limit,
                'pages': math.ceil(total_employees / limit) if total_employees > 0 else 1
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/attendance/manual-punch', methods=['POST'])
    @token_required
    @admin_required
    def add_manual_attendance():
        """Creates or sets a missing attendance punch for an employee with mandatory reason."""
        data = request.get_json() or {}
        emp_id = str(data.get('employee_id') or '').strip()
        att_date = data.get('date')
        sign_in = data.get('sign_in')
        sign_out = data.get('sign_out')
        reason = (data.get('reason') or '').strip()

        if not emp_id or not att_date:
            return jsonify({'error': 'Employee ID and attendance date are mandatory'}), 400

        if not reason:
            return jsonify({'error': 'A mandatory audit reason is required for manual attendance insertion'}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # Lookup employee name and department
            cur.execute("SELECT name, department, role FROM data.users WHERE employee_no = %s OR id = %s;", (emp_id if emp_id.isdigit() else 0, emp_id if emp_id.isdigit() else 0))
            u_info = cur.fetchone() or {'name': f"Employee {emp_id}", 'department': 'Operations', 'role': 'employee'}

            cur.execute("""
                INSERT INTO data.attendance (
                    employee_id, employee_name, date, sign_in, sign_out,
                    location, in_geofence, department, role, approval_status,
                    reviewed_by, reviewed_at
                ) VALUES (%s, %s, %s, %s::time, %s::time, %s, TRUE, %s, %s, 'Approved', %s, NOW())
                ON CONFLICT (employee_id, date) DO UPDATE SET
                    sign_in = COALESCE(EXCLUDED.sign_in, data.attendance.sign_in),
                    sign_out = COALESCE(EXCLUDED.sign_out, data.attendance.sign_out),
                    approval_status = 'Approved',
                    reviewed_by = EXCLUDED.reviewed_by,
                    reviewed_at = NOW()
                RETURNING *;
            """, (
                emp_id, u_info['name'], att_date, sign_in, sign_out,
                'Manual Admin Entry (HQ)', u_info['department'], u_info['role'],
                request.user.get('name')
            ))
            rec = cur.fetchone()
            conn.commit()

            # Audit log (every manual change records admin, timestamp, and reason)
            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='ATTENDANCE_MANUAL_INSERT',
                target_type='attendance',
                target_id=str(rec['id']),
                reason=reason,
                after_val={'employee_id': emp_id, 'date': att_date, 'sign_in': sign_in, 'sign_out': sign_out}
            )

            return jsonify({
                'success': True,
                'message': f"Manual attendance for {u_info['name']} on {att_date} recorded successfully.",
                'record': {
                    'id': rec['id'],
                    'employee_id': rec['employee_id'],
                    'employee_name': rec['employee_name'],
                    'date': rec['date'].isoformat() if hasattr(rec['date'], 'isoformat') else str(rec['date']),
                    'sign_in': str(rec['sign_in'])[:8] if rec.get('sign_in') else None,
                    'sign_out': str(rec['sign_out'])[:8] if rec.get('sign_out') else None,
                    'approval_status': rec['approval_status']
                }
            })

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/attendance/<int:record_id>/correct', methods=['PUT'])
    @token_required
    @admin_required
    def correct_attendance_record(record_id):
        """Corrects check-in / check-out times with mandatory audit tracking. Allows setting punches to NULL."""
        data = request.get_json() or {}
        raw_sign_in = data.get('sign_in')
        raw_sign_out = data.get('sign_out')
        clear_sign_in = bool(data.get('clear_sign_in'))
        clear_sign_out = bool(data.get('clear_sign_out'))

        new_sign_in = None if (clear_sign_in or raw_sign_in in [None, '', 'null', 'None', '--']) else str(raw_sign_in).strip()
        new_sign_out = None if (clear_sign_out or raw_sign_out in [None, '', 'null', 'None', '--']) else str(raw_sign_out).strip()

        new_status = data.get('approval_status') or 'Approved'
        reason = (data.get('reason') or '').strip()

        if not reason:
            return jsonify({'error': 'A mandatory audit reason is required for correcting attendance records'}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            cur.execute("SELECT * FROM data.attendance WHERE id = %s;", (record_id,))
            before = cur.fetchone()
            if not before:
                return jsonify({'error': 'Attendance record not found'}), 404

            cur.execute("""
                UPDATE data.attendance
                SET sign_in = %s::time,
                    sign_out = %s::time,
                    approval_status = COALESCE(%s, approval_status),
                    reviewed_by = %s,
                    reviewed_at = NOW(),
                    is_manually_corrected = TRUE,
                    clock_out_lat = CASE WHEN %s::time IS NULL THEN NULL ELSE clock_out_lat END,
                    clock_out_lng = CASE WHEN %s::time IS NULL THEN NULL ELSE clock_out_lng END,
                    clock_out_distance_meters = CASE WHEN %s::time IS NULL THEN NULL ELSE clock_out_distance_meters END,
                    clock_out_in_geofence = CASE WHEN %s::time IS NULL THEN FALSE ELSE clock_out_in_geofence END
                WHERE id = %s
                RETURNING *;
            """, (new_sign_in, new_sign_out, new_status, request.user.get('name'), new_sign_out, new_sign_out, new_sign_out, new_sign_out, record_id))
            updated = cur.fetchone()

            # Synchronize data.devicelogs so deleted/cleared punches do not resurrect
            rec_date = before.get('date')
            emp_id_val = str(before.get('employee_id') or '').strip()
            if rec_date and emp_id_val:
                devicelogs_tbl = f"devicelogs_{rec_date.month}_{rec_date.year}"
                id_variants = (emp_id_val, emp_id_val.lstrip('0'), emp_id_val.zfill(5))
                if new_sign_out is None:
                    try:
                        cur.execute(f"""
                            DELETE FROM data."{devicelogs_tbl}"
                            WHERE userid IN %s
                              AND logdate::date = %s
                              AND (direction = 'out' OR (logdate::time = %s AND %s IS NOT NULL));
                        """, (id_variants, rec_date, before.get('sign_out'), before.get('sign_out')))
                    except Exception as e_del:
                        logger.warning(f"Notice while removing out-punch from data.{devicelogs_tbl}: {e_del}")
                elif new_sign_out != (str(before.get('sign_out')) if before.get('sign_out') else None):
                    try:
                        new_dt = datetime.datetime.combine(rec_date, datetime.time.fromisoformat(new_sign_out))
                        cur.execute(f"""
                            UPDATE data."{devicelogs_tbl}"
                            SET logdate = %s
                            WHERE userid IN %s
                              AND logdate::date = %s
                              AND direction = 'out';
                        """, (new_dt, id_variants, rec_date))
                    except Exception as e_upd:
                        logger.warning(f"Notice while updating out-punch in data.{devicelogs_tbl}: {e_upd}")

                if new_sign_in is None:
                    try:
                        cur.execute(f"""
                            DELETE FROM data."{devicelogs_tbl}"
                            WHERE userid IN %s
                              AND logdate::date = %s
                              AND (direction = 'in' OR (logdate::time = %s AND %s IS NOT NULL));
                        """, (id_variants, rec_date, before.get('sign_in'), before.get('sign_in')))
                    except Exception as e_del_in:
                        logger.warning(f"Notice while removing in-punch from data.{devicelogs_tbl}: {e_del_in}")

            conn.commit()

            # Record in audit log: original value, updated value, admin, timestamp, reason
            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='ATTENDANCE_CORRECT',
                target_type='attendance',
                target_id=str(record_id),
                reason=reason,
                before_val={
                    'sign_in': str(before['sign_in']) if before.get('sign_in') else None,
                    'sign_out': str(before['sign_out']) if before.get('sign_out') else None,
                    'approval_status': before.get('approval_status')
                },
                after_val={
                    'sign_in': str(updated['sign_in']) if updated.get('sign_in') else None,
                    'sign_out': str(updated['sign_out']) if updated.get('sign_out') else None,
                    'approval_status': updated.get('approval_status')
                }
            )

            m = calculate_attendance_metrics(updated['sign_in'], updated['sign_out'])
            return jsonify({
                'success': True,
                'message': 'Attendance record successfully corrected.',
                'record': {
                    'id': updated['id'],
                    'employee_id': updated['employee_id'],
                    'employee_name': updated['employee_name'],
                    'date': updated['date'].isoformat() if hasattr(updated['date'], 'isoformat') else str(updated['date']),
                    'sign_in': str(updated['sign_in'])[:8] if updated.get('sign_in') else None,
                    'sign_out': str(updated['sign_out'])[:8] if updated.get('sign_out') else None,
                    'work_hours': m['work_hours'],
                    'status': m['status'],
                    'approval_status': updated['approval_status']
                }
            })

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/attendance/anomalies', methods=['GET'])
    @token_required
    @admin_required
    def get_attendance_anomalies():
        """Lists missing punches, out-of-geofence punches, and extreme late arrivals."""
        today_date = get_ist_today()
        today_str = today_date.isoformat()
        past_week = (today_date - datetime.timedelta(days=7)).isoformat()

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # 1. Missing checkouts
            cur.execute("""
                SELECT id, employee_id, employee_name, department, date, sign_in, 'Missing Checkout' as anomaly_type
                FROM data.attendance
                WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL AND sign_out IS NULL
                ORDER BY date DESC, id DESC
                LIMIT 30;
            """, (past_week, today_str))
            missing_checkouts = cur.fetchall()

            # 2. Out of geofence punches
            cur.execute("""
                SELECT id, employee_id, employee_name, department, date, sign_in, sign_out, location, distance_meters, 'Out of Geofence' as anomaly_type
                FROM data.attendance
                WHERE date BETWEEN %s AND %s AND in_geofence IS FALSE
                ORDER BY date DESC, id DESC
                LIMIT 30;
            """, (past_week, today_str))
            geofence_anomalies = cur.fetchall()

            # 3. Excessive tardiness (> 60m late)
            cur.execute("""
                SELECT id, employee_id, employee_name, department, date, sign_in, 'Late Arrival (>60m)' as anomaly_type
                FROM data.attendance
                WHERE date BETWEEN %s AND %s AND sign_in > '10:30:00'
                ORDER BY date DESC, id DESC
                LIMIT 30;
            """, (past_week, today_str))
            late_anomalies = cur.fetchall()

            combined = []
            for r in (missing_checkouts + geofence_anomalies + late_anomalies):
                combined.append({
                    'id': r['id'],
                    'employee_id': r['employee_id'],
                    'employee_name': r.get('employee_name') or f"Employee {r['employee_id']}",
                    'department': r.get('department') or 'Operations',
                    'date': r['date'].isoformat() if hasattr(r['date'], 'isoformat') else str(r['date']),
                    'sign_in': str(r['sign_in'])[:8] if r.get('sign_in') else None,
                    'sign_out': str(r.get('sign_out'))[:8] if r.get('sign_out') else None,
                    'anomaly': r['anomaly_type']
                })

            return jsonify({'anomalies': combined, 'total': len(combined)})

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 4. Leave Management Module ─────────────────────────────────────────────
    @app.route('/api/admin/leave-requests', methods=['GET'])
    @token_required
    @admin_required
    def get_admin_leave_requests():
        status_filter = request.args.get('status')
        dept_filter = request.args.get('department')
        emp_filter = request.args.get('employee_id')

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            conditions = ["1=1"]
            params = []

            if status_filter:
                conditions.append("status ILIKE %s")
                params.append(f"%{status_filter}%")

            if dept_filter:
                conditions.append("department = %s")
                params.append(dept_filter)

            if emp_filter:
                conditions.append("employee_id = %s")
                params.append(emp_filter)

            where_clause = " AND ".join(conditions)

            cur.execute(f"""
                SELECT id, employee_id, employee_name, department, title, leave_type,
                       start_date, end_date, days_count, status, applied_at, note,
                       reviewed_by, reviewed_at, rejection_reason, is_half_day, session
                FROM data.leaves
                WHERE {where_clause}
                ORDER BY applied_at DESC;
            """, tuple(params))
            rows = cur.fetchall()

            users_map = load_monarch_users_map()
            leaves = []
            for r in rows:
                target_emp_id = str(r['employee_id'] or '').strip()
                uinfo = users_map.get(target_emp_id) or users_map.get(target_emp_id.lstrip('0'))
                if not uinfo and r.get('employee_name'):
                    raw_name = str(r['employee_name']).strip()
                    uinfo = users_map.get(raw_name.lower()) or users_map.get(f"norm_{normalize_person_name(raw_name)}")
                uinfo = uinfo or {}

                manager_name = (uinfo.get('reporting_manager') or '').strip()
                has_direct_mgr = bool(manager_name)
                if not manager_name:
                    manager_name = 'Department Manager / Head'

                rev_by_raw = str(r.get('reviewed_by') or '').strip()
                rev_user = None
                rev_name = None
                rev_role = None
                if rev_by_raw:
                    rev_user = users_map.get(rev_by_raw) or users_map.get(rev_by_raw.lstrip('0'))
                    if not rev_user:
                        rev_user = users_map.get(rev_by_raw.lower())
                    rev_name = rev_user.get('name') if rev_user else rev_by_raw
                    rev_role = (rev_user.get('designation') or rev_user.get('role')) if rev_user else 'Administrator'

                applied_at_str = r['applied_at'].isoformat() if hasattr(r['applied_at'], 'isoformat') else str(r['applied_at'])
                reviewed_at_str = r['reviewed_at'].isoformat() if r.get('reviewed_at') and hasattr(r['reviewed_at'], 'isoformat') else None

                is_approved = (r['status'] == 'Approved')
                is_rejected = (r['status'] == 'Rejected')
                is_pending = not is_approved and not is_rejected

                step1 = {
                    'step': 1,
                    'title': 'Leave Request Submitted',
                    'actor': r.get('employee_name') or f"Employee {r['employee_id']}",
                    'role': uinfo.get('designation') or 'Staff Applicant',
                    'status': 'completed',
                    'badge': 'badge-green',
                    'timestamp': applied_at_str,
                    'note': r.get('note') or 'Application filed'
                }

                if is_approved:
                    step2_status = 'completed'
                    step2_badge = 'badge-green'
                    step2_note = f"Approved by {rev_name or manager_name} ({reviewed_at_str or 'Recorded'})"
                elif is_rejected:
                    step2_status = 'rejected'
                    step2_badge = 'badge-red'
                    step2_note = f"Rejected: {r.get('rejection_reason') or 'Application rejected'}"
                else:
                    step2_status = 'pending'
                    step2_badge = 'badge-amber'
                    step2_note = f"Awaiting review from Direct Reporting Manager: {manager_name}"

                step2 = {
                    'step': 2,
                    'title': 'Direct Reporting Manager Approval (Sole Authority)',
                    'actor': manager_name,
                    'role': 'Direct Reporting Manager',
                    'status': step2_status,
                    'badge': step2_badge,
                    'timestamp': reviewed_at_str if (is_approved or is_rejected) else None,
                    'note': step2_note
                }

                if is_approved:
                    step3_status = 'completed'
                    step3_badge = 'badge-green'
                    step3_note = f"Leave balance adjusted & finalized in attendance roster upon approval by {manager_name}"
                elif is_rejected:
                    step3_status = 'rejected'
                    step3_badge = 'badge-red'
                    step3_note = f"Leave request declined by {manager_name} — roster and quota unchanged"
                else:
                    step3_status = 'pending_manager'
                    step3_badge = 'badge-gray'
                    step3_note = f"Awaiting decision from Direct Reporting Manager ({manager_name}). System roster will auto-sync upon manager approval."

                step3 = {
                    'step': 3,
                    'title': 'Roster & Leave Quota Synchronization',
                    'actor': 'Automated Attendance System',
                    'role': 'Post-Approval Processing',
                    'status': step3_status,
                    'badge': step3_badge,
                    'timestamp': reviewed_at_str if (is_approved or is_rejected) else None,
                    'note': step3_note
                }

                flow = [step1, step2, step3]

                leaves.append({
                    'id': r['id'],
                    'employee_id': r['employee_id'],
                    'employee_name': r.get('employee_name') or f"Employee {r['employee_id']}",
                    'department': r.get('department') or '',
                    'designation': uinfo.get('designation') or 'Employee',
                    'reporting_manager': manager_name,
                    'has_direct_manager': has_direct_mgr,
                    'current_approver': manager_name if is_pending else (rev_name or 'Admin / HR'),
                    'reviewer_name': rev_name,
                    'reviewer_role': rev_role,
                    'title': r['title'],
                    'leave_type': r.get('leave_type') or 'Annual',
                    'start_date': r['start_date'].isoformat() if hasattr(r['start_date'], 'isoformat') else str(r['start_date']),
                    'end_date': r['end_date'].isoformat() if hasattr(r['end_date'], 'isoformat') else str(r['end_date']),
                    'days_count': float(r.get('days_count') or 1.0),
                    'is_half_day': bool(r.get('is_half_day') or float(r.get('days_count') or 1.0) == 0.5),
                    'session': r.get('session') or '',
                    'status': r['status'],
                    'applied_at': applied_at_str,
                    'note': r.get('note') or '',
                    'reviewed_by': r.get('reviewed_by') or '',
                    'reviewed_at': reviewed_at_str,
                    'rejection_reason': r.get('rejection_reason') or '',
                    'approval_flow': flow
                })

            return jsonify(leaves)

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/leave-requests/<int:leave_id>/review', methods=['POST'])
    @token_required
    @admin_required
    def review_leave_request(leave_id):
        """Admin and HR have full authority to review, approve, and reject leave requests."""
        data = request.get_json() or {}
        action = (data.get('action') or 'approve').strip().lower()
        reason = (data.get('reason') or data.get('rejection_reason') or '').strip()

        if action not in ['approve', 'reject']:
            return jsonify({'error': "Action must be 'approve' or 'reject'"}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            cur.execute("SELECT * FROM data.leaves WHERE id = %s;", (leave_id,))
            leave_req = cur.fetchone()
            if not leave_req:
                return jsonify({'error': 'Leave request not found'}), 404

            emp_id = str(leave_req['employee_id']).strip()
            days_count = float(leave_req.get('days_count') or 1.0)
            old_status = leave_req['status']

            if action == 'approve':
                new_status = 'Approved'
                cur.execute("""
                    UPDATE data.leaves
                    SET status = 'Approved',
                        reviewed_by = %s,
                        reviewed_at = NOW(),
                        rejection_reason = NULL
                    WHERE id = %s;
                """, (request.user.get('name'), leave_id))

                # Deduct balance only if not already approved
                if old_status != 'Approved':
                    cur.execute("""
                        INSERT INTO data.leave_balances (employee_id, total_allotted, used_days, remaining_days, updated_at)
                        VALUES (%s, 6.0, %s, 6.0 - %s, NOW())
                        ON CONFLICT (employee_id) DO UPDATE
                        SET used_days = data.leave_balances.used_days + EXCLUDED.used_days,
                            remaining_days = data.leave_balances.remaining_days - EXCLUDED.used_days,
                            updated_at = NOW();
                    """, (emp_id, days_count, days_count))

                audit_action = 'LEAVE_APPROVE'

            else:  # reject
                new_status = 'Rejected'
                cur.execute("""
                    UPDATE data.leaves
                    SET status = 'Rejected',
                        reviewed_by = %s,
                        reviewed_at = NOW(),
                        rejection_reason = %s
                    WHERE id = %s;
                """, (request.user.get('name'), reason, leave_id))

                # Refund balance if was previously approved
                if old_status == 'Approved':
                    cur.execute("""
                        UPDATE data.leave_balances
                        SET used_days = GREATEST(0.0, used_days - %s),
                            remaining_days = LEAST(total_allotted, remaining_days + %s),
                            updated_at = NOW()
                        WHERE employee_id = %s OR employee_id = %s;
                    """, (days_count, days_count, emp_id, emp_id.lstrip('0')))

                audit_action = 'LEAVE_REJECT'

            conn.commit()

            # Audit entry
            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action=audit_action,
                target_type='leave',
                target_id=str(leave_id),
                reason=reason,
                before_val={'status': old_status},
                after_val={'status': new_status, 'reviewer': request.user.get('name')}
            )

            return jsonify({
                'success': True,
                'message': f"Leave request #{leave_id} for {leave_req.get('employee_name')} has been {new_status.lower()}.",
                'status': new_status
            })

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/leaves/apply-on-behalf', methods=['POST'])
    @token_required
    @admin_required
    def apply_leave_on_behalf():
        """Applies leave on behalf of an employee directly with balance validation."""
        data = request.get_json() or {}
        emp_id = str(data.get('employee_id') or '').strip()
        title = (data.get('title') or '').strip()
        leave_type = data.get('leave_type') or 'Annual'
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        days_count = float(data.get('days_count') or 1.0)
        is_half_day = bool(data.get('is_half_day') or days_count == 0.5)
        session = (data.get('session') or ('Session 1' if is_half_day else None))
        if is_half_day and not session:
            session = 'Session 1'
        note = data.get('note') or ''
        reason = (data.get('reason') or 'Applied by HR / Admin').strip()

        if not emp_id or not start_date or not end_date:
            return jsonify({'error': 'Employee ID, start date, and end date are mandatory'}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # Ensure columns exist in data.leaves
            cur.execute("""
                ALTER TABLE data.leaves ADD COLUMN IF NOT EXISTS is_half_day BOOLEAN DEFAULT FALSE;
                ALTER TABLE data.leaves ADD COLUMN IF NOT EXISTS session VARCHAR(50);
                ALTER TABLE data.leaves ADD COLUMN IF NOT EXISTS from_session VARCHAR(50);
                ALTER TABLE data.leaves ADD COLUMN IF NOT EXISTS to_session VARCHAR(50);
            """)

            # Lookup employee
            cur.execute("SELECT name, department FROM data.users WHERE employee_no = %s OR id = %s;", (int(emp_id) if emp_id.isdigit() else 0, int(emp_id) if emp_id.isdigit() else 0))
            u_info = cur.fetchone() or {'name': f"Employee {emp_id}", 'department': 'Operations'}

            session_text = f" ({session})" if is_half_day and session else ""
            final_title = title or f"{leave_type}{session_text}"
            final_note = f"{reason} [Admin/HR Applied{session_text}]"

            # Insert leave
            cur.execute("""
                INSERT INTO data.leaves (
                    employee_id, employee_name, department, title, leave_type,
                    start_date, end_date, days_count, status, applied_at, note,
                    reviewed_by, reviewed_at, is_half_day, session, from_session, to_session
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Approved', NOW(), %s, %s, NOW(), %s, %s, %s, %s)
                RETURNING id;
            """, (
                emp_id, u_info['name'], u_info['department'], final_title,
                leave_type, start_date, end_date, days_count, final_note,
                request.user.get('name'), is_half_day, session, session, session
            ))
            new_id = cur.fetchone()['id']

            # Deduct balance
            cur.execute("""
                INSERT INTO data.leave_balances (employee_id, total_allotted, used_days, remaining_days, updated_at)
                VALUES (%s, 6.0, %s, 6.0 - %s, NOW())
                ON CONFLICT (employee_id) DO UPDATE
                SET used_days = data.leave_balances.used_days + EXCLUDED.used_days,
                    remaining_days = data.leave_balances.remaining_days - EXCLUDED.used_days,
                    updated_at = NOW();
            """, (emp_id, days_count, days_count))

            conn.commit()

            # Log audit
            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='LEAVE_APPLY_ADMIN',
                target_type='leave',
                target_id=str(new_id),
                reason=reason,
                after_val={'employee_id': emp_id, 'days_count': days_count, 'start_date': start_date, 'end_date': end_date, 'is_half_day': is_half_day, 'session': session}
            )

            half_str = f" [Half Day - {session}]" if is_half_day else ""
            return jsonify({
                'success': True,
                'message': f"Leave for {u_info['name']} ({days_count} days{half_str}) recorded and approved.",
                'leave_id': new_id
            })

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/leave-balances', methods=['GET'])
    @token_required
    @admin_required
    def get_all_leave_balances():
        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT u.id, u.employee_no, u.name, u.department, u.designation,
                       COALESCE(lb.total_allotted, 6.0) AS total_allotted,
                       COALESCE(lb.used_days, 0.0) AS used_days,
                       COALESCE(lb.remaining_days, 6.0) AS remaining_days
                FROM data.users u
                LEFT JOIN data.leave_balances lb 
                       ON CAST(u.employee_no AS TEXT) = lb.employee_id
                WHERE u.is_active IS NOT FALSE
                ORDER BY u.employee_no ASC, u.name ASC;
            """)
            rows = cur.fetchall()

            balances = []
            for r in rows:
                balances.append({
                    'employee_id': str(r['employee_no']),
                    'name': r['name'],
                    'department': r.get('department') or 'General',
                    'designation': r.get('designation') or 'Staff',
                    'total_allotted': float(r['total_allotted']),
                    'used_days': float(r['used_days']),
                    'remaining_days': float(r['remaining_days'])
                })

            return jsonify(balances)

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/leave-balances/<employee_id>', methods=['PUT'])
    @token_required
    @admin_required
    def adjust_leave_balance(employee_id):
        """Adjusts employee leave quota with mandatory reason and audit entry."""
        data = request.get_json() or {}
        total = float(data.get('total_allotted', 6.0))
        used = float(data.get('used_days', 0.0))
        remaining = float(data.get('remaining_days', total - used))
        reason = (data.get('reason') or '').strip()

        if not reason:
            return jsonify({'error': 'A mandatory audit reason is required for adjusting employee leave quota'}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            cur.execute("""
                SELECT total_allotted, used_days, remaining_days 
                FROM data.leave_balances 
                WHERE employee_id = %s OR employee_id = %s;
            """, (employee_id, employee_id.lstrip('0')))
            before = cur.fetchone() or {'total_allotted': 6.0, 'used_days': 0.0, 'remaining_days': 6.0}

            cur.execute("""
                INSERT INTO data.leave_balances (employee_id, total_allotted, used_days, remaining_days, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (employee_id) DO UPDATE
                SET total_allotted = EXCLUDED.total_allotted,
                    used_days = EXCLUDED.used_days,
                    remaining_days = EXCLUDED.remaining_days,
                    updated_at = NOW()
                RETURNING total_allotted, used_days, remaining_days;
            """, (employee_id, total, used, remaining))
            updated = cur.fetchone()
            conn.commit()

            # Record audit log
            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='LEAVE_BALANCE_ADJUST',
                target_type='leave_balance',
                target_id=str(employee_id),
                reason=reason,
                before_val=dict(before),
                after_val=dict(updated)
            )

            return jsonify({
                'success': True,
                'message': f'Leave balance for Employee #{employee_id} adjusted.',
                'balance': {
                    'employee_id': employee_id,
                    'total_allotted': float(updated['total_allotted']),
                    'used_days': float(updated['used_days']),
                    'remaining_days': float(updated['remaining_days'])
                }
            })

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/leave-types', methods=['GET', 'POST'])
    @token_required
    @admin_required
    def manage_leave_types():
        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            if request.method == 'GET':
                cur.execute("SELECT * FROM data.leave_types ORDER BY id ASC;")
                rows = cur.fetchall()
                types = []
                for r in rows:
                    types.append({
                        'id': r['id'],
                        'name': r['name'],
                        'code': r['code'],
                        'annual_days': float(r['annual_days']),
                        'carry_forward_max': float(r['carry_forward_max']),
                        'is_paid': bool(r['is_paid']),
                        'description': r.get('description') or ''
                    })
                return jsonify(types)

            elif request.method == 'POST':
                data = request.get_json() or {}
                name = (data.get('name') or '').strip()
                code = (data.get('code') or '').strip().upper()
                annual = float(data.get('annual_days', 12.0))
                carry = float(data.get('carry_forward_max', 5.0))
                is_paid = bool(data.get('is_paid', True))
                desc = data.get('description', '')

                if not name or not code:
                    return jsonify({'error': 'Name and code are required'}), 400

                cur.execute("""
                    INSERT INTO data.leave_types (name, code, annual_days, carry_forward_max, is_paid, description)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        annual_days = EXCLUDED.annual_days,
                        carry_forward_max = EXCLUDED.carry_forward_max,
                        is_paid = EXCLUDED.is_paid,
                        description = EXCLUDED.description
                    RETURNING *;
                """, (name, code, annual, carry, is_paid, desc))
                lt = cur.fetchone()
                conn.commit()

                log_audit_event(
                    get_monarch_connection,
                    actor_id=request.user.get('emp_id'),
                    actor_name=request.user.get('name'),
                    action='LEAVE_TYPE_CONFIGURE',
                    target_type='leave_type',
                    target_id=code,
                    reason=f"Configured leave type {name} ({code})",
                    after_val=dict(lt)
                )

                return jsonify({'success': True, 'leave_type': dict(lt)})

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 5. Shifts & Working Hours Module ───────────────────────────────────────
    @app.route('/api/admin/shifts', methods=['GET', 'POST'])
    @token_required
    @admin_required
    def manage_shifts():
        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            if request.method == 'GET':
                cur.execute("SELECT * FROM data.shifts ORDER BY id ASC;")
                rows = cur.fetchall()
                shifts = []
                for r in rows:
                    shifts.append({
                        'id': r['id'],
                        'shift_name': r['shift_name'],
                        'start_time': str(r['start_time'])[:8],
                        'end_time': str(r['end_time'])[:8],
                        'grace_period_mins': r['grace_period_mins'],
                        'half_day_hours': float(r['half_day_hours']),
                        'full_day_hours': float(r['full_day_hours']),
                        'min_overtime_mins': r['min_overtime_mins'],
                        'is_night_shift': bool(r['is_night_shift']),
                        'working_days': r.get('working_days') or 'Mon,Tue,Wed,Thu,Fri,Sat',
                        'description': r.get('description') or ''
                    })
                return jsonify(shifts)

            elif request.method == 'POST':
                data = request.get_json() or {}
                name = (data.get('shift_name') or '').strip()
                start_t = data.get('start_time')
                end_t = data.get('end_time')
                grace = int(data.get('grace_period_mins', 15))
                half_d = float(data.get('half_day_hours', 4.5))
                full_d = float(data.get('full_day_hours', 8.5))
                is_night = bool(data.get('is_night_shift', False))
                desc = data.get('description', '')

                if not name or not start_t or not end_t:
                    return jsonify({'error': 'Shift name, start time, and end time are mandatory'}), 400

                cur.execute("""
                    INSERT INTO data.shifts (
                        shift_name, start_time, end_time, grace_period_mins,
                        half_day_hours, full_day_hours, is_night_shift, description
                    ) VALUES (%s, %s::time, %s::time, %s, %s, %s, %s, %s)
                    ON CONFLICT (shift_name) DO UPDATE SET
                        start_time = EXCLUDED.start_time,
                        end_time = EXCLUDED.end_time,
                        grace_period_mins = EXCLUDED.grace_period_mins,
                        half_day_hours = EXCLUDED.half_day_hours,
                        full_day_hours = EXCLUDED.full_day_hours,
                        is_night_shift = EXCLUDED.is_night_shift,
                        description = EXCLUDED.description
                    RETURNING *;
                """, (name, start_t, end_t, grace, half_d, full_d, is_night, desc))
                sh = cur.fetchone()
                conn.commit()

                log_audit_event(
                    get_monarch_connection,
                    actor_id=request.user.get('emp_id'),
                    actor_name=request.user.get('name'),
                    action='SHIFT_CONFIG_UPDATE',
                    target_type='shift',
                    target_id=name,
                    reason=f"Configured work shift: {name} ({start_t} - {end_t})",
                    after_val=dict(sh)
                )

                return jsonify({'success': True, 'shift': dict(sh)})

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/employees/assign-shift', methods=['POST'])
    @token_required
    @admin_required
    def assign_shift_to_employees():
        """Assigns shift timing to specific employees or whole department."""
        data = request.get_json() or {}
        emp_ids = data.get('employee_ids') or [data.get('employee_id')]
        shift_timing = data.get('shift_timing') or '09:30 AM - 06:30 PM'
        shift_id = data.get('shift_id', 1)

        if not emp_ids:
            return jsonify({'error': 'Employee IDs required'}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            for eid in emp_ids:
                cur.execute("""
                    UPDATE data.users
                    SET shift_timing = %s, shift_id = %s
                    WHERE employee_no = %s OR id = %s;
                """, (shift_timing, shift_id, eid if str(eid).isdigit() else 0, eid if str(eid).isdigit() else 0))

            conn.commit()

            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action='SHIFT_ASSIGNMENT',
                target_type='user',
                target_id=str(emp_ids),
                reason=f"Assigned shift {shift_timing} to {len(emp_ids)} employees"
            )

            return jsonify({'success': True, 'message': f"Assigned shift to {len(emp_ids)} staff members."})

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 6. GPS Tracking & Live Locations Module ────────────────────────────────
    @app.route('/api/admin/gps/live-tracking', methods=['GET'])
    @token_required
    @admin_required
    def get_live_gps_tracking():
        """Returns verified employee coordinates for phone check-ins, phone check-outs, and biometric punches."""
        query_date_str = request.args.get('date', '').strip()
        if query_date_str:
            try:
                target_date = datetime.date.fromisoformat(query_date_str)
            except Exception:
                target_date = get_ist_today()
        else:
            target_date = get_ist_today()

        today_str = target_date.isoformat()
        is_today = (target_date == get_ist_today())
        now_dt = get_ist_now()

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            cur.execute("""
                SELECT id, employee_id, employee_name, department, date, sign_in, sign_out,
                       location, in_geofence, nearest_building, distance_meters,
                       clock_in_lat, clock_in_lng,
                       clock_out_lat, clock_out_lng,
                       clock_out_in_geofence, clock_out_distance_meters,
                       created_at
                FROM data.attendance
                WHERE date = %s
                ORDER BY id DESC;
            """, (today_str,))
            punches = cur.fetchall()

            events = []
            employees = []
            seen_emps = set()

            total_phone_in = 0
            total_phone_out = 0
            total_outside_geofence = 0

            for p in punches:
                eid = str(p['employee_id']).strip()
                if eid in seen_emps:
                    continue
                seen_emps.add(eid)

                emp_name = p.get('employee_name') or f"Employee {eid}"
                dept = p.get('department') or 'Operations'

                has_phone_in = (p.get('clock_in_lat') is not None and p.get('clock_in_lng') is not None)
                has_phone_out = (p.get('clock_out_lat') is not None and p.get('clock_out_lng') is not None)

                phone_in_obj = None
                phone_out_obj = None

                # ── Phone Check-In ──
                if has_phone_in:
                    total_phone_in += 1
                    in_lat = float(p['clock_in_lat'])
                    in_lng = float(p['clock_in_lng'])
                    in_geo = check_geofence(in_lat, in_lng)
                    if not in_geo['in_geofence']:
                        total_outside_geofence += 1

                    in_time_str = str(p['sign_in'])[:8] if p.get('sign_in') else 'Today'
                    is_in_live = False
                    if is_today and p.get('sign_in') and isinstance(p['sign_in'], datetime.time):
                        try:
                            p_dt = datetime.datetime.combine(target_date, p['sign_in'], tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
                            if abs((now_dt - p_dt).total_seconds()) < 1800:
                                is_in_live = True
                        except Exception:
                            pass

                    phone_in_obj = {
                        'event_id': f"{eid}_in",
                        'attendance_id': p['id'],
                        'employee_id': eid,
                        'employee_name': emp_name,
                        'department': dept,
                        'punch_type': 'phone_checkin',
                        'punch_label': 'Phone Check-In',
                        'latitude': in_lat,
                        'longitude': in_lng,
                        'punch_time': in_time_str,
                        'is_live': is_in_live,
                        'in_geofence': in_geo['in_geofence'],
                        'nearest_building': in_geo['nearest_building'],
                        'distance_meters': in_geo['distance_meters'],
                        'location_note': f"{in_geo['distance_meters']}m from {in_geo['nearest_building']}",
                        'source': 'Mobile Phone (GPS)'
                    }
                    events.append(phone_in_obj)

                # ── Phone Check-Out ──
                if has_phone_out:
                    total_phone_out += 1
                    out_lat = float(p['clock_out_lat'])
                    out_lng = float(p['clock_out_lng'])
                    out_geo = check_geofence(out_lat, out_lng)
                    if not out_geo['in_geofence']:
                        total_outside_geofence += 1

                    if p.get('sign_out'):
                        out_time_str = str(p['sign_out'])[:8]
                    elif p.get('created_at') and hasattr(p['created_at'], 'time'):
                        out_time_str = str(p['created_at'].time())[:8]
                    else:
                        out_time_str = 'Today'

                    is_out_live = False
                    if is_today and p.get('sign_out') and isinstance(p['sign_out'], datetime.time):
                        try:
                            p_dt = datetime.datetime.combine(target_date, p['sign_out'], tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
                            if abs((now_dt - p_dt).total_seconds()) < 1800:
                                is_out_live = True
                        except Exception:
                            pass

                    phone_out_obj = {
                        'event_id': f"{eid}_out",
                        'attendance_id': p['id'],
                        'employee_id': eid,
                        'employee_name': emp_name,
                        'department': dept,
                        'punch_type': 'phone_checkout',
                        'punch_label': 'Phone Check-Out',
                        'latitude': out_lat,
                        'longitude': out_lng,
                        'punch_time': out_time_str,
                        'is_live': is_out_live,
                        'in_geofence': out_geo['in_geofence'],
                        'nearest_building': out_geo['nearest_building'],
                        'distance_meters': out_geo['distance_meters'],
                        'location_note': f"{out_geo['distance_meters']}m from {out_geo['nearest_building']}",
                        'source': 'Mobile Phone (GPS)'
                    }
                    events.append(phone_out_obj)

                # ── Biometric Punch (if neither check-in nor check-out is phone GPS) ──
                if not has_phone_in and not has_phone_out:
                    bio_time_str = str(p['sign_in'])[:8] if p.get('sign_in') else (str(p['sign_out'])[:8] if p.get('sign_out') else 'Today')
                    events.append({
                        'event_id': f"{eid}_bio",
                        'attendance_id': p['id'],
                        'employee_id': eid,
                        'employee_name': emp_name,
                        'department': dept,
                        'punch_type': 'biometric',
                        'punch_label': 'Biometric Machine',
                        'latitude': COMPANY_BUILDINGS[0]['lat'],
                        'longitude': COMPANY_BUILDINGS[0]['lng'],
                        'punch_time': bio_time_str,
                        'is_live': False,
                        'in_geofence': True,
                        'nearest_building': 'Monarch House (HQ)',
                        'distance_meters': 0.0,
                        'location_note': p.get('location') or 'Biometric Machine Punch',
                        'source': p.get('location') or 'Biometric Machine'
                    })

                employees.append({
                    'employee_id': eid,
                    'employee_name': emp_name,
                    'department': dept,
                    'has_phone_in': has_phone_in,
                    'has_phone_out': has_phone_out,
                    'has_any_phone': has_phone_in or has_phone_out,
                    'phone_in': phone_in_obj,
                    'phone_out': phone_out_obj,
                    'raw_location': p.get('location'),
                    'sign_in': str(p['sign_in'])[:8] if p.get('sign_in') else None,
                    'sign_out': str(p['sign_out'])[:8] if p.get('sign_out') else None,
                })

            return jsonify({
                'events': events,
                'employees': employees,
                'total_tracked': len(employees),
                'total_phone_punches': len([e for e in employees if e['has_any_phone']]),
                'total_phone_checkins': total_phone_in,
                'total_phone_checkouts': total_phone_out,
                'total_outside_geofence': total_outside_geofence,
                'company_buildings': COMPANY_BUILDINGS,
                'geofence_radius_meters': GEOFENCE_RADIUS_METERS,
                'geofence_square': COMPANY_GEOFENCE_SQUARE,
                'date': today_str
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/gps/employee-trail', methods=['GET'])
    @token_required
    @admin_required
    def get_employee_gps_trail():
        """Returns coordinates trail for an employee on a given date."""
        emp_id = request.args.get('employee_id')
        att_date = request.args.get('date', get_ist_today().isoformat())

        if not emp_id:
            return jsonify({'error': 'Employee ID required'}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            cur.execute("""
                SELECT latitude, longitude, recorded_at, speed, nearest_building, distance_meters, in_geofence
                FROM data.employee_location_trail
                WHERE employee_id = %s AND recorded_at::date = %s::date
                ORDER BY recorded_at ASC;
            """, (emp_id, att_date))
            rows = cur.fetchall()

            trail = []
            for r in rows:
                trail.append({
                    'latitude': float(r['latitude']),
                    'longitude': float(r['longitude']),
                    'recorded_at': r['recorded_at'].isoformat() if hasattr(r['recorded_at'], 'isoformat') else str(r['recorded_at']),
                    'nearest_building': r.get('nearest_building'),
                    'in_geofence': bool(r.get('in_geofence'))
                })

            return jsonify({'employee_id': emp_id, 'date': att_date, 'trail': trail})

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 7. Centralized Requests & Approvals ────────────────────────────────────
    @app.route('/api/admin/all-requests', methods=['GET'])
    @token_required
    @admin_required
    def get_all_pending_requests():
        """Consolidated inbox of all pending leaves and punch corrections."""
        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            # Pending leaves
            cur.execute("""
                SELECT id, employee_id, employee_name, department, title, leave_type,
                       start_date, end_date, days_count, status, applied_at, note, 'leave' AS request_type
                FROM data.leaves
                WHERE status ILIKE '%%pending%%'
                ORDER BY applied_at DESC;
            """)
            leaves = cur.fetchall()

            # Pending attendance corrections
            cur.execute("""
                SELECT id, employee_id, employee_name, attendance_date, requested_sign_in, requested_sign_out,
                       reason, status, requested_at, 'attendance_correction' AS request_type
                FROM data.attendance_corrections
                WHERE status ILIKE '%%pending%%'
                ORDER BY requested_at DESC;
            """)
            corrections = cur.fetchall()

            users_map = load_monarch_users_map()
            items = []
            for l in leaves:
                target_emp_id = str(l['employee_id'] or '').strip()
                uinfo = users_map.get(target_emp_id) or users_map.get(target_emp_id.lstrip('0'))
                if not uinfo and l.get('employee_name'):
                    raw_name = str(l['employee_name']).strip()
                    uinfo = users_map.get(raw_name.lower()) or users_map.get(f"norm_{normalize_person_name(raw_name)}")
                uinfo = uinfo or {}
                manager_name = (uinfo.get('reporting_manager') or '').strip() or 'Department Manager / Head'

                items.append({
                    'id': l['id'],
                    'type': 'leave',
                    'employee_id': l['employee_id'],
                    'employee_name': l.get('employee_name') or f"Employee {l['employee_id']}",
                    'department': l.get('department') or uinfo.get('department') or 'General',
                    'designation': uinfo.get('designation') or 'Employee',
                    'reporting_manager': manager_name,
                    'title': f"{l.get('leave_type', 'Leave')}: {l['title']}",
                    'details': f"{l['start_date']} to {l['end_date']} ({l.get('days_count')} days)",
                    'reason': l.get('note') or 'Personal reasons',
                    'applied_at': l['applied_at'].isoformat() if hasattr(l['applied_at'], 'isoformat') else str(l['applied_at'])
                })

            for c in corrections:
                target_emp_id = str(c['employee_id'] or '').strip()
                uinfo = users_map.get(target_emp_id) or users_map.get(target_emp_id.lstrip('0'))
                if not uinfo and c.get('employee_name'):
                    raw_name = str(c['employee_name']).strip()
                    uinfo = users_map.get(raw_name.lower()) or users_map.get(f"norm_{normalize_person_name(raw_name)}")
                uinfo = uinfo or {}
                manager_name = (uinfo.get('reporting_manager') or '').strip() or 'Operations Lead'

                items.append({
                    'id': c['id'],
                    'type': 'correction',
                    'employee_id': c['employee_id'],
                    'employee_name': c.get('employee_name') or f"Employee {c['employee_id']}",
                    'department': uinfo.get('department') or 'Operations',
                    'designation': uinfo.get('designation') or 'Employee',
                    'reporting_manager': manager_name,
                    'title': f"Punch Regularization for {c['attendance_date']}",
                    'details': f"In: {str(c['requested_sign_in'])[:8] or '--'} | Out: {str(c['requested_sign_out'])[:8] or '--'}",
                    'reason': c['reason'],
                    'applied_at': c['requested_at'].isoformat() if hasattr(c['requested_at'], 'isoformat') else str(c['requested_at'])
                })

            return jsonify({'requests': items, 'total_pending': len(items)})

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    @app.route('/api/admin/corrections/<int:correction_id>/review', methods=['POST'])
    @token_required
    @admin_required
    def review_correction_request(correction_id):
        data = request.get_json() or {}
        action = (data.get('action') or '').strip().lower()
        comments = data.get('comments', '')

        if action not in ['approve', 'reject']:
            return jsonify({'error': "Action must be 'approve' or 'reject'"}), 400

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            cur.execute("SELECT * FROM data.attendance_corrections WHERE id = %s;", (correction_id,))
            corr = cur.fetchone()
            if not corr:
                return jsonify({'error': 'Correction request not found'}), 404

            new_status = 'Approved' if action == 'approve' else 'Rejected'

            cur.execute("""
                UPDATE data.attendance_corrections
                SET status = %s,
                    reviewed_by = %s,
                    reviewed_at = NOW(),
                    reviewer_comments = %s
                WHERE id = %s;
            """, (new_status, request.user.get('name'), comments, correction_id))

            # Apply change to attendance if approved
            if action == 'approve':
                cur.execute("""
                    UPDATE data.attendance
                    SET sign_in = COALESCE(%s, sign_in),
                        sign_out = COALESCE(%s, sign_out),
                        approval_status = 'Approved',
                        reviewed_by = %s,
                        reviewed_at = NOW()
                    WHERE (employee_id = %s OR employee_id = %s) AND date = %s;
                """, (
                    corr['requested_sign_in'], corr['requested_sign_out'],
                    request.user.get('name'), corr['employee_id'], corr['employee_id'].lstrip('0'),
                    corr['attendance_date']
                ))

            conn.commit()

            log_audit_event(
                get_monarch_connection,
                actor_id=request.user.get('emp_id'),
                actor_name=request.user.get('name'),
                action=f'CORRECTION_{new_status.upper()}',
                target_type='attendance_correction',
                target_id=str(correction_id),
                reason=comments or f"Punch correction {new_status.lower()}"
            )

            return jsonify({'success': True, 'status': new_status})

        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 8. Immutable Audit Logs Module ─────────────────────────────────────────
    @app.route('/api/admin/audit-logs', methods=['GET'])
    @token_required
    @admin_required
    def get_audit_logs():
        caller_eid = str(request.user.get('employee_no') or request.user.get('emp_id') or request.user.get('id') or '').strip()
        if caller_eid in ['1844', '965']:
            return jsonify({'error': 'Access denied: Audit Logs Trail is restricted for this account'}), 403

        action = request.args.get('action')
        actor = request.args.get('actor')
        limit = max(1, min(200, int(request.args.get('limit', 100))))

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            conditions = ["1=1"]
            params = []

            if action:
                conditions.append("action ILIKE %s")
                params.append(f"%{action}%")

            if actor:
                conditions.append("(actor_id LIKE %s OR LOWER(actor_name) LIKE %s)")
                params.extend([f"%{actor}%", f"%{actor.lower()}%"])

            where_clause = " AND ".join(conditions)

            cur.execute(f"""
                SELECT id, actor_id, actor_name, action, target_type, target_id,
                       reason, before_value, after_value, ip_address, timestamp
                FROM data.audit_logs
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT %s;
            """, tuple(params + [limit]))
            rows = cur.fetchall()

            logs = []
            for r in rows:
                logs.append({
                    'id': r['id'],
                    'actor_id': r['actor_id'],
                    'actor_name': r['actor_name'],
                    'action': r['action'],
                    'target_type': r['target_type'],
                    'target_id': r['target_id'],
                    'reason': r.get('reason') or '',
                    'before_value': r.get('before_value'),
                    'after_value': r.get('after_value'),
                    'ip_address': r.get('ip_address') or '127.0.0.1',
                    'timestamp': r['timestamp'].isoformat() if hasattr(r['timestamp'], 'isoformat') else str(r['timestamp'])
                })

            return jsonify(logs)

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 9. Reports & CSV Exports Module ────────────────────────────────────────
    @app.route('/api/admin/reports/export', methods=['GET'])
    @token_required
    @admin_required
    def export_admin_report():
        report_type = request.args.get('type', 'daily_attendance').lower()
        today_str = get_ist_today().isoformat()
        start_date = request.args.get('start_date', today_str)
        end_date = request.args.get('end_date', today_str)
        dept = request.args.get('department')

        conn = None
        try:
            conn = get_monarch_connection()
            cur = conn.cursor()

            output = io.StringIO()
            writer = csv.writer(output)

            filename = f"{report_type}_{start_date}.csv"

            if report_type == 'daily_attendance':
                writer.writerow([
                    'Attendance Date', 'Employee ID', 'Full Name', 'Department',
                    'Designation', 'Sign In', 'Sign Out', 'Work Hours', 'Late (Mins)',
                    'Early Exit (Mins)', 'Overtime (Hrs)', 'Status', 'Location',
                    'Geofence Status', 'Approval Status'
                ])
                cur.execute("""
                    SELECT a.date, a.employee_id, a.employee_name, a.department, a.role,
                           a.sign_in, a.sign_out, a.location, a.in_geofence, a.approval_status
                    FROM data.attendance a
                    WHERE a.date = %s
                    ORDER BY a.employee_name ASC;
                """, (start_date,))
                for r in cur.fetchall():
                    m = calculate_attendance_metrics(r['sign_in'], r['sign_out'])
                    writer.writerow([
                        str(r['date']), r['employee_id'], r.get('employee_name'),
                        r.get('department'), r.get('role'),
                        str(r['sign_in'])[:8] if r.get('sign_in') else '',
                        str(r['sign_out'])[:8] if r.get('sign_out') else '',
                        m['work_hours'], m['late_mins'], m['early_mins'],
                        m['overtime_hrs'], m['status'], r.get('location') or 'Monarch HQ',
                        'Within Geofence' if r.get('in_geofence', True) else 'Out of Range',
                        r.get('approval_status') or 'Approved'
                    ])

            elif report_type == 'monthly_attendance':
                filename = f"monthly_summary_{start_date}_to_{end_date}.csv"
                writer.writerow([
                    'Employee ID', 'Full Name', 'Department', 'Total Days Present',
                    'Total Days Late', 'Total Work Hours', 'Total Overtime Hours'
                ])
                cur.execute("""
                    SELECT a.employee_id, a.employee_name, a.department,
                           COUNT(DISTINCT a.date) AS days_present,
                           COUNT(CASE WHEN a.sign_in > '09:45:00' THEN 1 END) AS days_late
                    FROM data.attendance a
                    WHERE a.date BETWEEN %s AND %s AND a.sign_in IS NOT NULL
                    GROUP BY a.employee_id, a.employee_name, a.department
                    ORDER BY a.employee_name ASC;
                """, (start_date, end_date))
                for r in cur.fetchall():
                    writer.writerow([
                        r['employee_id'], r.get('employee_name'), r.get('department'),
                        r['days_present'], r['days_late'],
                        round(r['days_present'] * 8.5, 1), 0.0
                    ])

            elif report_type in ['monthly_cycle_vertical', 'monthly_vertical']:
                filename = f"monthly_vertical_attendance_{start_date}_to_{end_date}.csv"
                writer.writerow([
                    'Emp No', 'Employee Name', 'Department', 'Designation',
                    'Attendance Date', 'Day of Week', 'Clock In', 'Clock Out',
                    'Work Hours', 'Late (Mins)', 'Early (Mins)', 'Overtime (Hrs)',
                    'Attendance Status', 'Geofence Status', 'Location', 'Approval Status'
                ])
                conditions = ["a.date BETWEEN %s AND %s"]
                params = [start_date, end_date]
                if dept:
                    conditions.append("a.department = %s")
                    params.append(dept)
                cur.execute(f"""
                    SELECT a.date, a.employee_id, a.employee_name, a.department, a.role,
                           a.sign_in, a.sign_out, a.location, a.in_geofence, a.approval_status
                    FROM data.attendance a
                    WHERE {" AND ".join(conditions)}
                    ORDER BY a.date DESC, a.employee_id ASC;
                """, tuple(params))
                for r in cur.fetchall():
                    m = calculate_attendance_metrics(r['sign_in'], r['sign_out'])
                    d_obj = r['date']
                    day_name = d_obj.strftime('%a') if hasattr(d_obj, 'strftime') else ''
                    writer.writerow([
                        r['employee_id'],
                        r.get('employee_name') or '',
                        r.get('department') or '',
                        r.get('role') or '',
                        str(r['date']),
                        day_name,
                        str(r['sign_in'])[:8] if r.get('sign_in') else '',
                        str(r['sign_out'])[:8] if r.get('sign_out') else '',
                        m['work_hours'],
                        m['late_mins'],
                        m['early_mins'],
                        m['overtime_hrs'],
                        m['status'],
                        'Within Geofence' if r.get('in_geofence', True) else 'Out of Range',
                        r.get('location') or 'Monarch House HQ',
                        r.get('approval_status') or 'Approved'
                    ])

            elif report_type in ['attendance_muster', 'monthly_muster', 'muster']:
                kpi_filter = (request.args.get('filter') or 'all').strip().lower()
                filter_suffix = f"_{kpi_filter}" if kpi_filter != 'all' else ""
                filename = f"Attendance_Muster{filter_suffix}_{start_date}_to_{end_date}.csv"
                start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
                end_dt = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
                cycle_dates = []
                curr = start_dt
                while curr <= end_dt:
                    sat_idx = ((curr.day - 1) // 7) + 1
                    is_even_sat = (curr.weekday() == 5 and sat_idx % 2 == 0)
                    is_odd_sat = (curr.weekday() == 5 and sat_idx % 2 != 0)
                    is_sun = (curr.weekday() == 6)
                    is_weekend = is_sun or is_even_sat
                    cycle_dates.append({
                        'date': curr.isoformat(),
                        'day': curr.day,
                        'day_name': curr.strftime('%a'),
                        'is_weekend': is_weekend,
                        'is_sunday': is_sun,
                        'is_even_saturday': is_even_sat,
                        'is_odd_saturday': is_odd_sat,
                        'sat_index': sat_idx if curr.weekday() == 5 else None
                    })
                    curr += datetime.timedelta(days=1)

                holiday_dates = {h[1] for h in DEFAULT_HOLIDAYS_2026}
                today = get_ist_today()

                writer.writerow(
                    ['Employee Number', 'Employee Name', 'Month', 'Year'] +
                    [str(d['day']) for d in cycle_dates]
                )

                u_conds = ["u.employee_no IS NOT NULL"]
                u_params = []
                if kpi_filter in ['punches', 'total_punches']:
                    u_conds.append("""
                        u.employee_no::text IN (
                            SELECT DISTINCT employee_id FROM data.attendance
                            WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL
                            UNION
                            SELECT DISTINCT LTRIM(employee_id, '0') FROM data.attendance
                            WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL
                        )
                    """)
                    u_params.extend([start_dt, end_dt, start_dt, end_dt])
                elif kpi_filter in ['late', 'late_arrivals']:
                    u_conds.append("""
                        u.employee_no::text IN (
                            SELECT DISTINCT employee_id FROM data.attendance
                            WHERE date BETWEEN %s AND %s AND sign_in > '09:45:00'
                            UNION
                            SELECT DISTINCT LTRIM(employee_id, '0') FROM data.attendance
                            WHERE date BETWEEN %s AND %s AND sign_in > '09:45:00'
                        )
                    """)
                    u_params.extend([start_dt, end_dt, start_dt, end_dt])
                elif kpi_filter in ['out_of_range', 'geofence', 'out_of_geofence']:
                    u_conds.append("""
                        u.employee_no::text IN (
                            SELECT DISTINCT employee_id FROM data.attendance
                            WHERE date BETWEEN %s AND %s AND in_geofence = FALSE
                            UNION
                            SELECT DISTINCT LTRIM(employee_id, '0') FROM data.attendance
                            WHERE date BETWEEN %s AND %s AND in_geofence = FALSE
                        )
                    """)
                    u_params.extend([start_dt, end_dt, start_dt, end_dt])

                u_where = " AND ".join(u_conds)
                cur.execute(f"SELECT u.employee_no, u.name, u.weekly_off, u.date_of_joining FROM data.users u WHERE {u_where} ORDER BY u.employee_no ASC;", tuple(u_params))
                all_users = cur.fetchall()
                all_emp_ids = [str(u['employee_no']) for u in all_users]

                att_map = {}
                if all_emp_ids:
                    cur.execute("""
                        SELECT a.employee_id, a.date, a.sign_in, a.sign_out 
                        FROM data.attendance a 
                        WHERE a.date BETWEEN %s AND %s AND a.employee_id = ANY(%s);
                    """, (start_dt, end_dt, all_emp_ids))
                    for r in cur.fetchall():
                        att_map[(str(r['employee_id']), str(r['date']))] = r

                leaves_map = {}
                if all_emp_ids:
                    emp_id_variants = list(set(all_emp_ids + [e.lstrip('0') for e in all_emp_ids if e]))
                    cur.execute("""
                        SELECT id, employee_id, leave_type, title, start_date, end_date, days_count, status, note
                        FROM data.leaves
                        WHERE employee_id = ANY(%s)
                          AND start_date <= %s AND end_date >= %s
                          AND status NOT ILIKE '%%reject%%'
                        ORDER BY CASE WHEN status ILIKE '%%approved%%' THEN 1 WHEN status ILIKE '%%pending%%' THEN 2 ELSE 3 END, id DESC;
                    """, (emp_id_variants, end_dt, start_dt))
                    for lr in cur.fetchall():
                        l_eid = str(lr['employee_id']).strip()
                        l_start = lr['start_date']
                        l_end = lr['end_date']
                        c_dt = max(l_start, start_dt)
                        c_max = min(l_end, end_dt)
                        while c_dt <= c_max:
                            c_str = c_dt.isoformat()
                            k1 = (l_eid, c_str)
                            k2 = (l_eid.lstrip('0'), c_str)
                            if k1 not in leaves_map:
                                leaves_map[k1] = lr
                            if k2 not in leaves_map:
                                leaves_map[k2] = lr
                            c_dt += datetime.timedelta(days=1)

                for u in all_users:
                    eid = str(u['employee_no'])
                    emp_name = u['name'] or f"Employee {eid}"
                    weekly_off = (u.get('weekly_off') or 'Sunday').lower()
                    doj = u.get('date_of_joining')
                    if isinstance(doj, str):
                        try:
                            doj = datetime.date.fromisoformat(doj.split('T')[0])
                        except Exception:
                            doj = None
                    elif isinstance(doj, datetime.datetime):
                        doj = doj.date()

                    row_vals = [f"E{eid.zfill(4)}" if not str(eid).startswith('E') else eid, emp_name, start_dt.month, start_dt.year]
                    p_c, a_c, wo_c, hd_c, h_c, l_c = 0, 0, 0, 0, 0, 0
                    for d in cycle_dates:
                        d_str = d['date']
                        d_obj = datetime.datetime.strptime(d_str, '%Y-%m-%d').date()

                        # Pre-joining check: dates before joining date should be blank (--)
                        if doj and d_obj < doj:
                            row_vals.append('--')
                            continue

                        punch = att_map.get((eid, d_str)) or att_map.get((eid.lstrip('0'), d_str))
                        leave = leaves_map.get((eid, d_str)) or leaves_map.get((eid.lstrip('0'), d_str))
                        is_off = (weekly_off in d['day_name'].lower()) or (d['is_sunday'] and weekly_off in ['sunday', 'sun']) or d['is_even_saturday']
                        is_holiday = (d_str in holiday_dates)
                        leave_status = str(leave.get('status') or '').strip().lower() if leave else ''
                        is_leave_pending = bool(leave and ('pending' in leave_status))
                        is_leave_approved = bool(leave and ('approved' in leave_status))

                        # Check regularization
                        is_regularized = False
                        if leave:
                            l_full = f"{leave.get('leave_type') or ''} {leave.get('title') or ''} {leave.get('note') or ''}".lower()
                            if 'regulariz' in l_full and 'reject' not in leave_status:
                                is_regularized = True
                        if punch:
                            p_loc = str(punch.get('location') or '').lower()
                            p_appr = str(punch.get('approval_status') or '').lower()
                            if ('regulariz' in p_loc or 'regulariz' in p_appr) and 'reject' not in p_appr:
                                is_regularized = True

                        has_in = bool(punch and punch.get('sign_in'))
                        has_out = bool(punch and punch.get('sign_out'))
                        is_missed_punch = bool(punch and (d_obj < today) and ((has_in and not has_out) or (not has_in and has_out)))

                        if punch:
                            m = calculate_attendance_metrics(punch.get('sign_in'), punch.get('sign_out'), date=d_obj, is_regularized=is_regularized)
                            if is_missed_punch:
                                if is_regularized:
                                    code = 'P'
                                    p_c += 1
                                elif is_leave_approved and (leave.get('is_half_day') or float(leave.get('days_count') or 1.0) == 0.5 or 'half' in str(leave.get('leave_type') or '').lower()):
                                    hd_code, _ = determine_half_day_code(punch, leave)
                                    code = hd_code
                                    hd_c += 1
                                    l_c += 1
                                elif is_leave_approved:
                                    code = 'P'
                                    p_c += 1
                                    l_c += 1
                                else:
                                    code = 'A'
                                    a_c += 1
                            elif 'Half Day' in m['status'] or (3.0 <= m['work_hours'] < 8.83):
                                if is_leave_approved:
                                    code = 'P'
                                    p_c += 1
                                    l_c += 1
                                else:
                                    hd_code, _ = determine_half_day_code(punch, leave)
                                    code = hd_code
                                    hd_c += 1
                            else:
                                code = 'P'
                                p_c += 1
                                if is_leave_approved:
                                    l_c += 1
                        elif is_holiday:
                            code = 'H'
                            h_c += 1
                        elif is_off:
                            code = 'WO'
                            wo_c += 1
                        elif is_leave_pending:
                            if is_regularized:
                                code = 'P'
                                p_c += 1
                            else:
                                code = 'A'
                                a_c += 1
                        elif is_leave_approved:
                            try:
                                d_cnt = float(leave.get('days_count') or 1.0)
                            except (ValueError, TypeError):
                                d_cnt = 1.0
                            is_half = bool(leave.get('is_half_day') or d_cnt == 0.5)
                            if is_half:
                                hd_code, _ = determine_half_day_code(punch, leave)
                                code = hd_code
                                hd_c += 1
                            else:
                                code = 'P'
                                p_c += 1
                            l_c += 1
                        elif d_obj > today:
                            code = '--'
                        else:
                            code = 'A'
                            a_c += 1
                        row_vals.append(code)

                    writer.writerow(row_vals)

            elif report_type == 'leave_balances':
                filename = f"leave_balances_master.csv"
                writer.writerow([
                    'Employee ID', 'Full Name', 'Department', 'Designation',
                    'Total Allotted Days', 'Used Days', 'Remaining Balance'
                ])
                cur.execute("""
                    SELECT u.employee_no, u.name, u.department, u.designation,
                           COALESCE(lb.total_allotted, 6.0) AS total,
                           COALESCE(lb.used_days, 0.0) AS used,
                           COALESCE(lb.remaining_days, 6.0) AS remaining
                    FROM data.users u
                    LEFT JOIN data.leave_balances lb ON CAST(u.employee_no AS TEXT) = lb.employee_id
                    WHERE u.is_active IS NOT FALSE
                    ORDER BY u.employee_no ASC;
                """)
                for r in cur.fetchall():
                    writer.writerow([
                        r['employee_no'], r['name'], r.get('department'),
                        r.get('designation'), float(r['total']), float(r['used']), float(r['remaining'])
                    ])

            elif report_type == 'employee_master':
                filename = f"employee_directory_master.csv"
                writer.writerow([
                    'Employee ID', 'Name', 'Official Email', 'Mobile Number',
                    'Department', 'Designation', 'Reporting Manager', 'Office Location',
                    'Joining Date', 'Shift Timing', 'Weekly Off', 'Account Status'
                ])
                cur.execute("""
                    SELECT employee_no, name, personal_email, mobile_number, department,
                           designation, reporting_manager, location, date_of_joining,
                           shift_timing, weekly_off, employment_status, is_active
                    FROM data.users
                    ORDER BY employee_no ASC;
                """)
                for r in cur.fetchall():
                    status_text = 'Active' if r.get('is_active', True) else 'Inactive'
                    writer.writerow([
                        r['employee_no'], r['name'], r.get('personal_email'),
                        r.get('mobile_number'), r.get('department'), r.get('designation'),
                        r.get('reporting_manager'), r.get('location'), str(r.get('date_of_joining') or ''),
                        r.get('shift_timing'), r.get('weekly_off') or 'Sunday', status_text
                    ])

            else:  # punch_anomalies
                filename = f"attendance_anomalies_{start_date}.csv"
                writer.writerow([
                    'Date', 'Employee ID', 'Full Name', 'Department', 'Clock In', 'Clock Out', 'Issue Flagged'
                ])
                cur.execute("""
                    SELECT date, employee_id, employee_name, department, sign_in, sign_out
                    FROM data.attendance
                    WHERE date BETWEEN %s AND %s AND sign_in IS NOT NULL AND sign_out IS NULL;
                """, (start_date, end_date))
                for r in cur.fetchall():
                    writer.writerow([
                        str(r['date']), r['employee_id'], r.get('employee_name'),
                        r.get('department'), str(r['sign_in'])[:8] if r.get('sign_in') else '',
                        '', 'Missing Clock-Out Punch'
                    ])

            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment;filename={filename}"}
            )

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                cur.close()
                conn.close()

    # ─── 10. Single-Page Admin Dashboard Web UI ─────────────────────────────────
    @app.route('/admin', methods=['GET'])
    @app.route('/admin/', methods=['GET'])
    @app.route('/admin/<path:subpath>', methods=['GET'])
    @app.route('/', methods=['GET'])
    def serve_admin_dashboard_ui(subpath=None):
        """Renders the comprehensive Enterprise Admin & HR Web Dashboard."""
        return render_template_string(ADMIN_DASHBOARD_HTML)


# ─── Single-Page Application (HTML5 + Tailwind CSS + Lucide + Chart.js + Leaflet) ──
ADMIN_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" class="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Monarch HR • Admin & HR Management Dashboard</title>

  <!-- Google Fonts: Plus Jakarta Sans -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">

  <!-- Lucide Icons -->
  <script src="https://unpkg.com/lucide@latest"></script>

  <!-- Chart.js -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

  <!-- Leaflet CSS & JS for GPS Map -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

  <style>
    :root {
      --primary: #F5A952;
      --primary-hover: #E79A46;
      --primary-dark: #895100;
      --primary-subtle: #FFF4E5;
      
      --navy: #0F172A;
      --navy-card: #1E293B;
      --navy-border: #334155;
      
      --bg: #F8FAFC;
      --card: #FFFFFF;
      --border: #E2E8F0;
      --border-subtle: #F1F5F9;
      
      --text-main: #0F172A;
      --text-muted: #64748B;
      --text-dim: #94A3B8;
      
      --green: #10B981;
      --green-bg: #ECFDF5;
      --red: #EF4444;
      --red-bg: #FEF2F2;
      --blue: #3B82F6;
      --blue-bg: #EFF6FF;
      --amber: #F59E0B;
      --amber-bg: #FFFBEB;
      --purple: #8B5CF6;
      --purple-bg: #F5F3FF;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      display: flex;
      min-height: 100vh;
      overflow-x: hidden;
    }

    /* Layout Containers */
    #sidebar {
      width: 270px;
      background: #0B1120;
      color: #94A3B8;
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
      transition: all 0.25s ease;
      z-index: 40;
      border-right: 1px solid #1E293B;
    }
    #main-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
      overflow-y: auto;
      height: 100vh;
    }

    /* Sidebar Items */
    .nav-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 11px 16px;
      margin: 3px 12px;
      border-radius: 8px;
      font-size: 13.5px;
      font-weight: 500;
      color: #94A3B8;
      cursor: pointer;
      transition: all 0.15s ease;
      text-decoration: none;
    }
    .nav-item:hover {
      background: rgba(255, 255, 255, 0.06);
      color: #FFFFFF;
    }
    .nav-item.active {
      background: var(--primary);
      color: #0F172A;
      font-weight: 700;
    }
    .nav-badge {
      margin-left: auto;
      font-size: 11px;
      padding: 2px 7px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.12);
      color: #CBD5E1;
      font-weight: 700;
    }
    .nav-item.active .nav-badge {
      background: rgba(0, 0, 0, 0.18);
      color: #0F172A;
    }

    /* Top Bar */
    header {
      height: 68px;
      background: #FFFFFF;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 28px;
      position: sticky;
      top: 0;
      z-index: 30;
    }

    /* Cards & Components */
    .kpi-card {
      background: #FFFFFF;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.02);
      position: relative;
      overflow: hidden;
      transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .kpi-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    .kpi-icon-wrap {
      width: 44px;
      height: 44px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 14px;
    }

    /* Tables */
    .data-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 13.5px;
    }
    .data-table th {
      background: #F8FAFC;
      color: #64748B;
      font-weight: 600;
      text-align: left;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.5px;
    }
    .data-table td {
      padding: 14px 16px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text-main);
      vertical-align: middle;
    }
    .data-table tr:hover td {
      background: #F8FAFC;
    }

    /* Muster Roll Matrix Table Styles */
    .muster-container {
      overflow-x: auto;
      max-width: 100%;
      position: relative;
    }
    .muster-table {
      width: max-content;
      min-width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 12px;
    }
    .muster-table th, .muster-table td {
      padding: 7px 5px;
      text-align: center;
      border-bottom: 1px solid var(--border);
      border-right: 1px solid #F1F5F9;
      white-space: nowrap;
    }
    .muster-table th {
      background: #F8FAFC;
      color: #475569;
      font-weight: 700;
      font-size: 11px;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .muster-table th.sticky-col, .muster-table td.sticky-col {
      position: sticky;
      left: 0;
      background: #FFFFFF;
      z-index: 11;
      text-align: left;
      padding-left: 14px;
      padding-right: 10px;
      min-width: 90px;
      border-right: 1px solid #E2E8F0;
    }
    .muster-table th.sticky-col-2, .muster-table td.sticky-col-2 {
      position: sticky;
      left: 90px;
      background: #FFFFFF;
      z-index: 11;
      text-align: left;
      padding-left: 10px;
      padding-right: 14px;
      min-width: 180px;
      border-right: 2px solid #CBD5E1;
      box-shadow: 2px 0 4px rgba(0,0,0,0.03);
    }
    .muster-table th.sticky-col, .muster-table th.sticky-col-2 {
      background: #F8FAFC;
      z-index: 20;
    }
    .muster-table tr:hover td {
      background: #F8FAFC;
    }
    .muster-table tr:hover td.sticky-col, .muster-table tr:hover td.sticky-col-2 {
      background: #F1F5F9;
    }
    .muster-weekend-col {
      background: rgba(241, 245, 249, 0.7);
    }
    .muster-chip {
      display: inline-block;
      min-width: 26px;
      padding: 3px 5px;
      border-radius: 4px;
      font-weight: 700;
      font-size: 10.5px;
      text-align: center;
      line-height: 1;
      cursor: default;
      transition: transform 0.1s;
    }
    .muster-chip:hover {
      transform: scale(1.15);
      z-index: 5;
    }
    .chip-P { background: rgba(16, 185, 129, 0.16); color: #047857; border: 1px solid rgba(16, 185, 129, 0.35); }
    .chip-A { background: rgba(239, 68, 68, 0.12); color: #DC2626; border: 1px solid rgba(239, 68, 68, 0.25); }
    .chip-WO { background: #F1F5F9; color: #64748B; border: 1px solid #E2E8F0; }
    .chip-HD, .chip-AP, .chip-PA, .chip-A-P, .chip-P-A, .chip-A\\:P, .chip-P\\:A { background: rgba(245, 158, 11, 0.16); color: #B45309; border: 1px solid rgba(245, 158, 11, 0.35); }
    .chip-H { background: rgba(139, 92, 246, 0.15); color: #6D28D9; border: 1px solid rgba(139, 92, 246, 0.35); }
    .chip-L, .chip-EL, .chip-CL, .chip-SL, .chip-CO, .chip-COMP, .chip-LWP, .chip-LOP, .chip-ML, .chip-PL, .chip-REG {
      background: rgba(59, 130, 246, 0.15);
      color: #1D4ED8;
      border: 1px solid rgba(59, 130, 246, 0.35);
    }
    .chip-NONE, .chip--- { color: #94A3B8; font-weight: 500; background: transparent; }

    /* Status Pills */
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 11.5px;
      font-weight: 600;
    }
    .badge-green { background: var(--green-bg); color: #065F46; }
    .badge-amber { background: var(--amber-bg); color: #92400E; }
    .badge-red { background: var(--red-bg); color: #991B1B; }
    .badge-blue { background: var(--blue-bg); color: #1E40AF; }
    .badge-gray { background: #F1F5F9; color: #475569; }

    /* Buttons */
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 9px 16px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      transition: all 0.15s ease;
      text-decoration: none;
    }
    .btn-primary { background: var(--primary); color: #0F172A; }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-outline { background: #FFFFFF; border: 1px solid var(--border); color: #334155; }
    .btn-outline:hover { background: #F8FAFC; border-color: #CBD5E1; }
    .btn-danger { background: #EF4444; color: #FFFFFF; }
    .btn-danger:hover { background: #DC2626; }
    .btn-sm { padding: 6px 12px; font-size: 12px; }

    /* Modals */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.65);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 100;
      padding: 20px;
    }
    .modal-backdrop.active { display: flex; }
    .modal-card {
      background: #FFFFFF;
      border-radius: 16px;
      width: 100%;
      max-width: 600px;
      max-height: 90vh;
      overflow-y: auto;
      box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1);
      border: 1px solid var(--border);
    }

    /* Forms */
    .form-group { margin-bottom: 16px; }
    .form-label { display: block; font-size: 12.5px; font-weight: 600; margin-bottom: 6px; color: #334155; }
    .form-control {
      width: 100%;
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid var(--border);
      font-size: 13.5px;
      font-family: inherit;
      background: #FFFFFF;
      outline: none;
      transition: border-color 0.15s;
    }
    .form-control:focus { border-color: var(--primary); }

    /* Toast Notification */
    #toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #0F172A;
      color: #FFFFFF;
      padding: 14px 20px;
      border-radius: 10px;
      font-size: 13.5px;
      font-weight: 500;
      box-shadow: 0 10px 15px -3px rgba(0,0,0,0.2);
      display: none;
      align-items: center;
      gap: 10px;
      z-index: 150;
    }
    #toast.show { display: flex; animation: slideUp 0.25s ease; }
    @keyframes slideUp {
      from { transform: translateY(20px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }

    #map { height: 620px; width: 100%; border-radius: 12px; }
    .gps-filter-btn {
      padding: 6px 13px;
      border-radius: 20px;
      font-size: 11.5px;
      font-weight: 600;
      cursor: pointer;
      border: 1px solid var(--border);
      background: #FFFFFF;
      color: #64748B;
      transition: all 0.15s ease;
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .gps-filter-btn:hover {
      background: #F1F5F9;
      color: #0F172A;
    }
    .gps-filter-btn.active {
      background: #0F172A;
      color: #FFFFFF;
      border-color: #0F172A;
      box-shadow: 0 2px 5px rgba(0,0,0,0.15);
    }
    .custom-gps-pin {
      background: transparent !important;
      border: none !important;
    }
    @keyframes pulseRing {
      0% { transform: scale(0.9); opacity: 0.8; }
      50% { transform: scale(1.35); opacity: 0.2; }
      100% { transform: scale(0.9); opacity: 0.8; }
    }
    .pulse-ring {
      animation: pulseRing 2s infinite ease-in-out;
    }

    /* ─── Dedicated Full-Screen Login Page ─── */
    #login-page {
      position: fixed;
      inset: 0;
      z-index: 99999;
      display: none;
      background: #0B1120;
      width: 100vw;
      height: 100vh;
      overflow-y: auto;
    }
    .login-hero-pane {
      flex: 1.15;
      background: linear-gradient(135deg, #090E17 0%, #111C30 50%, #0A1120 100%);
      padding: 50px 48px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      position: relative;
      border-right: 1px solid rgba(255, 255, 255, 0.08);
      overflow: hidden;
    }
    .login-hero-pane::before {
      content: '';
      position: absolute;
      width: 480px;
      height: 480px;
      background: radial-gradient(circle, rgba(235, 142, 39, 0.16) 0%, rgba(235, 142, 39, 0) 70%);
      top: -120px;
      left: -120px;
      border-radius: 50%;
      pointer-events: none;
    }
    .login-hero-pane::after {
      content: '';
      position: absolute;
      width: 520px;
      height: 520px;
      background: radial-gradient(circle, rgba(37, 99, 235, 0.14) 0%, rgba(37, 99, 235, 0) 70%);
      bottom: -160px;
      right: -120px;
      border-radius: 50%;
      pointer-events: none;
    }
    .login-form-pane {
      flex: 1;
      background: #F8FAFC;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 40px 24px;
      position: relative;
      overflow-y: auto;
    }
    .login-box-card {
      width: 100%;
      max-width: 440px;
      background: #FFFFFF;
      border-radius: 20px;
      padding: 40px 34px;
      box-shadow: 0 20px 45px -15px rgba(0, 0, 0, 0.08), 0 0 0 1px rgba(226, 232, 240, 0.85);
    }
    @media (max-width: 900px) {
      #login-page { flex-direction: column; }
      .login-hero-pane { display: none; }
      .login-form-pane { min-height: 100vh; }
    }
  </style>
</head>
<body>

  <!-- ─── Sidebar Navigation ────────────────────────────────────────────────── -->
  <aside id="sidebar">
    <div style="padding: 24px 20px 20px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #1E293B;">
      <div style="width: 40px; height: 40px; border-radius: 10px; background: var(--primary); display: flex; align-items: center; justify-content: center; color: #0F172A; font-weight: 900; font-size: 18px;">
        M
      </div>
      <div>
        <div style="font-size: 15px; font-weight: 800; color: #FFFFFF; letter-spacing: -0.2px;">Monarch HR</div>
        <div style="font-size: 11px; color: #F5A952; font-weight: 600;">OPERATIONS & ADMIN</div>
      </div>
    </div>

    <div style="padding: 16px 0; flex: 1; overflow-y: auto;">
      <div style="padding: 0 24px 8px; font-size: 10.5px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.8px;">Core Operations</div>
      
      <a class="nav-item active" onclick="switchTab('dashboard')">
        <i data-lucide="layout-dashboard"></i>
        <span>Dashboard Overview</span>
      </a>
      
      <a class="nav-item" onclick="switchTab('employees')">
        <i data-lucide="users"></i>
        <span>Employees Directory</span>
        <span class="nav-badge" id="badge-total-emp">1,040</span>
      </a>

      <a class="nav-item" onclick="switchTab('attendance')">
        <i data-lucide="calendar-check"></i>
        <span>Daily Attendance</span>
      </a>

      <a class="nav-item" onclick="switchTab('monthly')">
        <i data-lucide="calendar-range"></i>
        <span>Monthly Attendance</span>
        <span class="nav-badge" style="background: rgba(245, 169, 82, 0.2); color: #F5A952;">26–25</span>
      </a>

      <a class="nav-item" onclick="switchTab('leaves')">
        <i data-lucide="calendar-off"></i>
        <span>Leave Management</span>
        <span class="nav-badge" id="badge-pending-leaves" style="background: rgba(245, 158, 11, 0.25); color: #FCD34D;">0</span>
      </a>

      <a class="nav-item" onclick="switchTab('gps')">
        <i data-lucide="map-pin"></i>
        <span>Live GPS Tracking</span>
        <span class="nav-badge" style="background: rgba(16, 185, 129, 0.25); color: #6EE7B7;">LIVE</span>
      </a>

      <div style="padding: 18px 24px 8px; font-size: 10.5px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.8px;">Workforce Control</div>

      <a class="nav-item" onclick="switchTab('requests')">
        <i data-lucide="inbox"></i>
        <span>Requests & Approvals</span>
        <span class="nav-badge" id="badge-all-requests">0</span>
      </a>

      <a class="nav-item" onclick="switchTab('holidays')">
        <i data-lucide="calendar"></i>
        <span>Company Calendar</span>
      </a>

      <a class="nav-item" onclick="switchTab('reports')">
        <i data-lucide="file-spreadsheet"></i>
        <span>Reports & Exports</span>
      </a>

      <a class="nav-item" id="nav-item-audit" onclick="switchTab('audit')">
        <i data-lucide="shield-check"></i>
        <span>Audit Logs Trail</span>
      </a>
    </div>

    <!-- Active Admin Profile Pill -->
    <div style="padding: 16px 20px; border-top: 1px solid #1E293B; display: flex; align-items: center; gap: 12px;">
      <div style="width: 36px; height: 36px; border-radius: 50%; background: #334155; color: #F8FAFC; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;" id="sidebar-user-avatar">
        U
      </div>
      <div style="flex: 1; min-width: 0;">
        <div style="font-size: 13px; font-weight: 700; color: #FFFFFF; truncate;" id="sidebar-user-name">Utkarsh Pingale</div>
        <div style="font-size: 11px; color: #10B981; font-weight: 600;" id="sidebar-user-role">Super Admin</div>
      </div>
      <button onclick="handleLogout()" style="background: transparent; border: none; color: #64748B; cursor: pointer; padding: 4px;" title="Sign Out">
        <i data-lucide="log-out" style="width: 18px; height: 18px;"></i>
      </button>
    </div>
  </aside>

  <!-- ─── Main Content Canvas ──────────────────────────────────────────────── -->
  <main id="main-content">
    
    <!-- Top Bar -->
    <header>
      <div style="display: flex; align-items: center; gap: 16px;">
        <div style="font-size: 18px; font-weight: 800; color: #0F172A;" id="page-title">Dashboard Overview</div>
        <div style="display: flex; align-items: center; gap: 6px; padding: 4px 10px; background: #F1F5F9; border-radius: 20px; font-size: 12px; font-weight: 600; color: #475569;">
          <span style="width: 7px; height: 7px; border-radius: 50%; background: #10B981; display: inline-block;"></span>
          <span id="digital-clock">00:00:00 IST</span>
        </div>
      </div>

      <div style="display: flex; align-items: center; gap: 12px;">
        <button class="btn btn-outline btn-sm" onclick="refreshCurrentTab()">
          <i data-lucide="rotate-cw" style="width: 14px; height: 14px;"></i>
          <span>Refresh</span>
        </button>
        <button class="btn btn-outline btn-sm" style="border-color: #10B981; color: #047857; background: #ECFDF5; font-weight: 600;" onclick="openUploadExcelModal()">
          <i data-lucide="file-spreadsheet" style="width: 14px; height: 14px; color: #10B981;"></i>
          <span>Upload Master Excel</span>
        </button>
        <button class="btn btn-primary btn-sm" onclick="openAddEmployeeModal()">
          <i data-lucide="user-plus" style="width: 14px; height: 14px;"></i>
          <span>Add Employee</span>
        </button>
      </div>
    </header>

    <!-- Content Workspace -->
    <div style="padding: 28px; flex: 1;">

      <!-- ═════════════════ TAB 1: DASHBOARD OVERVIEW ═════════════════ -->
      <section id="view-dashboard">
        <!-- Filter Bar -->
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; flex-wrap: wrap; gap: 12px;">
          <div>
            <h2 id="dashboard-title" style="font-size: 15px; font-weight: 700; color: #0F172A;">Enterprise Operations Today</h2>
            <p id="dashboard-subtitle" style="font-size: 12.5px; color: var(--text-muted);">Real-time aggregated KPIs from biometric terminals and mobile GPS punches.</p>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <div style="display: flex; background: #FFFFFF; border: 1px solid var(--border); border-radius: 8px; padding: 3px;">
              <button class="btn btn-sm" id="btn-period-today" style="background: var(--primary); color: #0F172A; font-weight: 700;" onclick="setPeriodFilter('today')">Today</button>
              <button class="btn btn-sm" id="btn-period-week" style="background: transparent; color: #64748B;" onclick="setPeriodFilter('week')">This Week</button>
              <button class="btn btn-sm" id="btn-period-month" style="background: transparent; color: #64748B;" onclick="setPeriodFilter('month')">This Month</button>
            </div>
          </div>
        </div>

        <!-- 10 KPI Cards Grid -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 28px;">
          
          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: var(--blue-bg); color: var(--blue);"><i data-lucide="users"></i></div>
            <div style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Total Headcount</div>
            <div style="font-size: 26px; font-weight: 800; color: #0F172A; margin: 4px 0;" id="kpi-total-emp">--</div>
            <div style="font-size: 11px; color: #10B981; font-weight: 600;">Directory verified</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: var(--green-bg); color: var(--green);"><i data-lucide="check-circle-2"></i></div>
            <div id="lbl-kpi-present" style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Present Today</div>
            <div style="font-size: 26px; font-weight: 800; color: var(--green); margin: 4px 0;" id="kpi-present">--</div>
            <div style="font-size: 11px; color: var(--text-muted);" id="kpi-att-rate">--% Attendance</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: var(--red-bg); color: var(--red);"><i data-lucide="user-x"></i></div>
            <div id="lbl-kpi-absent" style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Absent Today</div>
            <div style="font-size: 26px; font-weight: 800; color: var(--red); margin: 4px 0;" id="kpi-absent">--</div>
            <div style="font-size: 11px; color: var(--text-muted);" id="lbl-kpi-absent-sub">Not punched</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: var(--purple-bg); color: var(--purple);"><i data-lucide="calendar"></i></div>
            <div id="lbl-kpi-on-leave" style="font-size: 12px; font-weight: 600; color: var(--text-muted);">On Leave</div>
            <div style="font-size: 26px; font-weight: 800; color: var(--purple); margin: 4px 0;" id="kpi-on-leave">--</div>
            <div style="font-size: 11px; color: var(--text-muted);">Approved absence</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: var(--amber-bg); color: var(--amber);"><i data-lucide="clock"></i></div>
            <div style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Active Checked In</div>
            <div style="font-size: 26px; font-weight: 800; color: var(--amber); margin: 4px 0;" id="kpi-checked-in">--</div>
            <div style="font-size: 11px; color: #10B981; font-weight: 600;">● Shifts in progress</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: #FFF1F2; color: #E11D48;"><i data-lucide="alert-triangle"></i></div>
            <div id="lbl-kpi-late" style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Late Arrivals</div>
            <div style="font-size: 26px; font-weight: 800; color: #E11D48; margin: 4px 0;" id="kpi-late">--</div>
            <div style="font-size: 11px; color: var(--text-muted);">> 09:45 AM Grace</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: #F1F5F9; color: #475569;"><i data-lucide="log-out"></i></div>
            <div id="lbl-kpi-unclosed" style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Unclosed Shifts</div>
            <div style="font-size: 26px; font-weight: 800; color: #475569; margin: 4px 0;" id="kpi-unclosed">--</div>
            <div style="font-size: 11px; color: var(--text-muted);">No clock-out yet</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: var(--primary-subtle); color: var(--primary-dark);"><i data-lucide="inbox"></i></div>
            <div style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Pending Leaves</div>
            <div style="font-size: 26px; font-weight: 800; color: var(--primary-dark); margin: 4px 0;" id="kpi-pending-leaves">--</div>
            <div style="font-size: 11px; color: #2563EB; font-weight: 600; cursor: pointer;" onclick="switchTab('leaves')">Review queue →</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: #ECFDF5; color: #059669;"><i data-lucide="gauge"></i></div>
            <div id="lbl-kpi-rate" style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Attendance Rate</div>
            <div style="font-size: 26px; font-weight: 800; color: #059669; margin: 4px 0;" id="kpi-rate-pct">--%</div>
            <div style="font-size: 11px; color: var(--text-muted);">Company benchmark</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-icon-wrap" style="background: #EFF6FF; color: #2563EB;"><i data-lucide="timer"></i></div>
            <div id="lbl-kpi-hours" style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Total Hours Logged</div>
            <div style="font-size: 26px; font-weight: 800; color: #2563EB; margin: 4px 0;" id="kpi-work-hours">--</div>
            <div style="font-size: 11px; color: var(--text-muted);">Cumulative period</div>
          </div>

        </div>

        <!-- Charts Row -->
        <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 28px;">
          <!-- 7-Day Trend Chart -->
          <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 22px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
              <div>
                <h3 id="chart-trend-title" style="font-size: 14.5px; font-weight: 700; color: #0F172A;">Attendance Trend (Last 7 Days)</h3>
                <p id="chart-trend-subtitle" style="font-size: 12px; color: var(--text-muted);">Daily volume of Present, Late, and Absent workforce</p>
              </div>
            </div>
            <div style="height: 280px;">
              <canvas id="chart-attendance-trend"></canvas>
            </div>
          </div>

          <!-- Department Headcount Doughnut -->
          <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 22px;">
            <div style="margin-bottom: 16px;">
              <h3 style="font-size: 14.5px; font-weight: 700; color: #0F172A;">Department Allocation</h3>
              <p style="font-size: 12px; color: var(--text-muted);">Active staff per operational division</p>
            </div>
            <div style="height: 280px; position: relative;">
              <canvas id="chart-dept-distribution"></canvas>
            </div>
          </div>
        </div>

        <!-- Live Punch Stream -->
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 22px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div>
              <h3 style="font-size: 14.5px; font-weight: 700; color: #0F172A;">Real-Time Punch Activity Stream</h3>
              <p style="font-size: 12px; color: var(--text-muted);">Live updates from biometric hardware terminals & mobile attendance</p>
            </div>
            <button class="btn btn-outline btn-sm" onclick="switchTab('attendance')">View All Attendance →</button>
          </div>
          <div style="overflow-x: auto;">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Department</th>
                  <th>Date</th>
                  <th>Clock In</th>
                  <th>Clock Out</th>
                  <th>Terminal / Location</th>
                  <th>Geofence Range</th>
                </tr>
              </thead>
              <tbody id="table-recent-activity">
                <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">Loading real-time punch records...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- ═════════════════ TAB 2: EMPLOYEES DIRECTORY ═════════════════ -->
      <section id="view-employees" style="display: none;">
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 20px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
          <div style="display: flex; align-items: center; gap: 12px; flex: 1; max-width: 650px;">
            <div style="position: relative; flex: 1; min-width: 260px;">
              <input type="text" id="emp-search-input" class="form-control" style="padding-left: 36px; padding-right: 32px;" placeholder="Search by name, ID (#1009), email, phone..." oninput="handleEmployeeSearch(event)" onkeydown="if(event.key==='Enter') handleEmployeeSearch(event)">
              <i data-lucide="search" style="position: absolute; left: 11px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; color: var(--text-muted); pointer-events: none;"></i>
              <button type="button" id="emp-search-clear" onclick="clearEmployeeSearch()" style="position: absolute; right: 10px; top: 50%; transform: translateY(-50%); background: none; border: none; color: #94A3B8; cursor: pointer; display: none; padding: 2px;" title="Clear search">
                <i data-lucide="x" style="width: 14px; height: 14px;"></i>
              </button>
            </div>
            <select id="emp-dept-filter" class="form-control" style="width: 200px;" onchange="loadEmployees(1)">
              <option value="">All Departments</option>
            </select>
            <select id="emp-status-filter" class="form-control" style="width: 140px;" onchange="loadEmployees(1)">
              <option value="active">Active Only</option>
              <option value="inactive">Inactive</option>
              <option value="all">All Accounts</option>
            </select>
          </div>
          <div style="display: flex; gap: 10px;">
            <button class="btn btn-outline" onclick="downloadReport('employee_master')">
              <i data-lucide="download"></i>
              <span>Export CSV</span>
            </button>
            <button class="btn btn-outline" style="border-color: #10B981; color: #047857; background: #ECFDF5; font-weight: 600;" onclick="openUploadExcelModal()">
              <i data-lucide="file-spreadsheet" style="width: 15px; height: 15px; color: #10B981;"></i>
              <span>Upload Master Excel</span>
            </button>
            <button class="btn btn-primary" onclick="openAddEmployeeModal()">
              <i data-lucide="user-plus"></i>
              <span>Add Employee</span>
            </button>
          </div>
        </div>

        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; overflow: hidden;">
          <table class="data-table">
            <thead>
              <tr>
                <th>Emp ID</th>
                <th>Employee Name</th>
                <th>Department</th>
                <th>Designation</th>
                <th>Reporting Manager</th>
                <th>Shift & Off</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="table-employees-body">
              <tr><td colspan="8" style="text-align: center; padding: 30px;">Loading employee records...</td></tr>
            </tbody>
          </table>
          
          <div style="padding: 16px 20px; border-top: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
            <div style="font-size: 13px; color: var(--text-muted);" id="emp-pagination-info">Showing 0 of 0 employees</div>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-outline btn-sm" id="btn-emp-prev" onclick="changeEmployeePage(-1)">Previous</button>
              <button class="btn btn-outline btn-sm" id="btn-emp-next" onclick="changeEmployeePage(1)">Next</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ═════════════════ TAB 3: ATTENDANCE MANAGEMENT ═════════════════ -->
      <section id="view-attendance" style="display: none;">
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 20px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
          <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
            <input type="date" id="att-date-picker" class="form-control" style="width: 160px;" onchange="loadAttendanceRecords(1)">
            <input type="text" id="att-search-input" class="form-control" style="width: 220px;" placeholder="Search employee..." oninput="handleAttendanceSearch(event)" onkeydown="if(event.key==='Enter') handleAttendanceSearch(event)">
            <select id="att-status-filter" class="form-control" style="width: 150px;" onchange="loadAttendanceRecords(1)">
              <option value="all">All Statuses</option>
              <option value="present">Present</option>
              <option value="late">Late</option>
              <option value="half day">Half Day</option>
              <option value="missing">Missing Punch-Out</option>
            </select>
            <button id="btn-clear-daily-filter" class="btn btn-sm" onclick="setDailyKpiFilter('all')" style="display: none; padding: 4px 10px; font-size: 12px; background: #F1F5F9; color: #475569; border: 1px solid #CBD5E1; border-radius: 6px; cursor: pointer; align-items: center; gap: 4px;">✕ Reset Filter</button>
          </div>
          <div style="display: flex; gap: 10px;">
            <button class="btn btn-outline" onclick="openManualPunchModal()">
              <i data-lucide="plus-circle"></i>
              <span>Add Missing Punch</span>
            </button>
            <button class="btn btn-outline" onclick="downloadReport('daily_attendance')">
              <i data-lucide="download"></i>
              <span>Export CSV</span>
            </button>
          </div>
        </div>

        <!-- Daily KPI Metric Cards Grid (Click to Filter) -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 20px;">
          <div class="kpi-card" id="kpi-card-daily-all" onclick="setDailyKpiFilter('all')" style="cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select: none; position: relative;" title="Click to view all registered staff">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Total Staff</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="tag-daily-all" class="badge badge-blue" style="font-size: 10px; font-weight: 700; display: none; padding: 2px 6px;">FILTER ACTIVE</span>
                <i data-lucide="users" style="color: #3B82F6; width: 20px; height: 20px;"></i>
              </div>
            </div>
            <div style="font-size: 26px; font-weight: 800; color: #0F172A; margin: 8px 0 2px;" id="kpi-daily-emps">0</div>
            <div style="font-size: 11.5px; color: var(--text-muted);" id="kpi-daily-emps-sub">Registered in company master</div>
          </div>

          <div class="kpi-card" id="kpi-card-daily-punches" onclick="setDailyKpiFilter('punches')" style="cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select: none; position: relative;" title="Click to filter staff with punches on this date">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Total Punches</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="tag-daily-punches" class="badge badge-green" style="font-size: 10px; font-weight: 700; display: none; padding: 2px 6px;">FILTER ACTIVE</span>
                <i data-lucide="calendar" style="color: #10B981; width: 20px; height: 20px;"></i>
              </div>
            </div>
            <div style="font-size: 26px; font-weight: 800; color: #10B981; margin: 8px 0 2px;" id="kpi-daily-total">0</div>
            <div style="font-size: 11.5px; color: var(--text-muted);" id="kpi-daily-total-sub">Recorded today</div>
          </div>

          <div class="kpi-card" id="kpi-card-daily-late" onclick="setDailyKpiFilter('late')" style="cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select: none; position: relative;" title="Click to filter late arrivals on this date">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Late Arrivals</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="tag-daily-late" class="badge badge-amber" style="font-size: 10px; font-weight: 700; display: none; padding: 2px 6px;">FILTER ACTIVE</span>
                <i data-lucide="clock" style="color: #F59E0B; width: 20px; height: 20px;"></i>
              </div>
            </div>
            <div style="font-size: 26px; font-weight: 800; color: #F59E0B; margin: 8px 0 2px;" id="kpi-daily-late">0</div>
            <div style="font-size: 11.5px; color: var(--text-muted);" id="kpi-daily-late-sub">After 09:45 AM grace time</div>
          </div>

          <div class="kpi-card" id="kpi-card-daily-geofence" onclick="setDailyKpiFilter('out_of_range')" style="cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select: none; position: relative;" title="Click to filter staff outside company perimeter on this date">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Out of Range</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="tag-daily-geofence" class="badge badge-red" style="font-size: 10px; font-weight: 700; display: none; padding: 2px 6px;">FILTER ACTIVE</span>
                <i data-lucide="map-pin-off" style="color: #EF4444; width: 20px; height: 20px;"></i>
              </div>
            </div>
            <div style="font-size: 26px; font-weight: 800; color: #EF4444; margin: 8px 0 2px;" id="kpi-daily-geofence">0</div>
            <div style="font-size: 11.5px; color: var(--text-muted);" id="kpi-daily-geofence-sub">Outside company perimeter</div>
          </div>
        </div>

        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; overflow: hidden;">
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Employee Name</th>
                <th>Department</th>
                <th>Date</th>
                <th>Clock In</th>
                <th>Clock Out</th>
                <th>Hours</th>
                <th>Late / Early</th>
                <th>Status</th>
                <th>Location / Geofence</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="table-attendance-body">
              <tr><td colspan="11" style="text-align: center; padding: 30px;">Loading attendance records...</td></tr>
            </tbody>
          </table>

          <div style="padding: 16px 20px; border-top: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
            <div style="font-size: 13px; color: var(--text-muted);" id="att-pagination-info">Showing records...</div>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-outline btn-sm" id="btn-att-prev" onclick="changeAttendancePage(-1)">Previous</button>
              <button class="btn btn-outline btn-sm" id="btn-att-next" onclick="changeAttendancePage(1)">Next</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ═════════════════ TAB 3B: ATTENDANCE MUSTER ROLL (26th–25th) ═════════════════ -->
      <section id="view-monthly" style="display: none;">
        
        <!-- Controls & Filter Toolbar -->
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 20px; margin-bottom: 20px;">
          <div style="display: flex; align-items: flex-end; justify-content: space-between; flex-wrap: wrap; gap: 14px; margin-bottom: 16px;">
            <div style="display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap;">
              
              <!-- Cycle Selector Dropdown -->
              <div style="display: flex; flex-direction: column; gap: 4px;">
                <label style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Payroll Cycle (26th – 25th)</label>
                <select id="monthly-cycle-select" class="form-control" style="width: 270px; font-weight: 600;" onchange="handleMonthlyCycleChange()">
                  <option value="">Loading cycles...</option>
                </select>
              </div>

              <!-- Custom Date Pickers (Shown if custom chosen) -->
              <div id="monthly-custom-dates" style="display: none; align-items: flex-end; gap: 6px;">
                <div style="display: flex; flex-direction: column; gap: 4px;">
                  <label style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">From</label>
                  <input type="date" id="monthly-start-date" class="form-control" style="width: 140px;" onchange="loadMonthlyAttendance(1)">
                </div>
                <div style="display: flex; flex-direction: column; gap: 4px;">
                  <label style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">To</label>
                  <input type="date" id="monthly-end-date" class="form-control" style="width: 140px;" onchange="loadMonthlyAttendance(1)">
                </div>
              </div>

              <!-- Employee Search Input -->
              <div style="display: flex; flex-direction: column; gap: 4px;">
                <label style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Search Employee</label>
                <input type="text" id="monthly-search-input" class="form-control" style="width: 260px;" placeholder="Search Emp No (#1228) or Name..." onkeyup="handleMonthlySearch(event)">
              </div>

            </div>

            <!-- Action Buttons -->
            <div style="display: flex; gap: 10px;">
              <button class="btn btn-outline" onclick="loadMonthlyAttendance(1)" title="Reload records">
                <i data-lucide="refresh-cw"></i>
                <span>Refresh</span>
              </button>
              <button class="btn btn-primary" onclick="exportMonthlyAttendanceCsv()" title="Download Attendance Muster CSV/Excel matching template">
                <i data-lucide="download"></i>
                <span>Export Muster CSV</span>
              </button>
            </div>
          </div>

          <!-- Active Cycle Pill Banner & Legend -->
          <div style="background: rgba(245, 169, 82, 0.08); border: 1px solid rgba(245, 169, 82, 0.25); border-radius: 8px; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; font-size: 12px; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <i data-lucide="calendar-check-2" style="color: #F5A952; width: 16px; height: 16px;"></i>
              <span style="font-weight: 600; color: #0F172A;">Attendance Muster:</span>
              <span id="monthly-cycle-banner-text" style="font-weight: 700; color: #D97706;">26 Sep 2026 - 25 Oct 2026</span>
              <span id="monthly-filter-pill-count" style="font-weight: 600; color: var(--text-muted); margin-left: 8px;">(All Employees Master Roll)</span>
              <button id="btn-clear-monthly-filter" class="btn btn-sm" onclick="setMonthlyKpiFilter('all')" style="display: none; padding: 2px 8px; font-size: 11px; margin-left: 6px; background: #F1F5F9; color: #475569; border: 1px solid #CBD5E1; border-radius: 6px; cursor: pointer; align-items: center; gap: 4px;">✕ Reset to All</button>
            </div>
            
            <!-- Legend -->
            <div style="display: flex; align-items: center; gap: 12px; font-size: 11.5px; font-weight: 600; flex-wrap: wrap;">
              <span style="color: var(--text-muted); font-size: 11px; text-transform: uppercase;">Legend:</span>
              <span style="display: flex; align-items: center; gap: 4px;"><span class="muster-chip chip-P">P</span> Present (incl. Approved Leave)</span>
              <span style="display: flex; align-items: center; gap: 4px;"><span class="muster-chip chip-A">A</span> Absent (Pending Leave: Absent)</span>
              <span style="display: flex; align-items: center; gap: 4px;"><span class="muster-chip chip-WO">WO</span> Week Off (Sun & Even Sat)</span>
              <span style="display: flex; align-items: center; gap: 4px;"><span class="muster-chip chip-H">H</span> Holiday (Festivals)</span>
              <span style="display: flex; align-items: center; gap: 4px;"><span class="muster-chip chip-HD">A:P</span> Absent 1st Session</span>
              <span style="display: flex; align-items: center; gap: 4px;"><span class="muster-chip chip-HD">P:A</span> Absent 2nd Session</span>
              <span style="color: #64748B; font-size: 11px; background: #F1F5F9; padding: 2px 6px; border-radius: 4px; border: 1px dashed #CBD5E1;">📅 Even Sat: Week Off (WO) | Odd Sat: Working</span>
            </div>
          </div>
        </div>

        <!-- KPI Metric Cards Grid (Click to Filter) -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 20px;">
          <div class="kpi-card" id="kpi-card-monthly-all" onclick="setMonthlyKpiFilter('all')" style="cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select: none; position: relative;" title="Click to view all registered staff">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Total Staff</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="tag-monthly-all" class="badge badge-blue" style="font-size: 10px; font-weight: 700; display: none; padding: 2px 6px;">FILTER ACTIVE</span>
                <i data-lucide="users" style="color: #3B82F6; width: 20px; height: 20px;"></i>
              </div>
            </div>
            <div style="font-size: 26px; font-weight: 800; color: #0F172A; margin: 8px 0 2px;" id="kpi-monthly-emps">0</div>
            <div style="font-size: 11.5px; color: var(--text-muted);" id="kpi-monthly-emps-sub">Registered in company master</div>
          </div>

          <div class="kpi-card" id="kpi-card-monthly-punches" onclick="setMonthlyKpiFilter('punches')" style="cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select: none; position: relative;" title="Click to filter staff with punches in active cycle">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Total Punches</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="tag-monthly-punches" class="badge badge-green" style="font-size: 10px; font-weight: 700; display: none; padding: 2px 6px;">FILTER ACTIVE</span>
                <i data-lucide="calendar" style="color: #10B981; width: 20px; height: 20px;"></i>
              </div>
            </div>
            <div style="font-size: 26px; font-weight: 800; color: #10B981; margin: 8px 0 2px;" id="kpi-monthly-total">0</div>
            <div style="font-size: 11.5px; color: var(--text-muted);" id="kpi-monthly-total-sub">Recorded in active cycle</div>
          </div>

          <div class="kpi-card" id="kpi-card-monthly-late" onclick="setMonthlyKpiFilter('late')" style="cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select: none; position: relative;" title="Click to filter staff with late arrivals in active cycle">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Late Arrivals</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="tag-monthly-late" class="badge badge-amber" style="font-size: 10px; font-weight: 700; display: none; padding: 2px 6px;">FILTER ACTIVE</span>
                <i data-lucide="clock" style="color: #F59E0B; width: 20px; height: 20px;"></i>
              </div>
            </div>
            <div style="font-size: 26px; font-weight: 800; color: #F59E0B; margin: 8px 0 2px;" id="kpi-monthly-late">0</div>
            <div style="font-size: 11.5px; color: var(--text-muted);" id="kpi-monthly-late-sub">After 09:45 AM grace time</div>
          </div>

          <div class="kpi-card" id="kpi-card-monthly-geofence" onclick="setMonthlyKpiFilter('out_of_range')" style="cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select: none; position: relative;" title="Click to filter staff with out-of-range punches">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Out of Range</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="tag-monthly-geofence" class="badge badge-red" style="font-size: 10px; font-weight: 700; display: none; padding: 2px 6px;">FILTER ACTIVE</span>
                <i data-lucide="map-pin-off" style="color: #EF4444; width: 20px; height: 20px;"></i>
              </div>
            </div>
            <div style="font-size: 26px; font-weight: 800; color: #EF4444; margin: 8px 0 2px;" id="kpi-monthly-geofence">0</div>
            <div style="font-size: 11.5px; color: var(--text-muted);" id="kpi-monthly-geofence-sub">Outside company perimeter</div>
          </div>
        </div>

        <!-- Attendance Muster Matrix Table Container -->
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
          <div class="muster-container">
            <table class="muster-table" id="table-monthly-muster">
              <thead id="table-monthly-muster-head">
                <tr>
                  <th class="sticky-col">Emp No</th>
                  <th class="sticky-col-2">Employee Name</th>
                  <th colspan="30" style="text-align: center;">Loading Payroll Cycle Dates...</th>
                  <th>P</th>
                  <th>A</th>
                  <th>WO</th>
                  <th>HD</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody id="table-monthly-attendance-body">
                <tr><td colspan="36" style="text-align: center; padding: 40px; color: var(--text-muted);">Loading Attendance Muster Roll...</td></tr>
              </tbody>
            </table>
          </div>

          <!-- Pagination Bar -->
          <div style="padding: 16px 20px; border-top: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 14px;">
              <span style="font-size: 13px; color: var(--text-muted);" id="monthly-pagination-info">Showing records...</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span style="font-size: 12px; color: var(--text-muted);">Rows per page:</span>
                <select id="monthly-page-size" class="form-control" style="width: 75px; padding: 4px 8px; font-size: 12px;" onchange="loadMonthlyAttendance(1)">
                  <option value="25">25</option>
                  <option value="50" selected>50</option>
                  <option value="100">100</option>
                  <option value="200">200</option>
                </select>
              </div>
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-outline btn-sm" id="btn-monthly-prev" onclick="changeMonthlyPage(-1)">Previous</button>
              <span id="monthly-page-indicator" style="font-size: 13px; font-weight: 700; align-self: center; padding: 0 6px;">1</span>
              <button class="btn btn-outline btn-sm" id="btn-monthly-next" onclick="changeMonthlyPage(1)">Next</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ═════════════════ TAB 4: LEAVE MANAGEMENT ═════════════════ -->
      <section id="view-leaves" style="display: none;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px;">
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-primary btn-sm" id="btn-sub-leaves-req" onclick="switchLeavesSubtab('requests')">Leave Requests Queue</button>
            <button class="btn btn-outline btn-sm" id="btn-sub-leaves-bal" onclick="switchLeavesSubtab('balances')">Employee Leave Quotas</button>
            <button class="btn btn-outline btn-sm" id="btn-sub-leaves-types" onclick="switchLeavesSubtab('types')">Leave Categories</button>
          </div>
          <button class="btn btn-outline btn-sm" onclick="openApplyOnBehalfModal()">
            <i data-lucide="plus"></i>
            <span>Apply on Behalf of Staff</span>
          </button>
        </div>

        <!-- Subview: Requests Queue -->
        <div id="subview-leaves-requests">
          <!-- Filter Controls Bar -->
          <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 14px 18px; margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
            <!-- Status Filter Pills -->
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span style="font-size: 12px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.5px; margin-right: 4px;">Status:</span>
              <button type="button" class="btn btn-primary btn-sm" id="btn-leaves-filter-all" onclick="setLeavesStatusFilter('all')" style="font-size: 12px; padding: 5px 12px; border-radius: 8px;">
                <span>All Requests</span>
                <span id="badge-count-all" style="background: rgba(255,255,255,0.25); padding: 1px 6px; border-radius: 10px; font-size: 11px; margin-left: 4px;">0</span>
              </button>
              <button type="button" class="btn btn-outline btn-sm" id="btn-leaves-filter-pending" onclick="setLeavesStatusFilter('pending')" style="font-size: 12px; padding: 5px 12px; border-radius: 8px; border-color: #F59E0B; color: #D97706;">
                <span>⏳ Pending Review</span>
                <span id="badge-count-pending" style="background: #FEF3C7; color: #B45309; padding: 1px 7px; border-radius: 10px; font-size: 11px; margin-left: 4px; font-weight: 700;">0</span>
              </button>
              <button type="button" class="btn btn-outline btn-sm" id="btn-leaves-filter-approved" onclick="setLeavesStatusFilter('approved')" style="font-size: 12px; padding: 5px 12px; border-radius: 8px; border-color: #10B981; color: #059669;">
                <span>✅ Approved</span>
                <span id="badge-count-approved" style="background: #D1FAE5; color: #047857; padding: 1px 7px; border-radius: 10px; font-size: 11px; margin-left: 4px; font-weight: 700;">0</span>
              </button>
              <button type="button" class="btn btn-outline btn-sm" id="btn-leaves-filter-rejected" onclick="setLeavesStatusFilter('rejected')" style="font-size: 12px; padding: 5px 12px; border-radius: 8px; border-color: #EF4444; color: #DC2626;">
                <span>❌ Rejected</span>
                <span id="badge-count-rejected" style="background: #FEE2E2; color: #B91C1C; padding: 1px 7px; border-radius: 10px; font-size: 11px; margin-left: 4px; font-weight: 700;">0</span>
              </button>
            </div>

            <!-- Search & Type Filters -->
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
              <input type="text" id="leaves-search-input" class="form-control" style="width: 210px; font-size: 12.5px; padding: 6px 12px;" placeholder="🔍 Search Emp ID or Name..." oninput="renderLeavesRequestsTable()">
              <select id="leaves-type-filter" class="form-control" style="width: 175px; font-size: 12.5px; padding: 6px 10px;" onchange="renderLeavesRequestsTable()">
                <option value="all">All Categories</option>
                <option value="Casual Leave">Casual Leave (CL)</option>
                <option value="Sick Leave">Sick Leave (SL)</option>
                <option value="Earned Leave">Earned Leave (EL)</option>
                <option value="Leave Without Pay">Leave Without Pay (LWP)</option>
                <option value="Compensatory Off">Compensatory Off</option>
              </select>
              <button type="button" class="btn btn-outline btn-sm" onclick="loadLeaveRequests()" title="Refresh Queue" style="padding: 6px 12px;">
                🔄 Refresh
              </button>
            </div>
          </div>

          <!-- Table Container -->
          <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; overflow: hidden;">
            <table class="data-table">
            <thead>
              <tr>
                <th>Employee</th>
                <th>Leave Type</th>
                <th>Period & Duration</th>
                <th>Approval Hierarchy & Flow</th>
                <th>Reason / Note</th>
                <th>Status</th>
                <th>Manager Authority & Decision</th>
              </tr>
            </thead>
            <tbody id="table-leaves-requests-body">
              <tr><td colspan="7" style="text-align: center; padding: 30px;">Loading leave applications...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

        <!-- Subview: Balances -->
        <div id="subview-leaves-balances" style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; display: none;">
          <table class="data-table">
            <thead>
              <tr>
                <th>Emp ID</th>
                <th>Name</th>
                <th>Department</th>
                <th>Annual Allotted</th>
                <th>Used Days</th>
                <th>Remaining Balance</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="table-leaves-balances-body">
              <tr><td colspan="7" style="text-align: center; padding: 30px;">Loading employee balances...</td></tr>
            </tbody>
          </table>
        </div>

        <!-- Subview: Types -->
        <div id="subview-leaves-types" style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 22px; display: none;">
          <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 16px;">Configured Leave Categories</h3>
          <table class="data-table">
            <thead>
              <tr>
                <th>Leave Name</th>
                <th>Code</th>
                <th>Annual Days</th>
                <th>Carry Forward Max</th>
                <th>Paid Leave</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody id="table-leaves-types-body">
              <tr><td colspan="6" style="text-align: center; padding: 20px;">Loading categories...</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ═════════════════ TAB 5: LIVE GPS TRACKING ═════════════════ -->
      <section id="view-gps" style="display: none;">
        <!-- Header controls & KPI Stats Bar -->
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 18px 22px; margin-bottom: 18px;">
          <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px;">
            <div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <h3 style="font-size: 16px; font-weight: 800; color: #0F172A; margin: 0;">Live GPS Tracking & Mobile Punch Radar</h3>
                <span class="badge badge-green" id="gps-live-indicator" style="font-size: 10px;">● RADAR ACTIVE</span>
              </div>
              <p style="font-size: 12.5px; color: var(--text-muted); margin: 3px 0 0 0;">
                Live employee punch radar with GPS coordinates, campus geofence boundary, and movement trails.
              </p>
            </div>
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="display: flex; align-items: center; gap: 6px; background: #F8FAFC; border: 1px solid var(--border); border-radius: 8px; padding: 5px 10px;">
                <span style="font-size: 11px; font-weight: 700; color: #64748B;">DATE:</span>
                <input type="date" id="gps-date-filter" class="form-input" style="border: none; background: transparent; padding: 2px 4px; font-size: 12.5px; font-weight: 600;" onchange="loadGpsTracking()">
              </div>
              <button class="btn btn-secondary btn-sm" onclick="setGpsToday()" style="font-size: 12px; padding: 7px 12px;">
                Today
              </button>
              <button class="btn btn-primary btn-sm" onclick="loadGpsTracking()" style="font-size: 12px; padding: 7px 14px;">
                <i data-lucide="refresh-cw" style="width: 14px; height: 14px;"></i>
                <span>Refresh Radar</span>
              </button>
            </div>
          </div>

          <!-- GPS Summary Stats Cards -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;">
            <div style="background: #F8FAFC; border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px;">
              <div style="font-size: 11px; font-weight: 700; color: #64748B; text-transform: uppercase;">Total Tracked</div>
              <div style="font-size: 20px; font-weight: 800; color: #0F172A; margin-top: 2px;" id="stat-gps-total">0</div>
              <div style="font-size: 11px; color: var(--text-muted);">Active employee punches</div>
            </div>
            <div style="background: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 10px; padding: 12px 14px;">
              <div style="font-size: 11px; font-weight: 700; color: #065F46; text-transform: uppercase;">📱 Phone Check-Ins</div>
              <div style="font-size: 20px; font-weight: 800; color: #065F46; margin-top: 2px;" id="stat-gps-phone-in">0</div>
              <div style="font-size: 11px; color: #047857;">GPS captured at clock-in</div>
            </div>
            <div style="background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 10px; padding: 12px 14px;">
              <div style="font-size: 11px; font-weight: 700; color: #1E40AF; text-transform: uppercase;">📱 Phone Check-Outs</div>
              <div style="font-size: 20px; font-weight: 800; color: #1E40AF; margin-top: 2px;" id="stat-gps-phone-out">0</div>
              <div style="font-size: 11px; color: #1D4ED8;">GPS captured at clock-out</div>
            </div>
            <div style="background: #F8FAFC; border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px;">
              <div style="font-size: 11px; font-weight: 700; color: #64748B; text-transform: uppercase;">🏢 Biometric Machine</div>
              <div style="font-size: 20px; font-weight: 800; color: #334155; margin-top: 2px;" id="stat-gps-biometric">0</div>
              <div style="font-size: 11px; color: var(--text-muted);">Punched via hardware</div>
            </div>
            <div style="background: #FEF2F2; border: 1px solid #FECACA; border-radius: 10px; padding: 12px 14px;">
              <div style="font-size: 11px; font-weight: 700; color: #991B1B; text-transform: uppercase;">⚠️ Outside Geofence</div>
              <div style="font-size: 20px; font-weight: 800; color: #DC2626; margin-top: 2px;" id="stat-gps-outside">0</div>
              <div style="font-size: 11px; color: #B91C1C;">> 40m from building</div>
            </div>
          </div>
        </div>

        <!-- Radar Layout: Map (left) + Staff Position List (right) -->
        <div style="display: grid; grid-template-columns: 2.8fr 1.2fr; gap: 18px;">
          <!-- Map Container -->
          <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 16px; display: flex; flex-direction: column;">
            <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px;">
              <!-- Map Filter Pills -->
              <div style="display: flex; flex-wrap: wrap; gap: 6px;" id="gps-map-filters">
                <button class="gps-filter-btn active" onclick="setGpsFilter('all')">All Punches</button>
                <button class="gps-filter-btn" onclick="setGpsFilter('phone_only')">📱 Phone Only</button>
                <button class="gps-filter-btn" onclick="setGpsFilter('phone_in')">🟢 Phone Check-In</button>
                <button class="gps-filter-btn" onclick="setGpsFilter('phone_out')">🔵 Phone Check-Out</button>
                <button class="gps-filter-btn" onclick="setGpsFilter('biometric')">🏢 Biometric</button>
                <button class="gps-filter-btn" onclick="setGpsFilter('out_geofence')">⚠️ Outside Geofence</button>
              </div>

              <!-- Map Legend -->
              <div style="display: flex; align-items: center; gap: 10px; font-size: 11px; color: #64748B;">
                <span style="display: inline-flex; align-items: center; gap: 4px;"><span style="width: 10px; height: 10px; border-radius: 50%; background: #10B981; display: inline-block;"></span> Phone In</span>
                <span style="display: inline-flex; align-items: center; gap: 4px;"><span style="width: 10px; height: 10px; border-radius: 50%; background: #3B82F6; display: inline-block;"></span> Phone Out</span>
                <span style="display: inline-flex; align-items: center; gap: 4px;"><span style="width: 14px; height: 10px; border-radius: 2px; background: rgba(16, 185, 129, 0.15); border: 1.5px dashed #EF4444; display: inline-block;"></span> Campus Geofence</span>
              </div>
            </div>

            <!-- Leaflet Map Div -->
            <div id="map" style="height: 620px; width: 100%; border-radius: 10px; border: 1px solid var(--border);"></div>
          </div>

          <!-- Staff Location List -->
          <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 18px; height: 688px; display: flex; flex-direction: column;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
              <h3 style="font-size: 14px; font-weight: 700; color: #0F172A; margin: 0;">Employee Punch Locations</h3>
              <span class="badge badge-gray" id="gps-staff-count" style="font-size: 10px;">0 staff</span>
            </div>

            <!-- Search box -->
            <div style="margin-bottom: 12px;">
              <input type="text" id="gps-staff-search" class="form-input" placeholder="Search by name or ID..." oninput="renderGpsStaffList()" style="font-size: 12px; padding: 7px 10px; width: 100%;">
            </div>

            <!-- Scrollable list of cards -->
            <div style="flex: 1; overflow-y: auto; padding-right: 4px;" id="gps-staff-list">
              <div style="text-align: center; color: var(--text-muted); padding: 40px 10px;">Loading radar pins...</div>
            </div>
          </div>
        </div>
      </section>

      <!-- ═════════════════ TAB 7: REQUESTS & APPROVALS ═════════════════ -->
      <section id="view-requests" style="display: none;">
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 22px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div>
              <h3 style="font-size: 15px; font-weight: 700; color: #0F172A;">Unified Approvals Inbox</h3>
              <p style="font-size: 12.5px; color: var(--text-muted);">Centralized queue of pending leave requests and punch corrections.</p>
            </div>
            <span class="badge badge-amber" id="requests-pending-count">0 Pending</span>
          </div>

          <table class="data-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Employee</th>
                <th>Request Title</th>
                <th>Period / Punch Details</th>
                <th>Reason Provided</th>
                <th>Applied Date</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="table-all-requests-body">
              <tr><td colspan="7" style="text-align: center; padding: 30px;">Loading approval queue...</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ═════════════════ TAB 8: HOLIDAYS & CALENDAR ═════════════════ -->
      <section id="view-holidays" style="display: none;">
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 22px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div>
              <h3 style="font-size: 15px; font-weight: 700;">Company Holidays Calendar (2026)</h3>
              <p style="font-size: 12px; color: var(--text-muted);">Official gazetted and declared paid company holidays</p>
            </div>
            <button class="btn btn-primary btn-sm" onclick="openAddHolidayModal()">
              <i data-lucide="plus"></i>
              <span>Add Holiday</span>
            </button>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Weekday</th>
                <th>Holiday Title</th>
                <th>Type</th>
              </tr>
            </thead>
            <tbody id="table-holidays-body">
              <tr><td colspan="4" style="text-align: center; padding: 30px;">Loading holiday calendar...</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ═════════════════ TAB 9: REPORTS & EXPORTS ═════════════════ -->
      <section id="view-reports" style="display: none;">
        <div style="margin-bottom: 24px;">
          <h2 style="font-size: 16px; font-weight: 800;">Enterprise Analytics & CSV Reports</h2>
          <p style="font-size: 12.5px; color: var(--text-muted);">Generate, filter, and stream compliant CSV data formatted for Excel & payroll.</p>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px;">
          
          <div class="kpi-card">
            <h3 style="font-size: 14.5px; font-weight: 700; margin-bottom: 6px;">Daily Attendance Master</h3>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">Comprehensive employee punches, exact check-in/out, hours, and punctuality flags for selected date.</p>
            <button class="btn btn-primary btn-sm" onclick="downloadReport('daily_attendance')">
              <i data-lucide="download"></i>
              <span>Download Daily CSV</span>
            </button>
          </div>

          <div class="kpi-card">
            <h3 style="font-size: 14.5px; font-weight: 700; margin-bottom: 6px;">Monthly Aggregated Attendance</h3>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">Employee-wise sum of present days, late arrivals, total hours, and overtime across month cycle.</p>
            <button class="btn btn-primary btn-sm" onclick="downloadReport('monthly_attendance')">
              <i data-lucide="download"></i>
              <span>Download Monthly CSV</span>
            </button>
          </div>

          <div class="kpi-card">
            <h3 style="font-size: 14.5px; font-weight: 700; margin-bottom: 6px;">Leave Balances & Utilization</h3>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">Real-time leave balance report containing total allotted, used, and remaining leaves per employee.</p>
            <button class="btn btn-primary btn-sm" onclick="downloadReport('leave_balances')">
              <i data-lucide="download"></i>
              <span>Download Balances CSV</span>
            </button>
          </div>

          <div class="kpi-card">
            <h3 style="font-size: 14.5px; font-weight: 700; margin-bottom: 6px;">Employee Master Directory</h3>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">Complete directory with verified employee IDs, phone numbers, emails, departments, designations, and managers.</p>
            <button class="btn btn-primary btn-sm" onclick="downloadReport('employee_master')">
              <i data-lucide="download"></i>
              <span>Download Directory CSV</span>
            </button>
          </div>

          <div class="kpi-card">
            <h3 style="font-size: 14.5px; font-weight: 700; margin-bottom: 6px;">Attendance Anomalies & Missing Punches</h3>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">Flagged audit report of missing clock-outs, geofence radius violations, and excessive tardiness.</p>
            <button class="btn btn-primary btn-sm" onclick="downloadReport('punch_anomalies')">
              <i data-lucide="download"></i>
              <span>Download Anomalies CSV</span>
            </button>
          </div>

        </div>
      </section>

      <!-- ═════════════════ TAB 10: AUDIT LOGS ═════════════════ -->
      <section id="view-audit" style="display: none;">
        <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 14px; padding: 22px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div>
              <h3 style="font-size: 15px; font-weight: 700;">Immutable Administrative Audit Trail</h3>
              <p style="font-size: 12px; color: var(--text-muted);">Cryptographically signed records of all administrative modifications, corrections, and approvals.</p>
            </div>
            <button class="btn btn-outline btn-sm" onclick="loadAuditLogs()">
              <i data-lucide="refresh-cw"></i>
              <span>Refresh Trail</span>
            </button>
          </div>

          <table class="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Administrator</th>
                <th>Action</th>
                <th>Target</th>
                <th>Mandatory Reason</th>
                <th>Audit Diff</th>
              </tr>
            </thead>
            <tbody id="table-audit-body">
              <tr><td colspan="6" style="text-align: center; padding: 30px;">Loading audit logs...</td></tr>
            </tbody>
          </table>
        </div>
      </section>

    </div>
  </main>

  <!-- ─── Modals ───────────────────────────────────────────────────────────── -->

  <!-- Add Employee Modal -->
  <div class="modal-backdrop" id="modal-add-employee">
    <div class="modal-card">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
        <h3 style="font-size: 16px; font-weight: 700;">Add New Employee</h3>
        <button onclick="closeModal('modal-add-employee')" style="background: transparent; border: none; font-size: 20px; cursor: pointer;">&times;</button>
      </div>
      <form onsubmit="handleCreateEmployee(event)" style="padding: 24px;">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <label class="form-label">Employee Number *</label>
            <input type="number" id="inp-emp-no" class="form-control" required placeholder="e.g. 2501">
          </div>
          <div class="form-group">
            <label class="form-label">Full Name *</label>
            <input type="text" id="inp-emp-name" class="form-control" required placeholder="e.g. Ramesh Kumar">
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <label class="form-label">Official Email</label>
            <input type="email" id="inp-emp-email" class="form-control" placeholder="name@monarch.com">
          </div>
          <div class="form-group">
            <label class="form-label">Mobile Number</label>
            <input type="tel" id="inp-emp-phone" class="form-control" placeholder="9876543210">
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <label class="form-label">Department</label>
            <input type="text" id="inp-emp-dept" class="form-control" placeholder="IT Department">
          </div>
          <div class="form-group">
            <label class="form-label">Designation</label>
            <input type="text" id="inp-emp-desig" class="form-control" placeholder="Engineer">
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <label class="form-label">Reporting Manager</label>
            <select id="inp-emp-mgr" class="form-control">
              <option value="">-- Select Reporting Manager --</option>
              <option value="Direct Management">Direct Management</option>
            </select>
            <input type="text" id="inp-emp-mgr-custom" class="form-control" placeholder="Type new manager name..." style="display: none; margin-top: 6px;">
          </div>
          <div class="form-group">
            <label class="form-label">Joining Date</label>
            <input type="date" id="inp-emp-doj" class="form-control">
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <label class="form-label">Shift Timing</label>
            <select id="inp-emp-shift" class="form-control">
              <option value="09:30 AM - 06:30 PM">General Shift (09:30 AM - 06:30 PM)</option>
              <option value="07:00 AM - 03:30 PM">Morning Shift (07:00 AM - 03:30 PM)</option>
              <option value="02:00 PM - 10:30 PM">Evening Shift (02:00 PM - 10:30 PM)</option>
              <option value="10:00 PM - 06:30 AM">Night Shift (10:00 PM - 06:30 AM)</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Role</label>
            <select id="inp-emp-role" class="form-control">
              <option value="employee">Employee</option>
              <option value="teamleader">Team Leader</option>
              <option value="manager">Manager</option>
              <option value="admin">Administrator</option>
            </select>
          </div>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px;">
          <button type="button" class="btn btn-outline" onclick="closeModal('modal-add-employee')">Cancel</button>
          <button type="submit" class="btn btn-primary">Create Employee Profile</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Edit Employee Modal -->
  <div class="modal-backdrop" id="modal-edit-employee">
    <div class="modal-card" style="max-width: 680px; width: 100%;">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
        <div>
          <h3 style="font-size: 16px; font-weight: 700; color: #0F172A; margin: 0;">✏️ Edit Employee Profile</h3>
          <p style="font-size: 11.5px; color: var(--text-muted); margin: 3px 0 0 0;">Update reporting manager, designation, department, contact, and system access</p>
        </div>
        <button onclick="closeModal('modal-edit-employee')" style="background: transparent; border: none; font-size: 22px; cursor: pointer; color: #64748B;">&times;</button>
      </div>
      <form onsubmit="handleEditEmployeeSubmit(event)" style="padding: 24px;">
        <input type="hidden" id="edit-emp-id">

        <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 14px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Employee ID</label>
            <input type="text" id="edit-emp-no" class="form-control" readonly style="background: #F1F5F9; font-weight: 700; color: #0F172A;">
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Full Name *</label>
            <input type="text" id="edit-emp-name" class="form-control" required placeholder="Employee Full Name">
          </div>
        </div>

        <!-- Reporting Manager (Prominent Section) -->
        <div style="background: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 10px; padding: 14px 16px; margin-bottom: 14px;">
          <label class="form-label" style="font-weight: 700; color: #1E40AF; margin-bottom: 6px; display: flex; justify-content: space-between;">
            <span>👤 Direct Reporting Manager *</span>
            <span style="font-size: 11px; font-weight: 500; color: #3B82F6;">Controls Leave &amp; Attendance Approvals</span>
          </label>
          <select id="edit-emp-mgr" class="form-control" style="font-size: 13.5px; font-weight: 600; border-color: #93C5FD;">
            <option value="">-- Select Reporting Manager --</option>
            <option value="Direct Management">Direct Management</option>
          </select>
          <input type="text" id="edit-emp-mgr-custom" class="form-control" placeholder="Type new reporting manager's full name..." style="display: none; margin-top: 8px; border-color: #93C5FD;">
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Department</label>
            <input type="text" id="edit-emp-dept" class="form-control" placeholder="e.g. Projects, Railway, HR">
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Designation</label>
            <input type="text" id="edit-emp-desig" class="form-control" placeholder="e.g. Senior Engineer">
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Mobile Number</label>
            <input type="tel" id="edit-emp-phone" class="form-control" placeholder="10-digit mobile number">
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Email Address</label>
            <input type="email" id="edit-emp-email" class="form-control" placeholder="email@monarchpune.in">
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Date of Joining</label>
            <input type="date" id="edit-emp-doj" class="form-control">
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Gender</label>
            <select id="edit-emp-gender" class="form-control">
              <option value="Male">Male</option>
              <option value="Female">Female</option>
              <option value="Other">Other</option>
            </select>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Location / Base</label>
            <input type="text" id="edit-emp-location" class="form-control" placeholder="Pune, Mumbai, etc.">
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Shift Timing</label>
            <select id="edit-emp-shift" class="form-control">
              <option value="General- 9.30 Am To 6.30 Pm">General- 9.30 Am To 6.30 Pm</option>
              <option value="09:30 AM - 06:30 PM">09:30 AM - 06:30 PM</option>
              <option value="07:00 AM - 03:30 PM">Morning Shift (07:00 AM - 03:30 PM)</option>
              <option value="02:00 PM - 10:30 PM">Evening Shift (02:00 PM - 10:30 PM)</option>
              <option value="10:00 PM - 06:30 AM">Night Shift (10:00 PM - 06:30 AM)</option>
            </select>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Weekly Off</label>
            <select id="edit-emp-weekly-off" class="form-control">
              <option value="Sunday">Sunday</option>
              <option value="Saturday">Saturday</option>
              <option value="Monday">Monday</option>
              <option value="Tuesday">Tuesday</option>
              <option value="Wednesday">Wednesday</option>
              <option value="Thursday">Thursday</option>
              <option value="Friday">Friday</option>
            </select>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">System Role</label>
            <select id="edit-emp-role" class="form-control">
              <option value="employee">Employee</option>
              <option value="teamleader">Team Leader</option>
              <option value="seniorteamleader">Senior Team Leader</option>
              <option value="manager">Manager</option>
              <option value="hr">HR</option>
              <option value="admin">Administrator</option>
            </select>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Employment Status</label>
            <select id="edit-emp-status" class="form-control">
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
              <option value="Probation">Probation</option>
              <option value="Consultant">Consultant</option>
              <option value="Intern">Intern</option>
              <option value="Resigned">Resigned</option>
            </select>
          </div>
        </div>

        <div class="form-group" style="margin-bottom: 14px;">
          <label class="form-label">Reset Password (Optional)</label>
          <input type="password" id="edit-emp-password" class="form-control" placeholder="Leave empty to retain current password">
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">Only enter a new password if the employee needs their password reset.</div>
        </div>

        <div class="form-group">
          <label class="form-label" style="color: #475569;">Reason for Modification</label>
          <input type="text" id="edit-emp-reason" class="form-control" placeholder="e.g. Reporting manager change, promotion, phone update">
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--border);">
          <button type="button" class="btn btn-outline" onclick="closeModal('modal-edit-employee')">Cancel</button>
          <button type="submit" class="btn btn-primary" id="btn-edit-emp-save">Save Changes</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Upload Weekly Master Excel Modal -->
  <div class="modal-backdrop" id="modal-upload-excel">
    <div class="modal-card" style="max-width: 860px; max-height: 92vh;">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: linear-gradient(135deg, #F0FDF4 0%, #FFFFFF 100%);">
        <div style="display: flex; align-items: center; gap: 12px;">
          <div style="width: 40px; height: 40px; border-radius: 10px; background: #DCFCE7; color: #15803D; display: flex; align-items: center; justify-content: center;">
            <i data-lucide="file-spreadsheet" style="width: 22px; height: 22px;"></i>
          </div>
          <div>
            <h3 style="font-size: 16px; font-weight: 700; color: #0F172A; margin: 0;">Upload Weekly Master Excel</h3>
            <p style="font-size: 12px; color: #64748B; margin: 2px 0 0 0;">Add new staff only. All existing staff records remain 100% untouched.</p>
          </div>
        </div>
        <button onclick="closeModal('modal-upload-excel')" style="background: transparent; border: none; font-size: 22px; cursor: pointer; color: #64748B;">&times;</button>
      </div>

      <div style="padding: 24px;">
        <!-- Step 1: File Selection -->
        <div id="excel-initial-step">
          <input type="file" id="excel-file-input" accept=".xlsx, .xls" style="display: none;" onchange="handleExcelFileChange(event)">
          <div onclick="document.getElementById('excel-file-input').click()" style="border: 2px dashed #86EFAC; background: #F0FDF4; border-radius: 12px; padding: 28px; text-align: center; cursor: pointer; transition: all 0.2s ease;">
            <div style="width: 50px; height: 50px; margin: 0 auto 10px; border-radius: 50%; background: #DCFCE7; color: #15803D; display: flex; align-items: center; justify-content: center;">
              <i data-lucide="upload-cloud" style="width: 26px; height: 26px;"></i>
            </div>
            <div style="font-size: 14.5px; font-weight: 700; color: #166534; margin-bottom: 4px;">Click to Choose Weekly Excel File</div>
            <div style="font-size: 12px; color: #475569; margin-bottom: 12px;">Supports standard format: <code>Employee Master Details Till [Date].xlsx</code></div>
            <div id="excel-filename-display" style="display: inline-block; padding: 6px 14px; background: #FFFFFF; border: 1px solid #BBF7D0; border-radius: 20px; font-size: 12.5px; color: #15803D;">No file chosen</div>
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px;">
            <button type="button" class="btn btn-outline" onclick="closeModal('modal-upload-excel')">Cancel</button>
            <button type="button" class="btn btn-primary" id="excel-upload-btn-scan" disabled onclick="handleExcelPreviewUpload()" style="background: #10B981; border-color: #059669;">
              <i data-lucide="scan-line" style="width: 14px; height: 14px;"></i>
              <span>Scan &amp; Map Employees</span>
            </button>
          </div>
        </div>

        <!-- Step 2: Preview & Comparison Metrics -->
        <div id="excel-preview-step" style="display: none; margin-top: 18px; border-top: 1px solid var(--border); padding-top: 20px;">
          <!-- KPI Summary Cards -->
          <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px;">
            <div style="background: #F0FDF4; border: 1.5px solid #86EFAC; border-radius: 10px; padding: 14px 12px; text-align: center;">
              <div style="font-size: 11px; font-weight: 700; color: #15803D; text-transform: uppercase; letter-spacing: 0.5px;">New Employees</div>
              <div id="excel-stat-new-count" style="font-size: 24px; font-weight: 800; color: #166534; margin: 4px 0;">0</div>
              <div style="font-size: 11px; color: #15803D;">Will be added</div>
            </div>

            <div style="background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 10px; padding: 14px 12px; text-align: center;">
              <div style="font-size: 11px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.5px;">Existing Untouched</div>
              <div id="excel-stat-skipped-count" style="font-size: 24px; font-weight: 800; color: #334155; margin: 4px 0;">0</div>
              <div style="font-size: 11px; color: #64748B;">Already in DB</div>
            </div>

            <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 14px 12px; text-align: center;">
              <div style="font-size: 11px; font-weight: 700; color: #64748B; text-transform: uppercase; letter-spacing: 0.5px;">Current in DB</div>
              <div id="excel-stat-current-count" style="font-size: 24px; font-weight: 800; color: #0F172A; margin: 4px 0;">0</div>
              <div style="font-size: 11px; color: #64748B;">Active Users</div>
            </div>

            <div style="background: #EFF6FF; border: 1.5px solid #93C5FD; border-radius: 10px; padding: 14px 12px; text-align: center;">
              <div style="font-size: 11px; font-weight: 700; color: #1D4ED8; text-transform: uppercase; letter-spacing: 0.5px;">Total After Adding</div>
              <div id="excel-stat-total-after" style="font-size: 24px; font-weight: 800; color: #1E40AF; margin: 4px 0;">0</div>
              <div style="font-size: 11px; color: #2563EB;">New Total Users</div>
            </div>
          </div>

          <!-- Informational Banner -->
          <div id="excel-status-banner" style="margin-bottom: 16px; padding: 12px 16px; font-size: 13px; border-radius: 8px;"></div>

          <!-- Preview Table -->
          <div style="background: #FFFFFF; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 20px;">
            <div style="padding: 10px 14px; background: #F8FAFC; border-bottom: 1px solid var(--border); font-size: 12px; font-weight: 700; color: #475569; display: flex; justify-content: space-between; align-items: center;">
              <span>New Employees Staged for Addition</span>
              <span style="font-size: 11px; font-weight: normal; color: #64748B;">Review details before confirming</span>
            </div>
            <div style="max-height: 250px; overflow-y: auto;">
              <table class="data-table" style="font-size: 12.5px; width: 100%;">
                <thead>
                  <tr style="position: sticky; top: 0; background: #FFFFFF; z-index: 1;">
                    <th>Emp ID</th>
                    <th>Name</th>
                    <th>Department</th>
                    <th>Designation</th>
                    <th>Reporting Manager</th>
                    <th>DOJ</th>
                    <th>Shift</th>
                  </tr>
                </thead>
                <tbody id="excel-preview-table-body">
                </tbody>
              </table>
            </div>
          </div>

          <!-- Step 2 Actions -->
          <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--border); padding-top: 16px;">
            <button type="button" class="btn btn-outline" onclick="resetUploadExcelModal()">
              <i data-lucide="refresh-cw" style="width: 14px; height: 14px;"></i>
              <span>Choose Another File</span>
            </button>
            <div style="display: flex; gap: 10px;">
              <button type="button" class="btn btn-outline" onclick="closeModal('modal-upload-excel')">Cancel</button>
              <button type="button" class="btn btn-primary" id="btn-confirm-excel-import" onclick="confirmExcelImport()" style="background: #10B981; border-color: #059669; font-weight: 700;">
                <i data-lucide="user-plus" style="width: 14px; height: 14px;"></i>
                <span>Confirm &amp; Add New Employees</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Correct Punch Modal -->
  <div class="modal-backdrop" id="modal-correct-punch">
    <div class="modal-card">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
        <h3 style="font-size: 16px; font-weight: 700;">Correct Attendance Record</h3>
        <button onclick="closeModal('modal-correct-punch')" style="background: transparent; border: none; font-size: 20px; cursor: pointer;">&times;</button>
      </div>
      <form onsubmit="handleCorrectPunchSubmit(event)" style="padding: 24px;">
        <input type="hidden" id="corr-record-id">
        <div class="form-group">
          <label class="form-label">Employee</label>
          <input type="text" id="corr-emp-name" class="form-control" readonly style="background: #F8FAFC;">
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
              <label class="form-label" style="margin-bottom: 0;">Correct Clock-In Time</label>
              <button type="button" class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 2px 7px; color: #DC2626; border-color: #FECACA; background: #FEF2F2;" onclick="clearPunchField('corr-sign-in')">
                ✕ Clear (NULL)
              </button>
            </div>
            <input type="time" step="1" id="corr-sign-in" class="form-control">
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">
              Leave blank or click <b>Clear</b> to set to NULL.
            </div>
          </div>
          <div class="form-group">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
              <label class="form-label" style="margin-bottom: 0;">Correct Clock-Out Time</label>
              <button type="button" class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 2px 7px; color: #DC2626; border-color: #FECACA; background: #FEF2F2;" onclick="clearPunchField('corr-sign-out')">
                ✕ Clear (NULL)
              </button>
            </div>
            <input type="time" step="1" id="corr-sign-out" class="form-control">
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">
              Leave blank or click <b>Clear</b> to set to NULL.
            </div>
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Approval Status</label>
          <select id="corr-approval-status" class="form-control">
            <option value="Approved">Approved</option>
            <option value="Pending Review">Pending Review</option>
            <option value="Rejected">Rejected</option>
          </select>
        </div>

        <div class="form-group">
          <label class="form-label" style="color: #DC2626;">Mandatory Administrative Reason *</label>
          <textarea id="corr-reason" class="form-control" rows="3" required placeholder="Explain why this correction is being applied (Recorded in immutable audit log)..."></textarea>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px;">
          <button type="button" class="btn btn-outline" onclick="closeModal('modal-correct-punch')">Cancel</button>
          <button type="submit" class="btn btn-primary">Save & Audit Correction</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Manual Punch Modal -->
  <div class="modal-backdrop" id="modal-manual-punch">
    <div class="modal-card">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
        <h3 style="font-size: 16px; font-weight: 700;">Record Missing Attendance Punch</h3>
        <button onclick="closeModal('modal-manual-punch')" style="background: transparent; border: none; font-size: 20px; cursor: pointer;">&times;</button>
      </div>
      <form onsubmit="handleManualPunchSubmit(event)" style="padding: 24px;">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <label class="form-label">Employee ID *</label>
            <input type="text" id="man-emp-id" class="form-control" required placeholder="e.g. 1009">
          </div>
          <div class="form-group">
            <label class="form-label">Date *</label>
            <input type="date" id="man-date" class="form-control" required>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <label class="form-label">Clock In Time</label>
            <input type="time" step="1" id="man-sign-in" class="form-control" value="09:30:00">
          </div>
          <div class="form-group">
            <label class="form-label">Clock Out Time</label>
            <input type="time" step="1" id="man-sign-out" class="form-control" value="18:30:00">
          </div>
        </div>

        <div class="form-group">
          <label class="form-label" style="color: #DC2626;">Mandatory Administrative Reason *</label>
          <textarea id="man-reason" class="form-control" rows="3" required placeholder="Explain why manual attendance is being registered (Biometric network outage, field duty, etc.)..."></textarea>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px;">
          <button type="button" class="btn btn-outline" onclick="closeModal('modal-manual-punch')">Cancel</button>
          <button type="submit" class="btn btn-primary">Submit Manual Attendance</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Review Leave Modal -->
  <div class="modal-backdrop" id="modal-review-leave">
    <div class="modal-card">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
        <h3 style="font-size: 16px; font-weight: 700;">Review Leave Application</h3>
        <button onclick="closeModal('modal-review-leave')" style="background: transparent; border: none; font-size: 20px; cursor: pointer;">&times;</button>
      </div>
      <form onsubmit="handleLeaveReviewSubmit(event)" style="padding: 24px;">
        <input type="hidden" id="rev-leave-id">
        <input type="hidden" id="rev-leave-action">

        <div style="padding: 14px; background: #F8FAFC; border-radius: 10px; margin-bottom: 16px;">
          <div style="font-size: 14px; font-weight: 700;" id="rev-emp-name">Employee Name</div>
          <div style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;" id="rev-leave-details">Period details...</div>
        </div>

        <div class="form-group">
          <label class="form-label" style="color: #DC2626;">Administrative Comment / Reason *</label>
          <textarea id="rev-leave-reason" class="form-control" rows="3" required placeholder="Mandatory comment explaining the approval or rejection..."></textarea>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button type="button" class="btn btn-outline" onclick="closeModal('modal-review-leave')">Cancel</button>
          <button type="submit" class="btn btn-primary" id="rev-submit-btn">Confirm Decision</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Adjust Leave Quota Modal -->
  <div class="modal-backdrop" id="modal-adjust-leave-quota">
    <div class="modal-card" style="max-width: 520px;">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: linear-gradient(135deg, #F8FAFC 0%, #FFFFFF 100%);">
        <div style="display: flex; align-items: center; gap: 12px;">
          <div style="width: 38px; height: 38px; border-radius: 10px; background: #FEF3C7; color: #D97706; display: flex; align-items: center; justify-content: center;">
            <i data-lucide="sliders" style="width: 20px; height: 20px;"></i>
          </div>
          <div>
            <h3 style="font-size: 16px; font-weight: 700; color: #0F172A; margin: 0;">Adjust Leave Quota</h3>
            <p style="font-size: 12px; color: var(--text-muted); margin: 2px 0 0 0;">Modify allocated days, used days, and balance</p>
          </div>
        </div>
        <button onclick="closeModal('modal-adjust-leave-quota')" style="background: transparent; border: none; font-size: 22px; cursor: pointer; color: #64748B;">&times;</button>
      </div>

      <form onsubmit="handleAdjustQuotaSubmit(event)" style="padding: 24px;">
        <input type="hidden" id="adj-emp-id">

        <!-- Employee Summary Card -->
        <div style="padding: 14px 16px; background: #F8FAFC; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 18px; display: flex; align-items: center; justify-content: space-between;">
          <div>
            <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">Employee</div>
            <div style="font-size: 14.5px; font-weight: 700; color: #0F172A;" id="adj-emp-name">Employee Name</div>
            <div style="font-size: 12px; color: #64748B;" id="adj-emp-id-badge">ID: #0</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">Current Balance</div>
            <div style="font-size: 16px; font-weight: 800; color: #10B981;" id="adj-current-remaining">6.0 Days</div>
          </div>
        </div>

        <!-- Quota Inputs -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="font-weight: 600;">Total Allotted Days *</label>
            <input type="number" step="0.5" min="0" id="adj-total-allotted" class="form-control" required placeholder="e.g. 6.0" oninput="calculateAdjustRemaining()">
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="font-weight: 600;">Used / Consumed Days *</label>
            <input type="number" step="0.5" min="0" id="adj-used-days" class="form-control" required placeholder="e.g. 0.0" oninput="calculateAdjustRemaining()">
          </div>
        </div>

        <!-- Real-Time Calculated Remaining Balance Preview -->
        <div style="background: #F0FDF4; border: 1.5px solid #BBF7D0; border-radius: 10px; padding: 12px 16px; margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <i data-lucide="check-circle" style="width: 18px; height: 18px; color: #16A34A;"></i>
            <span style="font-size: 13px; font-weight: 600; color: #166534;">Calculated Remaining Quota:</span>
          </div>
          <div id="adj-remaining-calc" style="font-size: 16px; font-weight: 800; color: #15803D;">6.0 Days</div>
        </div>

        <!-- Mandatory Audit Reason -->
        <div class="form-group" style="margin-bottom: 20px;">
          <label class="form-label" style="font-weight: 600; color: #0F172A;">
            <span>Reason for Quota Adjustment *</span>
            <span style="font-size: 11px; font-weight: 500; color: #DC2626; margin-left: 4px;">(Mandatory Audit Log)</span>
          </label>
          <textarea id="adj-reason" class="form-control" rows="2" required placeholder="e.g. Annual quota carryover, policy update, manual correction..."></textarea>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">
            This adjustment and explanation will be permanently recorded in the immutable audit trail.
          </div>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid var(--border); padding-top: 16px;">
          <button type="button" class="btn btn-outline" onclick="closeModal('modal-adjust-leave-quota')">Cancel</button>
          <button type="submit" class="btn btn-primary" id="btn-save-quota-adj" style="background: #10B981; border-color: #059669; font-weight: 600;">
            <i data-lucide="check" style="width: 14px; height: 14px;"></i>
            <span>Save Quota Changes</span>
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- Add Holiday Modal -->
  <div class="modal-backdrop" id="modal-add-holiday">
    <div class="modal-card" style="max-width: 500px;">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: linear-gradient(135deg, #EFF6FF 0%, #FFFFFF 100%);">
        <div style="display: flex; align-items: center; gap: 12px;">
          <div style="width: 38px; height: 38px; border-radius: 10px; background: #DBEAFE; color: #2563EB; display: flex; align-items: center; justify-content: center;">
            <i data-lucide="calendar-plus" style="width: 20px; height: 20px;"></i>
          </div>
          <div>
            <h3 style="font-size: 16px; font-weight: 700; color: #0F172A; margin: 0;">Add Company Holiday</h3>
            <p style="font-size: 12px; color: var(--text-muted); margin: 2px 0 0 0;">Declare a new paid public holiday for the calendar</p>
          </div>
        </div>
        <button onclick="closeModal('modal-add-holiday')" style="background: transparent; border: none; font-size: 22px; cursor: pointer; color: #64748B;">&times;</button>
      </div>

      <form onsubmit="handleAddHolidaySubmit(event)" style="padding: 24px;">
        <div class="form-group" style="margin-bottom: 16px;">
          <label class="form-label" style="font-weight: 600;">Holiday Title *</label>
          <input type="text" id="inp-holiday-title" class="form-control" required placeholder="e.g. Diwali / Republic Day / Eid">
        </div>

        <div style="display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; margin-bottom: 16px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="font-weight: 600;">Holiday Date *</label>
            <input type="date" id="inp-holiday-date" class="form-control" required onchange="handleHolidayDateChange(event)">
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="font-weight: 600;">Day of Week</label>
            <input type="text" id="inp-holiday-weekday" class="form-control" readonly placeholder="e.g. Sunday" style="background: #F8FAFC; font-weight: 600; color: #1E293B;">
          </div>
        </div>

        <div class="form-group" style="margin-bottom: 22px;">
          <label class="form-label" style="font-weight: 600;">Holiday Type</label>
          <select id="inp-holiday-type" class="form-control">
            <option value="Paid Public Holiday">Paid Public Holiday</option>
            <option value="Gazetted Holiday">Gazetted Holiday</option>
            <option value="Restricted / Optional Holiday">Restricted / Optional Holiday</option>
          </select>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">
            This will be visible on employee mobile apps and company attendance calendars.
          </div>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid var(--border); padding-top: 16px;">
          <button type="button" class="btn btn-outline" onclick="closeModal('modal-add-holiday')">Cancel</button>
          <button type="submit" class="btn btn-primary" id="btn-save-holiday" style="background: #2563EB; border-color: #1D4ED8; font-weight: 600;">
            <i data-lucide="plus" style="width: 14px; height: 14px;"></i>
            <span>Add Holiday</span>
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- Leave Approval Flow & Hierarchy Modal -->
  <div class="modal-backdrop" id="modal-approval-flow">
    <div class="modal-card" style="max-width: 620px;">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
        <div>
          <h3 style="font-size: 16px; font-weight: 800; color: #0F172A; margin: 0;">Leave Approval Routing & Hierarchy</h3>
          <p style="font-size: 12px; color: var(--text-muted); margin: 3px 0 0 0;">End-to-end multi-level approval pipeline</p>
        </div>
        <button onclick="closeModal('modal-approval-flow')" style="background: transparent; border: none; font-size: 22px; cursor: pointer; color: #64748B;">&times;</button>
      </div>

      <div style="padding: 24px;">
        <!-- Employee & Leave Summary Card -->
        <div style="padding: 16px; background: #F8FAFC; border: 1px solid var(--border); border-radius: 12px; margin-bottom: 22px;">
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div>
              <div style="font-size: 15px; font-weight: 800; color: #0F172A;" id="flow-emp-name">Employee Name</div>
              <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;" id="flow-emp-sub">Emp # • Dept • Designation</div>
            </div>
            <div id="flow-status-pill"></div>
          </div>
          <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid #E2E8F0; display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px;">
            <div><span style="color: var(--text-muted);">Leave Type:</span> <b id="flow-leave-type">Annual</b></div>
            <div><span style="color: var(--text-muted);">Period:</span> <b id="flow-leave-period">Oct 12 - Oct 14 (3 days)</b></div>
            <div><span style="color: var(--text-muted);">Applied On:</span> <b id="flow-applied-date">2026-10-12</b></div>
          </div>
          <div style="margin-top: 8px; font-size: 12px; color: #475569;" id="flow-leave-reason">Reason: ...</div>
        </div>

        <!-- Vertical Stepper Timeline -->
        <div style="position: relative; padding-left: 6px; margin-bottom: 20px;" id="flow-stepper-steps">
          <!-- Dynamically populated by renderApprovalFlowSteps() -->
        </div>

        <!-- Admin Quick Actions inside Modal -->
        <!-- Sole Reporting Manager Authority Notice -->
        <div id="flow-admin-actions" style="border-top: 1px solid var(--border); padding-top: 18px; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
          <div style="font-size: 11.5px; color: #475569; max-width: 440px; display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 15px;">🔒</span>
            <span><b>Approval Policy:</b> Direct Reporting Managers, Admin &amp; HR have authorization to review, approve, or reject employee leave requests and attendance adjustments.</span>
          </div>
          <div style="display: flex; gap: 8px;" id="flow-action-buttons">
            <button type="button" class="btn btn-outline btn-sm" onclick="closeModal('modal-approval-flow')">Close</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Apply on Behalf Modal -->
  <div class="modal-backdrop" id="modal-apply-behalf">
    <div class="modal-card" style="max-width: 580px; width: 100%;">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
        <div>
          <h3 style="font-size: 16px; font-weight: 700; color: #0F172A; margin: 0;">Apply Leave on Behalf of Staff</h3>
          <p style="font-size: 11.5px; color: var(--text-muted); margin: 3px 0 0 0;">Admin &amp; HR direct authorized leave grant &amp; attendance recording</p>
        </div>
        <button onclick="closeModal('modal-apply-behalf')" style="background: transparent; border: none; font-size: 22px; cursor: pointer; color: #64748B;">&times;</button>
      </div>
      <form onsubmit="handleApplyOnBehalfSubmit(event)" style="padding: 24px;">
        <!-- Employee Selector (Searchable Dropdown with ID & Name) -->
        <div class="form-group" style="margin-bottom: 16px;">
          <label class="form-label" style="display: flex; justify-content: space-between; align-items: center;">
            <span>Select Staff Member (ID &amp; Name) *</span>
            <span id="beh-emp-count" style="font-size: 11px; color: var(--text-muted); font-weight: 500;"></span>
          </label>
          <div style="position: relative;">
            <input type="text" id="beh-emp-filter" class="form-control" placeholder="🔍 Type ID or Name to filter staff (e.g. 1209)..." oninput="filterBehalfEmployees()" style="margin-bottom: 6px; font-size: 13px;">
            <select id="beh-emp-select" class="form-control" required onchange="onBehalfEmployeeSelected()" size="5" style="height: 120px; font-size: 13px; font-family: inherit;">
              <option value="" disabled selected>-- Loading staff directory... --</option>
            </select>
          </div>
          <div id="beh-selected-card" style="display: none; margin-top: 8px; padding: 10px 14px; background: #F1F5F9; border: 1px solid #CBD5E1; border-radius: 8px; font-size: 12.5px; color: #1E293B;">
            <!-- Rendered employee badge -->
          </div>
          <input type="hidden" id="beh-emp-id" required>
        </div>

        <!-- Leave Type & Duration Type (Full Day vs Half Day) -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Leave Category</label>
            <select id="beh-leave-type" class="form-control">
              <option value="Casual Leave">Casual Leave (CL)</option>
              <option value="Sick Leave">Sick Leave (SL)</option>
              <option value="Earned Leave">Earned Leave (EL)</option>
              <option value="Leave Without Pay">Leave Without Pay (LWP)</option>
              <option value="Compensatory Off">Compensatory Off</option>
            </select>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Days Count</label>
            <input type="number" step="0.5" id="beh-days" class="form-control" value="1.0" required>
          </div>
        </div>

        <!-- Half Day Toggle & Session Selection Card -->
        <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 12px 16px; margin-bottom: 16px;">
          <label class="form-label" style="font-weight: 700; color: #1E293B; margin-bottom: 8px; display: block;">Leave Duration</label>
          <div style="display: flex; gap: 20px; align-items: center; margin-bottom: 8px;">
            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; font-weight: 600; color: #334155;">
              <input type="radio" name="beh-duration-type" id="beh-type-full" value="full" checked onchange="onBehalfDurationChanged()">
              <span>Full Day</span>
            </label>
            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; font-weight: 600; color: #334155;">
              <input type="radio" name="beh-duration-type" id="beh-type-half" value="half" onchange="onBehalfDurationChanged()">
              <span>Half Day (0.5 Day)</span>
            </label>
          </div>

          <!-- Session 1 / Session 2 Selection (Appears when Half Day is selected) -->
          <div id="beh-session-container" style="display: none; padding-top: 10px; border-top: 1px dashed #CBD5E1;">
            <label class="form-label" style="font-weight: 700; color: #1E293B; margin-bottom: 8px; font-size: 12px;">Select Half Day Session *</label>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <label id="beh-label-sess1" style="display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border: 1.5px solid #2563EB; background: #EFF6FF; border-radius: 8px; cursor: pointer;">
                <input type="radio" name="beh-session" id="beh-sess-1" value="Session 1" checked onchange="updateBehalfSessionStyles()" style="margin-top: 3px;">
                <div>
                  <div style="font-size: 12.5px; font-weight: 700; color: #1E40AF;">Session 1</div>
                  <div style="font-size: 11px; color: #64748B;">Morning / First Half<br>(09:30 AM - 01:30 PM)</div>
                </div>
              </label>
              <label id="beh-label-sess2" style="display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border: 1.5px solid #E2E8F0; background: #FFFFFF; border-radius: 8px; cursor: pointer;">
                <input type="radio" name="beh-session" id="beh-sess-2" value="Session 2" onchange="updateBehalfSessionStyles()" style="margin-top: 3px;">
                <div>
                  <div style="font-size: 12.5px; font-weight: 700; color: #1E40AF;">Session 2</div>
                  <div style="font-size: 11px; color: #64748B;">Afternoon / Second Half<br>(01:31 PM - 06:30 PM)</div>
                </div>
              </label>
            </div>
          </div>
        </div>

        <!-- Date Range -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Start Date *</label>
            <input type="date" id="beh-start-date" class="form-control" required onchange="onBehalfDateChanged()">
          </div>
          <div class="form-group" id="beh-end-date-group" style="margin-bottom: 0;">
            <label class="form-label">End Date *</label>
            <input type="date" id="beh-end-date" class="form-control" required onchange="onBehalfDateChanged()">
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Mandatory Administrative Reason *</label>
          <textarea id="beh-reason" class="form-control" rows="3" required placeholder="Authorized reason for submitting leave on behalf of employee (e.g. Approved leave request, site emergency)..."></textarea>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button type="button" class="btn btn-outline" onclick="closeModal('modal-apply-behalf')">Cancel</button>
          <button type="submit" class="btn btn-primary" id="btn-beh-submit">Apply & Approve Leave</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Employee 360 Profile Modal -->
  <div class="modal-backdrop" id="modal-employee-360">
    <div class="modal-card" style="max-width: 750px;">
      <div style="padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between;">
        <h3 style="font-size: 16px; font-weight: 700;">Employee 360° Operations Profile</h3>
        <button onclick="closeModal('modal-employee-360')" style="background: transparent; border: none; font-size: 20px; cursor: pointer;">&times;</button>
      </div>
      <div style="padding: 24px;" id="emp-360-content">
        Loading complete employee profile...
      </div>
    </div>
  </div>

  <!-- ═════════════════ DEDICATED FULL-SCREEN LOGIN PAGE ═════════════════ -->
  <div id="login-page">
    <!-- Left Hero Pane -->
    <div class="login-hero-pane">
      <div>
        <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 24px;">
          <div style="width: 50px; height: 50px; border-radius: 12px; background: var(--primary); display: flex; align-items: center; justify-content: center; color: #0F172A; font-weight: 900; font-size: 24px; box-shadow: 0 4px 14px rgba(235, 142, 39, 0.45);">
            M
          </div>
          <div>
            <div style="font-size: 22px; font-weight: 800; color: #FFFFFF; letter-spacing: -0.3px;">Monarch HR</div>
            <div style="font-size: 11px; color: #F5A952; font-weight: 700; letter-spacing: 0.8px;">ENTERPRISE OPERATIONS & HR PORTAL</div>
          </div>
        </div>

        <div style="margin-top: 40px;">
          <span style="background: rgba(235, 142, 39, 0.15); color: #F5A952; border: 1px solid rgba(235, 142, 39, 0.3); border-radius: 20px; padding: 4px 14px; font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">
            Workforce Intelligence & Administration
          </span>
          <h1 style="font-size: 32px; font-weight: 800; color: #FFFFFF; line-height: 1.25; margin: 16px 0 12px 0;">
            Unified Admin Control & Real-Time HR Intelligence
          </h1>
          <p style="font-size: 14px; color: #94A3B8; line-height: 1.6; max-width: 480px;">
            Integrated with 1,000+ employee biometric logs, mobile GPS geofenced clock-ins, multi-level leave approvals, and immutable audit trails.
          </p>
        </div>

        <!-- Capability Pills / Feature List -->
        <div style="display: flex; flex-direction: column; gap: 16px; margin-top: 36px;">
          <div style="display: flex; align-items: center; gap: 12px; color: #CBD5E1; font-size: 13.5px;">
            <div style="width: 28px; height: 28px; border-radius: 8px; background: rgba(16, 185, 129, 0.15); color: #10B981; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px;">✓</div>
            <span><b>Live GPS Tracking Radar:</b> 40m geofence verification with phone punch trails</span>
          </div>
          <div style="display: flex; align-items: center; gap: 12px; color: #CBD5E1; font-size: 13.5px;">
            <div style="width: 28px; height: 28px; border-radius: 8px; background: rgba(59, 130, 246, 0.15); color: #3B82F6; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px;">✓</div>
            <span><b>Approval Routing Engine:</b> Direct reporting manager hierarchy with automated sync</span>
          </div>
          <div style="display: flex; align-items: center; gap: 12px; color: #CBD5E1; font-size: 13.5px;">
            <div style="width: 28px; height: 28px; border-radius: 8px; background: rgba(245, 158, 11, 0.15); color: #F59E0B; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px;">✓</div>
            <span><b>Automated Biometric Sync:</b> Machine punch aggregation across all company branches</span>
          </div>
        </div>
      </div>

      <div style="border-top: 1px solid rgba(255, 255, 255, 0.08); padding-top: 20px; font-size: 11.5px; color: #64748B;">
        Monarch Surveyors & Engineering Consultants Limited • ISO 9001:2015 Certified
      </div>
    </div>

    <!-- Right Form Pane -->
    <div class="login-form-pane">
      <div class="login-box-card">
        <div style="margin-bottom: 24px;">
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
            <span style="font-size: 18px;">🔐</span>
            <h2 style="font-size: 20px; font-weight: 800; color: #0F172A; margin: 0;">Administrator Sign In</h2>
          </div>
          <p style="font-size: 13px; color: #64748B; margin: 0;">Sign in to access your operations & management dashboard</p>
        </div>

        <form id="admin-login-form" onsubmit="handleAdminLogin(event)">
          <div class="form-group">
            <label class="form-label" style="font-weight: 700;">Employee ID / Username</label>
            <div style="position: relative;">
              <input type="text" id="login-identifier" class="form-control" required placeholder="e.g. 1951 or 1228" style="padding-left: 38px; font-weight: 600;">
              <span style="position: absolute; left: 13px; top: 50%; transform: translateY(-50%); font-size: 13px; color: #64748B;">👤</span>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-weight: 700;">Password</label>
            <div style="position: relative;">
              <input type="password" id="login-password" class="form-control" required placeholder="Enter password" style="padding-left: 38px; padding-right: 42px;">
              <span style="position: absolute; left: 13px; top: 50%; transform: translateY(-50%); font-size: 13px; color: #64748B;">🔒</span>
              <button type="button" onclick="togglePasswordVisibility()" style="position: absolute; right: 10px; top: 50%; transform: translateY(-50%); background: transparent; border: none; cursor: pointer; color: #64748B; font-size: 14px; padding: 4px;" title="Show/Hide Password">
                👁️
              </button>
            </div>
          </div>

          <div id="login-error" style="color: #DC2626; background: #FEF2F2; border: 1px solid #FECACA; border-radius: 8px; padding: 10px 12px; font-size: 12.5px; margin-bottom: 16px; display: none; align-items: center; gap: 8px;">
            <span>⚠️</span>
            <span id="login-error-text">Invalid Employee ID or password</span>
          </div>

          <button type="submit" id="btn-login-submit" class="btn btn-primary" style="width: 100%; justify-content: center; padding: 13px; font-size: 14px; font-weight: 700; border-radius: 10px;">
            <span>Authenticate & Access Dashboard ➔</span>
          </button>
        </form>

        <div style="margin-top: 22px; text-align: center; font-size: 11.5px; color: #94A3B8; display: flex; align-items: center; justify-content: center; gap: 6px;">
          <span>🔒</span>
          <span>Secured with 256-Bit Cryptographic JWT Session</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Toast Notification -->
  <div id="toast">
    <i data-lucide="check-circle" style="color: #10B981; width: 18px; height: 18px;"></i>
    <span id="toast-msg">Operation completed successfully.</span>
  </div>

  <!-- ─── Single-Page Application Client Logic ─────────────────────────────── -->
  <script>
    // State
    const state = {
      token: localStorage.getItem('monarch_admin_token') || '',
      user: JSON.parse(localStorage.getItem('monarch_admin_user') || 'null'),
      activeTab: 'dashboard',
      period: 'today',
      empPage: 1,
      attPage: 1,
      dailyKpiFilter: 'all',
      monthlyPage: 1,
      monthlyFilter: 'all',
      chartTrend: null,
      chartDept: null,
      map: null,
      mapMarkers: [],
      mapPolylines: [],
      gpsData: null,
      gpsFilter: 'all'
    };

    // Digital Clock
    setInterval(() => {
      const d = new Date();
      const timeStr = d.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) + ' IST';
      const el = document.getElementById('digital-clock');
      if (el) el.innerText = timeStr;
    }, 1000);

    // Login Screen Controller
    function showLoginPage() {
      const p = document.getElementById('login-page');
      if (p) p.style.display = 'flex';
      const side = document.getElementById('sidebar');
      if (side) side.style.display = 'none';
      const main = document.getElementById('main-content');
      if (main) main.style.display = 'none';
    }

    function hideLoginPage() {
      const p = document.getElementById('login-page');
      if (p) p.style.display = 'none';
      const side = document.getElementById('sidebar');
      if (side) side.style.display = 'flex';
      const main = document.getElementById('main-content');
      if (main) main.style.display = 'flex';
    }

    function togglePasswordVisibility() {
      const inp = document.getElementById('login-password');
      if (!inp) return;
      inp.type = (inp.type === 'password') ? 'text' : 'password';
    }

    // Initializer
    window.addEventListener('DOMContentLoaded', () => {
      lucide.createIcons();
      document.getElementById('att-date-picker').valueAsDate = new Date();
      const gpsDateEl = document.getElementById('gps-date-filter');
      if (gpsDateEl) gpsDateEl.valueAsDate = new Date();

      if (!state.token || !state.user) {
        showLoginPage();
      } else {
        hideLoginPage();
        updateUserInfoDisplay();
        switchTab('dashboard');
      }
    });

    function updateUserInfoDisplay() {
      if (state.user) {
        document.getElementById('sidebar-user-name').innerText = state.user.name || 'Admin User';
        document.getElementById('sidebar-user-role').innerText = (state.user.role || 'Admin').toUpperCase();
        document.getElementById('sidebar-user-avatar').innerText = (state.user.name || 'A')[0].toUpperCase();

        const cleanEid = String(state.user.employee_no || state.user.emp_id || state.user.id || '').trim();
        const isAuditRestricted = (cleanEid === '1844' || cleanEid === '965');
        const auditNav = document.getElementById('nav-item-audit');
        if (auditNav) {
          auditNav.style.display = isAuditRestricted ? 'none' : 'flex';
        }
        const auditView = document.getElementById('view-audit');
        if (auditView && isAuditRestricted) {
          auditView.style.display = 'none';
        }
      }
    }

    async function handleAdminLogin(e) {
      e.preventDefault();
      const id = document.getElementById('login-identifier').value.trim();
      const pw = document.getElementById('login-password').value.trim();
      const errEl = document.getElementById('login-error');
      const errText = document.getElementById('login-error-text');
      const submitBtn = document.getElementById('btn-login-submit');

      errEl.style.display = 'none';
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span>Verifying credentials...</span>';

      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ identifier: id, password: pw, source: 'admin_portal' })
        });
        const d = await res.json();
        if (d.error) {
          errText.innerText = d.error;
          errEl.style.display = 'flex';
        } else {
          state.token = d.token;
          state.user = d.user;
          localStorage.setItem('monarch_admin_token', d.token);
          localStorage.setItem('monarch_admin_user', JSON.stringify(d.user));
          hideLoginPage();
          updateUserInfoDisplay();
          showToast('Welcome back, ' + d.user.name + ' (Admin)');
          switchTab('dashboard');
        }
      } catch (err) {
        errText.innerText = 'Connection error to backend server';
        errEl.style.display = 'flex';
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span>Authenticate & Access Dashboard ➔</span>';
      }
    }

    function handleLogout() {
      if (confirm('Sign out from Monarch HR Operations Dashboard?')) {
        localStorage.removeItem('monarch_admin_token');
        localStorage.removeItem('monarch_admin_user');
        state.token = '';
        state.user = null;
        showLoginPage();
      }
    }

    // Tab Switching
    function switchTab(tabId) {
      const cleanEid = String((state.user && (state.user.employee_no || state.user.emp_id || state.user.id)) || '').trim();
      const isAuditRestricted = (cleanEid === '1844' || cleanEid === '965');
      if (tabId === 'audit' && isAuditRestricted) {
        showToast('Access to Audit Logs Trail is restricted for this account.', true);
        return switchTab('dashboard');
      }

      state.activeTab = tabId;
      document.querySelectorAll('#sidebar .nav-item').forEach(el => el.classList.remove('active'));
      const activeNav = Array.from(document.querySelectorAll('#sidebar .nav-item')).find(el => el.getAttribute('onclick') && el.getAttribute('onclick').includes(tabId));
      if (activeNav) activeNav.classList.add('active');

      const tabs = ['dashboard', 'employees', 'attendance', 'monthly', 'leaves', 'gps', 'requests', 'holidays', 'reports', 'audit'];
      tabs.forEach(t => {
        const el = document.getElementById('view-' + t);
        if (el) el.style.display = (t === tabId && (!isAuditRestricted || t !== 'audit')) ? 'block' : 'none';
      });

      const titleMap = {
        'dashboard': 'Dashboard Overview',
        'employees': 'Employees Directory',
        'attendance': 'Daily Attendance Management',
        'monthly': 'Monthly Attendance (26th–25th Payroll Cycle)',
        'leaves': 'Leave Administration & Policy',
        'gps': 'Live GPS Tracking & Radar',
        'requests': 'Centralized Requests & Approvals',
        'holidays': 'Company Holidays Calendar (2026)',
        'reports': 'Reports & CSV Analytics',
        'audit': 'Administrative Audit Logs'
      };
      document.getElementById('page-title').innerText = titleMap[tabId] || 'Monarch HR Portal';

      // Load specific tab data
      if (tabId === 'dashboard') loadDashboardStats();
      if (tabId === 'employees') loadEmployees(state.empPage);
      if (tabId === 'attendance') {
        updateDailyFilterCardStyles();
        loadAttendanceRecords(state.attPage);
      }
      if (tabId === 'monthly') {
        updateMonthlyFilterCardStyles();
        loadMonthlyAttendance(state.monthlyPage || 1);
      }
      if (tabId === 'leaves') switchLeavesSubtab('requests');
      if (tabId === 'gps') {
        loadGpsTracking();
        setTimeout(() => {
          if (state.map) state.map.invalidateSize();
        }, 150);
      }
      if (tabId === 'requests') loadAllRequests();
      if (tabId === 'holidays') loadHolidays();
      if (tabId === 'audit') loadAuditLogs();

      lucide.createIcons();
    }

    function refreshCurrentTab() {
      switchTab(state.activeTab);
      showToast('Data refreshed from database.');
    }

    // ─── 1. Dashboard Logic ──────────────────────────────────────────────────
    async function loadDashboardStats() {
      try {
        const res = await fetch(`/api/admin/dashboard-stats?period=${state.period}`, {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        if (res.status === 401 || res.status === 403) return showModal('modal-admin-login');
        const d = await res.json();
        if (d.error) return;

        const k = d.kpis;
        document.getElementById('kpi-total-emp').innerText = k.total_employees.toLocaleString();
        document.getElementById('badge-total-emp').innerText = k.total_employees.toLocaleString();
        document.getElementById('kpi-present').innerText = k.present_today.toLocaleString();
        document.getElementById('kpi-absent').innerText = k.absent_today.toLocaleString();
        document.getElementById('kpi-on-leave').innerText = k.on_leave_today.toLocaleString();
        document.getElementById('kpi-checked-in').innerText = k.checked_in_active.toLocaleString();
        document.getElementById('kpi-late').innerText = k.late_arrivals.toLocaleString();
        document.getElementById('kpi-unclosed').innerText = k.unclosed_shifts.toLocaleString();
        document.getElementById('kpi-pending-leaves').innerText = k.pending_leaves.toLocaleString();
        document.getElementById('badge-pending-leaves').innerText = k.pending_leaves.toLocaleString();
        document.getElementById('kpi-rate-pct').innerText = k.attendance_percentage + '%';
        document.getElementById('kpi-work-hours').innerText = k.total_work_hours.toLocaleString() + 'h';
        document.getElementById('badge-all-requests').innerText = (k.pending_leaves + k.pending_corrections).toLocaleString();

        // Update titles and labels based on period_info
        if (d.period_info) {
          const pi = d.period_info;
          const tEl = document.getElementById('dashboard-title');
          if (tEl) tEl.innerText = pi.title;
          const sEl = document.getElementById('dashboard-subtitle');
          if (sEl) sEl.innerText = pi.subtitle;

          const lPres = document.getElementById('lbl-kpi-present');
          if (lPres) lPres.innerText = pi.present_label;
          const lAbs = document.getElementById('lbl-kpi-absent');
          if (lAbs) lAbs.innerText = pi.absent_label;
          const lAbsSub = document.getElementById('lbl-kpi-absent-sub');
          if (lAbsSub) lAbsSub.innerText = (state.period === 'today') ? 'Not punched' : 'No punches in period';
          const lLeave = document.getElementById('lbl-kpi-on-leave');
          if (lLeave) lLeave.innerText = pi.on_leave_label;
          const lLate = document.getElementById('lbl-kpi-late');
          if (lLate) lLate.innerText = pi.late_label;
          const lUncl = document.getElementById('lbl-kpi-unclosed');
          if (lUncl) lUncl.innerText = pi.unclosed_label;
          const lRate = document.getElementById('lbl-kpi-rate');
          if (lRate) lRate.innerText = pi.rate_label;
          const lHours = document.getElementById('lbl-kpi-hours');
          if (lHours) lHours.innerText = pi.hours_label;

          const chartTitle = document.getElementById('chart-trend-title');
          if (chartTitle) chartTitle.innerText = pi.trend_title;

          const attRateSub = document.getElementById('kpi-att-rate');
          if (attRateSub) {
            attRateSub.innerText = (state.period === 'today') ? `${k.attendance_percentage}% Attendance` : `${k.attendance_percentage}% Active Workforce`;
          }
        }

        // Render Trend Chart
        renderAttendanceTrendChart(d.charts.attendance_trend);

        // Render Dept Distribution
        renderDeptChart(d.charts.department_stats);

        // Recent Activity Table
        const tb = document.getElementById('table-recent-activity');
        if (!d.recent_activity || d.recent_activity.length === 0) {
          tb.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">No punches registered for this selected period.</td></tr>';
        } else {
          tb.innerHTML = d.recent_activity.map(r => `
            <tr>
              <td>
                <div style="font-weight: 700; color: #0F172A;">${escapeHtml(r.employee_name)}</div>
                <div style="font-size: 11px; color: var(--text-muted);">#${r.employee_id}</div>
              </td>
              <td>${escapeHtml(r.department)}</td>
              <td>${r.date}</td>
              <td><span style="font-weight: 700; color: #10B981;">${r.sign_in || '--'}</span></td>
              <td><span style="font-weight: 700; color: #64748B;">${r.sign_out || '--'}</span></td>
              <td>${escapeHtml(r.location)}</td>
              <td>
                <span class="badge ${r.in_geofence ? 'badge-green' : 'badge-amber'}">
                  ${r.in_geofence ? '✓ In Geofence' : '⚠ Out of Range'}
                </span>
              </td>
            </tr>
          `).join('');
        }
      } catch (err) {
        console.error('Error loading dashboard stats:', err);
      }
    }

    function setPeriodFilter(p) {
      state.period = p;
      ['today', 'week', 'month'].forEach(id => {
        const btn = document.getElementById('btn-period-' + id);
        if (btn) {
          btn.style.background = (id === p) ? 'var(--primary)' : 'transparent';
          btn.style.color = (id === p) ? '#0F172A' : '#64748B';
          btn.style.fontWeight = (id === p) ? '700' : '500';
        }
      });
      loadDashboardStats();
    }

    function renderAttendanceTrendChart(trend) {
      const ctx = document.getElementById('chart-attendance-trend').getContext('2d');
      if (state.chartTrend) state.chartTrend.destroy();

      state.chartTrend = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: trend.map(t => t.label),
          datasets: [
            {
              label: 'Present On-Time',
              data: trend.map(t => Math.max(0, t.present - t.late)),
              backgroundColor: '#10B981',
              borderRadius: 6
            },
            {
              label: 'Late Arrivals',
              data: trend.map(t => t.late),
              backgroundColor: '#F59E0B',
              borderRadius: 6
            },
            {
              label: 'Absent',
              data: trend.map(t => t.absent),
              backgroundColor: '#F1F5F9',
              borderRadius: 6
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { stacked: true, grid: { display: false } },
            y: { stacked: true, grid: { color: '#F1F5F9' } }
          },
          plugins: {
            legend: { position: 'bottom', labels: { boxWidth: 12, font: { family: 'Plus Jakarta Sans', size: 11 } } }
          }
        }
      });
    }

    function renderDeptChart(depts) {
      const ctx = document.getElementById('chart-dept-distribution').getContext('2d');
      if (state.chartDept) state.chartDept.destroy();

      state.chartDept = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: depts.map(d => d.department),
          datasets: [{
            data: depts.map(d => d.count),
            backgroundColor: ['#F5A952', '#3B82F6', '#10B981', '#8B5CF6', '#EC4899', '#6366F1', '#14B8A6', '#64748B']
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { boxWidth: 10, font: { family: 'Plus Jakarta Sans', size: 10 } } }
          },
          cutout: '70%'
        }
      });
    }

    // ─── 2. Employees Module Logic ──────────────────────────────────────────
    async function loadEmployees(page = 1) {
      state.empPage = page;
      const search = document.getElementById('emp-search-input').value.trim();
      const dept = document.getElementById('emp-dept-filter').value;
      const status = document.getElementById('emp-status-filter').value;

      try {
        const res = await fetch(`/api/admin/employees?page=${page}&limit=20&search=${encodeURIComponent(search)}&department=${encodeURIComponent(dept)}&status=${status}`, {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const d = await res.json();
        const tb = document.getElementById('table-employees-body');

        if (!d.employees || d.employees.length === 0) {
          tb.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 30px;">No employees matched your criteria.</td></tr>';
          document.getElementById('emp-pagination-info').innerText = 'Showing 0 of 0 staff members';
          document.getElementById('btn-emp-prev').disabled = true;
          document.getElementById('btn-emp-next').disabled = true;
          return;
        }

        tb.innerHTML = d.employees.map(u => `
          <tr>
            <td style="font-weight: 700;">#${u.employee_no}</td>
            <td>
              <div style="font-weight: 700; color: #0F172A;">${escapeHtml(u.name)}</div>
              <div style="font-size: 11px; color: var(--text-muted);">${escapeHtml(u.personal_email || u.mobile_number || 'No contact')}</div>
            </td>
            <td>${escapeHtml(u.department)}</td>
            <td>${escapeHtml(u.designation)}</td>
            <td>${escapeHtml(u.reporting_manager)}</td>
            <td>
              <div style="font-size: 12px; font-weight: 600;">${escapeHtml(u.shift_timing)}</div>
              <div style="font-size: 11px; color: var(--text-muted);">Off: ${u.weekly_off}</div>
            </td>
            <td>
              <span class="badge ${u.is_active ? 'badge-green' : 'badge-red'}">
                ${u.is_active ? 'Active' : 'Inactive'}
              </span>
            </td>
            <td>
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-primary btn-sm" onclick="openEditEmployeeModal(${u.id})">✏️ Edit</button>
                <button class="btn btn-outline btn-sm" onclick="openEmployee360Modal(${u.id})">360°</button>
                <button class="btn btn-outline btn-sm" style="color: ${u.is_active ? '#DC2626' : '#10B981'};" onclick="toggleEmployeeStatus(${u.id})">
                  ${u.is_active ? 'Deactivate' : 'Activate'}
                </button>
              </div>
            </td>
          </tr>
        `).join('');

        document.getElementById('emp-pagination-info').innerText = `Showing page ${d.page} of ${d.pages} (${d.total.toLocaleString()} staff members)`;
        document.getElementById('btn-emp-prev').disabled = (d.page <= 1);
        document.getElementById('btn-emp-next').disabled = (d.page >= d.pages);

      } catch (err) {
        console.error('Error loading employees:', err);
      }
    }

    let _empSearchTimer = null;
    function handleEmployeeSearch(e) {
      const input = document.getElementById('emp-search-input');
      const clearBtn = document.getElementById('emp-search-clear');
      if (clearBtn && input) {
        clearBtn.style.display = input.value.trim().length > 0 ? 'inline-flex' : 'none';
        if (window.lucide) lucide.createIcons();
      }
      if (e && e.key === 'Enter') {
        if (_empSearchTimer) clearTimeout(_empSearchTimer);
        loadEmployees(1);
        return;
      }
      if (_empSearchTimer) clearTimeout(_empSearchTimer);
      const val = (input ? input.value : '').trim();
      if (val.length === 0) {
        loadEmployees(1);
        return;
      }
      _empSearchTimer = setTimeout(() => {
        loadEmployees(1);
      }, 280);
    }

    function clearEmployeeSearch() {
      const input = document.getElementById('emp-search-input');
      if (input) input.value = '';
      const clearBtn = document.getElementById('emp-search-clear');
      if (clearBtn) clearBtn.style.display = 'none';
      if (_empSearchTimer) clearTimeout(_empSearchTimer);
      loadEmployees(1);
    }

    function changeEmployeePage(delta) {
      loadEmployees(state.empPage + delta);
    }

    async function toggleEmployeeStatus(userId) {
      if (!confirm('Change account status for this employee? (Historical attendance & leave records will be completely preserved)')) return;
      try {
        const res = await fetch(`/api/admin/employees/${userId}/toggle-status`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const d = await res.json();
        if (d.success) {
          showToast(d.message);
          loadEmployees(state.empPage);
        } else alert(d.error);
      } catch (err) {
        alert('Status change failed');
      }
    }

    async function handleCreateEmployee(e) {
      e.preventDefault();
      const mgrSel = document.getElementById('inp-emp-mgr');
      let mgrVal = mgrSel ? mgrSel.value : '';
      if (mgrVal === '__custom__') {
        const customInp = document.getElementById('inp-emp-mgr-custom');
        mgrVal = customInp ? customInp.value.trim() : '';
      }

      const payload = {
        employee_no: document.getElementById('inp-emp-no').value,
        name: document.getElementById('inp-emp-name').value,
        personal_email: document.getElementById('inp-emp-email').value,
        mobile_number: document.getElementById('inp-emp-phone').value,
        department: document.getElementById('inp-emp-dept').value,
        designation: document.getElementById('inp-emp-desig').value,
        reporting_manager: mgrVal,
        date_of_joining: document.getElementById('inp-emp-doj').value,
        shift_timing: document.getElementById('inp-emp-shift').value,
        role: document.getElementById('inp-emp-role').value
      };

      try {
        const res = await fetch('/api/admin/employees', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.success) {
          closeModal('modal-add-employee');
          showToast('Employee #' + payload.employee_no + ' created successfully.');
          loadEmployees(1);
        } else alert(d.error);
      } catch (err) {
        alert('Failed to create employee profile');
      }
    }

    async function populateEditReportingManagersDropdown(selectedVal = '') {
      const sel = document.getElementById('edit-emp-mgr');
      if (!sel) return;

      let mgrs = window._reportingManagersCache;
      if (!mgrs || mgrs.length === 0) {
        try {
          const res = await fetch('/api/admin/reporting-managers', {
            headers: { 'Authorization': `Bearer ${state.token}` }
          });
          const d = await res.json();
          if (d.success && d.managers) {
            window._reportingManagersCache = d.managers;
            mgrs = d.managers;
          }
        } catch (err) {
          console.warn('Failed to fetch reporting managers:', err);
        }
      }

      let html = '<option value="">-- Select Reporting Manager --</option>';
      html += '<option value="Direct Management">Direct Management</option>';

      let matched = false;
      const normSel = (selectedVal || '').trim().toLowerCase();

      if (mgrs && mgrs.length > 0) {
        mgrs.forEach(m => {
          const label = m.department ? `${m.name} (${m.department})` : (m.designation ? `${m.name} - ${m.designation}` : m.name);
          const isSel = (normSel && normSel === m.name.toLowerCase().trim());
          if (isSel) matched = true;
          html += `<option value="${escapeHtml(m.name)}" ${isSel ? 'selected' : ''}>${escapeHtml(label)}</option>`;
        });
      }

      html += '<option value="__custom__">➕ Other / Enter Custom Name...</option>';
      sel.innerHTML = html;

      const customInp = document.getElementById('edit-emp-mgr-custom');
      if (customInp) {
        if (!matched && selectedVal && selectedVal !== 'Direct Management' && selectedVal !== '') {
          sel.value = '__custom__';
          customInp.style.display = 'block';
          customInp.value = selectedVal;
        } else {
          customInp.style.display = 'none';
          customInp.value = '';
        }
      }

      sel.onchange = function() {
        if (customInp) {
          if (this.value === '__custom__') {
            customInp.style.display = 'block';
            customInp.focus();
          } else {
            customInp.style.display = 'none';
            customInp.value = '';
          }
        }
      };
    }

    async function openEditEmployeeModal(userId) {
      try {
        const res = await fetch(`/api/admin/employees/${userId}/detail`, {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const d = await res.json();
        if (d.error) {
          alert('Could not fetch employee details: ' + d.error);
          return;
        }

        const p = d.profile;
        document.getElementById('edit-emp-id').value = p.id;
        document.getElementById('edit-emp-no').value = '#' + p.employee_no;
        document.getElementById('edit-emp-name').value = p.name || '';
        document.getElementById('edit-emp-dept').value = p.department || '';
        document.getElementById('edit-emp-desig').value = p.designation || '';
        document.getElementById('edit-emp-phone').value = p.mobile_number || '';
        document.getElementById('edit-emp-email').value = p.personal_email || '';
        document.getElementById('edit-emp-doj').value = p.date_of_joining ? p.date_of_joining.substring(0, 10) : '';
        document.getElementById('edit-emp-gender').value = p.gender || 'Male';
        document.getElementById('edit-emp-location').value = p.location || 'Pune';
        document.getElementById('edit-emp-shift').value = p.shift_timing || 'General- 9.30 Am To 6.30 Pm';
        document.getElementById('edit-emp-weekly-off').value = p.weekly_off || 'Sunday';
        document.getElementById('edit-emp-role').value = p.role || 'employee';
        document.getElementById('edit-emp-status').value = p.employment_status || (p.is_active ? 'Active' : 'Inactive');
        document.getElementById('edit-emp-password').value = '';
        document.getElementById('edit-emp-reason').value = '';

        await populateEditReportingManagersDropdown(p.reporting_manager || '');
        showModal('modal-edit-employee');
      } catch (err) {
        console.error('Failed to open edit modal:', err);
        alert('Failed to load employee details');
      }
    }

    async function handleEditEmployeeSubmit(e) {
      e.preventDefault();
      const userId = document.getElementById('edit-emp-id').value;
      if (!userId) return;

      const mgrSel = document.getElementById('edit-emp-mgr');
      let mgrVal = mgrSel ? mgrSel.value : '';
      if (mgrVal === '__custom__') {
        const customInp = document.getElementById('edit-emp-mgr-custom');
        mgrVal = customInp ? customInp.value.trim() : '';
      }

      const payload = {
        name: document.getElementById('edit-emp-name').value.trim(),
        reporting_manager: mgrVal,
        department: document.getElementById('edit-emp-dept').value.trim(),
        designation: document.getElementById('edit-emp-desig').value.trim(),
        mobile_number: document.getElementById('edit-emp-phone').value.trim(),
        personal_email: document.getElementById('edit-emp-email').value.trim(),
        date_of_joining: document.getElementById('edit-emp-doj').value,
        gender: document.getElementById('edit-emp-gender').value,
        location: document.getElementById('edit-emp-location').value.trim(),
        shift_timing: document.getElementById('edit-emp-shift').value,
        weekly_off: document.getElementById('edit-emp-weekly-off').value,
        role: document.getElementById('edit-emp-role').value,
        employment_status: document.getElementById('edit-emp-status').value,
        is_active: (document.getElementById('edit-emp-status').value.toLowerCase() === 'active')
      };

      const pw = document.getElementById('edit-emp-password').value.trim();
      if (pw) {
        payload.password = pw;
      }

      const reason = document.getElementById('edit-emp-reason').value.trim();
      if (reason) {
        payload.reason = reason;
      }

      const saveBtn = document.getElementById('btn-edit-emp-save');
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerText = 'Saving...';
      }

      try {
        const res = await fetch(`/api/admin/employees/${userId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${state.token}`
          },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.success) {
          closeModal('modal-edit-employee');
          showToast(`Employee #${d.employee ? d.employee.employee_no : ''} details updated successfully.`);
          loadEmployees(state.empPage || 1);
        } else {
          alert('Update failed: ' + (d.error || 'Unknown error'));
        }
      } catch (err) {
        console.error('Update error:', err);
        alert('Server error while updating employee details');
      } finally {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.innerText = 'Save Changes';
        }
      }
    }

    async function openEmployee360Modal(userId) {
      showModal('modal-employee-360');
      const container = document.getElementById('emp-360-content');
      container.innerHTML = '<div style="text-align: center; padding: 30px;">Loading profile overview...</div>';

      try {
        const res = await fetch(`/api/admin/employees/${userId}/detail`, {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const d = await res.json();
        if (d.error) return container.innerText = d.error;

        const p = d.profile;
        const lb = d.leave_balance;

        container.innerHTML = `
          <div style="display: flex; align-items: center; gap: 16px; margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border);">
            <div style="width: 56px; height: 56px; border-radius: 50%; background: var(--primary); display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 800; color: #0F172A;">
              ${escapeHtml(p.name[0])}
            </div>
            <div>
              <div style="font-size: 18px; font-weight: 800; color: #0F172A;">${escapeHtml(p.name)}</div>
              <div style="font-size: 12.5px; color: var(--text-muted);">
                #${p.employee_no} • ${escapeHtml(p.designation)} • ${escapeHtml(p.department)}
              </div>
            </div>
            <div style="margin-left: auto; display: flex; align-items: center; gap: 8px;">
              <span class="badge ${p.is_active ? 'badge-green' : 'badge-red'}">${p.employment_status}</span>
              <button class="btn btn-primary btn-sm" onclick="closeModal('modal-employee-360'); openEditEmployeeModal(${p.id});">✏️ Edit Profile</button>
            </div>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 24px;">
            <div style="padding: 14px; background: #F8FAFC; border-radius: 10px; border: 1px solid var(--border);">
              <div style="font-size: 11px; color: var(--text-muted); font-weight: 700;">TOTAL ALLOTTED LEAVES</div>
              <div style="font-size: 20px; font-weight: 800; color: #0F172A;">${lb.total_allotted} Days</div>
            </div>
            <div style="padding: 14px; background: #F8FAFC; border-radius: 10px; border: 1px solid var(--border);">
              <div style="font-size: 11px; color: var(--text-muted); font-weight: 700;">USED LEAVES</div>
              <div style="font-size: 20px; font-weight: 800; color: #F59E0B;">${lb.used_days} Days</div>
            </div>
            <div style="padding: 14px; background: #F8FAFC; border-radius: 10px; border: 1px solid var(--border);">
              <div style="font-size: 11px; color: var(--text-muted); font-weight: 700;">REMAINING BALANCE</div>
              <div style="font-size: 20px; font-weight: 800; color: #10B981;">${lb.remaining_days} Days</div>
            </div>
          </div>

          <h4 style="font-size: 13.5px; font-weight: 700; margin-bottom: 10px;">Recent 10 Attendance Punches</h4>
          <table class="data-table" style="font-size: 12.5px;">
            <thead>
              <tr>
                <th>Date</th>
                <th>Clock In</th>
                <th>Clock Out</th>
                <th>Hours</th>
                <th>Status</th>
                <th>Location</th>
              </tr>
            </thead>
            <tbody>
              ${d.recent_attendance.slice(0, 10).map(r => `
                <tr>
                  <td>${r.date}</td>
                  <td style="font-weight: 700; color: #10B981;">${r.sign_in || '--'}</td>
                  <td style="font-weight: 700; color: #64748B;">${r.sign_out || '--'}</td>
                  <td>${r.work_hours}h</td>
                  <td><span class="badge ${r.status === 'Present' ? 'badge-green' : (r.status === 'Late' ? 'badge-amber' : 'badge-gray')}">${r.status}</span></td>
                  <td>${escapeHtml(r.location)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      } catch (err) {
        container.innerText = 'Failed to load profile details.';
      }
    }

    // ─── 3. Attendance Module Logic ──────────────────────────────────────────
    function setDailyKpiFilter(filterName) {
      if (state.dailyKpiFilter === filterName) {
        state.dailyKpiFilter = 'all';
      } else {
        state.dailyKpiFilter = filterName;
      }
      updateDailyFilterCardStyles();
      loadAttendanceRecords(1);
    }

    function updateDailyFilterCardStyles() {
      const cur = state.dailyKpiFilter || 'all';
      const cardAll = document.getElementById('kpi-card-daily-all');
      const cardPunches = document.getElementById('kpi-card-daily-punches');
      const cardLate = document.getElementById('kpi-card-daily-late');
      const cardGeo = document.getElementById('kpi-card-daily-geofence');

      const tagAll = document.getElementById('tag-daily-all');
      const tagPunches = document.getElementById('tag-daily-punches');
      const tagLate = document.getElementById('tag-daily-late');
      const tagGeo = document.getElementById('tag-daily-geofence');

      [cardAll, cardPunches, cardLate, cardGeo].forEach(c => {
        if (c) {
          c.style.border = '1px solid var(--border)';
          c.style.background = '#FFFFFF';
          c.style.boxShadow = '0 1px 3px rgba(0,0,0,0.04)';
          c.style.transform = 'none';
        }
      });
      [tagAll, tagPunches, tagLate, tagGeo].forEach(t => {
        if (t) t.style.display = 'none';
      });

      if (cur === 'punches' && cardPunches) {
        cardPunches.style.border = '2px solid #10B981';
        cardPunches.style.background = '#F0FDF4';
        cardPunches.style.boxShadow = '0 4px 14px rgba(16, 185, 129, 0.22)';
        cardPunches.style.transform = 'translateY(-2px)';
        if (tagPunches) tagPunches.style.display = 'inline-block';
      } else if (cur === 'late' && cardLate) {
        cardLate.style.border = '2px solid #F59E0B';
        cardLate.style.background = '#FFFBEB';
        cardLate.style.boxShadow = '0 4px 14px rgba(245, 158, 11, 0.22)';
        cardLate.style.transform = 'translateY(-2px)';
        if (tagLate) tagLate.style.display = 'inline-block';
      } else if (cur === 'out_of_range' && cardGeo) {
        cardGeo.style.border = '2px solid #EF4444';
        cardGeo.style.background = '#FEF2F2';
        cardGeo.style.boxShadow = '0 4px 14px rgba(239, 68, 68, 0.22)';
        cardGeo.style.transform = 'translateY(-2px)';
        if (tagGeo) tagGeo.style.display = 'inline-block';
      } else if (cardAll) {
        cardAll.style.border = '2px solid #3B82F6';
        cardAll.style.background = '#F8FAFC';
        cardAll.style.boxShadow = '0 4px 14px rgba(59, 130, 246, 0.18)';
        cardAll.style.transform = 'translateY(-2px)';
        if (tagAll) tagAll.style.display = 'inline-block';
      }

      const clearBtn = document.getElementById('btn-clear-daily-filter');
      if (clearBtn) {
        clearBtn.style.display = (cur && cur !== 'all') ? 'inline-flex' : 'none';
      }
    }

    async function loadAttendanceRecords(page = 1) {
      state.attPage = page;
      const date = document.getElementById('att-date-picker').value;
      const search = document.getElementById('att-search-input').value.trim();
      const status = document.getElementById('att-status-filter').value;
      const kpiFilter = state.dailyKpiFilter || 'all';

      updateDailyFilterCardStyles();

      try {
        const res = await fetch(`/api/admin/attendance-records?date=${date}&page=${page}&limit=25&search=${encodeURIComponent(search)}&status=${status}&kpi_filter=${kpiFilter}`, {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const d = await res.json();
        const tb = document.getElementById('table-attendance-body');

        // Update Daily Attendance KPIs
        const summary = d.kpis || d.summary;
        if (summary) {
          const kTot = document.getElementById('kpi-daily-total');
          const kEmp = document.getElementById('kpi-daily-emps');
          const kLat = document.getElementById('kpi-daily-late');
          const kGeo = document.getElementById('kpi-daily-geofence');

          if (kEmp) kEmp.innerText = (summary.total_staff || 0).toLocaleString();
          if (kTot) kTot.innerText = (summary.total_punches || 0).toLocaleString();
          if (kLat) kLat.innerText = (summary.unique_late || summary.late_arrivals || summary.late_punches || 0).toLocaleString();
          if (kGeo) kGeo.innerText = (summary.unique_out_of_geofence || summary.out_of_range || summary.out_of_geofence || 0).toLocaleString();

          const subTot = document.getElementById('kpi-daily-total-sub');
          const subLat = document.getElementById('kpi-daily-late-sub');
          const subGeo = document.getElementById('kpi-daily-geofence-sub');

          if (subTot) {
            const uTot = summary.unique_employees || summary.total_punches || 0;
            subTot.innerText = `${uTot.toLocaleString()} active staff in cycle`;
          }
          if (subLat) {
            const uLat = summary.unique_late || summary.late_arrivals || summary.late_punches || 0;
            subLat.innerText = `${uLat.toLocaleString()} staff with late punches`;
          }
          if (subGeo) {
            const uGeo = summary.unique_out_of_geofence || summary.out_of_range || summary.out_of_geofence || 0;
            subGeo.innerText = `${uGeo.toLocaleString()} staff outside perimeter`;
          }
        }

        if (!d.records || d.records.length === 0) {
          let emptyMsg = 'No attendance punches recorded for this date.';
          if (kpiFilter === 'late') emptyMsg = 'No late arrival punches found for this date.';
          else if (kpiFilter === 'out_of_range') emptyMsg = 'No out-of-range punches found for this date.';
          else if (kpiFilter === 'punches') emptyMsg = 'No recorded punches found for this date.';
          tb.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 30px;">${emptyMsg}</td></tr>`;
          document.getElementById('att-pagination-info').innerText = 'Showing 0 records';
          document.getElementById('btn-att-prev').disabled = true;
          document.getElementById('btn-att-next').disabled = true;
          lucide.createIcons();
          return;
        }

        tb.innerHTML = d.records.map(r => `
          <tr>
            <td style="font-weight: 700;">#${r.employee_id}</td>
            <td style="font-weight: 700; color: #0F172A;">${escapeHtml(r.employee_name)}</td>
            <td>${escapeHtml(r.department)}</td>
            <td>${r.date}</td>
            <td style="font-weight: 700; color: #10B981;">${r.sign_in || '--'}</td>
            <td style="font-weight: 700; color: #64748B;">${r.sign_out || '--'}</td>
            <td>${r.work_hours}h</td>
            <td>
              ${r.late_mins > 0 ? `<span style="color: #DC2626; font-weight: 600;">+${r.late_mins}m late</span>` : '<span style="color: #10B981;">On Time</span>'}
            </td>
            <td>
              <span class="badge ${r.status.includes('Present') ? 'badge-green' : (r.status === 'Late' ? 'badge-amber' : 'badge-gray')}">
                ${r.status}
              </span>
            </td>
            <td>
              <div style="font-size: 12px;">${escapeHtml(r.location)}</div>
              <span class="badge ${r.in_geofence ? 'badge-green' : 'badge-amber'}" style="font-size: 10px;">
                ${r.in_geofence ? 'In Geofence' : 'Out of Range'}
              </span>
            </td>
            <td>
              <button class="btn btn-outline btn-sm" onclick="openCorrectPunchModal(${r.id}, '${escapeHtml(r.employee_name)}', '${r.sign_in || ''}', '${r.sign_out || ''}', '${r.approval_status}')">
                Correct
              </button>
            </td>
          </tr>
        `).join('');

        let filterDesc = '';
        if (kpiFilter === 'punches') filterDesc = ' [With Punches]';
        else if (kpiFilter === 'late') filterDesc = ' [Late Arrivals]';
        else if (kpiFilter === 'out_of_range') filterDesc = ' [Out of Range]';

        document.getElementById('att-pagination-info').innerText = `Showing page ${d.page} of ${d.pages} (${d.total.toLocaleString()} total punches${filterDesc})`;
        document.getElementById('btn-att-prev').disabled = (d.page <= 1);
        document.getElementById('btn-att-next').disabled = (d.page >= d.pages);

        lucide.createIcons();
      } catch (err) {
        console.error('Error loading attendance records:', err);
      }
    }

    let _attSearchTimer = null;
    function handleAttendanceSearch(e) {
      if (e && e.key === 'Enter') {
        if (_attSearchTimer) clearTimeout(_attSearchTimer);
        loadAttendanceRecords(1);
        return;
      }
      if (_attSearchTimer) clearTimeout(_attSearchTimer);
      const val = (document.getElementById('att-search-input')?.value || '').trim();
      if (val.length === 0) {
        loadAttendanceRecords(1);
        return;
      }
      _attSearchTimer = setTimeout(() => {
        loadAttendanceRecords(1);
      }, 280);
    }

    function changeAttendancePage(delta) {
      loadAttendanceRecords(state.attPage + delta);
    }

    function clearPunchField(inputId) {
      const el = document.getElementById(inputId);
      if (el) {
        el.value = '';
        showToast('Punch time cleared — will be set to NULL on save.');
      }
    }

    function openCorrectPunchModal(id, name, inTime, outTime, status) {
      document.getElementById('corr-record-id').value = id;
      document.getElementById('corr-emp-name').value = name;
      document.getElementById('corr-sign-in').value = (inTime && inTime !== 'null' && inTime !== '--') ? inTime : '';
      document.getElementById('corr-sign-out').value = (outTime && outTime !== 'null' && outTime !== '--') ? outTime : '';
      document.getElementById('corr-approval-status').value = status || 'Approved';
      document.getElementById('corr-reason').value = '';
      showModal('modal-correct-punch');
    }

    async function handleCorrectPunchSubmit(e) {
      e.preventDefault();
      const id = document.getElementById('corr-record-id').value;
      const inVal = document.getElementById('corr-sign-in').value.trim();
      const outVal = document.getElementById('corr-sign-out').value.trim();

      const payload = {
        sign_in: inVal ? inVal : null,
        sign_out: outVal ? outVal : null,
        clear_sign_in: !inVal,
        clear_sign_out: !outVal,
        approval_status: document.getElementById('corr-approval-status').value,
        reason: document.getElementById('corr-reason').value.trim()
      };

      try {
        const res = await fetch(`/api/admin/attendance/${id}/correct`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.success) {
          closeModal('modal-correct-punch');
          showToast('Attendance record updated & audited successfully.');
          if (state.activeTab === 'monthly') {
            loadMonthlyAttendance(state.monthlyPage);
          } else {
            loadAttendanceRecords(state.attPage);
          }
        } else alert(d.error);
      } catch (err) {
        alert('Correction submission failed');
      }
    }

    function openManualPunchModal() {
      document.getElementById('man-date').value = document.getElementById('att-date-picker').value;
      document.getElementById('man-emp-id').value = '';
      document.getElementById('man-reason').value = '';
      showModal('modal-manual-punch');
    }

    async function handleManualPunchSubmit(e) {
      e.preventDefault();
      const payload = {
        employee_id: document.getElementById('man-emp-id').value.trim(),
        date: document.getElementById('man-date').value,
        sign_in: document.getElementById('man-sign-in').value,
        sign_out: document.getElementById('man-sign-out').value,
        reason: document.getElementById('man-reason').value.trim()
      };

      try {
        const res = await fetch('/api/admin/attendance/manual-punch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.success) {
          closeModal('modal-manual-punch');
          showToast(d.message);
          if (state.activeTab === 'monthly') {
            loadMonthlyAttendance(1);
          } else {
            loadAttendanceRecords(1);
          }
        } else alert(d.error);
      } catch (err) {
        alert('Manual punch submission failed');
      }
    }

    // ─── 3B. Monthly Attendance Cycle (26th to 25th) Module Logic ─────────────
    let monthlyCyclesLoaded = false;

    async function loadMonthlyAttendance(page = 1) {
      state.monthlyPage = page;
      const kpiFilter = state.monthlyFilter || 'all';
      updateMonthlyFilterCardStyles();
      
      const cycleSelect = document.getElementById('monthly-cycle-select');
      let startDate = '';
      let endDate = '';
      
      if (cycleSelect && cycleSelect.value && cycleSelect.value !== 'custom') {
        const parts = cycleSelect.value.split('|');
        if (parts.length === 2) {
          startDate = parts[0];
          endDate = parts[1];
        }
      } else {
        startDate = document.getElementById('monthly-start-date')?.value || '';
        endDate = document.getElementById('monthly-end-date')?.value || '';
      }

      const search = (document.getElementById('monthly-search-input')?.value || '').trim();
      const limit = document.getElementById('monthly-page-size')?.value || 50;

      const tb = document.getElementById('table-monthly-attendance-body');
      tb.innerHTML = '<tr><td colspan="36" style="text-align: center; padding: 40px; color: var(--text-muted);"><div class="spinner" style="margin: 0 auto 10px;"></div>Loading Attendance Muster Roll...</td></tr>';

      try {
        let url = `/api/admin/attendance/monthly-cycle?page=${page}&limit=${limit}&search=${encodeURIComponent(search)}&filter=${kpiFilter}`;
        if (startDate && endDate) {
          url += `&start_date=${startDate}&end_date=${endDate}`;
        }

        const res = await fetch(url, {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const d = await res.json();

        if (d.error) {
          tb.innerHTML = `<tr><td colspan="36" style="text-align: center; color: #EF4444; padding: 30px;">Error: ${escapeHtml(d.error)}</td></tr>`;
          return;
        }

        // Populate cycle dropdown if not already populated
        if (!monthlyCyclesLoaded && d.available_cycles && cycleSelect) {
          monthlyCyclesLoaded = true;
          cycleSelect.innerHTML = d.available_cycles.map(c => 
            `<option value="${c.start_date}|${c.end_date}">${c.label}</option>`
          ).join('') + '<option value="custom">📅 Custom Date Range...</option>';

          if (d.cycle) {
            cycleSelect.value = `${d.cycle.start_date}|${d.cycle.end_date}`;
            const sInp = document.getElementById('monthly-start-date');
            const eInp = document.getElementById('monthly-end-date');
            if (sInp) sInp.value = d.cycle.start_date;
            if (eInp) eInp.value = d.cycle.end_date;
          }
        }

        // Update banner text
        if (d.cycle) {
          const bannerEl = document.getElementById('monthly-cycle-banner-text');
          if (bannerEl) bannerEl.innerText = d.cycle.label;
        }

        // Update KPIs
        if (d.summary) {
          const kTot = document.getElementById('kpi-monthly-total');
          const kEmp = document.getElementById('kpi-monthly-emps');
          const kLat = document.getElementById('kpi-monthly-late');
          const kGeo = document.getElementById('kpi-monthly-geofence');
          if (kTot) kTot.innerText = (d.summary.total_punches || 0).toLocaleString();
          if (kEmp) kEmp.innerText = (d.summary.total_staff || d.total_all_staff || d.total || 0).toLocaleString();
          if (kLat) kLat.innerText = (d.summary.late_punches || 0).toLocaleString();
          if (kGeo) kGeo.innerText = (d.summary.out_of_geofence || 0).toLocaleString();

          const subTot = document.getElementById('kpi-monthly-total-sub');
          const subLat = document.getElementById('kpi-monthly-late-sub');
          const subGeo = document.getElementById('kpi-monthly-geofence-sub');
          if (subTot && d.summary.unique_employees) {
            subTot.innerText = `${(d.summary.unique_employees).toLocaleString()} active staff in cycle`;
          }
          if (subLat && d.summary.unique_late) {
            subLat.innerText = `${(d.summary.unique_late).toLocaleString()} staff with late punches`;
          }
          if (subGeo && d.summary.unique_out_of_geofence) {
            subGeo.innerText = `${(d.summary.unique_out_of_geofence).toLocaleString()} staff outside perimeter`;
          }
        }

        // Filter pill
        const pillCount = document.getElementById('monthly-filter-pill-count');
        if (pillCount) {
          if (kpiFilter === 'punches') {
            pillCount.innerHTML = `<span style="color: #059669; font-weight: 700;">(Showing ${d.total.toLocaleString()} Staff with Recorded Punches)</span>`;
          } else if (kpiFilter === 'late') {
            pillCount.innerHTML = `<span style="color: #D97706; font-weight: 700;">(Showing ${d.total.toLocaleString()} Staff with Late Arrivals > 09:45 AM)</span>`;
          } else if (kpiFilter === 'out_of_range') {
            pillCount.innerHTML = `<span style="color: #DC2626; font-weight: 700;">(Showing ${d.total.toLocaleString()} Staff with Out of Range Punches)</span>`;
          } else {
            pillCount.innerText = `(${d.total.toLocaleString()} Total Employees Master Roll)`;
          }
        }

        // ── Render Muster Header (26th to 25th Cycle Dates) ──
        const thead = document.getElementById('table-monthly-muster-head');
        if (thead && d.cycle_dates && d.cycle_dates.length > 0) {
          let headHtml = '<tr><th class="sticky-col">Emp No</th><th class="sticky-col-2">Employee Name</th>';
          d.cycle_dates.forEach(cd => {
            let titleTip = cd.date;
            if (cd.is_even_saturday) titleTip += ` (${cd.sat_index}${cd.sat_index === 2 ? 'nd' : 'th'} Saturday - Week Off)`;
            else if (cd.is_odd_saturday) titleTip += ` (${cd.sat_index}${cd.sat_index === 1 ? 'st' : (cd.sat_index === 3 ? 'rd' : 'th')} Saturday - Working Day)`;
            else if (cd.is_sunday) titleTip += ` (Sunday - Weekly Off)`;
            headHtml += `<th class="${cd.is_weekend ? 'muster-weekend-col' : ''}" title="${titleTip}" style="min-width: 36px; padding: 7px 4px;">${cd.day}</th>`;
          });
          headHtml += '<th style="min-width: 36px; color: #047857;" title="Total Present">P</th>';
          headHtml += '<th style="min-width: 36px; color: #DC2626;" title="Total Absent (Includes Pending Leave Requests)">A</th>';
          headHtml += '<th style="min-width: 36px; color: #475569;" title="Total Weekly Offs (Sundays & Even Saturdays)">WO</th>';
          headHtml += '<th style="min-width: 36px; color: #7C3AED;" title="Total Festival / Public Holidays">H</th>';
          headHtml += '<th style="min-width: 36px; color: #B45309;" title="Total Half Days">HD</th>';
          headHtml += '<th style="min-width: 36px; color: #1D4ED8;" title="Total Approved Leaves">L</th>';
          headHtml += '<th style="min-width: 44px; font-weight: 800; background: #F1F5F9;" title="Total Work Days">Total</th></tr>';

          // Day of week sub-row
          headHtml += '<tr><th class="sticky-col" style="font-size: 10px; color: var(--text-muted);"># ID</th><th class="sticky-col-2" style="font-size: 10px; color: var(--text-muted);">Staff Directory</th>';
          d.cycle_dates.forEach(cd => {
            let nameColor = '#64748B';
            let titleTip = `${cd.date} (${cd.day_name})`;
            let dayText = cd.day_name;
            if (cd.is_sunday) {
              nameColor = '#EF4444';
              titleTip = `${cd.date} (Sunday - Weekly Off)`;
            } else if (cd.is_even_saturday) {
              nameColor = '#EF4444';
              titleTip = `${cd.date} (${cd.sat_index}${cd.sat_index === 2 ? 'nd' : 'th'} Saturday - Week Off)`;
            } else if (cd.is_odd_saturday) {
              nameColor = '#0F172A';
              titleTip = `${cd.date} (${cd.sat_index}${cd.sat_index === 1 ? 'st' : (cd.sat_index === 3 ? 'rd' : 'th')} Saturday - Working Day)`;
            }
            headHtml += `<th class="${cd.is_weekend ? 'muster-weekend-col' : ''}" title="${titleTip}" style="font-size: 9.5px; font-weight: ${cd.is_odd_saturday ? '700' : '600'}; padding: 4px; color: ${nameColor};">${dayText}</th>`;
          });
          headHtml += '<th style="font-size: 9.5px; color: #047857;">Pres</th>';
          headHtml += '<th style="font-size: 9.5px; color: #DC2626;">Abs</th>';
          headHtml += '<th style="font-size: 9.5px; color: #475569;">Off</th>';
          headHtml += '<th style="font-size: 9.5px; color: #7C3AED;">Hol</th>';
          headHtml += '<th style="font-size: 9.5px; color: #B45309;">Half</th>';
          headHtml += '<th style="font-size: 9.5px; color: #1D4ED8;">Leave</th>';
          headHtml += '<th style="font-size: 9.5px; font-weight: 700; color: #0F172A; background: #F1F5F9;">Work</th></tr>';
          thead.innerHTML = headHtml;
        }

        // ── Render Muster Body ──
        if (!d.muster || d.muster.length === 0) {
          const colSpan = (d.cycle_dates ? d.cycle_dates.length : 30) + 9;
          tb.innerHTML = `<tr><td colspan="${colSpan}" style="text-align: center; color: var(--text-muted); padding: 40px; font-weight: 500;">No employees found matching the filter or search criteria.</td></tr>`;
        } else {
          tb.innerHTML = d.muster.map(m => `
            <tr>
              <td class="sticky-col" style="font-weight: 700; color: #0F172A;">
                <span style="background: #F1F5F9; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 11.5px;">#${m.employee_number}</span>
              </td>
              <td class="sticky-col-2">
                <div style="font-weight: 700; color: #1E293B; max-width: 170px; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(m.employee_name)}">${escapeHtml(m.employee_name)}</div>
                <div style="font-size: 10px; color: var(--text-muted); max-width: 170px; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(m.designation || m.department || '')}</div>
              </td>
              ${m.days.map(dy => {
                const chipClass = (dy.status || '').replace(':', '-');
                return `
                <td class="${dy.is_weekend ? 'muster-weekend-col' : ''}" title="${dy.date} (${dy.day_name})\nStatus: ${dy.status}\n${dy.details}" style="padding: 4px 2px;">
                  <span class="muster-chip chip-${chipClass}">${dy.status}</span>
                </td>
                `;
              }).join('')}
              <td style="font-weight: 700; color: #047857; background: #FAFAF9;">${m.summary.present}</td>
              <td style="font-weight: 700; color: ${m.summary.absent > 0 ? '#DC2626' : '#94A3B8'}; background: #FAFAF9;">${m.summary.absent}</td>
              <td style="font-weight: 600; color: #64748B; background: #FAFAF9;">${m.summary.week_off}</td>
              <td style="font-weight: 600; color: ${m.summary.holiday > 0 ? '#7C3AED' : '#94A3B8'}; background: #FAFAF9;">${m.summary.holiday || 0}</td>
              <td style="font-weight: 600; color: ${m.summary.half_day > 0 ? '#B45309' : '#94A3B8'}; background: #FAFAF9;">${m.summary.half_day}</td>
              <td style="font-weight: 600; color: ${m.summary.leave > 0 ? '#1D4ED8' : '#94A3B8'}; background: #FAFAF9;">${m.summary.leave || 0}</td>
              <td style="font-weight: 800; color: #0F172A; background: #F1F5F9;">${m.summary.total_worked}</td>
            </tr>
          `).join('');
        }

        // Pagination controls
        const pInfo = document.getElementById('monthly-pagination-info');
        const pInd = document.getElementById('monthly-page-indicator');
        const pPrev = document.getElementById('btn-monthly-prev');
        const pNext = document.getElementById('btn-monthly-next');
        const startRec = d.total === 0 ? 0 : ((page - 1) * limit) + 1;
        const endRec = Math.min(page * limit, d.total);
        let filterDesc = '';
        if (kpiFilter === 'punches') filterDesc = ' [With Punches]';
        else if (kpiFilter === 'late') filterDesc = ' [Late Arrivals]';
        else if (kpiFilter === 'out_of_range') filterDesc = ' [Out of Range]';
        if (pInfo) pInfo.innerText = `Showing ${startRec} - ${endRec} of ${d.total.toLocaleString()} employees${filterDesc} (Page ${d.page} of ${d.pages})`;
        if (pInd) pInd.innerText = `${d.page} / ${d.pages}`;
        if (pPrev) pPrev.disabled = (d.page <= 1);
        if (pNext) pNext.disabled = (d.page >= d.pages);

        lucide.createIcons();
      } catch (err) {
        console.error('Error loading monthly attendance muster:', err);
        tb.innerHTML = `<tr><td colspan="36" style="text-align: center; color: #EF4444; padding: 30px;">Network or server error while loading muster records.</td></tr>`;
      }
    }

    function setMonthlyKpiFilter(filterName) {
      if (state.monthlyFilter === filterName) {
        state.monthlyFilter = 'all';
      } else {
        state.monthlyFilter = filterName;
      }
      updateMonthlyFilterCardStyles();
      loadMonthlyAttendance(1);
    }

    function updateMonthlyFilterCardStyles() {
      const cur = state.monthlyFilter || 'all';
      const cardAll = document.getElementById('kpi-card-monthly-all');
      const cardPunches = document.getElementById('kpi-card-monthly-punches');
      const cardLate = document.getElementById('kpi-card-monthly-late');
      const cardGeo = document.getElementById('kpi-card-monthly-geofence');

      const tagAll = document.getElementById('tag-monthly-all');
      const tagPunches = document.getElementById('tag-monthly-punches');
      const tagLate = document.getElementById('tag-monthly-late');
      const tagGeo = document.getElementById('tag-monthly-geofence');

      [cardAll, cardPunches, cardLate, cardGeo].forEach(c => {
        if (c) {
          c.style.border = '1px solid var(--border)';
          c.style.background = '#FFFFFF';
          c.style.boxShadow = '0 1px 3px rgba(0,0,0,0.04)';
          c.style.transform = 'none';
        }
      });
      [tagAll, tagPunches, tagLate, tagGeo].forEach(t => {
        if (t) t.style.display = 'none';
      });

      if (cur === 'punches' && cardPunches) {
        cardPunches.style.border = '2px solid #10B981';
        cardPunches.style.background = '#F0FDF4';
        cardPunches.style.boxShadow = '0 4px 14px rgba(16, 185, 129, 0.22)';
        cardPunches.style.transform = 'translateY(-2px)';
        if (tagPunches) tagPunches.style.display = 'inline-block';
      } else if (cur === 'late' && cardLate) {
        cardLate.style.border = '2px solid #F59E0B';
        cardLate.style.background = '#FFFBEB';
        cardLate.style.boxShadow = '0 4px 14px rgba(245, 158, 11, 0.22)';
        cardLate.style.transform = 'translateY(-2px)';
        if (tagLate) tagLate.style.display = 'inline-block';
      } else if (cur === 'out_of_range' && cardGeo) {
        cardGeo.style.border = '2px solid #EF4444';
        cardGeo.style.background = '#FEF2F2';
        cardGeo.style.boxShadow = '0 4px 14px rgba(239, 68, 68, 0.22)';
        cardGeo.style.transform = 'translateY(-2px)';
        if (tagGeo) tagGeo.style.display = 'inline-block';
      } else if (cardAll) {
        cardAll.style.border = '2px solid #3B82F6';
        cardAll.style.background = '#F8FAFC';
        cardAll.style.boxShadow = '0 4px 14px rgba(59, 130, 246, 0.18)';
        cardAll.style.transform = 'translateY(-2px)';
        if (tagAll) tagAll.style.display = 'inline-block';
      }

      const clearBtn = document.getElementById('btn-clear-monthly-filter');
      if (clearBtn) {
        clearBtn.style.display = (cur && cur !== 'all') ? 'inline-flex' : 'none';
      }
    }

    function handleMonthlyCycleChange() {
      const cycleSelect = document.getElementById('monthly-cycle-select');
      const customDatesEl = document.getElementById('monthly-custom-dates');
      if (!cycleSelect) return;
      if (cycleSelect.value === 'custom') {
        if (customDatesEl) customDatesEl.style.display = 'flex';
      } else {
        if (customDatesEl) customDatesEl.style.display = 'none';
        const parts = cycleSelect.value.split('|');
        if (parts.length === 2) {
          const sInp = document.getElementById('monthly-start-date');
          const eInp = document.getElementById('monthly-end-date');
          if (sInp) sInp.value = parts[0];
          if (eInp) eInp.value = parts[1];
        }
      }
      loadMonthlyAttendance(1);
    }

    function handleMonthlySearch(e) {
      if (e.key === 'Enter' || e.target.value.length === 0) {
        loadMonthlyAttendance(1);
      }
    }

    function changeMonthlyPage(delta) {
      const newPage = (state.monthlyPage || 1) + delta;
      if (newPage >= 1) {
        loadMonthlyAttendance(newPage);
      }
    }

    function exportMonthlyAttendanceCsv() {
      const cycleSelect = document.getElementById('monthly-cycle-select');
      let startDate = '';
      let endDate = '';
      if (cycleSelect && cycleSelect.value && cycleSelect.value !== 'custom') {
        const parts = cycleSelect.value.split('|');
        if (parts.length === 2) {
          startDate = parts[0];
          endDate = parts[1];
        }
      } else {
        startDate = document.getElementById('monthly-start-date')?.value || '';
        endDate = document.getElementById('monthly-end-date')?.value || '';
      }
      
      const kpiFilter = state.monthlyFilter || 'all';
      const url = `/api/admin/reports/export?type=attendance_muster&start_date=${startDate}&end_date=${endDate}&filter=${kpiFilter}`;
      
      showToast(`Generating Attendance Muster CSV (${kpiFilter})...`);
      fetch(url, { headers: { 'Authorization': `Bearer ${state.token}` } })
        .then(res => {
          if (!res.ok) throw new Error('Download failed');
          return res.blob();
        })
        .then(blob => {
          const a = document.createElement('a');
          a.href = window.URL.createObjectURL(blob);
          const filterSuffix = kpiFilter !== 'all' ? `_${kpiFilter}` : '';
          a.download = `Attendance_Muster${filterSuffix}_${startDate}_to_${endDate}.csv`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          showToast('Attendance Muster CSV exported successfully!');
        })
        .catch(err => alert('Failed to download muster report: ' + err));
    }

    // ─── 4. Leave Management Module Logic ────────────────────────────────────
    function switchLeavesSubtab(sub) {
      ['requests', 'balances', 'types'].forEach(id => {
        document.getElementById('subview-leaves-' + id).style.display = (id === sub) ? 'block' : 'none';
        const btn = document.getElementById('btn-sub-leaves-' + id.substring(0, 3));
        if (btn) {
          btn.className = (id === sub) ? 'btn btn-primary btn-sm' : 'btn btn-outline btn-sm';
        }
      });

      if (sub === 'requests') loadLeaveRequests();
      if (sub === 'balances') loadLeaveBalances();
      if (sub === 'types') loadLeaveTypes();
    }

    let currentLeavesStatusFilter = 'all'; // 'all', 'pending', 'approved', 'rejected'

    function setLeavesStatusFilter(status) {
      currentLeavesStatusFilter = status;
      updateLeavesFilterButtonStyles();
      renderLeavesRequestsTable();
    }

    function updateLeavesFilterButtonStyles() {
      const statuses = ['all', 'pending', 'approved', 'rejected'];
      statuses.forEach(st => {
        const btn = document.getElementById('btn-leaves-filter-' + st);
        if (!btn) return;
        if (st === currentLeavesStatusFilter) {
          if (st === 'all') {
            btn.className = 'btn btn-primary btn-sm';
            btn.style.background = '#2563EB';
            btn.style.color = '#FFFFFF';
            btn.style.borderColor = '#2563EB';
          } else if (st === 'pending') {
            btn.className = 'btn btn-sm';
            btn.style.background = '#F59E0B';
            btn.style.color = '#FFFFFF';
            btn.style.borderColor = '#D97706';
          } else if (st === 'approved') {
            btn.className = 'btn btn-sm';
            btn.style.background = '#10B981';
            btn.style.color = '#FFFFFF';
            btn.style.borderColor = '#059669';
          } else if (st === 'rejected') {
            btn.className = 'btn btn-sm';
            btn.style.background = '#EF4444';
            btn.style.color = '#FFFFFF';
            btn.style.borderColor = '#DC2626';
          }
        } else {
          btn.className = 'btn btn-outline btn-sm';
          if (st === 'pending') {
            btn.style.background = 'transparent';
            btn.style.color = '#D97706';
            btn.style.borderColor = '#F59E0B';
          } else if (st === 'approved') {
            btn.style.background = 'transparent';
            btn.style.color = '#059669';
            btn.style.borderColor = '#10B981';
          } else if (st === 'rejected') {
            btn.style.background = 'transparent';
            btn.style.color = '#DC2626';
            btn.style.borderColor = '#EF4444';
          } else {
            btn.style.background = 'transparent';
            btn.style.color = '';
            btn.style.borderColor = '';
          }
        }
      });
    }

    async function loadLeaveRequests() {
      try {
        const res = await fetch('/api/admin/leave-requests', {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const leaves = await res.json();
        state.leavesList = leaves || [];

        // Count for badges
        const total = state.leavesList.length;
        const pending = state.leavesList.filter(l => (l.status || '').toLowerCase().includes('pending')).length;
        const approved = state.leavesList.filter(l => (l.status || '').toLowerCase() === 'approved').length;
        const rejected = state.leavesList.filter(l => (l.status || '').toLowerCase() === 'rejected').length;

        const bAll = document.getElementById('badge-count-all');
        if (bAll) bAll.innerText = total;
        const bPending = document.getElementById('badge-count-pending');
        if (bPending) bPending.innerText = pending;
        const bApproved = document.getElementById('badge-count-approved');
        if (bApproved) bApproved.innerText = approved;
        const bRejected = document.getElementById('badge-count-rejected');
        if (bRejected) bRejected.innerText = rejected;

        updateLeavesFilterButtonStyles();
        renderLeavesRequestsTable();
      } catch (err) {
        console.error('Error loading leaves:', err);
      }
    }

    function renderLeavesRequestsTable() {
      const leaves = state.leavesList || [];
      const tb = document.getElementById('table-leaves-requests-body');
      if (!tb) return;

      const searchInp = document.getElementById('leaves-search-input');
      const search = (searchInp ? searchInp.value : '').trim().toLowerCase();
      const typeFilterEl = document.getElementById('leaves-type-filter');
      const typeFilter = typeFilterEl ? typeFilterEl.value : 'all';

      const filtered = leaves.filter(l => {
        const st = (l.status || '').toLowerCase();
        if (currentLeavesStatusFilter === 'pending' && !st.includes('pending')) return false;
        if (currentLeavesStatusFilter === 'approved' && st !== 'approved') return false;
        if (currentLeavesStatusFilter === 'rejected' && st !== 'rejected') return false;

        if (typeFilter !== 'all' && l.leave_type !== typeFilter) return false;

        if (search) {
          const eid = String(l.employee_id || '').toLowerCase();
          const name = String(l.employee_name || '').toLowerCase();
          const dept = String(l.department || '').toLowerCase();
          const reason = String(l.note || l.title || '').toLowerCase();
          if (!eid.includes(search) && !name.includes(search) && !dept.includes(search) && !reason.includes(search)) {
            return false;
          }
        }
        return true;
      });

      if (filtered.length === 0) {
        let msg = 'No leave requests matched your filter criteria.';
        if (currentLeavesStatusFilter === 'pending') {
          msg = '🎉 No pending leave applications! All submitted requests have been reviewed.';
        }
        tb.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 36px; font-size: 13.5px;">${msg}</td></tr>`;
        return;
      }

      tb.innerHTML = filtered.map(l => {
        const isPending = (l.status || '').toLowerCase().includes('pending');
        const isApproved = (l.status || '').toLowerCase() === 'approved';
        const isRejected = (l.status || '').toLowerCase() === 'rejected';

        let statusBadgeClass = 'badge-amber';
        if (isApproved) statusBadgeClass = 'badge-green';
        else if (isRejected) statusBadgeClass = 'badge-red';

        // Flow summary cell
        let flowSummary = '';
        if (isPending) {
          flowSummary = `
            <div style="display: flex; flex-direction: column; gap: 4px;">
              <div style="font-size: 11.5px; font-weight: 700; color: #0F172A; display: flex; align-items: center; gap: 4px;">
                <span style="color: #3B82F6;">👤</span> <span>${escapeHtml(l.reporting_manager || 'Reporting Manager')}</span>
              </div>
              <div style="font-size: 10px; color: #D97706; font-weight: 600; display: inline-flex; align-items: center; gap: 3px;">
                <span>⏳ Awaiting Review</span>
              </div>
              <button class="btn btn-outline btn-sm" style="font-size: 10.5px; padding: 2px 7px; width: fit-content; margin-top: 2px;" onclick="openApprovalFlowModal(${l.id})">
                Flow Details ➔
              </button>
            </div>
          `;
        } else if (isApproved) {
          flowSummary = `
            <div style="display: flex; flex-direction: column; gap: 4px;">
              <div style="font-size: 11.5px; font-weight: 700; color: #0F172A; display: flex; align-items: center; gap: 4px;">
                <span style="color: #10B981;">👤</span> <span>${escapeHtml(l.reviewer_name || l.reporting_manager || 'Admin')}</span>
              </div>
              <div style="font-size: 10px; color: #059669; font-weight: 600;">
                <span>✅ Approved & Quota Deducted</span>
              </div>
              <button class="btn btn-outline btn-sm" style="font-size: 10.5px; padding: 2px 7px; width: fit-content; margin-top: 2px;" onclick="openApprovalFlowModal(${l.id})">
                Flow Details ➔
              </button>
            </div>
          `;
        } else {
          flowSummary = `
            <div style="display: flex; flex-direction: column; gap: 4px;">
              <div style="font-size: 11.5px; font-weight: 700; color: #0F172A; display: flex; align-items: center; gap: 4px;">
                <span style="color: #EF4444;">👤</span> <span>${escapeHtml(l.reviewer_name || l.reporting_manager || 'Admin')}</span>
              </div>
              <div style="font-size: 10px; color: #DC2626; font-weight: 600;">
                <span>❌ Rejected</span>
              </div>
              <button class="btn btn-outline btn-sm" style="font-size: 10.5px; padding: 2px 7px; width: fit-content; margin-top: 2px;" onclick="openApprovalFlowModal(${l.id})">
                Flow Details ➔
              </button>
            </div>
          `;
        }

        return `
          <tr>
            <td>
              <div style="font-weight: 700; color: #0F172A;">${escapeHtml(l.employee_name)}</div>
              <div style="font-size: 11px; color: var(--text-muted);">#${l.employee_id} • ${escapeHtml(l.department || 'General')}</div>
              <div style="font-size: 10.5px; color: #64748B;">${escapeHtml(l.designation || 'Staff')}</div>
            </td>
            <td><span class="badge badge-blue">${escapeHtml(l.leave_type)}</span></td>
            <td>
              <div style="font-weight: 700; color: #0F172A;">${l.start_date} to ${l.end_date}</div>
              <div style="font-size: 11px; color: var(--text-muted);">${l.days_count} Working Day${l.days_count === 1 ? '' : 's'} ${l.session ? `• <b style="color: #2563EB;">${escapeHtml(l.session)}</b>` : ''}</div>
            </td>
            <td>${flowSummary}</td>
            <td style="max-width: 220px;">
              <div style="font-size: 12px; color: #334155; word-break: break-word;">${escapeHtml(l.note || l.title || 'Personal')}</div>
            </td>
            <td>
              <span class="badge ${statusBadgeClass}">
                ${l.status}
              </span>
            </td>
            <td>
              ${isPending ? `
                <div style="display: flex; flex-direction: column; gap: 5px;">
                  <div style="display: flex; gap: 4px;">
                    <button class="btn btn-primary btn-sm" style="font-size: 11px; padding: 3px 8px;" onclick="openReviewLeaveModal(${l.id}, '${escapeHtml(l.employee_name)}', '${l.start_date} to ${l.end_date} (${l.days_count}d ${escapeHtml(l.leave_type)}${l.session ? ' ' + escapeHtml(l.session) : ''})', 'approve')">Approve</button>
                    <button class="btn btn-outline btn-sm" style="font-size: 11px; padding: 3px 8px; color: #DC2626; border-color: #FCA5A5;" onclick="openReviewLeaveModal(${l.id}, '${escapeHtml(l.employee_name)}', '${l.start_date} to ${l.end_date} (${l.days_count}d ${escapeHtml(l.leave_type)}${l.session ? ' ' + escapeHtml(l.session) : ''})', 'reject')">Reject</button>
                  </div>
                  <button class="btn btn-outline btn-sm" style="font-size: 10px; padding: 2px 7px; width: fit-content;" onclick="openApprovalFlowModal(${l.id})">
                    View Flow ➔
                  </button>
                </div>
              ` : `
                <div style="display: flex; flex-direction: column; gap: 4px;">
                  <span class="badge ${isApproved ? 'badge-green' : 'badge-red'}" style="font-size: 10px; width: fit-content;">
                    ${isApproved ? '✅ Approved' : '❌ Rejected'}
                  </span>
                  <div style="font-size: 10.5px; color: #64748B;">By: <b>${escapeHtml(l.reviewer_name || l.reviewed_by || 'Admin / HR')}</b></div>
                  <button class="btn btn-outline btn-sm" style="font-size: 10px; padding: 2px 7px; width: fit-content; margin-top: 2px;" onclick="openApprovalFlowModal(${l.id})">
                    View Flow ➔
                  </button>
                </div>
              `}
            </td>
          </tr>
        `;
      }).join('');
    }

    function openApprovalFlowModal(leaveId) {
      if (!state.leavesList) return;
      const l = state.leavesList.find(x => x.id === leaveId);
      if (!l) return;

      document.getElementById('flow-emp-name').innerText = l.employee_name;
      document.getElementById('flow-emp-sub').innerText = `Emp #${l.employee_id} • ${l.department || 'Operations'} • ${l.designation || 'Staff'}`;
      
      const isPending = (l.status || '').toLowerCase().includes('pending');
      const isApproved = (l.status || '').toLowerCase() === 'approved';
      const isRejected = (l.status || '').toLowerCase() === 'rejected';

      const pillEl = document.getElementById('flow-status-pill');
      if (isApproved) {
        pillEl.innerHTML = '<span class="badge badge-green" style="font-size: 11px;">✅ Approved</span>';
      } else if (isRejected) {
        pillEl.innerHTML = '<span class="badge badge-red" style="font-size: 11px;">❌ Rejected</span>';
      } else {
        pillEl.innerHTML = '<span class="badge badge-amber" style="font-size: 11px;">⏳ Pending Approval</span>';
      }

      document.getElementById('flow-leave-type').innerText = l.leave_type;
      document.getElementById('flow-leave-period').innerText = `${l.start_date} to ${l.end_date} (${l.days_count} Days)`;
      document.getElementById('flow-applied-date').innerText = (l.applied_at || '').substring(0, 10);
      document.getElementById('flow-leave-reason').innerHTML = `<b>Applicant Reason / Note:</b> ${escapeHtml(l.note || l.title || 'Personal reasons')}`;

      // Render 3-step vertical progress timeline
      const stepsContainer = document.getElementById('flow-stepper-steps');
      const flowSteps = l.approval_flow || [];

      stepsContainer.innerHTML = flowSteps.map((st, idx) => {
        const isLast = (idx === flowSteps.length - 1);
        let circleBg = '#E2E8F0';
        let circleColor = '#64748B';
        let circleIcon = `${st.step}`;
        let statusBadge = '';

        if (st.status === 'completed') {
          circleBg = '#10B981';
          circleColor = '#FFFFFF';
          circleIcon = '✓';
          statusBadge = `<span class="badge badge-green" style="font-size: 9.5px;">Completed</span>`;
        } else if (st.status === 'rejected') {
          circleBg = '#EF4444';
          circleColor = '#FFFFFF';
          circleIcon = '✕';
          statusBadge = `<span class="badge badge-red" style="font-size: 9.5px;">Rejected</span>`;
        } else if (st.status === 'pending') {
          circleBg = '#F59E0B';
          circleColor = '#FFFFFF';
          circleIcon = '⏳';
          statusBadge = `<span class="badge badge-amber" style="font-size: 9.5px;">Pending Action</span>`;
        } else {
          // active_override / future
          circleBg = '#3B82F6';
          circleColor = '#FFFFFF';
          circleIcon = '⚡';
          statusBadge = `<span class="badge badge-blue" style="font-size: 9.5px;">Admin Authority</span>`;
        }

        const lineStyle = isLast ? 'display: none;' : `
          position: absolute;
          left: 17px;
          top: 36px;
          bottom: -10px;
          width: 2px;
          background: ${st.status === 'completed' ? '#10B981' : '#E2E8F0'};
        `;

        return `
          <div style="position: relative; display: flex; gap: 14px; margin-bottom: 22px;">
            <div style="${lineStyle}"></div>
            <div style="width: 36px; height: 36px; border-radius: 50%; background: ${circleBg}; color: ${circleColor}; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 13px; flex-shrink: 0; z-index: 2; box-shadow: 0 2px 5px rgba(0,0,0,0.08);">
              ${circleIcon}
            </div>
            <div style="flex: 1; padding-top: 4px;">
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                <div style="font-size: 13.5px; font-weight: 700; color: #0F172A;">${escapeHtml(st.title)}</div>
                ${statusBadge}
              </div>
              <div style="font-size: 12px; color: #2563EB; font-weight: 600; margin-top: 2px;">
                ${escapeHtml(st.actor)} <span style="font-size: 11px; color: var(--text-muted); font-weight: 400;">(${escapeHtml(st.role)})</span>
              </div>
              <div style="font-size: 11.5px; color: #475569; margin-top: 4px; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 6px 10px;">
                ${escapeHtml(st.note || '')}
              </div>
              ${st.timestamp ? `<div style="font-size: 10.5px; color: var(--text-muted); margin-top: 4px;">Timestamp: ${st.timestamp.replace('T', ' ').substring(0, 19)}</div>` : ''}
            </div>
          </div>
        `;
      }).join('');

      // Action buttons for modal
      const btnContainer = document.getElementById('flow-action-buttons');
      if (isPending) {
        btnContainer.innerHTML = `
          <button type="button" class="btn btn-outline btn-sm" onclick="closeModal('modal-approval-flow')">Close</button>
          <button type="button" class="btn btn-outline btn-sm" style="color: #DC2626; border-color: #FCA5A5;" onclick="closeModal('modal-approval-flow'); openReviewLeaveModal(${l.id}, '${escapeHtml(l.employee_name)}', '${l.start_date} to ${l.end_date} (${l.days_count}d ${escapeHtml(l.leave_type)}${l.session ? ' ' + escapeHtml(l.session) : ''})', 'reject')">Reject Request</button>
          <button type="button" class="btn btn-primary btn-sm" onclick="closeModal('modal-approval-flow'); openReviewLeaveModal(${l.id}, '${escapeHtml(l.employee_name)}', '${l.start_date} to ${l.end_date} (${l.days_count}d ${escapeHtml(l.leave_type)}${l.session ? ' ' + escapeHtml(l.session) : ''})', 'approve')">Approve Request</button>
        `;
      } else {
        btnContainer.innerHTML = `
          <button type="button" class="btn btn-outline btn-sm" onclick="closeModal('modal-approval-flow')">Close</button>
        `;
      }

      showModal('modal-approval-flow');
    }

    function openReviewLeaveModal(id, name, details, action) {
      document.getElementById('rev-leave-id').value = id;
      document.getElementById('rev-leave-action').value = action;
      document.getElementById('rev-emp-name').innerText = name;
      document.getElementById('rev-leave-details').innerText = details;
      document.getElementById('rev-leave-reason').value = '';
      const btn = document.getElementById('rev-submit-btn');
      btn.className = (action === 'approve') ? 'btn btn-primary' : 'btn btn-danger';
      btn.innerText = (action === 'approve') ? 'Confirm Approval' : 'Confirm Rejection';
      showModal('modal-review-leave');
    }

    async function handleLeaveReviewSubmit(e) {
      e.preventDefault();
      const id = document.getElementById('rev-leave-id').value;
      const action = document.getElementById('rev-leave-action').value;
      const reason = document.getElementById('rev-leave-reason').value.trim();

      try {
        const res = await fetch(`/api/admin/leave-requests/${id}/review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ action: action, reason: reason })
        });
        const d = await res.json();
        if (d.success) {
          closeModal('modal-review-leave');
          showToast(d.message);
          loadLeaveRequests();
        } else alert(d.error);
      } catch (err) {
        alert('Decision submission failed');
      }
    }

    async function loadLeaveBalances() {
      try {
        const res = await fetch('/api/admin/leave-balances', {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const list = await res.json();
        const tb = document.getElementById('table-leaves-balances-body');

        tb.innerHTML = list.map(b => `
          <tr>
            <td style="font-weight: 700;">#${b.employee_id}</td>
            <td style="font-weight: 700; color: #0F172A;">${escapeHtml(b.name)}</td>
            <td>${escapeHtml(b.department)}</td>
            <td style="font-weight: 700;">${b.total_allotted} Days</td>
            <td style="color: #F59E0B; font-weight: 700;">${b.used_days} Days</td>
            <td style="color: #10B981; font-weight: 700;">${b.remaining_days} Days</td>
            <td>
              <button class="btn btn-outline btn-sm" onclick="openAdjustQuotaModal('${b.employee_id}', '${escapeHtml(b.name || '')}', ${b.total_allotted}, ${b.used_days}, ${b.remaining_days})">
                Adjust Quota
              </button>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        console.error('Error loading balances:', err);
      }
    }

    function openAdjustQuotaModal(empId, empName, total, used, remaining) {
      document.getElementById('adj-emp-id').value = empId;
      document.getElementById('adj-emp-name').innerText = empName ? empName : ('Employee #' + empId);
      document.getElementById('adj-emp-id-badge').innerText = 'Employee #' + empId;
      document.getElementById('adj-current-remaining').innerText = (remaining !== undefined ? remaining : (total - used)) + ' Days';
      document.getElementById('adj-total-allotted').value = (total !== undefined ? total : 6.0);
      document.getElementById('adj-used-days').value = (used !== undefined ? used : 0.0);
      document.getElementById('adj-reason').value = '';
      calculateAdjustRemaining();
      showModal('modal-adjust-leave-quota');
      if (window.lucide) lucide.createIcons();
    }

    // Keep promptAdjustBalance for backwards compatibility
    function promptAdjustBalance(empId, total, used, remaining) {
      openAdjustQuotaModal(empId, '', total, used, remaining);
    }

    function calculateAdjustRemaining() {
      const total = parseFloat(document.getElementById('adj-total-allotted').value) || 0;
      const used = parseFloat(document.getElementById('adj-used-days').value) || 0;
      const rem = total - used;
      const calcEl = document.getElementById('adj-remaining-calc');
      calcEl.innerText = (Number.isInteger(rem) ? rem : rem.toFixed(1)) + ' Days';
      if (rem < 0) {
        calcEl.style.color = '#DC2626';
      } else {
        calcEl.style.color = '#15803D';
      }
    }

    async function handleAdjustQuotaSubmit(e) {
      e.preventDefault();
      const empId = document.getElementById('adj-emp-id').value;
      const total = parseFloat(document.getElementById('adj-total-allotted').value) || 0;
      const used = parseFloat(document.getElementById('adj-used-days').value) || 0;
      const remaining = total - used;
      const reason = document.getElementById('adj-reason').value.trim();

      if (!reason) {
        alert('A mandatory reason is required for audit logs.');
        return;
      }

      const btn = document.getElementById('btn-save-quota-adj');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner" style="width: 14px; height: 14px; border-width: 2px; display: inline-block; vertical-align: middle; margin-right: 6px;"></span> Saving...';

      try {
        const res = await fetch(`/api/admin/leave-balances/${empId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({
            total_allotted: total,
            used_days: used,
            remaining_days: remaining,
            reason: reason
          })
        });
        const d = await res.json();
        if (d.success) {
          closeModal('modal-adjust-leave-quota');
          showToast(d.message || `Leave quota for #${empId} updated.`);
          loadLeaveBalances();
        } else {
          alert(d.error || 'Failed to adjust quota.');
        }
      } catch (err) {
        alert('Failed to adjust quota: ' + err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="check" style="width: 14px; height: 14px;"></i> <span>Save Quota Changes</span>';
        if (window.lucide) lucide.createIcons();
      }
    }

    async function loadLeaveTypes() {
      try {
        const res = await fetch('/api/admin/leave-types', {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const types = await res.json();
        const tb = document.getElementById('table-leaves-types-body');
        tb.innerHTML = types.map(t => `
          <tr>
            <td style="font-weight: 700; color: #0F172A;">${escapeHtml(t.name)}</td>
            <td><span class="badge badge-blue">${t.code}</span></td>
            <td style="font-weight: 700;">${t.annual_days} Days / year</td>
            <td>${t.carry_forward_max} Days max</td>
            <td>${t.is_paid ? '✓ Paid' : 'Unpaid'}</td>
            <td>${escapeHtml(t.description)}</td>
          </tr>
        `).join('');
      } catch (err) {
        console.error('Error loading types:', err);
      }
    }

    let allStaffMembersCache = [];

    async function openApplyOnBehalfModal() {
      const filterInp = document.getElementById('beh-emp-filter');
      if (filterInp) filterInp.value = '';
      document.getElementById('beh-emp-id').value = '';
      const previewCard = document.getElementById('beh-selected-card');
      if (previewCard) previewCard.style.display = 'none';

      document.getElementById('beh-type-full').checked = true;
      document.getElementById('beh-type-half').checked = false;
      document.getElementById('beh-sess-1').checked = true;
      document.getElementById('beh-sess-2').checked = false;
      document.getElementById('beh-session-container').style.display = 'none';
      document.getElementById('beh-end-date-group').style.display = 'block';

      const today = new Date().toISOString().substring(0, 10);
      document.getElementById('beh-start-date').value = today;
      document.getElementById('beh-end-date').value = today;
      document.getElementById('beh-days').value = '1.0';
      document.getElementById('beh-days').readOnly = false;
      document.getElementById('beh-reason').value = '';

      showModal('modal-apply-behalf');
      await populateBehalfEmployeesList();
    }

    async function populateBehalfEmployeesList() {
      const select = document.getElementById('beh-emp-select');
      if (!select) return;
      if (allStaffMembersCache.length === 0) {
        try {
          select.innerHTML = '<option value="" disabled selected>⏳ Loading staff directory...</option>';
          const res = await fetch('/api/admin/users', {
            headers: { 'Authorization': `Bearer ${state.token}` }
          });
          const data = await res.json();
          allStaffMembersCache = (data || []).sort((a, b) => {
            const idA = parseInt(a.employee_no || a.id) || 0;
            const idB = parseInt(b.employee_no || b.id) || 0;
            return idA - idB;
          });
        } catch (err) {
          console.error('Failed to load users for behalf modal:', err);
          select.innerHTML = '<option value="" disabled>Error loading staff directory</option>';
          return;
        }
      }
      renderBehalfEmployeeOptions('');
    }

    function renderBehalfEmployeeOptions(query = '') {
      const select = document.getElementById('beh-emp-select');
      if (!select) return;
      const q = (query || '').trim().toLowerCase();
      const filtered = allStaffMembersCache.filter(u => {
        if (!q) return true;
        const eid = String(u.employee_no || u.id || '').toLowerCase();
        const name = String(u.name || u.full_name || '').toLowerCase();
        const dept = String(u.department || '').toLowerCase();
        const desig = String(u.designation || '').toLowerCase();
        return eid.includes(q) || name.includes(q) || dept.includes(q) || desig.includes(q);
      });

      const countEl = document.getElementById('beh-emp-count');
      if (countEl) countEl.innerText = `${filtered.length} of ${allStaffMembersCache.length} staff`;

      if (filtered.length === 0) {
        select.innerHTML = '<option value="" disabled>No employees match your search</option>';
        return;
      }

      select.innerHTML = '<option value="" disabled selected>-- Select Staff Member from Dropdown --</option>' +
        filtered.map(u => {
          const eid = u.employee_no || u.id;
          const dept = u.department ? ` • ${u.department}` : '';
          const desig = u.designation ? ` (${u.designation})` : '';
          return `<option value="${eid}" data-name="${escapeHtml(u.name)}" data-dept="${escapeHtml(u.department || '')}" data-desig="${escapeHtml(u.designation || '')}">#${eid} - ${escapeHtml(u.name)}${desig}${dept}</option>`;
        }).join('');
    }

    function filterBehalfEmployees() {
      const q = document.getElementById('beh-emp-filter').value;
      renderBehalfEmployeeOptions(q);
    }

    function onBehalfEmployeeSelected() {
      const select = document.getElementById('beh-emp-select');
      const opt = select.options[select.selectedIndex];
      if (!opt || !opt.value) return;

      const eid = opt.value;
      const name = opt.getAttribute('data-name') || '';
      const dept = opt.getAttribute('data-dept') || '';
      const desig = opt.getAttribute('data-desig') || '';

      document.getElementById('beh-emp-id').value = eid;
      const card = document.getElementById('beh-selected-card');
      if (card) {
        card.style.display = 'flex';
        card.style.alignItems = 'center';
        card.innerHTML = `
          <div style="width: 32px; height: 32px; border-radius: 50%; background: #2563EB; color: white; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; margin-right: 10px; flex-shrink: 0;">
            ${name ? name.charAt(0).toUpperCase() : '#'}
          </div>
          <div style="flex: 1;">
            <div style="font-weight: 700; color: #0F172A; font-size: 13px;">${escapeHtml(name)} <span style="font-weight: 600; color: #2563EB;">(#${eid})</span></div>
            <div style="font-size: 11px; color: #64748B;">${escapeHtml(desig || 'Staff')}${dept ? ' • ' + escapeHtml(dept) : ''}</div>
          </div>
          <div style="font-size: 18px; color: #10B981; font-weight: 700;">✓</div>
        `;
      }
    }

    function onBehalfDurationChanged() {
      const isHalf = document.getElementById('beh-type-half').checked;
      const sessCont = document.getElementById('beh-session-container');
      const daysInp = document.getElementById('beh-days');
      const endDateGrp = document.getElementById('beh-end-date-group');
      const startDate = document.getElementById('beh-start-date').value;

      if (isHalf) {
        sessCont.style.display = 'block';
        daysInp.value = '0.5';
        daysInp.readOnly = true;
        endDateGrp.style.display = 'none';
        document.getElementById('beh-end-date').value = startDate;
        updateBehalfSessionStyles();
      } else {
        sessCont.style.display = 'none';
        daysInp.readOnly = false;
        endDateGrp.style.display = 'block';
        calculateBehalfDays();
      }
    }

    function updateBehalfSessionStyles() {
      const isSess1 = document.getElementById('beh-sess-1').checked;
      const l1 = document.getElementById('beh-label-sess1');
      const l2 = document.getElementById('beh-label-sess2');
      if (isSess1) {
        l1.style.borderColor = '#2563EB';
        l1.style.background = '#EFF6FF';
        l2.style.borderColor = '#E2E8F0';
        l2.style.background = '#FFFFFF';
      } else {
        l1.style.borderColor = '#E2E8F0';
        l1.style.background = '#FFFFFF';
        l2.style.borderColor = '#2563EB';
        l2.style.background = '#EFF6FF';
      }
    }

    function onBehalfDateChanged() {
      const isHalf = document.getElementById('beh-type-half').checked;
      const startDate = document.getElementById('beh-start-date').value;
      if (isHalf) {
        document.getElementById('beh-end-date').value = startDate;
        document.getElementById('beh-days').value = '0.5';
      } else {
        calculateBehalfDays();
      }
    }

    function calculateBehalfDays() {
      const start = document.getElementById('beh-start-date').value;
      const end = document.getElementById('beh-end-date').value;
      if (!start || !end) return;
      const d1 = new Date(start);
      const d2 = new Date(end);
      if (d2 < d1) {
        document.getElementById('beh-end-date').value = start;
        document.getElementById('beh-days').value = '1.0';
        return;
      }
      const diffDays = Math.round((d2 - d1) / (1000 * 60 * 60 * 24)) + 1;
      document.getElementById('beh-days').value = (diffDays > 0 ? diffDays : 1.0).toFixed(1);
    }

    async function handleApplyOnBehalfSubmit(e) {
      e.preventDefault();
      const empId = document.getElementById('beh-emp-id').value.trim();
      if (!empId) {
        alert('Please select an employee from the dropdown list.');
        const filterInput = document.getElementById('beh-emp-filter');
        if (filterInput) filterInput.focus();
        return;
      }

      const isHalfDay = document.getElementById('beh-type-half').checked;
      const session = isHalfDay ? (document.getElementById('beh-sess-1').checked ? 'Session 1' : 'Session 2') : null;
      const daysCount = isHalfDay ? 0.5 : parseFloat(document.getElementById('beh-days').value || 1.0);
      const startDate = document.getElementById('beh-start-date').value;
      const endDate = isHalfDay ? startDate : document.getElementById('beh-end-date').value;
      const leaveType = document.getElementById('beh-leave-type').value;
      const reason = document.getElementById('beh-reason').value.trim();

      const payload = {
        employee_id: empId,
        leave_type: leaveType,
        is_half_day: isHalfDay,
        session: session,
        days_count: daysCount,
        start_date: startDate,
        end_date: endDate,
        reason: reason
      };

      const submitBtn = document.getElementById('btn-beh-submit');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerText = 'Submitting...';
      }

      try {
        const res = await fetch('/api/admin/leaves/apply-on-behalf', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.success) {
          closeModal('modal-apply-behalf');
          showToast(d.message);
          switchLeavesSubtab('requests');
          const monthlyView = document.getElementById('view-monthly');
          if (monthlyView && monthlyView.style.display !== 'none') {
            loadMonthlyAttendance();
          }
        } else {
          alert(d.error || 'Failed to submit leave on behalf');
        }
      } catch (err) {
        alert('Failed to submit leave on behalf');
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerText = 'Apply & Approve Leave';
        }
      }
    }

    // ─── 5. Shifts Module Logic ──────────────────────────────────────────────
    async function loadShifts() {
      try {
        const res = await fetch('/api/admin/shifts', {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const shifts = await res.json();
        const container = document.getElementById('shifts-cards-container');

        container.innerHTML = shifts.map(s => `
          <div class="kpi-card">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
              <span class="badge ${s.is_night_shift ? 'badge-amber' : 'badge-blue'}">${s.is_night_shift ? '🌙 Overnight Shift' : '☀️ Standard Shift'}</span>
              <span style="font-size: 11px; color: var(--text-muted); font-weight: 600;">Grace: ${s.grace_period_mins}m</span>
            </div>
            <h3 style="font-size: 16px; font-weight: 800; color: #0F172A;">${escapeHtml(s.shift_name)}</h3>
            <div style="font-size: 20px; font-weight: 800; color: #2563EB; margin: 8px 0;">
              ${s.start_time} - ${s.end_time}
            </div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;">
              ${escapeHtml(s.description || 'Full day quota: ' + s.full_day_hours + ' hours')}
            </div>
            <div style="display: flex; align-items: center; justify-content: space-between; padding-top: 12px; border-top: 1px solid var(--border);">
              <span style="font-size: 11.5px; color: var(--text-muted);">Days: ${s.working_days}</span>
              <button class="btn btn-outline btn-sm" onclick="promptAssignShift(${s.id}, '${escapeHtml(s.shift_name)} (${s.start_time} - ${s.end_time})')">Assign to Staff</button>
            </div>
          </div>
        `).join('');

      } catch (err) {
        console.error('Error loading shifts:', err);
      }
    }

    async function promptAssignShift(shiftId, shiftTiming) {
      const empId = prompt(`Enter Employee ID to assign ${shiftTiming}:`);
      if (!empId) return;

      try {
        const res = await fetch('/api/admin/employees/assign-shift', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ employee_id: empId.trim(), shift_id: shiftId, shift_timing: shiftTiming })
        });
        const d = await res.json();
        if (d.success) showToast(d.message);
        else alert(d.error);
      } catch (err) {
        alert('Failed to assign shift');
      }
    }

    // ─── 6. GPS Tracking Module Logic ────────────────────────────────────────
    function setGpsFilter(filterType) {
      state.gpsFilter = filterType;
      document.querySelectorAll('.gps-filter-btn').forEach(b => b.classList.remove('active'));
      const activeBtn = Array.from(document.querySelectorAll('.gps-filter-btn')).find(b => b.getAttribute('onclick')?.includes(`'${filterType}'`));
      if (activeBtn) activeBtn.classList.add('active');
      renderGpsMarkersAndList();
    }

    function setGpsToday() {
      const el = document.getElementById('gps-date-filter');
      if (el) el.valueAsDate = new Date();
      loadGpsTracking();
    }

    async function loadGpsTracking() {
      try {
        const dateInput = document.getElementById('gps-date-filter');
        const selectedDate = dateInput ? dateInput.value : '';
        const url = selectedDate ? `/api/admin/gps/live-tracking?date=${selectedDate}` : '/api/admin/gps/live-tracking';

        const res = await fetch(url, {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const d = await res.json();
        if (d.error) {
          showToast('GPS Radar: ' + d.error);
          return;
        }

        state.gpsData = d;

        // Update Summary Stats
        if (document.getElementById('stat-gps-total')) {
          document.getElementById('stat-gps-total').innerText = d.total_tracked || 0;
          document.getElementById('stat-gps-phone-in').innerText = d.total_phone_checkins || 0;
          document.getElementById('stat-gps-phone-out').innerText = d.total_phone_checkouts || 0;
          document.getElementById('stat-gps-biometric').innerText = (d.total_tracked - (d.total_phone_punches || 0)) || 0;
          document.getElementById('stat-gps-outside').innerText = d.total_outside_geofence || 0;
        }

        // Initialize Map if not yet created
        if (!state.map) {
          const sq = d.geofence_square || {
            min_lat: 18.522450,
            max_lat: 18.524450,
            min_lng: 73.905150,
            max_lng: 73.907450,
            center_lat: 18.523450,
            center_lng: 73.906300
          };
          const centerLat = sq.center_lat || 18.523450;
          const centerLng = sq.center_lng || 73.906300;

          // ── Render Unified Campus Big Geofence Square (All 3 Office Locations) ──
          const squareBounds = [
            [sq.min_lat, sq.min_lng],
            [sq.max_lat, sq.max_lng]
          ];

          state.map = L.map('map');
          state.map.fitBounds(squareBounds, { padding: [35, 35] });
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
          }).addTo(state.map);

          const campusSquare = L.rectangle(squareBounds, {
            color: '#EF4444', // Red border indicating campus geofence boundary
            weight: 2,
            fillColor: '#10B981',
            fillOpacity: 0.05,
            dashArray: '6, 6'
          }).addTo(state.map);

          // Clickable popup on perimeter (no permanent floating card blocking the center)
          campusSquare.bindPopup(`
            <div style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 12px; text-align: center; padding: 4px;">
              <div style="font-weight: 800; color: #0F172A; font-size: 12.5px;">🏢 Unified Campus Geofence Zone</div>
              <div style="color: #059669; font-weight: 700; font-size: 11px; margin-top: 2px;">Verified Safe Boundary</div>
              <div style="color: #64748B; font-size: 10.5px; margin-top: 3px;">Morya Palace • KK Empire • Monarch House HQ</div>
            </div>
          `);

          // Render Headquarters Buildings Markers inside the square
          if (d.company_buildings) {
            d.company_buildings.forEach(b => {
              const bldgIcon = L.divIcon({
                className: 'custom-gps-pin',
                html: `
                  <div style="background: #0F172A; color: #FFFFFF; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 8px; box-shadow: 0 3px 8px rgba(0,0,0,0.3); border: 1.5px solid #38BDF8; white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; pointer-events: auto;">
                    🏢 <span>${escapeHtml(b.name)}</span>
                  </div>
                `,
                iconSize: [120, 26],
                iconAnchor: [60, 13]
              });

              L.marker([b.lat, b.lng], { icon: bldgIcon, zIndexOffset: 400 }).addTo(state.map)
                .bindPopup(`
                  <div style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 12.5px;">
                    <b style="color: #0F172A;">🏢 ${escapeHtml(b.name)}</b><br>
                    <span style="color: #64748B;">Monarch Campus Office Location</span>
                    <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 6px 0;">
                    <div style="color: #059669; font-weight: 700;">✅ Inside Unified Campus Geofence Square</div>
                    <div>Lat: ${b.lat.toFixed(6)}, Lng: ${b.lng.toFixed(6)}</div>
                  </div>
                `);
            });
          }
        }

        setTimeout(() => {
          if (state.map) {
            state.map.invalidateSize();
            if (d.geofence_square && (!state.gpsFilter || state.gpsFilter === 'all')) {
              const sq = d.geofence_square;
              state.map.fitBounds([
                [sq.min_lat, sq.min_lng],
                [sq.max_lat, sq.max_lng]
              ], { padding: [35, 35] });
            }
          }
        }, 150);

        renderGpsMarkersAndList();

      } catch (err) {
        console.error('Error loading GPS radar:', err);
      }
    }

    function renderGpsMarkersAndList() {
      if (!state.gpsData) return;
      const d = state.gpsData;

      // Clear existing markers & polylines
      if (state.mapMarkers) {
        state.mapMarkers.forEach(m => state.map.removeLayer(m));
      }
      state.mapMarkers = [];

      if (state.mapPolylines) {
        state.mapPolylines.forEach(l => state.map.removeLayer(l));
      }
      state.mapPolylines = [];

      // Filter events based on active filter
      const filter = state.gpsFilter || 'all';
      let filteredEvents = (d.events || []).filter(ev => {
        if (filter === 'phone_only') return ev.punch_type.startsWith('phone_');
        if (filter === 'phone_in') return ev.punch_type === 'phone_checkin';
        if (filter === 'phone_out') return ev.punch_type === 'phone_checkout';
        if (filter === 'biometric') return ev.punch_type === 'biometric';
        if (filter === 'out_geofence') return ev.in_geofence === false;
        return true;
      });

      const bounds = [];

      // Render Map Markers for filtered events
      filteredEvents.forEach(ev => {
        bounds.push([ev.latitude, ev.longitude]);

        let pinHtml = '';
        if (ev.punch_type === 'phone_checkin') {
          pinHtml = `
            <div style="position: relative; display: flex; align-items: center; justify-content: center; cursor: pointer;">
              <div class="pulse-ring" style="position: absolute; width: 34px; height: 34px; border-radius: 50%; background: rgba(16, 185, 129, 0.35);"></div>
              <div style="width: 26px; height: 26px; border-radius: 50%; background: #10B981; border: 2px solid #FFFFFF; box-shadow: 0 2px 6px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; color: #FFFFFF; font-size: 10px; font-weight: 800;">
                IN
              </div>
            </div>
          `;
        } else if (ev.punch_type === 'phone_checkout') {
          pinHtml = `
            <div style="position: relative; display: flex; align-items: center; justify-content: center; cursor: pointer;">
              <div class="pulse-ring" style="position: absolute; width: 34px; height: 34px; border-radius: 50%; background: rgba(59, 130, 246, 0.35);"></div>
              <div style="width: 26px; height: 26px; border-radius: 50%; background: #3B82F6; border: 2px solid #FFFFFF; box-shadow: 0 2px 6px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; color: #FFFFFF; font-size: 9px; font-weight: 800;">
                OUT
              </div>
            </div>
          `;
        } else {
          pinHtml = `
            <div style="width: 22px; height: 22px; border-radius: 50%; background: #64748B; border: 2px solid #FFFFFF; box-shadow: 0 1px 4px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; color: #FFFFFF; font-size: 11px;">
              🏢
            </div>
          `;
        }

        const customIcon = L.divIcon({
          className: 'custom-gps-pin',
          html: pinHtml,
          iconSize: [28, 28],
          iconAnchor: [14, 14]
        });

        const marker = L.marker([ev.latitude, ev.longitude], { icon: customIcon }).addTo(state.map);

        marker.bindTooltip(`
          <div style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11px; font-weight: 600; color: #0F172A; white-space: nowrap;">
            <b>${escapeHtml(ev.employee_name)}</b> • ${ev.punch_type === 'phone_checkin' ? '🟢 Check-In' : (ev.punch_type === 'phone_checkout' ? '🔵 Check-Out' : '🏢 Biometric')} (${escapeHtml(ev.punch_time)})
          </div>
        `, { direction: 'top', offset: [0, -14] });

        const badgeClass = ev.punch_type === 'phone_checkin' ? 'badge-green' : (ev.punch_type === 'phone_checkout' ? 'badge-blue' : 'badge-gray');
        const badgeIcon = ev.punch_type.startsWith('phone_') ? '📱' : '🏢';
        const geofenceText = ev.in_geofence
          ? `<span style="color: #059669; font-weight: 700;">✅ Within 40m Geofence</span>`
          : `<span style="color: #DC2626; font-weight: 700;">⚠️ Outside Geofence (${ev.distance_meters}m)</span>`;

        marker.bindPopup(`
          <div style="font-family: 'Plus Jakarta Sans', sans-serif; min-width: 220px; font-size: 12.5px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
              <span class="badge ${badgeClass}" style="font-size: 10px;">${badgeIcon} ${escapeHtml(ev.punch_label)}</span>
              <span style="font-size: 11px; font-weight: 700; color: #64748B;">${escapeHtml(ev.punch_time)}</span>
            </div>
            <div style="font-weight: 800; font-size: 14px; color: #0F172A;">${escapeHtml(ev.employee_name)}</div>
            <div style="font-size: 11.5px; color: #64748B; margin-bottom: 8px;">EMP #${escapeHtml(ev.employee_id)} • ${escapeHtml(ev.department)}</div>
            
            <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; font-size: 11.5px;">
              <div>Nearest Building: <b>${escapeHtml(ev.nearest_building)}</b></div>
              <div>Distance: <b>${ev.distance_meters}m</b></div>
              <div style="margin-top: 3px;">${geofenceText}</div>
              <div style="margin-top: 4px; font-size: 10.5px; color: #64748B;">GPS: ${ev.latitude.toFixed(6)}, ${ev.longitude.toFixed(6)}</div>
            </div>

            <a href="https://www.google.com/maps?q=${ev.latitude},${ev.longitude}" target="_blank" class="btn btn-secondary btn-sm" style="width: 100%; justify-content: center; font-size: 11.5px; padding: 5px 8px;">
              View on Google Maps ↗
            </a>
          </div>
        `);

        ev._marker = marker;
        state.mapMarkers.push(marker);
      });

      // Connect Phone Check-In & Phone Check-Out for employees with both punches
      (d.employees || []).forEach(emp => {
        if (emp.has_phone_in && emp.has_phone_out && emp.phone_in && emp.phone_out) {
          const latlngs = [
            [emp.phone_in.latitude, emp.phone_in.longitude],
            [emp.phone_out.latitude, emp.phone_out.longitude]
          ];
          const line = L.polyline(latlngs, {
            color: '#3B82F6',
            weight: 3,
            dashArray: '6, 6',
            opacity: 0.8
          }).addTo(state.map);

          line.bindTooltip(`📍 ${escapeHtml(emp.employee_name)} Movement Trail (In ➔ Out)`, {
            sticky: true,
            direction: 'top'
          });

          state.mapPolylines.push(line);
        }
      });

      // Adjust map view to encompass markers if available
      if (bounds.length > 0 && filter !== 'all') {
        state.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 18 });
      } else if (d.geofence_square) {
        const sq = d.geofence_square;
        state.map.fitBounds([
          [sq.min_lat, sq.min_lng],
          [sq.max_lat, sq.max_lng]
        ], { padding: [35, 35] });
      }

      renderGpsStaffList();
    }

    function renderGpsStaffList() {
      if (!state.gpsData) return;
      const d = state.gpsData;
      const search = (document.getElementById('gps-staff-search')?.value || '').toLowerCase().trim();
      const filter = state.gpsFilter || 'all';

      let staff = (d.employees || []).filter(emp => {
        if (search) {
          const matches = emp.employee_name.toLowerCase().includes(search) || emp.employee_id.toLowerCase().includes(search);
          if (!matches) return false;
        }
        if (filter === 'phone_only') return emp.has_any_phone;
        if (filter === 'phone_in') return emp.has_phone_in;
        if (filter === 'phone_out') return emp.has_phone_out;
        if (filter === 'biometric') return !emp.has_any_phone;
        if (filter === 'out_geofence') {
          const inOutGeo = (emp.phone_in && !emp.phone_in.in_geofence) || (emp.phone_out && !emp.phone_out.in_geofence);
          return inOutGeo;
        }
        return true;
      });

      const countEl = document.getElementById('gps-staff-count');
      if (countEl) countEl.innerText = `${staff.length} staff`;

      const listEl = document.getElementById('gps-staff-list');
      if (!listEl) return;

      if (staff.length === 0) {
        listEl.innerHTML = `
          <div style="text-align: center; color: var(--text-muted); padding: 30px 10px; font-size: 12.5px;">
            No employee punches match current filter.
          </div>
        `;
        return;
      }

      listEl.innerHTML = staff.map(emp => {
        let phoneBadges = '';
        if (emp.has_phone_in) {
          const inGeoPill = emp.phone_in.in_geofence 
            ? '<span class="badge badge-green" style="font-size: 9px;">✅ Within 40m</span>' 
            : `<span class="badge badge-red" style="font-size: 9px;">⚠️ Out (${emp.phone_in.distance_meters}m)</span>`;
          phoneBadges += `
            <div style="margin-top: 6px; padding: 6px 8px; background: #ECFDF5; border-radius: 6px; border: 1px solid #A7F3D0; font-size: 11px;">
              <div style="display: flex; align-items: center; justify-content: space-between;">
                <span style="font-weight: 700; color: #065F46;">📱 Phone Check-In: ${escapeHtml(emp.phone_in.punch_time)}</span>
                ${inGeoPill}
              </div>
              <div style="color: #047857; margin-top: 2px; font-size: 10.5px;">
                Near ${escapeHtml(emp.phone_in.nearest_building)} (${emp.phone_in.distance_meters}m)
              </div>
              <div style="display: flex; gap: 6px; margin-top: 5px;">
                <button class="btn btn-secondary btn-sm" onclick="focusGpsEvent('${emp.phone_in.event_id}')" style="padding: 2px 8px; font-size: 10px;">
                  📍 Zoom Check-In Pin
                </button>
                <a href="https://www.google.com/maps?q=${emp.phone_in.latitude},${emp.phone_in.longitude}" target="_blank" class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 10px;">
                  Map ↗
                </a>
              </div>
            </div>
          `;
        }
        if (emp.has_phone_out) {
          const outGeoPill = emp.phone_out.in_geofence 
            ? '<span class="badge badge-green" style="font-size: 9px;">✅ Within 40m</span>' 
            : `<span class="badge badge-red" style="font-size: 9px;">⚠️ Out (${emp.phone_out.distance_meters}m)</span>`;
          phoneBadges += `
            <div style="margin-top: 6px; padding: 6px 8px; background: #EFF6FF; border-radius: 6px; border: 1px solid #BFDBFE; font-size: 11px;">
              <div style="display: flex; align-items: center; justify-content: space-between;">
                <span style="font-weight: 700; color: #1E40AF;">📱 Phone Check-Out: ${escapeHtml(emp.phone_out.punch_time)}</span>
                ${outGeoPill}
              </div>
              <div style="color: #1D4ED8; margin-top: 2px; font-size: 10.5px;">
                Near ${escapeHtml(emp.phone_out.nearest_building)} (${emp.phone_out.distance_meters}m)
              </div>
              <div style="display: flex; gap: 6px; margin-top: 5px;">
                <button class="btn btn-secondary btn-sm" onclick="focusGpsEvent('${emp.phone_out.event_id}')" style="padding: 2px 8px; font-size: 10px;">
                  📍 Zoom Check-Out Pin
                </button>
                <a href="https://www.google.com/maps?q=${emp.phone_out.latitude},${emp.phone_out.longitude}" target="_blank" class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 10px;">
                  Map ↗
                </a>
              </div>
            </div>
          `;
        }

        if (!emp.has_phone_in && !emp.has_phone_out) {
          phoneBadges = `
            <div style="margin-top: 6px; padding: 6px 8px; background: #F8FAFC; border-radius: 6px; border: 1px solid var(--border); font-size: 11px;">
              <span style="font-weight: 600; color: #475569;">🏢 Biometric Machine</span>
              <div style="color: var(--text-muted); font-size: 10.5px; margin-top: 1px;">
                ${escapeHtml(emp.raw_location || 'Machine punch at Monarch House')}
              </div>
            </div>
          `;
        }

        return `
          <div style="padding: 10px 12px; background: #FFFFFF; border-radius: 10px; border: 1px solid var(--border); margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); transition: transform 0.1s ease;">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <div style="font-weight: 800; font-size: 13px; color: #0F172A;">${escapeHtml(emp.employee_name)}</div>
              <span class="badge ${emp.has_any_phone ? 'badge-amber' : 'badge-gray'}" style="font-size: 9.5px;">
                ${emp.has_any_phone ? '📱 MOBILE GPS' : '🏢 BIOMETRIC'}
              </span>
            </div>
            <div style="font-size: 11px; color: #64748B; margin-top: 1px;">
              EMP #${escapeHtml(emp.employee_id)} • ${escapeHtml(emp.department)}
            </div>
            ${phoneBadges}
          </div>
        `;
      }).join('');
    }

    function focusGpsEvent(eventId) {
      if (!state.gpsData || !state.gpsData.events) return;
      const ev = state.gpsData.events.find(e => e.event_id === eventId);
      if (ev && state.map) {
        state.map.flyTo([ev.latitude, ev.longitude], 18, { duration: 1.0 });
        if (ev._marker) {
          setTimeout(() => ev._marker.openPopup(), 1100);
        }
      }
    }

    // ─── 7. Unified Requests Module Logic ────────────────────────────────────
    async function loadAllRequests() {
      try {
        const res = await fetch('/api/admin/all-requests', {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const d = await res.json();
        document.getElementById('requests-pending-count').innerText = `${d.total_pending} Pending`;
        const tb = document.getElementById('table-all-requests-body');

        if (!d.requests || d.requests.length === 0) {
          tb.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 30px;">All requests have been reviewed and approved!</td></tr>';
          return;
        }

        tb.innerHTML = d.requests.map(r => `
          <tr>
            <td><span class="badge ${r.type === 'leave' ? 'badge-blue' : 'badge-amber'}">${r.type === 'leave' ? 'Leave Application' : 'Punch Correction'}</span></td>
            <td>
              <div style="font-weight: 700; color: #0F172A;">${escapeHtml(r.employee_name)}</div>
              <div style="font-size: 11px; color: var(--text-muted);">#${r.employee_id} • ${escapeHtml(r.department)} • ${escapeHtml(r.designation || 'Staff')}</div>
              <div style="font-size: 10.5px; color: #2563EB; font-weight: 600; margin-top: 2px;">
                👤 Mgr: ${escapeHtml(r.reporting_manager || '--')}
              </div>
            </td>
            <td style="font-weight: 600;">${escapeHtml(r.title)}</td>
            <td>${escapeHtml(r.details)}</td>
            <td>${escapeHtml(r.reason)}</td>
            <td>${r.applied_at.substring(0, 10)}</td>
            <td>
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-primary btn-sm" onclick="quickApproveRequest('${r.type}', ${r.id})">Approve</button>
                <button class="btn btn-outline btn-sm" style="color: #DC2626;" onclick="quickRejectRequest('${r.type}', ${r.id})">Reject</button>
              </div>
            </td>
          </tr>
        `).join('');

      } catch (err) {
        console.error('Error loading requests:', err);
      }
    }

    async function quickApproveRequest(type, id) {
      const comment = prompt('Approval comment (Optional):', 'Approved by administrator');
      if (comment === null) return;
      const url = (type === 'leave') ? `/api/admin/leave-requests/${id}/review` : `/api/admin/corrections/${id}/review`;
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ action: 'approve', reason: comment, comments: comment })
        });
        const d = await res.json();
        if (d.success) {
          showToast('Request approved successfully.');
          loadAllRequests();
        } else alert(d.error);
      } catch (err) {
        alert('Action failed');
      }
    }

    async function quickRejectRequest(type, id) {
      const reason = prompt('Mandatory rejection reason:');
      if (!reason) return alert('Mandatory reason required');
      const url = (type === 'leave') ? `/api/admin/leave-requests/${id}/review` : `/api/admin/corrections/${id}/review`;
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ action: 'reject', reason: reason, comments: reason })
        });
        const d = await res.json();
        if (d.success) {
          showToast('Request rejected.');
          loadAllRequests();
        } else alert(d.error);
      } catch (err) {
        alert('Action failed');
      }
    }

    // ─── 8. Holidays Module Logic ────────────────────────────────────────────
    async function loadHolidays() {
      try {
        const res = await fetch('/api/holidays', {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const holidays = await res.json();
        const tb = document.getElementById('table-holidays-body');
        tb.innerHTML = holidays.map(h => `
          <tr>
            <td style="font-weight: 700; color: #0F172A;">${h.date}</td>
            <td>${h.weekday}</td>
            <td style="font-weight: 700;">${escapeHtml(h.title)}</td>
            <td><span class="badge badge-green">Paid Public Holiday</span></td>
          </tr>
        `).join('');
      } catch (err) {
        console.error('Error loading holidays:', err);
      }
    }

    function openAddHolidayModal() {
      document.getElementById('inp-holiday-title').value = '';
      const dateInp = document.getElementById('inp-holiday-date');
      const today = new Date();
      dateInp.valueAsDate = today;
      updateHolidayWeekday(today);
      showModal('modal-add-holiday');
      if (window.lucide) lucide.createIcons();
    }

    function handleHolidayDateChange(e) {
      const val = e.target.value;
      if (!val) {
        document.getElementById('inp-holiday-weekday').value = '';
        return;
      }
      const parts = val.split('-');
      if (parts.length === 3) {
        const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        updateHolidayWeekday(d);
      }
    }

    function updateHolidayWeekday(dateObj) {
      const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
      const dayName = days[dateObj.getDay()] || '';
      document.getElementById('inp-holiday-weekday').value = dayName;
    }

    async function handleAddHolidaySubmit(e) {
      e.preventDefault();
      const title = document.getElementById('inp-holiday-title').value.trim();
      const hDate = document.getElementById('inp-holiday-date').value;
      const weekday = document.getElementById('inp-holiday-weekday').value || 'Sunday';

      if (!title || !hDate) {
        alert('Please provide holiday title and date.');
        return;
      }

      const btn = document.getElementById('btn-save-holiday');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner" style="width: 14px; height: 14px; border-width: 2px; display: inline-block; vertical-align: middle; margin-right: 6px;"></span> Adding...';

      try {
        const res = await fetch('/api/admin/holidays', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ title: title, date: hDate, weekday: weekday })
        });
        const d = await res.json();
        if (d.id || d.date) {
          closeModal('modal-add-holiday');
          showToast(`Holiday "${title}" added to calendar.`);
          loadHolidays();
        } else {
          alert(d.error || 'Failed to add holiday.');
        }
      } catch (err) {
        alert('Failed to add holiday: ' + err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="plus" style="width: 14px; height: 14px;"></i> <span>Add Holiday</span>';
        if (window.lucide) lucide.createIcons();
      }
    }

    // ─── 9. Audit Logs Module Logic ──────────────────────────────────────────
    async function loadAuditLogs() {
      try {
        const res = await fetch('/api/admin/audit-logs', {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const logs = await res.json();
        const tb = document.getElementById('table-audit-body');
        if (!logs || logs.length === 0) {
          tb.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 30px;">No audit records found.</td></tr>';
          return;
        }

        tb.innerHTML = logs.map(l => `
          <tr>
            <td style="font-size: 12px; color: var(--text-muted);">${l.timestamp.replace('T', ' ').substring(0, 19)}</td>
            <td>
              <div style="font-weight: 700; color: #0F172A;">${escapeHtml(l.actor_name)}</div>
              <div style="font-size: 11px; color: var(--text-muted);">#${l.actor_id} • ${l.ip_address}</div>
            </td>
            <td><span class="badge badge-blue">${l.action}</span></td>
            <td>${l.target_type} #${l.target_id || '--'}</td>
            <td>${escapeHtml(l.reason || 'Administrative Action')}</td>
            <td>
              <button class="btn btn-outline btn-sm" onclick='viewAuditDiff(${JSON.stringify(l.before_value)}, ${JSON.stringify(l.after_value)})'>View Diff</button>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        console.error('Error loading audit trail:', err);
      }
    }

    function viewAuditDiff(before, after) {
      alert(`AUDIT RECORD DIFF:\n\nBEFORE:\n${JSON.stringify(before, null, 2)}\n\nAFTER:\n${JSON.stringify(after, null, 2)}`);
    }

    // ─── 10. Reports CSV Downloader ──────────────────────────────────────────
    function downloadReport(type) {
      const today = document.getElementById('att-date-picker').value || new Date().toISOString().substring(0, 10);
      const url = `/api/admin/reports/export?type=${type}&start_date=${today}&end_date=${today}`;
      
      // Fetch with auth header and trigger browser download
      fetch(url, { headers: { 'Authorization': `Bearer ${state.token}` } })
        .then(res => {
          if (!res.ok) throw new Error('Download failed');
          return res.blob();
        })
        .then(blob => {
          const a = document.createElement('a');
          a.href = window.URL.createObjectURL(blob);
          a.download = `${type}_${today}.csv`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          showToast(`Report ${type} downloaded successfully.`);
        })
        .catch(err => alert('Failed to download report: ' + err));
    }

    // ─── Modal Helpers ───────────────────────────────────────────────────────
    function showModal(id) {
      const el = document.getElementById(id);
      if (el) el.classList.add('active');
    }
    function closeModal(id) {
      const el = document.getElementById(id);
      if (el) el.classList.remove('active');
    }
    let _reportingManagersCache = null;

    async function populateReportingManagersDropdown(selectedVal = '') {
      const sel = document.getElementById('inp-emp-mgr');
      if (!sel) return;

      if (!_reportingManagersCache) {
        try {
          const res = await fetch('/api/admin/reporting-managers', {
            headers: { 'Authorization': `Bearer ${state.token}` }
          });
          const d = await res.json();
          if (d.success && d.managers) {
            _reportingManagersCache = d.managers;
          }
        } catch (err) {
          console.warn('Failed to fetch reporting managers:', err);
        }
      }

      let html = '<option value="">-- Select Reporting Manager --</option>';
      html += '<option value="Direct Management">Direct Management</option>';

      if (_reportingManagersCache && _reportingManagersCache.length > 0) {
        _reportingManagersCache.forEach(m => {
          const label = m.department ? `${m.name} (${m.department})` : (m.designation ? `${m.name} - ${m.designation}` : m.name);
          const isSel = (selectedVal && selectedVal.toLowerCase() === m.name.toLowerCase()) ? 'selected' : '';
          html += `<option value="${escapeHtml(m.name)}" ${isSel}>${escapeHtml(label)}</option>`;
        });
      }

      html += '<option value="__custom__">➕ Other / Enter Custom Name...</option>';
      sel.innerHTML = html;

      sel.onchange = function() {
        const customInp = document.getElementById('inp-emp-mgr-custom');
        if (customInp) {
          if (this.value === '__custom__') {
            customInp.style.display = 'block';
            customInp.focus();
          } else {
            customInp.style.display = 'none';
            customInp.value = '';
          }
        }
      };
    }

    function openAddEmployeeModal() {
      document.getElementById('inp-emp-no').value = '';
      document.getElementById('inp-emp-name').value = '';
      document.getElementById('inp-emp-email').value = '';
      document.getElementById('inp-emp-phone').value = '';
      document.getElementById('inp-emp-dept').value = '';
      document.getElementById('inp-emp-desig').value = '';
      const customInp = document.getElementById('inp-emp-mgr-custom');
      if (customInp) { customInp.style.display = 'none'; customInp.value = ''; }
      populateReportingManagersDropdown('');
      document.getElementById('inp-emp-doj').valueAsDate = new Date();
      showModal('modal-add-employee');
    }

    // ─── Weekly Master Excel Upload & Preview ─────────────────────────────────
    let _stagedNewEmployees = [];

    function openUploadExcelModal() {
      resetUploadExcelModal();
      showModal('modal-upload-excel');
      if (window.lucide) lucide.createIcons();
    }

    function resetUploadExcelModal() {
      _stagedNewEmployees = [];
      const fileInput = document.getElementById('excel-file-input');
      if (fileInput) fileInput.value = '';
      const nameDisplay = document.getElementById('excel-filename-display');
      if (nameDisplay) nameDisplay.innerText = 'No file chosen';
      const scanBtn = document.getElementById('excel-upload-btn-scan');
      if (scanBtn) {
        scanBtn.disabled = true;
        scanBtn.innerHTML = '<i data-lucide="scan-line" style="width: 14px; height: 14px;"></i> <span>Scan &amp; Map Employees</span>';
      }
      const previewStep = document.getElementById('excel-preview-step');
      if (previewStep) previewStep.style.display = 'none';
      const initialStep = document.getElementById('excel-initial-step');
      if (initialStep) initialStep.style.display = 'block';
      const confirmBtn = document.getElementById('btn-confirm-excel-import');
      if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<i data-lucide="user-plus" style="width: 14px; height: 14px;"></i> <span>Confirm &amp; Add New Employees</span>';
      }
      const tbody = document.getElementById('excel-preview-table-body');
      if (tbody) tbody.innerHTML = '';
      if (window.lucide) lucide.createIcons();
    }

    function handleExcelFileChange(e) {
      const file = e.target.files[0];
      const nameDisplay = document.getElementById('excel-filename-display');
      const scanBtn = document.getElementById('excel-upload-btn-scan');
      if (file) {
        nameDisplay.innerHTML = `<strong>${escapeHtml(file.name)}</strong> (${(file.size / 1024).toFixed(1)} KB)`;
        scanBtn.disabled = false;
      } else {
        nameDisplay.innerText = 'No file chosen';
        scanBtn.disabled = true;
      }
    }

    async function handleExcelPreviewUpload() {
      const fileInput = document.getElementById('excel-file-input');
      if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        alert('Please select an Excel (.xlsx or .xls) file first.');
        return;
      }
      const file = fileInput.files[0];
      const scanBtn = document.getElementById('excel-upload-btn-scan');
      scanBtn.disabled = true;
      scanBtn.innerHTML = '<span class="spinner" style="width: 14px; height: 14px; border-width: 2px; display: inline-block; vertical-align: middle; margin-right: 6px;"></span> <span>Scanning Excel...</span>';

      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch('/api/admin/employees/upload-excel/preview', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${state.token}`
          },
          body: formData
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || 'Failed to scan Excel file');
        }

        _stagedNewEmployees = data.new_employees || [];

        // Update counts
        document.getElementById('excel-stat-new-count').innerText = data.new_count;
        document.getElementById('excel-stat-skipped-count').innerText = data.skipped_count;
        document.getElementById('excel-stat-current-count').innerText = data.existing_db_count;
        document.getElementById('excel-stat-total-after').innerText = data.total_after_adding;

        // Render preview banner & table
        const tbody = document.getElementById('excel-preview-table-body');
        const banner = document.getElementById('excel-status-banner');
        const confirmBtn = document.getElementById('btn-confirm-excel-import');

        if (data.new_count === 0) {
          banner.style.display = 'block';
          banner.style.background = '#F1F5F9';
          banner.style.border = '1px solid #CBD5E1';
          banner.style.color = '#334155';
          banner.innerHTML = `<strong>100% Up to Date:</strong> All ${data.skipped_count} employees in this Excel file already exist in the database. <strong>0 new employees</strong> to add, so all previous records will remain completely untouched.`;
          confirmBtn.disabled = true;
          tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 24px; color: #64748B;">No brand-new employees found in this file. All records already exist in the database and are preserved without modification.</td></tr>';
        } else {
          banner.style.display = 'block';
          banner.style.background = '#ECFDF5';
          banner.style.border = '1px solid #A7F3D0';
          banner.style.color = '#065F46';
          banner.innerHTML = `<strong>Ready for Confirmation:</strong> Found <strong>${data.new_count} brand-new employee(s)</strong>. Previous employees (${data.skipped_count}) will <strong>NOT be touched</strong>. Click "Confirm &amp; Add New Employees" below to insert them into the system.`;
          confirmBtn.disabled = false;
          confirmBtn.innerHTML = `<i data-lucide="user-plus" style="width: 14px; height: 14px;"></i> <span>Confirm &amp; Add ${data.new_count} New Employees</span>`;

          let rowsHtml = '';
          _stagedNewEmployees.forEach(emp => {
            rowsHtml += `
              <tr>
                <td style="font-weight: 700; color: #1E40AF;">#${emp.employee_no}</td>
                <td style="font-weight: 600;">${escapeHtml(emp.name)}</td>
                <td><span style="font-size: 11.5px; padding: 2px 7px; border-radius: 4px; background: #F1F5F9; color: #475569;">${escapeHtml(emp.department)}</span></td>
                <td>${escapeHtml(emp.designation)}</td>
                <td style="color: #047857; font-weight: 500;">${escapeHtml(emp.reporting_manager)}</td>
                <td style="font-size: 12px; color: #64748B;">${escapeHtml(emp.date_of_joining)}</td>
                <td style="font-size: 11.5px; color: #475569;">${escapeHtml(emp.shift_timing)}</td>
              </tr>
            `;
          });
          tbody.innerHTML = rowsHtml;
        }

        document.getElementById('excel-preview-step').style.display = 'block';
        if (window.lucide) lucide.createIcons();
      } catch (err) {
        alert('Upload / Scan Error: ' + err.message);
      } finally {
        scanBtn.disabled = false;
        scanBtn.innerHTML = '<i data-lucide="scan-line" style="width: 14px; height: 14px;"></i> <span>Re-Scan File</span>';
        if (window.lucide) lucide.createIcons();
      }
    }

    async function confirmExcelImport() {
      if (!_stagedNewEmployees || _stagedNewEmployees.length === 0) {
        alert('No new employees staged for addition.');
        return;
      }

      const totalAfter = document.getElementById('excel-stat-total-after').innerText;
      if (!confirm(`Are you sure you want to add ${_stagedNewEmployees.length} new employee(s)?\n\n• Existing employees: Kept untouched\n• Total employees after addition: ${totalAfter}\n\nProceed with adding to database?`)) {
        return;
      }

      const confirmBtn = document.getElementById('btn-confirm-excel-import');
      confirmBtn.disabled = true;
      confirmBtn.innerHTML = '<span class="spinner" style="width: 14px; height: 14px; border-width: 2px; display: inline-block; vertical-align: middle; margin-right: 6px;"></span> <span>Adding Employees...</span>';

      try {
        const res = await fetch('/api/admin/employees/upload-excel/confirm', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${state.token}`
          },
          body: JSON.stringify({ new_employees: _stagedNewEmployees })
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || 'Failed to confirm employee import');
        }

        showToast(data.message || `Successfully added ${data.added_count} new employees! Total employees: ${data.total_employees}`);
        closeModal('modal-upload-excel');

        // Refresh employee master table & dropdowns
        _reportingManagersCache = null;
        if (typeof refreshCurrentTab === 'function') {
          refreshCurrentTab();
        }
        if (typeof loadEmployees === 'function') {
          loadEmployees(1);
        }
      } catch (err) {
        alert('Confirmation Error: ' + err.message);
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = '<i data-lucide="user-plus" style="width: 14px; height: 14px;"></i> <span>Confirm &amp; Add New Employees</span>';
        if (window.lucide) lucide.createIcons();
      }
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      document.getElementById('toast-msg').innerText = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 3500);
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
  </script>
</body>
</html>
"""


register_admin_dashboard(
    app,
    get_monarch_connection=get_monarch_connection,
    get_db_connection=get_db_connection,
    token_required=token_required,
    admin_required=admin_required,
    format_monarch_user=format_monarch_user,
    load_monarch_users_map=load_monarch_users_map,
    get_ist_today=get_ist_today,
    get_ist_now=get_ist_now,
    jwt_secret=JWT_SECRET
)


# ─── Biometric Sync Service Core ───────────────────────────────────────────────
def discover_devicelogs_tables(monarch_conn, min_year=2026, min_month=9):
    """Dynamically finds all active monthly devicelogs tables in Monarch DB public schema from September 2026 onward."""
    cur = monarch_conn.cursor()
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
          AND table_name ~* '^devicelogs?_\\d{1,2}_\\d{4}$';
    """)
    raw_tables = [r['table_name'] for r in cur.fetchall()]
    cur.close()

    pattern = re.compile(r"^devicelogs?_(\d{1,2})_(\d{4})$", re.IGNORECASE)
    valid_tables = []

    for t in raw_tables:
        m = pattern.match(t)
        if m:
            month, year = int(m.group(1)), int(m.group(2))
            if (year, month) >= (min_year, min_month):
                valid_tables.append((year * 100 + month, t))

    valid_tables.sort(key=lambda x: x[0])
    return [t[1] for t in valid_tables]


def replicate_to_data_schema(table_name, monarch_conn):
    """
    Copies new punch records from public.{table_name} into data.{table_name}.
    Guarantees that existing rows in data.{table_name} will NEVER be overwritten,
    preserving any manual edits or customizations made in the data schema.
    """
    cur = monarch_conn.cursor()
    try:
        cur.execute("CREATE SCHEMA IF NOT EXISTS data;")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS data."{table_name}" (
                LIKE public."{table_name}" INCLUDING ALL
            );
        """)

        # Safeguard 1: Auto-relocate any mobile punches in data that have IDs < 90,000,000 so they never block physical machine logs
        cur.execute(f"""
            UPDATE data."{table_name}"
            SET devicelogid = devicelogid + 90000000
            WHERE deviceid = 99 AND devicelogid < 90000000;
        """)

        # Safeguard 2: Direct replication of new records from public into data
        cur.execute(f"""
            INSERT INTO data."{table_name}"
            SELECT p.* FROM public."{table_name}" p
            WHERE NOT EXISTS (
                SELECT 1 FROM data."{table_name}" d
                WHERE d.devicelogid = p.devicelogid
            )
            ON CONFLICT (devicelogid) DO NOTHING;
        """)

        # Safeguard 3: Fail-safe verification - if any physical punch (userid, logdate, deviceid) is still missing in data, insert it with a safe ID
        cur.execute(f"""
            INSERT INTO data."{table_name}" (
                devicelogid, downloaddate, deviceid, userid, logdate, direction,
                verificationmode, isapproved, logrecordlocation, attenndancemarkingtype
            )
            SELECT 
                (COALESCE((SELECT MAX(devicelogid) FROM data."{table_name}"), 0) + ROW_NUMBER() OVER ()),
                p.downloaddate, p.deviceid, p.userid, p.logdate, p.direction,
                p.verificationmode, p.isapproved, p.logrecordlocation, p.attenndancemarkingtype
            FROM public."{table_name}" p
            WHERE NOT EXISTS (
                SELECT 1 FROM data."{table_name}" d
                WHERE d.userid = p.userid AND d.logdate = p.logdate AND d.deviceid = p.deviceid
            );
        """)

        monarch_conn.commit()
    except Exception as e:
        monarch_conn.rollback()
        logger.warning(f"Replication to data.{table_name} notice: {e}")
    finally:
        cur.close()


def sync_biometric_table(table_name, monarch_conn, app_conn, users_map, since_date=None):
    """
    Processes devicelogs table:
    1. Replicates punches from public.{table_name} to data.{table_name} WITHOUT overwriting any existing records in data schema.
    2. Reads punches directly from data.{table_name} (with fallback to public) to compute daily attendance.
    """
    # Step 1: Copy to schema 'data' without overwriting existing data
    replicate_to_data_schema(table_name, monarch_conn)

    # Step 2: Read punches directly from schema 'data' (where Admin/HR can adjust timings without overwriting)
    rows = []
    cur_read = monarch_conn.cursor(cursor_factory=RealDictCursor)
    try:
        if since_date:
            cur_read.execute(f"""
                SELECT devicelogid, deviceid, userid, logdate, isapproved, direction
                FROM data."{table_name}"
                WHERE userid IS NOT NULL AND logdate >= %s
                ORDER BY logdate ASC;
            """, (since_date,))
        else:
            cur_read.execute(f"""
                SELECT devicelogid, deviceid, userid, logdate, isapproved, direction
                FROM data."{table_name}"
                WHERE userid IS NOT NULL AND logdate IS NOT NULL
                ORDER BY logdate ASC;
            """)
        rows = cur_read.fetchall()
    except Exception:
        monarch_conn.rollback()
        try:
            if since_date:
                cur_read.execute(f"""
                    SELECT devicelogid, deviceid, userid, logdate, isapproved, direction
                    FROM public."{table_name}"
                    WHERE userid IS NOT NULL AND logdate >= %s
                    ORDER BY logdate ASC;
                """, (since_date,))
            else:
                cur_read.execute(f"""
                    SELECT devicelogid, deviceid, userid, logdate, isapproved, direction
                    FROM public."{table_name}"
                    WHERE userid IS NOT NULL AND logdate IS NOT NULL
                    ORDER BY logdate ASC;
                """)
            rows = cur_read.fetchall()
        except Exception:
            monarch_conn.rollback()
            rows = []
    finally:
        cur_read.close()

    if not rows:
        return 0, 0

    user_date_groups = defaultdict(list)

    for r in rows:
        uid = str(r['userid']).strip()
        ldate = r['logdate']
        if not ldate:
            continue
        dt_key = ldate.date()
        user_date_groups[(uid, dt_key)].append(r)

    cur_app = app_conn.cursor(cursor_factory=RealDictCursor)
    inserted_count = 0
    updated_count = 0

    for (uid, date_val), punches in user_date_groups.items():
        punches.sort(key=lambda x: x['logdate'])
        first_punch = punches[0]
        last_punch = punches[-1] if len(punches) > 1 else None

        in_time = first_punch['logdate'].time().replace(microsecond=0)
        in_device_id = first_punch['deviceid']

        out_time = last_punch['logdate'].time().replace(microsecond=0) if last_punch else None
        out_device_id = last_punch['deviceid'] if last_punch else None

        # Check geofence approval from the punch records
        first_is_appr = (first_punch.get('isapproved') != 0)
        last_is_appr = (last_punch.get('isapproved') != 0) if last_punch else True

        in_geo = first_is_appr
        out_geo = last_is_appr if last_punch else True

        clean_uid = uid.lstrip('0')
        uinfo = users_map.get(uid) or users_map.get(clean_uid) or {
            'employee_no': uid,
            'emp_id': uid,
            'name': f"Employee {uid}",
            'department': 'Engineering',
            'role': 'Employee'
        }

        emp_id = str(uinfo.get('employee_no') or uinfo.get('emp_id') or uid)
        emp_name = uinfo.get('name') or uinfo.get('full_name') or f"Employee {emp_id}"
        dept = uinfo.get('department') or 'Engineering'
        role = uinfo.get('role') or 'Employee'
        user_role = normalize_role(role)

        is_exempt = (
            clean_uid == '1228' 
            or str(emp_id).strip().lstrip('0') == '1228' 
            or uinfo.get('is_location_bound') is False
        )

        if (in_geo and out_geo) or is_exempt:
            initial_approval = 'Approved'
        else:
            if user_role == 'teamleader':
                initial_approval = 'Pending Manager Approval'
            elif user_role in ['seniorteamleader', 'manager', 'admin']:
                initial_approval = 'Pending Manager Approval'
            else:
                initial_approval = 'Pending TL Approval'

        if in_device_id and out_device_id:
            if in_device_id == 99 and out_device_id == 99:
                location_str = "Mobile Phone (GPS)"
            elif in_device_id == 99:
                location_str = f"Mobile GPS (In) + Biometric #{out_device_id} (Out)"
            elif out_device_id == 99:
                location_str = f"Biometric #{in_device_id} (In) + Mobile GPS (Out)"
            else:
                location_str = f"Biometric Machine (In #{in_device_id}, Out #{out_device_id})"
        elif in_device_id:
            if in_device_id == 99:
                location_str = "Mobile Phone (GPS)"
            else:
                location_str = f"Biometric Machine (In #{in_device_id})"
        else:
            location_str = "Biometric Machine"

        cur_app.execute("""
            INSERT INTO attendance (
                employee_id, employee_name, date, sign_in, sign_out,
                location, in_geofence, clock_out_in_geofence, department, role, approval_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (employee_id, date) DO UPDATE SET
                sign_in = CASE 
                    WHEN attendance.is_manually_corrected = TRUE AND attendance.sign_in IS NOT NULL
                        THEN attendance.sign_in
                    WHEN attendance.sign_in IS NOT NULL AND EXCLUDED.sign_in IS NOT NULL 
                        THEN LEAST(attendance.sign_in, EXCLUDED.sign_in)
                    ELSE COALESCE(attendance.sign_in, EXCLUDED.sign_in)
                END,
                sign_out = CASE 
                    WHEN attendance.is_manually_corrected = TRUE AND attendance.sign_out IS NOT NULL
                        THEN attendance.sign_out
                    WHEN attendance.sign_out IS NOT NULL AND EXCLUDED.sign_out IS NOT NULL 
                        THEN GREATEST(attendance.sign_out, EXCLUDED.sign_out)
                    ELSE COALESCE(attendance.sign_out, EXCLUDED.sign_out)
                END,
                clock_out_lat = attendance.clock_out_lat,
                clock_out_lng = attendance.clock_out_lng,
                clock_out_distance_meters = attendance.clock_out_distance_meters,
                employee_name = COALESCE(EXCLUDED.employee_name, attendance.employee_name),
                department = COALESCE(EXCLUDED.department, attendance.department),
                role = COALESCE(EXCLUDED.role, attendance.role),
                location = CASE
                    WHEN attendance.location LIKE 'Biometric%%' AND EXCLUDED.location LIKE 'Biometric%%'
                        THEN EXCLUDED.location
                    WHEN attendance.location IS NOT NULL AND (
                        attendance.location ILIKE '%%' || EXCLUDED.location || '%%'
                        OR (EXCLUDED.location = 'Mobile Phone (GPS)' AND attendance.location NOT LIKE 'Biometric%%')
                        OR (EXCLUDED.location LIKE '%%Biometric%%' AND attendance.location LIKE '%%Biometric%%')
                    ) THEN attendance.location
                    WHEN attendance.location IS NOT NULL 
                         AND attendance.location NOT LIKE '%%Biometric%%' 
                         AND EXCLUDED.location LIKE '%%Biometric%%'
                        THEN attendance.location || ' + ' || EXCLUDED.location
                    ELSE COALESCE(attendance.location, EXCLUDED.location)
                END,
                in_geofence = CASE
                    WHEN attendance.clock_in_lat IS NOT NULL THEN attendance.in_geofence
                    ELSE EXCLUDED.in_geofence
                END,
                clock_out_in_geofence = CASE
                    WHEN attendance.clock_out_lat IS NOT NULL THEN attendance.clock_out_in_geofence
                    ELSE EXCLUDED.clock_out_in_geofence
                END,
                approval_status = CASE
                    WHEN attendance.approval_status IN ('Approved', 'Rejected') AND (attendance.reviewed_by IS NOT NULL OR attendance.reviewed_at IS NOT NULL)
                        THEN attendance.approval_status
                    WHEN EXCLUDED.in_geofence = FALSE OR EXCLUDED.clock_out_in_geofence = FALSE OR attendance.in_geofence = FALSE OR attendance.clock_out_in_geofence = FALSE
                        THEN EXCLUDED.approval_status
                    ELSE COALESCE(attendance.approval_status, EXCLUDED.approval_status, 'Approved')
                END
            RETURNING (xmax = 0) AS is_insert;
        """, (emp_id, emp_name, date_val, in_time, out_time, location_str, in_geo, out_geo, dept, role, initial_approval))
        
        row_res = cur_app.fetchone()
        if row_res and row_res.get('is_insert'):
            inserted_count += 1
        else:
            updated_count += 1

    app_conn.commit()
    cur_app.close()

    if inserted_count > 0 or updated_count > 0:
        logger.info(f"[SUCCESS] Table Monarch.{table_name} synced to attendance! (New Inserts: {inserted_count}, Updated/Verified: {updated_count})")
    return inserted_count, updated_count


def run_full_biometric_sync():
    """Syncs all discovered biometric tables from Monarch DB into attendance table."""
    logger.info("=" * 60)
    logger.info("[START] STARTING BIOMETRIC ATTENDANCE SYNC PROCESS")
    logger.info(f"   Monarch DB (Device Logs & Users) : {MONARCH_DB_URI.split('@')[-1]}")
    logger.info(f"   Monarch DB (Attendance Table)    : {DB_URI.split('@')[-1]}")
    logger.info("=" * 60)

    try:
        monarch_conn = get_monarch_connection()
        app_conn = get_db_connection()

        tables = discover_devicelogs_tables(monarch_conn, min_year=2026, min_month=9)
        logger.info(f"Discovered Monarch biometric tables: {tables}")

        if not tables:
            logger.warning("No devicelogs tables found in Monarch database.")
            monarch_conn.close()
            app_conn.close()
            return {'success': False, 'error': 'No devicelogs tables found in Monarch database'}

        users_map = load_monarch_users_map()

        total_inserted = 0
        total_updated = 0

        for tbl in tables:
            ins, upd = sync_biometric_table(tbl, monarch_conn, app_conn, users_map)
            total_inserted += ins
            total_updated += upd

        monarch_conn.close()
        app_conn.close()

        logger.info("=" * 60)
        logger.info("[SUCCESS] BIOMETRIC SYNC COMPLETED SUCCESSFULLY!")
        logger.info(f"   Total New Inserted Records : {total_inserted}")
        logger.info(f"   Total Updated/Verified     : {total_updated}")
        logger.info("=" * 60)
        return {'success': True, 'inserted': total_inserted, 'updated': total_updated, 'tables': tables}

    except Exception as e:
        logger.error(f"[ERROR] Error during biometric sync: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def run_incremental_biometric_sync():
    """Lightweight sync for background loop: checks current month table for punches in the last 48 hours."""
    try:
        monarch_conn = get_monarch_connection()
        app_conn = get_db_connection()

        today = get_ist_today()
        active_tbl = f"devicelogs_{today.month}_{today.year}"
        since_dt = datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time.min)

        users_map = load_monarch_users_map()
        ins, upd = sync_biometric_table(active_tbl, monarch_conn, app_conn, users_map, since_date=since_dt)

        monarch_conn.close()
        app_conn.close()
        return ins, upd
    except Exception as e:
        logger.error(f"Incremental biometric sync error: {e}")
        return 0, 0


@app.route('/api/sync/biometric', methods=['GET', 'POST'])
def trigger_biometric_sync():
    """
    Triggers biometric sync from local Monarch DB (devicelogs_M_YYYY) 
    into Monarch DB (data.attendance).
    """
    try:
        res = run_full_biometric_sync()
        return jsonify(res)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def start_background_biometric_sync():
    """Starts background thread syncing biometric machines in real-time."""
    import threading
    import time

    def sync_loop():
        time.sleep(2)  # initial brief delay
        # Run one full sync at server startup
        try:
            run_full_biometric_sync()
        except Exception as e:
            logger.error(f"Startup full biometric sync error: {e}")

        # Continuous lightweight real-time sync every 10 seconds for current day punches
        while True:
            time.sleep(10)
            try:
                run_incremental_biometric_sync()
            except Exception as e:
                logger.error(f"Real-time incremental sync error: {e}")

    t = threading.Thread(target=sync_loop, daemon=True)
    t.start()


# ─── Main Entry Point ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    print("[START] STARTING POSTGRESQL API SERVER FOR WORKTRACK / MONARCH HR")
    print(f"   Database (Monarch DB) : {MONARCH_DB_URI}")
    print(f"   Port                  : {PORT}")
    print("=" * 60)

    init_db()
    start_background_biometric_sync()

    app.run(host='0.0.0.0', port=PORT, debug=True, use_reloader=False)