#!/usr/bin/env python3
"""
================================================================================
Monarch HR & WorkTrack — Pixel-Perfect Phone-Identical Web App (web_app.py)
================================================================================
Completely standalone Python web application serving a 100% faithful, pixel-perfect
mirror of every single screen, widget, dialog, and flow from the Flutter Mobile App:
  1. Login Screen (Hero Logo, Welcome Back 👋, Employee ID, Password, Remember Device)
  2. Mobile App Bar (Logo, Day/Night Theme Toggle, Notification Bell, User Avatar)
  3. Floating Bottom Navigation Bar (Home, History [Badge], Leave [Badge], Profile)
  4. Tab 1: Dashboard (Home):
     - Profile Header Bar (Avatar, Verified Badge, Designation/Dept, On/Off Shift badge)
     - Today's Attendance Capsule Card (Date, Shift, Check In / Out / Live Stopwatch, Action button with Confirm Dialogs)
     - Employee Overview (Leave Days Left, Pending Requests)
     - Quick Action 2x2 Grid (Attendance Rate gauge SVG, Log Project Work, Work Schedule bars, Punctuality ring SVG)
     - Activity Log (Biometric & GPS punches, On-Site/Out of Range, On Time tags)
     - Work Entry Sheet (Log Project Work popup with Dept, Task, Subtask, Qty, Hours, Revision)
  5. Tab 2: Attendance History:
     - Manager Segment Switcher: [📅 My Attendance] | [👤 Punch Approvals (Badge)]
     - Subtabs: [Day wise] | [Weekly] | [Overview]
     - Day wise: Month Cycle Selector, Collapsible Legend, 26th-25th Calendar Grid, Day Detail
     - Weekly: Total Hours, Overtime, 7-Bar Chart with rotated DAY OFF, Daily breakdown
     - Overview: Segmented Donut Chart SVG, 5 Metric Columns, Average Work Hours
     - Punch Approvals: Company Geofence Range (20m) & 3 Building GPS chips + Pending/Zero Punches
  6. Tab 3: Leave Management:
     - Subtabs: [☂ My Leaves] | [📋 Team & Approvals (Badge)]
     - My Leaves: Annual Leave Hero, Apply Leave CTA, Filter chips, Recent applications, Holidays
     - Team & Approvals: Manager Operations card (Leads, Present Today, Pending Leave Action), Leave Requests Status with Approve/Reject action buttons, and Live Team Attendance Monitor
     - Apply Leave / Regularization Modal Sheet (Session 1/2, calculation green box, Direct 1-on-1 manager)
  7. Tab 4: Profile:
     - User Avatar Hero with Verified badge & Contact pills (#ID, Joined, Phone, Email, Active)
     - Profile Complete 100% progress card
     - Employee Information editable form & Save & Verify Profile button
     - Monthly Performance stats (Present Rate, Work Days, Punctuality)
     - Shift & Work Details
     - Attendance Settings (Daily Check-in Reminder toggle & time badge)
     - Account Security (Change Password & Sign Out)
================================================================================
"""

import os
import sys
from flask import render_template_string, send_from_directory, jsonify, request

# Import backend resources
from postgres_api_server import (
    app,
    logger,
    COMPANY_BUILDINGS,
    COMPANY_GEOFENCE_SQUARE,
    GEOFENCE_RADIUS_METERS,
    get_ist_now,
    get_ist_today
)

PORT = int(os.environ.get('PORT', 8555))

# ─── Single-Page Application (HTML5 + CSS3 + Vanilla JS) ──────────────────────
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" class="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <meta name="theme-color" content="#0C0E14" id="meta-theme-color">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>Monarch HR • WorkTrack</title>
  
  <!-- Modern Font: Plus Jakarta Sans / Inter -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  
  <!-- Lucide Icons -->
  <script src="https://unpkg.com/lucide@latest"></script>

  <style>
    :root {
      --font-main: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      
      /* Monarch Brand Palette */
      --primary: #F5A952;
      --primary-hover: #E79A46;
      --primary-dark: #895100;
      --primary-text: #1A0E00;
      --primary-subtle: rgba(245, 169, 82, 0.15);
      
      /* Light Mode */
      --bg-scaffold: #F8F9FF;
      --bg-card: #FFFFFF;
      --bg-card-subtle: #F0F4FD;
      --bg-input: #F0F4FD;
      --border-card: #EAEFF8;
      --border-input: #E2E8F0;
      
      --text-primary: #171C23;
      --text-secondary: #524437;
      --text-dim: #94A3B8;
      
      /* Status Colors */
      --green: #10B981;
      --green-dark: #146C43;
      --green-bg: rgba(16, 185, 129, 0.12);
      
      --amber: #F59E0B;
      --amber-dark: #B45309;
      --amber-bg: rgba(245, 158, 11, 0.12);
      
      --blue: #2563EB;
      --blue-bg: rgba(37, 99, 235, 0.12);
      
      --pink: #DB2777;
      --pink-bg: rgba(219, 39, 119, 0.12);
      
      --red: #EF4444;
      --red-bg: rgba(239, 68, 68, 0.12);
      
      --purple: #8B5CF6;
      --purple-bg: #EDE7F6;
      
      --radius-xs: 8px;
      --radius-sm: 12px;
      --radius-md: 16px;
      --radius-lg: 20px;
      --radius-xl: 24px;
      --radius-pill: 30px;
      
      --shadow-card: 0 4px 20px -2px rgba(23, 28, 35, 0.05);
      --shadow-nav: 0 8px 30px rgba(0, 0, 0, 0.12);
    }

    html.dark {
      --bg-scaffold: #0C0E14;
      --bg-card: #131722;
      --bg-card-subtle: #1A1F2C;
      --bg-input: #1A1F2C;
      --border-card: #1F2637;
      --border-input: #283044;
      
      --text-primary: #FFFFFF;
      --text-secondary: #9CA3AF;
      --text-dim: #64748B;
      
      --primary-dark: #FBBF24;
      --primary-text: #1A0E00;
      --green-dark: #34D399;
      --green-bg: rgba(16, 185, 129, 0.18);
      --amber-dark: #FBBF24;
      --purple-bg: rgba(139, 92, 246, 0.15);
      
      --shadow-card: 0 4px 20px -2px rgba(0, 0, 0, 0.4);
      --shadow-nav: 0 8px 30px rgba(0, 0, 0, 0.7);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: var(--font-main);
      -webkit-tap-highlight-color: transparent;
    }

    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow-x: hidden;
      background-color: var(--bg-scaffold);
    }

    body {
      color: var(--text-primary);
      min-height: 100vh;
      min-height: 100dvh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }

    /* ─── Phone Frame Viewport Container ─────────────────────────────── */
    .phone-viewport {
      width: 100%;
      max-width: 440px;
      height: 100vh;
      height: 100dvh;
      max-height: 920px;
      background: var(--bg-scaffold);
      display: flex;
      flex-direction: column;
      position: relative;
      overflow: hidden;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.08);
      border-radius: 40px;
    }

    /* Mobile First: On phones/browsers <= 640px, become true 100% full screen */
    @media (max-width: 640px) {
      body {
        display: block;
        background-color: var(--bg-scaffold);
        min-height: 100dvh;
        height: 100dvh;
        overflow: hidden;
      }
      .phone-viewport {
        max-width: 100%;
        width: 100%;
        height: 100%;
        height: 100dvh;
        max-height: none;
        border-radius: 0;
        border: none;
        box-shadow: none;
      }
    }

    /* ─── Phone Header Bar ─────────────────────────────────────────── */
    .phone-appbar {
      padding: max(10px, env(safe-area-inset-top, 10px)) 14px 10px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-scaffold);
      position: sticky;
      top: 0;
      z-index: 40;
      flex-shrink: 0;
      gap: 8px;
    }

    .brand-left {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .brand-logo-img {
      width: 26px;
      height: 26px;
      object-fit: contain;
      border-radius: 6px;
      flex-shrink: 0;
    }

    .brand-titles {
      min-width: 0;
    }

    .brand-titles h3 {
      font-size: 9.5px;
      font-weight: 700;
      color: var(--text-secondary);
      letter-spacing: 1px;
      line-height: 1;
    }

    .brand-titles h1 {
      font-size: clamp(15px, 4.2vw, 18px);
      font-weight: 800;
      color: var(--text-primary);
      letter-spacing: -0.4px;
      line-height: 1.2;
      margin-top: 1px;
      white-space: nowrap;
    }

    .appbar-actions {
      display: flex;
      align-items: center;
      gap: 5px;
      flex-shrink: 0;
    }

    .action-icon-btn {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: var(--bg-card-subtle);
      border: 1px solid var(--border-card);
      color: var(--text-secondary);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: transform 0.15s ease;
      flex-shrink: 0;
    }
    .action-icon-btn:active { transform: scale(0.92); }

    .user-avatar-pill {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: #895100;
      color: #FFFFFF;
      font-weight: 800;
      font-size: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(137, 81, 0, 0.3);
      border: 2px solid var(--bg-card);
      position: relative;
      flex-shrink: 0;
    }

    .avatar-alert-dot {
      position: absolute;
      top: -2px;
      right: -2px;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #FF2A55;
      border: 2px solid var(--bg-card);
    }

    /* ─── Scrollable Screen Area ─────────────────────────────────────── */
    .screen-body {
      flex: 1;
      overflow-y: auto;
      overflow-x: hidden;
      -webkit-overflow-scrolling: touch;
      padding: 10px 14px calc(86px + env(safe-area-inset-bottom, 16px)) 14px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .screen-body::-webkit-scrollbar { width: 4px; }
    .screen-body::-webkit-scrollbar-thumb { background: var(--border-card); border-radius: 4px; }

    /* ─── Cards & Containers ────────────────────────────────────────── */
    .app-card {
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: var(--radius-lg);
      padding: 16px 14px;
      box-shadow: var(--shadow-card);
    }

    /* ─── Floating Bottom Navigation Capsule ───────────────────────── */
    .floating-nav-container {
      position: absolute;
      bottom: max(10px, env(safe-area-inset-bottom, 10px));
      left: 12px;
      right: 12px;
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: var(--radius-pill);
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-around;
      padding: 4px 6px;
      box-shadow: var(--shadow-nav);
      z-index: 50;
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
    }

    .nav-item {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2px;
      padding: 6px 4px;
      border-radius: 16px;
      cursor: pointer;
      color: var(--text-secondary);
      font-size: 10.5px;
      font-weight: 700;
      transition: background 0.15s ease, color 0.15s ease;
      position: relative;
      min-width: 0;
      text-align: center;
      touch-action: manipulation;
      -webkit-tap-highlight-color: transparent;
      user-select: none;
      -webkit-user-select: none;
    }

    .nav-item * {
      pointer-events: none;
    }

    .nav-item i, .nav-item svg {
      width: 18px;
      height: 18px;
    }

    .nav-item.active {
      background: var(--primary);
      color: #1A0E00;
      font-weight: 800;
    }

    .nav-badge-dot {
      position: absolute;
      top: 2px;
      right: calc(50% - 16px);
      background: #FF2A55;
      color: #FFF;
      font-size: 8.5px;
      font-weight: 900;
      padding: 1px 4px;
      border-radius: 10px;
    }

    /* ─── Buttons ─────────────────────────────────────────────────────── */
    .btn-solid-primary {
      background: var(--primary);
      color: #1A0E00;
      font-weight: 900;
      font-size: 14.5px;
      letter-spacing: 0.2px;
      border-radius: var(--radius-pill);
      padding: 13px 18px;
      border: none;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      cursor: pointer;
      box-shadow: 0 4px 14px rgba(245, 169, 82, 0.35);
      transition: transform 0.15s ease, opacity 0.15s ease;
    }
    .btn-solid-primary:active { transform: scale(0.98); }

    .btn-approve-solid {
      flex: 1;
      background: #10B981;
      color: #FFFFFF;
      font-weight: 800;
      font-size: 13px;
      padding: 10px;
      border-radius: 12px;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      box-shadow: 0 3px 10px rgba(16, 185, 129, 0.3);
    }

    .btn-reject-outline {
      flex: 1;
      background: var(--bg-card);
      color: #EF4444;
      font-weight: 800;
      font-size: 13px;
      padding: 10px;
      border-radius: 12px;
      border: 1.5px solid #EF4444;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }

    /* ─── Modals & Bottom Sheets ─────────────────────────────────────── */
    .app-modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.65);
      backdrop-filter: blur(4px);
      z-index: 100;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      opacity: 0;
      visibility: hidden;
      pointer-events: none;
      transition: opacity 0.25s ease, visibility 0.25s ease;
    }

    .app-modal-backdrop.active {
      opacity: 1;
      visibility: visible;
      pointer-events: auto;
    }

    .app-modal-sheet {
      width: 100%;
      max-width: 430px;
      max-height: 90vh;
      overflow-y: auto;
      background: var(--bg-scaffold);
      border-top-left-radius: 28px;
      border-top-right-radius: 28px;
      padding: 20px 18px calc(48px + env(safe-area-inset-bottom, 24px)) 18px;
      border-top: 1px solid var(--border-card);
      transform: translateY(100%);
      transition: transform 0.28s cubic-bezier(0.32, 0.72, 0, 1);
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .app-modal-backdrop.active .app-modal-sheet {
      transform: translateY(0);
    }

    /* ─── Confirmation Alert Dialog Modal ─────────────────────────────── */
    .alert-dialog-card {
      width: 90%;
      max-width: 360px;
      background: var(--bg-card);
      border-radius: 22px;
      padding: 20px;
      border: 1px solid var(--border-card);
      box-shadow: 0 15px 40px rgba(0, 0, 0, 0.25);
      transform: scale(0.92);
      transition: transform 0.2s ease;
      margin: auto;
    }

    .app-modal-backdrop.active .alert-dialog-card {
      transform: scale(1);
    }

    /* ─── Form Inputs ─────────────────────────────────────────────────── */
    .field-label {
      font-size: 10.5px;
      font-weight: 800;
      color: var(--text-dim);
      letter-spacing: 0.6px;
      text-transform: uppercase;
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .field-input, .field-select, .field-textarea {
      width: 100%;
      background: var(--bg-input);
      border: 1px solid var(--border-input);
      padding: 12px 14px;
      border-radius: var(--radius-sm);
      color: var(--text-primary);
      font-size: 13.5px;
      font-weight: 600;
      outline: none;
    }
    .field-input:focus, .field-select:focus, .field-textarea:focus {
      border-color: var(--primary);
    }

    /* ─── Floating Toast Notification ─────────────────────────────────── */
    .app-toast-banner {
      position: fixed;
      top: 24px;
      left: 50%;
      transform: translateX(-50%);
      max-width: 90%;
      width: 380px;
      z-index: 9999;
      padding: 12px 16px;
      border-radius: 16px;
      font-size: 13px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
      animation: toastSlideDown 0.25s ease-out;
    }
    .toast-success {
      background: #16A34A;
      color: #FFFFFF;
    }
    .toast-error {
      background: #DC2626;
      color: #FFFFFF;
    }
    .toast-info {
      background: #2563EB;
      color: #FFFFFF;
    }
    @keyframes toastSlideDown {
      from { transform: translate(-50%, -20px); opacity: 0; }
      to { transform: translate(-50%, 0); opacity: 1; }
    }

    /* ─── Work Entry Quick Chips & Dropdown ───────────────────────────── */
    .we-quick-chip {
      flex-shrink: 0;
      padding: 6px 12px;
      border-radius: 20px;
      background: var(--bg-input);
      border: 1px solid var(--border-input);
      color: var(--text-secondary);
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
      white-space: nowrap;
    }
    .we-quick-chip:hover {
      background: var(--bg-card-subtle);
      color: var(--text-primary);
      border-color: var(--primary);
    }

    #we-project-dropdown-list::-webkit-scrollbar {
      width: 5px;
    }
    #we-project-dropdown-list::-webkit-scrollbar-thumb {
      background: var(--border-card);
      border-radius: 4px;
    }

    /* ─── Top Sub-Tab Segmented Controls ─────────────────────────────── */
    .segmented-pill-bar {
      background: var(--bg-card-subtle);
      border: 1px solid var(--border-card);
      border-radius: var(--radius-pill);
      padding: 4px;
      display: flex;
      gap: 4px;
    }

    .segment-tab-btn {
      flex: 1;
      padding: 8px 10px;
      border-radius: 20px;
      border: none;
      background: transparent;
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: all 0.2s ease;
    }

    .segment-tab-btn.active {
      background: var(--bg-card);
      color: var(--text-primary);
      font-weight: 800;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    }

    /* Calendar Grid */
    .cal-grid-7 {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      gap: 4px;
      text-align: center;
    }

    .cal-header-day {
      font-size: 11px;
      font-weight: 800;
      color: var(--text-dim);
      padding-bottom: 6px;
    }

    .cal-cell {
      aspect-ratio: 0.95;
      border-radius: 8px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 800;
      cursor: pointer;
      position: relative;
      border: 1.5px solid transparent;
      background: var(--bg-card-subtle);
      transition: all 0.15s ease;
    }
    .cal-cell.selected-day {
      box-shadow: 0 0 0 2px var(--primary);
    }
    .cal-cell.today-active {
      border-color: #895100;
      background: #FDF4E7;
      color: #895100;
    }
    .cal-cell.present { background: #ECFDF5; color: #059669; }
    .cal-cell.half-day { background: #FFF3E0; color: #D97706; }
    .cal-cell.missed-punch { background: #FEF3C7; color: #B45309; border-color: #F59E0B; }
    .cal-cell.holiday { background: #EFF6FF; color: #2563EB; }
    .cal-cell.leave { background: #FDF2F8; color: #DB2777; }
    .cal-cell.week-off { background: #F9FAFB; color: #4B5563; }
    .cal-cell.absent { background: #FEE2E2; color: #DC2626; }
    .cal-cell.future-plan { background: #FAFAFA; color: #94A3B8; }

    .dark .cal-cell.today-active { border-color: #F5A952; background: #261D12; color: #F5A952; }
    .dark .cal-cell.present { background: #11221E; color: #34D399; }
    .dark .cal-cell.half-day { background: #241C14; color: #FBA442; }
    .dark .cal-cell.missed-punch { background: #281C10; color: #F5A952; border-color: #F5A952; }
    .dark .cal-cell.holiday { background: #132235; color: #38BDF8; }
    .dark .cal-cell.leave { background: #26151B; color: #FB7185; }
    .dark .cal-cell.week-off { background: #161C28; color: #94A3B8; }
    .dark .cal-cell.absent { background: #2B1618; color: #F87171; }
    .dark .cal-cell.future-plan { background: #131823; color: #64748B; }

    .bar-pill.empty { background: var(--bg-card-subtle); border: 1px solid var(--border-card); }

    .cal-cell .code-sub {
      font-size: 8px;
      font-weight: 800;
      margin-top: 1px;
      letter-spacing: 0.3px;
    }

    /* Weekly Bar Chart */
    .bar-chart-container {
      display: flex;
      align-items: flex-end;
      justify-content: space-around;
      height: 180px;
      padding: 10px 0 2px 0;
      border-bottom: 1px dashed var(--border-card);
    }

    .bar-col {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      height: 100%;
      justify-content: flex-end;
    }

    .bar-pill {
      width: 24px;
      border-radius: 12px;
      transition: height 0.3s ease;
      min-height: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #FFF;
      font-size: 8px;
      font-weight: 800;
    }

    .bar-pill.regular { background: #10B981; }
    .bar-pill.dayoff { background: #EDE9FE; color: #7C3AED; }
    .bar-pill.holiday { background: #60A5FA; }

    /* Circular Donut */
    .donut-wrapper {
      position: relative;
      width: 170px;
      height: 170px;
      margin: 0 auto;
    }
  </style>
</head>
<body>

  <!-- ─── PHONE CONTAINER VIEWPORT ─────────────────────────────────────────── -->
  <div class="phone-viewport">

    <!-- Floating Global Toast / Alert -->
    <div id="app-toast" class="app-toast-banner" style="display: none;"></div>

    <!-- ── 1. LOGIN SCREEN (Flutter login_screen.dart mirror) ───────────────── -->
    <div id="screen-login" class="screen-body" style="justify-content: center; padding: 20px 20px;">
      
      <!-- Top Appbar for Login Screen -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <img src="https://static.share.market/cube/instrument/icon/PEBYEHT" style="width: 28px; height: 28px; border-radius: 8px;" alt="Logo" onerror="this.src='https://cdn-icons-png.flaticon.com/512/2921/2921226.png'">
          <span style="font-size: 18px; font-weight: 800; letter-spacing: -0.5px;">Monarch HR</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 12px; font-weight: 600; color: var(--text-secondary);">Sign In</span>
          <div class="user-avatar-pill" style="width: 28px; height: 28px; font-size: 13px; background: #FDF0DE; color: #F5A952;">
            <i data-lucide="user" style="width: 14px;"></i>
          </div>
          <button onclick="toggleTheme()" class="action-icon-btn" style="width: 32px; height: 32px;">
            <i id="theme-icon-login" data-lucide="moon" style="width: 16px; color: #2563EB;"></i>
          </button>
        </div>
      </div>

      <!-- Hero Circular Logo Badge with Checkmark -->
      <div style="text-align: center; margin: 10px 0 16px 0;">
        <div style="position: relative; width: 68px; height: 68px; margin: 0 auto;">
          <div style="width: 68px; height: 68px; border-radius: 50%; background: var(--bg-card); border: 1.5px solid var(--border-card); display: flex; align-items: center; justify-content: center; box-shadow: var(--shadow-card);">
            <img src="https://static.share.market/cube/instrument/icon/PEBYEHT" style="width: 36px; height: 36px; object-fit: contain;" alt="Logo" onerror="this.src='https://cdn-icons-png.flaticon.com/512/2921/2921226.png'">
          </div>
          <div style="position: absolute; bottom: 0; right: 0; width: 20px; height: 20px; border-radius: 50%; background: #9FF1BD; display: flex; align-items: center; justify-content: center; border: 2px solid var(--bg-card);">
            <i data-lucide="check" style="width: 12px; color: #1B7047; stroke-width: 3;"></i>
          </div>
        </div>

        <h2 style="font-size: 24px; font-weight: 800; letter-spacing: -0.5px; margin-top: 14px;">Welcome back 👋</h2>
        <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px; line-height: 1.4;">
          Sign in to track your shifts, attendance, and leave balance effortlessly.
        </p>
      </div>

      <!-- Form Container Card -->
      <div class="app-card" style="padding: 22px; border-radius: 28px;">
        <form id="login-form" onsubmit="handleLoginSubmit(event)" style="display: flex; flex-direction: column; gap: 16px;">
          
          <div>
            <label class="field-label">EMPLOYEE ID</label>
            <div style="position: relative; display: flex; align-items: center;">
              <i data-lucide="badge" style="position: absolute; left: 14px; width: 18px; color: var(--text-dim);"></i>
              <input type="text" id="login-emp-id" class="field-input" placeholder="e.g. 1951" required autocomplete="username" style="padding-left: 42px;">
            </div>
          </div>

          <div>
            <label class="field-label">PASSWORD</label>
            <div style="position: relative; display: flex; align-items: center;">
              <i data-lucide="lock" style="position: absolute; left: 14px; width: 18px; color: var(--text-dim);"></i>
              <input type="password" id="login-pwd" class="field-input" placeholder="Enter your work password" required autocomplete="current-password" style="padding-left: 42px; padding-right: 42px;">
              <button type="button" onclick="togglePasswordVisibility()" style="position: absolute; right: 12px; background: none; border: none; cursor: pointer; color: var(--text-dim);">
                <i id="pwd-eye-icon" data-lucide="eye" style="width: 18px;"></i>
              </button>
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px;">
            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; color: var(--text-secondary);">
              <input type="checkbox" checked style="accent-color: var(--primary);">
              <span>Remember device</span>
            </label>
            <span style="color: #B45309; font-weight: 700; cursor: pointer;">Forgot password?</span>
          </div>

          <div id="login-err-box" style="display: none; background: rgba(239, 68, 68, 0.15); color: #EF4444; padding: 10px; border-radius: 12px; font-size: 12px; font-weight: 700; text-align: center;"></div>

          <button type="submit" id="btn-login-submit" class="btn-solid-primary" style="margin-top: 6px; padding: 16px;">
            <span>Sign In</span>
            <i data-lucide="arrow-right" style="width: 18px;"></i>
          </button>
        </form>
      </div>

      <!-- ── Google Play Download Badge & Footer ── -->
      <div style="margin-top: 20px; display: flex; flex-direction: column; align-items: center; gap: 12px; width: 100%;">
        <a href="https://play.google.com/store/apps/details?id=com.monarchconsultants.monarchhr" 
           target="_blank" 
           rel="noopener noreferrer" 
           style="display: inline-flex; align-items: center; justify-content: center; gap: 12px; background: var(--bg-card); border: 1.5px solid var(--border-card); padding: 10px 20px; border-radius: 16px; text-decoration: none; color: var(--text-primary); box-shadow: 0 4px 16px rgba(0,0,0,0.04); transition: all 0.2s ease; max-width: 280px; width: 100%; box-sizing: border-box;"
           onmouseover="this.style.borderColor='var(--primary)'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 8px 20px rgba(245,169,82,0.18)';"
           onmouseout="this.style.borderColor='var(--border-card)'; this.style.transform='none'; this.style.boxShadow='0 4px 16px rgba(0,0,0,0.04)';">
          
          <!-- Official Google Play Logo SVG -->
          <svg width="24" height="26" viewBox="0 0 512 512" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex-shrink: 0;">
            <path d="M47.2 18.3C44.4 21.3 42.8 26 42.8 32.2V479.8C42.8 486 44.4 490.7 47.2 493.7L48.6 495.1L274.6 269.1V261V252.9L48.6 16.9L47.2 18.3Z" fill="url(#gp_a)"/>
            <path d="M350 344.5L274.6 269.1V261V252.9L350.1 177.5L351.7 178.4L441.1 229.2C466.6 243.7 466.6 267.4 441.1 281.9L351.7 332.7L350 344.5Z" fill="url(#gp_b)"/>
            <path d="M351.7 342.8L274.6 265.7L47.2 493.1C55.7 502.1 69.5 503.2 85.3 494.3L351.7 342.8Z" fill="url(#gp_c)"/>
            <path d="M351.7 169.2L85.3 17.7C69.5 8.8 55.7 9.9 47.2 18.9L274.6 246.3L351.7 169.2Z" fill="url(#gp_d)"/>
            <defs>
              <linearGradient id="gp_a" x1="254.7" y1="36.1" x2="31.8" y2="259" gradientUnits="userSpaceOnUse">
                <stop stop-color="#00A0FF"/><stop offset="0.007" stop-color="#00A1FF"/><stop offset="0.26" stop-color="#00BEFF"/><stop offset="0.512" stop-color="#00D2FF"/><stop offset="0.76" stop-color="#00DFFF"/><stop offset="1" stop-color="#00E3FF"/>
              </linearGradient>
              <linearGradient id="gp_b" x1="472.9" y1="256" x2="41.3" y2="256" gradientUnits="userSpaceOnUse">
                <stop stop-color="#FFE000"/><stop offset="0.409" stop-color="#FFBD00"/><stop offset="0.775" stop-color="#FFA500"/><stop offset="1" stop-color="#FF9C00"/>
              </linearGradient>
              <linearGradient id="gp_c" x1="305" y1="299.5" x2="88.7" y2="515.8" gradientUnits="userSpaceOnUse">
                <stop stop-color="#FF3A44"/><stop offset="1" stop-color="#C31162"/>
              </linearGradient>
              <linearGradient id="gp_d" x1="88.7" y1="-3.8" x2="305" y2="212.5" gradientUnits="userSpaceOnUse">
                <stop stop-color="#32A071"/><stop offset="0.069" stop-color="#2DA771"/><stop offset="0.476" stop-color="#15CF74"/><stop offset="0.801" stop-color="#06E775"/><stop offset="1" stop-color="#00F076"/>
              </linearGradient>
            </defs>
          </svg>

          <div style="text-align: left; line-height: 1.15;">
            <div style="font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px; color: var(--text-dim);">GET IT ON</div>
            <div style="font-size: 14px; font-weight: 800; color: var(--text-primary); letter-spacing: -0.2px;">Google Play</div>
          </div>
        </a>

        <div style="text-align: center; font-size: 10.5px; color: var(--text-dim); line-height: 1.5; padding: 0 10px;">
          Protected by Monarch Surveyors & Engineering Consultants Ltd.
        </div>
      </div>
    </div>

    <!-- ── 2. PHONE TOP APPBAR (Logged In) ───────────────────────────────── -->
    <header id="phone-appbar" class="phone-appbar" style="display: none;">
      <div class="brand-left">
        <img src="https://static.share.market/cube/instrument/icon/PEBYEHT" class="brand-logo-img" alt="Logo" onerror="this.src='https://cdn-icons-png.flaticon.com/512/2921/2921226.png'">
        <div class="brand-titles">
          <h3>MONARCHHR</h3>
          <h1 id="topbar-title">Dashboard</h1>
        </div>
      </div>

      <div class="appbar-actions">
        <!-- Theme Toggle -->
        <button onclick="toggleTheme()" class="action-icon-btn" title="Toggle Light/Dark">
          <i id="theme-icon" data-lucide="moon" style="width: 17px; color: #2563EB;"></i>
        </button>
        <!-- Bell Notifications -->
        <button class="action-icon-btn" title="Notifications">
          <i data-lucide="bell" style="width: 17px;"></i>
        </button>
        <!-- User Avatar Circle -->
        <div class="user-avatar-pill" id="topbar-avatar" onclick="switchNavTab('profile')">
          <span>U</span>
          <span class="avatar-alert-dot" id="topbar-avatar-dot" style="display: none;"></span>
        </div>
        <!-- Logout on Dashboard -->
        <button onclick="handleLogout()" class="action-icon-btn" id="topbar-logout-btn" title="Sign Out">
          <i data-lucide="log-out" style="width: 16px;"></i>
        </button>
      </div>
    </header>

    <!-- ── 3. MAIN TAB VIEWS ─────────────────────────────────────────────── -->
    <div id="main-screens-wrap" style="display: none; flex: 1; flex-direction: column; overflow: hidden;">
      
      <!-- ═══════════════════════════════════════════════════════════════════ -->
      <!-- TAB 1: DASHBOARD (HOME)                                             -->
      <!-- ═══════════════════════════════════════════════════════════════════ -->
      <div id="view-dashboard" class="screen-body">
        
        <!-- Employee Profile Header Chip -->
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
            <div class="user-avatar-pill" style="width: 42px; height: 42px; font-size: 16px; flex-shrink: 0;" id="dash-avatar" onclick="switchNavTab('profile')">
              <span>U</span>
              <span class="avatar-alert-dot" id="dash-avatar-dot" style="display: none;"></span>
            </div>
            <div onclick="switchNavTab('profile')" style="cursor: pointer; min-width: 0; flex: 1;">
              <div style="display: flex; align-items: center; gap: 4px; overflow: hidden;">
                <h2 style="font-size: 16px; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" id="dash-fullname">Utkarsh Rajendra Pingale</h2>
                <i data-lucide="badge-check" style="width: 16px; height: 16px; color: #F5A952; fill: #F5A952; flex-shrink: 0;"></i>
              </div>
              <p style="font-size: 11px; color: var(--text-secondary); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" id="dash-role-dept">Developer • IT Department</p>
            </div>
          </div>
          <div id="dash-shift-badge" style="background: rgba(16, 185, 129, 0.15); color: #146C43; padding: 5px 10px; border-radius: 20px; font-size: 10.5px; font-weight: 800; display: flex; align-items: center; gap: 5px; flex-shrink: 0; white-space: nowrap;">
            <span style="width: 6px; height: 6px; border-radius: 50%; background: #10B981;"></span>
            <span id="dash-shift-status-text">On Shift</span>
          </div>
        </div>

        <!-- Team Pending Approvals Banner (If Manager) -->
        <div id="dash-manager-pending-banner" onclick="switchNavTab('leaves', 'team')" style="display: none; background: rgba(255, 42, 85, 0.1); border: 1px solid rgba(255, 42, 85, 0.4); padding: 12px 14px; border-radius: 16px; cursor: pointer; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div style="width: 32px; height: 32px; border-radius: 50%; background: rgba(255, 42, 85, 0.2); color: #FF2A55; display: flex; align-items: center; justify-content: center;">
              <i data-lucide="clipboard-check" style="width: 16px;"></i>
            </div>
            <div>
              <div style="font-size: 13px; font-weight: 800; color: var(--text-primary);">Subordinate Actions Required</div>
              <div style="font-size: 11px; color: #FF2A55;" id="dash-pending-count-text">1 pending leave approval</div>
            </div>
          </div>
          <i data-lucide="chevron-right" style="width: 18px; color: var(--text-dim);"></i>
        </div>

        <!-- ── Today's Attendance Capsule Card (Screenshot 1) ── -->
        <div class="app-card" style="text-align: center; padding: 18px 14px;">
          <h2 style="font-size: 17px; font-weight: 800; letter-spacing: -0.3px;">Today's Attendance</h2>
          
          <div style="display: flex; align-items: center; justify-content: center; gap: 6px; margin-top: 5px;">
            <i data-lucide="calendar" style="width: 14px; color: var(--primary);"></i>
            <span style="font-size: 12px; font-weight: 700; color: var(--text-secondary);" id="dash-date-label">Friday, 09 Oct 2026</span>
          </div>

          <div style="display: flex; align-items: center; justify-content: center; gap: 5px; margin-top: 3px;">
            <i data-lucide="clock" style="width: 13px; color: var(--text-dim);"></i>
            <span style="font-size: 11.5px; color: var(--text-secondary);" id="dash-shift-time-label">Work shift: 09:30 AM – 06:30 PM</span>
          </div>

          <!-- 3 Rounded Metric Boxes -->
          <div style="display: grid; grid-template-columns: 1fr 1fr 1.15fr; gap: 6px; margin: 16px 0;">
            <div style="background: var(--bg-card-subtle); padding: 10px 4px; border-radius: 14px;">
              <div style="font-size: clamp(12px, 3.4vw, 14px); font-weight: 800; white-space: nowrap;" id="box-checkin-time">09:00 AM</div>
              <div style="font-size: 10.5px; color: var(--text-secondary); margin-top: 2px;">Check In</div>
            </div>
            <div style="background: var(--bg-card-subtle); padding: 10px 4px; border-radius: 14px;">
              <div style="font-size: clamp(12px, 3.4vw, 14px); font-weight: 800; color: var(--text-dim); white-space: nowrap;" id="box-checkout-time">-- : --</div>
              <div style="font-size: 10.5px; color: var(--text-secondary); margin-top: 2px;">Check Out</div>
            </div>
            <div style="background: var(--bg-card-subtle); padding: 10px 4px; border-radius: 14px;">
              <div style="font-size: clamp(12px, 3.4vw, 14px); font-weight: 800; color: var(--primary-dark); white-space: nowrap;" id="box-working-hrs">00:00:00</div>
              <div style="font-size: 10.5px; color: var(--text-secondary); margin-top: 2px;">Working Hrs</div>
            </div>
          </div>

          <!-- Solid Action Button -->
          <button id="btn-punch-action" onclick="handlePunchButtonPress()" class="btn-solid-primary">
            <span id="btn-punch-text" style="color: inherit; font-weight: 900;">Check Out</span>
            <i data-lucide="clock" style="width: 18px;"></i>
          </button>
        </div>

        <!-- ── Employee Overview ── -->
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <h3 style="font-size: 16px; font-weight: 800;">Employee Overview</h3>
            <span onclick="switchNavTab('leaves')" style="font-size: 11.5px; font-weight: 800; color: var(--primary-dark); cursor: pointer;">Details</span>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
            <!-- Leave Days Left -->
            <div onclick="switchNavTab('leaves')" class="app-card" style="padding: 12px; display: flex; align-items: center; gap: 10px; cursor: pointer;">
              <div style="width: 38px; height: 38px; border-radius: 12px; background: var(--purple-bg); display: flex; align-items: center; justify-content: center; color: var(--purple); flex-shrink: 0;">
                <i data-lucide="calendar" style="width: 18px;"></i>
              </div>
              <div style="min-width: 0;">
                <div style="font-size: 17px; font-weight: 900;" id="overview-leaves-left">6.0</div>
                <div style="font-size: 10.5px; color: var(--text-secondary); white-space: nowrap;">Leave Days Left</div>
              </div>
            </div>

            <!-- Pending Requests -->
            <div onclick="switchNavTab('leaves')" class="app-card" style="padding: 12px; display: flex; align-items: center; gap: 10px; cursor: pointer;">
              <div style="width: 38px; height: 38px; border-radius: 12px; background: #FFF8E1; display: flex; align-items: center; justify-content: center; color: #F59E0B; flex-shrink: 0;">
                <i data-lucide="clipboard-list" style="width: 18px;"></i>
              </div>
              <div style="min-width: 0;">
                <div style="font-size: 17px; font-weight: 900;" id="overview-pending-req">0</div>
                <div style="font-size: 10.5px; color: var(--text-secondary); white-space: nowrap;">Pending Requests</div>
              </div>
            </div>
          </div>
        </div>

        <!-- ── Quick Action Grid 2x2 ── -->
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <h3 style="font-size: 16px; font-weight: 800;">Quick Action</h3>
            <span style="font-size: 11.5px; font-weight: 600; color: var(--text-secondary);">Monthly Stats</span>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
            
            <!-- Card 1: Attendance Rate (Semicircle Gauge) -->
            <div onclick="switchNavTab('attendance')" class="app-card" style="padding: 12px; display: flex; flex-direction: column; justify-content: space-between; min-height: 146px; cursor: pointer;">
              <div style="display: flex; justify-content: flex-end;">
                <span style="font-size: 9.5px; font-weight: 800; padding: 2px 7px; border-radius: 10px; background: #FFDCBC; color: #683D00;" id="dash-rate-tag">Good</span>
              </div>
              <div style="text-align: center; position: relative;">
                <svg viewBox="0 0 100 55" style="width: 84px; height: 46px; margin: 0 auto; display: block;">
                  <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="#E2E8F0" stroke-width="8" stroke-linecap="round" />
                  <path id="dash-rate-gauge-path" d="M 10 50 A 40 40 0 0 1 85 30" fill="none" stroke="#10B981" stroke-width="8" stroke-linecap="round" />
                </svg>
                <div style="position: absolute; bottom: 0; left: 0; right: 0; font-size: 15px; font-weight: 900;" id="dash-rate-text">98%</div>
              </div>
              <div style="font-size: 11.5px; font-weight: 700; text-align: center;">Attendance Rate</div>
            </div>

            <!-- Card 2: Log Project Work -->
            <div class="app-card" style="padding: 12px; display: flex; flex-direction: column; justify-content: space-between; min-height: 146px;">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="display: flex; align-items: center; gap: 4px; font-size: 10px; font-weight: 700; color: var(--text-secondary);">
                  <i data-lucide="clipboard-pen" style="width: 13px; color: #D97706;"></i>
                  <span>Work Entry</span>
                </div>
                <span style="font-size: 8.5px; font-weight: 800; padding: 2px 5px; border-radius: 8px; background: rgba(16, 185, 129, 0.15); color: #146C43;">Daily Log</span>
              </div>
              <div>
                <div style="font-size: 12px; font-weight: 800;">Log Project Work</div>
                <div style="font-size: 9.5px; color: var(--text-secondary); margin-top: 1px;">Task, quantity & revisions</div>
              </div>
              <button onclick="openWorkEntryModal()" style="width: 100%; background: var(--primary); color: #1A0E00; font-weight: 900; font-size: 10.5px; padding: 7px; border-radius: 20px; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 4px; box-shadow: 0 2px 8px rgba(245, 169, 82, 0.3);">
                <i data-lucide="file-plus" style="width: 13px;"></i>
                <span>Fill Work Entry</span>
              </button>
            </div>

            <!-- Card 3: Work Schedule (Weekly Goal) -->
            <div onclick="switchNavTab('attendance', 'Weekly')" class="app-card" style="padding: 12px; display: flex; flex-direction: column; justify-content: space-between; min-height: 146px; cursor: pointer;">
              <div style="display: flex; justify-content: space-between; font-size: 10px;">
                <span style="color: var(--text-secondary); font-weight: 600;">Weekly Goal</span>
                <span style="color: #146C43; font-weight: 800;" id="dash-weekly-goal-text">38/45h</span>
              </div>
              <div style="display: flex; justify-content: space-around; align-items: flex-end; height: 46px;">
                <div style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
                  <div style="width: 8px; height: 32px; border-radius: 4px; background: #10B981;"></div>
                  <span style="font-size: 8.5px; font-weight: 700; color: var(--text-dim);">M</span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
                  <div style="width: 8px; height: 36px; border-radius: 4px; background: #10B981;"></div>
                  <span style="font-size: 8.5px; font-weight: 700; color: var(--text-dim);">T</span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
                  <div style="width: 8px; height: 34px; border-radius: 4px; background: #10B981;"></div>
                  <span style="font-size: 8.5px; font-weight: 700; color: var(--text-dim);">W</span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
                  <div style="width: 8px; height: 38px; border-radius: 4px; background: #10B981;"></div>
                  <span style="font-size: 8.5px; font-weight: 700; color: var(--text-dim);">T</span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
                  <div style="width: 8px; height: 28px; border-radius: 4px; background: #10B981;"></div>
                  <span style="font-size: 8.5px; font-weight: 800; color: var(--text-primary);">F</span>
                </div>
              </div>
              <div style="font-size: 11.5px; font-weight: 700; text-align: center;">Work Schedule</div>
            </div>

            <!-- Card 4: Punctuality / Efficiency -->
            <div class="app-card" style="padding: 12px; display: flex; flex-direction: column; justify-content: space-between; min-height: 146px;">
              <div style="display: flex; justify-content: space-between; font-size: 10px;">
                <span style="color: var(--text-secondary); font-weight: 600;">Efficiency</span>
                <i data-lucide="trending-up" style="width: 13px; color: #146C43;"></i>
              </div>
              <div style="text-align: center; position: relative; width: 46px; height: 46px; margin: 0 auto;">
                <svg viewBox="0 0 36 36" style="width: 46px; height: 46px; transform: rotate(-90deg);">
                  <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#E2E8F0" stroke-width="3.8"/>
                  <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#10B981" stroke-dasharray="96, 100" stroke-width="3.8" stroke-linecap="round"/>
                </svg>
                <div style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 9.5px; font-weight: 900;">96%</div>
              </div>
              <div style="font-size: 11.5px; font-weight: 700; text-align: center;">Punctuality</div>
            </div>

          </div>
        </div>

        <!-- ── Activity Log ── -->
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <h3 style="font-size: 17px; font-weight: 800;">Activity Log</h3>
            <span style="font-size: 12px; font-weight: 600; color: var(--text-secondary);">Today</span>
          </div>

          <div id="dash-activity-list" style="display: flex; flex-direction: column; gap: 8px;">
            <div class="app-card" style="padding: 12px 14px; display: flex; align-items: center; justify-content: space-between;">
              <div style="display: flex; align-items: center; gap: 12px;">
                <div style="width: 38px; height: 38px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center;">
                  <i data-lucide="log-in" style="width: 18px;"></i>
                </div>
                <div>
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 14px; font-weight: 800;">Punch In</span>
                    <span style="font-size: 9.5px; font-weight: 800; padding: 2px 6px; border-radius: 8px; background: #F1F5F9; color: #475569;">On-Site</span>
                  </div>
                  <div style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">Biometric Machine #8</div>
                </div>
              </div>
              <div style="text-align: right;">
                <div style="font-size: 14px; font-weight: 800;" id="activity-in-time">09:00 AM</div>
                <div style="font-size: 10.5px; font-weight: 700; color: #146C43; margin-top: 1px;">On Time</div>
              </div>
            </div>
          </div>
        </div>

      </div>

      <!-- ═══════════════════════════════════════════════════════════════════ -->
      <!-- TAB 2: ATTENDANCE HISTORY (Employee + Manager Punch Approvals)      -->
      <!-- ═══════════════════════════════════════════════════════════════════ -->
      <div id="view-attendance" class="screen-body" style="display: none;">
        
        <!-- Manager Top Switcher (My Attendance vs Punch Approvals) -->
        <div id="att-mgr-top-bar" class="segmented-pill-bar" style="display: none; margin-bottom: 4px;">
          <button id="att-main-my" onclick="switchAttMainSegment('my')" class="segment-tab-btn active">
            <i data-lucide="calendar" style="width: 14px;"></i>
            <span>My Attendance</span>
          </button>
          <button id="att-main-punches" onclick="switchAttMainSegment('punches')" class="segment-tab-btn">
            <i data-lucide="user-check" style="width: 14px;"></i>
            <span>Punch Approvals</span>
            <span id="att-punch-count-badge" style="display: none; background: #FF2A55; color: #FFF; font-size: 9px; padding: 1px 5px; border-radius: 10px;">0</span>
          </button>
        </div>

        <!-- ── SECTION A: MY ATTENDANCE ── -->
        <div id="att-my-section" style="display: flex; flex-direction: column; gap: 14px;">
          
          <!-- Top Sub-Tab Segmented Switcher -->
          <div class="segmented-pill-bar">
            <button id="att-subtab-day" onclick="switchAttSubTab('Day wise')" class="segment-tab-btn active">
              <i data-lucide="calendar" style="width: 14px;"></i>
              <span>Day wise</span>
            </button>
            <button id="att-subtab-weekly" onclick="switchAttSubTab('Weekly')" class="segment-tab-btn">
              <i data-lucide="bar-chart-2" style="width: 14px;"></i>
              <span>Weekly</span>
            </button>
            <button id="att-subtab-overview" onclick="switchAttSubTab('Overview')" class="segment-tab-btn">
              <i data-lucide="sparkles" style="width: 14px;"></i>
              <span>Overview</span>
            </button>
          </div>

          <!-- ── SUB-VIEW 1: DAY WISE ── -->
          <div id="att-view-daywise" style="display: flex; flex-direction: column; gap: 14px;">
            
            <!-- Month Cycle Selector Bar -->
            <div class="app-card" style="padding: 12px 14px; display: flex; align-items: center; justify-content: space-between;">
              <button onclick="shiftPayrollCycle(-1)" style="background: none; border: none; cursor: pointer; color: var(--text-primary);"><i data-lucide="chevron-left"></i></button>
              <div style="text-align: center;">
                <div style="font-size: 14px; font-weight: 800;" id="cal-month-title">November 2026</div>
                <div style="font-size: 11px; color: var(--text-dim);" id="cal-cycle-range">26 Oct – 25 Nov</div>
              </div>
              <div style="display: flex; align-items: center; gap: 6px;">
                <button onclick="toggleLegendBox()" style="background: var(--bg-card-subtle); border: 1px solid var(--border-card); padding: 4px 8px; border-radius: 12px; font-size: 11px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 4px;">
                  <span>Legend</span>
                  <i data-lucide="chevron-down" style="width: 12px;"></i>
                </button>
                <span id="cal-cycle-days-badge" style="font-size: 10.5px; font-weight: 800; padding: 4px 8px; border-radius: 12px; background: var(--bg-card-subtle);">31 Days</span>
              </div>
              <button onclick="shiftPayrollCycle(1)" style="background: none; border: none; cursor: pointer; color: var(--text-primary);"><i data-lucide="chevron-right"></i></button>
            </div>

            <!-- Collapsible Legend -->
            <div id="att-legend-box" style="display: none; background: var(--bg-card); padding: 10px; border-radius: 16px; border: 1px solid var(--border-card); font-size: 11px; font-weight: 700; gap: 8px; flex-wrap: wrap;">
              <span style="background: #ECFDF5; color: #059669; padding: 2px 8px; border-radius: 6px;">P Present</span>
              <span style="background: #EFF6FF; color: #2563EB; padding: 2px 8px; border-radius: 6px;">H Holiday</span>
              <span style="background: #FDF2F8; color: #DB2777; padding: 2px 8px; border-radius: 6px;">EL Leave</span>
              <span style="background: #F9FAFB; color: #4B5563; padding: 2px 8px; border-radius: 6px;">Off Week Off</span>
            </div>

            <!-- Calendar Grid Card -->
            <div class="app-card" style="padding: 14px;">
              <div class="cal-grid-7" id="payroll-cal-grid">
                <div class="cal-header-day">Sun</div>
                <div class="cal-header-day">Mon</div>
                <div class="cal-header-day">Tue</div>
                <div class="cal-header-day">Wed</div>
                <div class="cal-header-day">Thu</div>
                <div class="cal-header-day">Fri</div>
                <div class="cal-header-day">Sat</div>
              </div>
            </div>

            <!-- Selected Day Detail Sheet Card -->
            <div id="selected-day-card" class="app-card" style="display: none; padding: 18px; border: 1.5px solid var(--primary); margin-top: 6px;">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                <div>
                  <div style="font-size: 10px; font-weight: 800; color: var(--text-dim); letter-spacing: 0.8px;">SESSION RECAP</div>
                  <h4 style="font-size: 16px; font-weight: 800; margin-top: 2px;" id="sel-day-date-str">Tuesday, 13 Oct 2026</h4>
                  <div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;" id="sel-day-shift-sub">Shift: 09:00 AM – 06:00 PM</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span id="sel-day-status-pill" style="font-size: 11px; font-weight: 800; padding: 4px 10px; border-radius: 12px; background: #DCFCE7; color: #166534;">Shift Active</span>
                  <button onclick="document.getElementById('selected-day-card').style.display='none'" style="background: none; border: none; cursor: pointer; color: var(--text-dim); padding: 2px;"><i data-lucide="x" style="width: 16px;"></i></button>
                </div>
              </div>

              <!-- Missed Punch Out Action Notice (if applicable) -->
              <div id="sel-day-missed-alert" style="display: none; background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 12px; padding: 10px 12px; margin-bottom: 12px; color: #92400E;">
                <div style="display: flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 800;">
                  <i data-lucide="alert-triangle" style="width: 14px; color: #D97706;"></i>
                  <span>Missing Check-Out Punch</span>
                </div>
                <p style="font-size: 11px; margin-top: 4px; color: #78350F;">
                  A check-in was logged without a check-out. If you completed your shift, apply for Regularization.
                </p>
                <div style="display: flex; gap: 8px; margin-top: 8px;">
                  <button onclick="openLeaveModalForDate('Regularization')" style="padding: 6px 12px; font-size: 11px; font-weight: 700; border-radius: 8px; background: #D97706; color: #FFFFFF; border: none; cursor: pointer;">Regularize Attendance</button>
                  <button onclick="openLeaveModalForDate('Earned Leave', true)" style="padding: 6px 12px; font-size: 11px; font-weight: 700; border-radius: 8px; background: #FEF3C7; color: #92400E; border: 1px solid #FCD34D; cursor: pointer;">Apply Half Day Leave</button>
                </div>
              </div>

              <!-- 2 Stat Metrics -->
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;">
                <div style="background: var(--bg-card-subtle); padding: 10px 12px; border-radius: 12px;">
                  <div style="font-size: 10px; font-weight: 700; color: var(--text-dim);">Total Work Hours</div>
                  <div style="font-size: 16px; font-weight: 900; margin-top: 2px;" id="sel-day-work-hours">09:05 hrs</div>
                  <div style="font-size: 10px; font-weight: 700; color: #16A34A; margin-top: 2px;" id="sel-day-hours-badge">Standard Met</div>
                </div>
                <div style="background: var(--bg-card-subtle); padding: 10px 12px; border-radius: 12px;">
                  <div style="font-size: 10px; font-weight: 700; color: var(--text-dim);">Overtime</div>
                  <div style="font-size: 16px; font-weight: 900; color: var(--primary-dark); margin-top: 2px;" id="sel-day-ot-hours">00:05 hrs</div>
                  <div style="font-size: 10px; color: var(--text-secondary); margin-top: 2px;">Standard: 09:00h</div>
                </div>
              </div>

              <!-- In & Out Summary Comparison -->
              <div style="display: flex; justify-content: space-around; align-items: center; padding: 10px 0; border-top: 1px solid var(--border-card); border-bottom: 1px solid var(--border-card); margin-bottom: 12px;">
                <div style="text-align: center;">
                  <div style="font-size: 10px; font-weight: 600; color: var(--text-dim);">First Check In</div>
                  <div style="font-size: 14px; font-weight: 800; margin-top: 1px;" id="sel-day-in-time">08:48 AM</div>
                  <div style="font-size: 9.5px; font-weight: 700; color: #16A34A;" id="sel-day-in-status">On Time</div>
                </div>
                <div style="width: 1px; height: 28px; background: var(--border-card);"></div>
                <div style="text-align: center;">
                  <div style="font-size: 10px; font-weight: 600; color: var(--text-dim);">Last Check Out</div>
                  <div style="font-size: 14px; font-weight: 800; margin-top: 1px;" id="sel-day-out-time">Active</div>
                  <div style="font-size: 9.5px; font-weight: 700; color: #16A34A;" id="sel-day-out-status">In Progress</div>
                </div>
              </div>

              <!-- Hourly Timeline Touchpoints -->
              <div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                  <div style="font-size: 11px; font-weight: 800; color: var(--text-secondary);">Timeline Touchpoints</div>
                  <span style="font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 8px; background: var(--bg-card-subtle);" id="sel-day-touchpoint-count">1 Touchpoint</span>
                </div>
                <div id="sel-day-timeline-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
              </div>
            </div>

          </div>

          <!-- ── SUB-VIEW 2: WEEKLY ── -->
          <div id="att-view-weekly" style="display: none; flex-direction: column; gap: 14px;">
            <div class="app-card" style="padding: 18px;">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                <div>
                  <div style="font-size: 10px; font-weight: 800; color: var(--text-dim); letter-spacing: 0.8px;">TOTAL HOURS</div>
                  <div style="font-size: 26px; font-weight: 900; letter-spacing: -0.5px;" id="weekly-total-hrs">00:00 <span style="font-size: 14px; font-weight: 700; color: var(--text-secondary);">hrs</span></div>
                </div>
                <div style="text-align: right;">
                  <div style="font-size: 10px; font-weight: 800; color: var(--text-dim); letter-spacing: 0.8px;">OVERTIME</div>
                  <div style="font-size: 20px; font-weight: 900; color: var(--primary-dark);" id="weekly-overtime-hrs">00:00 <span style="font-size: 13px; font-weight: 700; color: var(--text-secondary);">hrs</span></div>
                </div>
              </div>

              <!-- Vertical Bar Chart -->
              <div class="bar-chart-container" id="weekly-bar-chart-container">
                 <!-- Populated dynamically by renderWeeklyView() -->
              </div>

              <div style="display: flex; justify-content: center; gap: 10px; margin-top: 14px;">
                <span style="font-size: 11px; font-weight: 700; color: #059669; background: #ECFDF5; padding: 4px 10px; border-radius: 12px;">• Regular</span>
                <span style="font-size: 11px; font-weight: 700; color: #2563EB; background: #EFF6FF; padding: 4px 10px; border-radius: 12px;">• Holiday</span>
                <span style="font-size: 11px; font-weight: 700; color: #7C3AED; background: #EDE9FE; padding: 4px 10px; border-radius: 12px;">• Day Off</span>
              </div>
            </div>

            <!-- Daily Breakdown List -->
            <div>
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h3 style="font-size: 16px; font-weight: 800;">Daily Breakdown</h3>
                <span style="font-size: 11px; font-weight: 600; color: var(--text-secondary);">This week recorded</span>
              </div>

              <div id="weekly-breakdown-list" style="display: flex; flex-direction: column; gap: 8px;">
                 <!-- Populated dynamically by renderWeeklyView() -->
              </div>
            </div>
          </div>

          <!-- ── SUB-VIEW 3: OVERVIEW ── -->
          <div id="att-view-overview" style="display: none; flex-direction: column; gap: 14px;">
            <div class="app-card" style="padding: 20px 16px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div>
                  <div style="font-size: 11px; font-weight: 700; color: var(--text-dim);">Summary</div>
                  <div style="font-size: 14px; font-weight: 900;" id="overview-cycle-range">26 Oct - 25 Nov</div>
                </div>
                <span style="font-size: 12px; font-weight: 800; color: var(--text-secondary);" id="overview-working-days">0 Working days</span>
              </div>

              <!-- Segmented Donut -->
              <div class="donut-wrapper" id="overview-donut-wrapper">
                 <!-- Populated dynamically by renderOverviewView() -->
              </div>

              <!-- 5 Breakdown Metric Columns -->
              <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 20px;">
                <div>
                  <div style="width: 20px; height: 3px; background: #10B981; border-radius: 2px; margin-bottom: 4px;"></div>
                  <div style="font-size: 11px; color: var(--text-secondary); font-weight: 600;">Present</div>
                  <div style="font-size: 18px; font-weight: 900;" id="overview-metric-present">00</div>
                </div>
                <div>
                  <div style="width: 20px; height: 3px; background: #EF4444; border-radius: 2px; margin-bottom: 4px;"></div>
                  <div style="font-size: 11px; color: var(--text-secondary); font-weight: 600;">Absent</div>
                  <div style="font-size: 18px; font-weight: 900;" id="overview-metric-absent">00</div>
                </div>
                <div>
                  <div style="width: 20px; height: 3px; background: #06B6D4; border-radius: 2px; margin-bottom: 4px;"></div>
                  <div style="font-size: 11px; color: var(--text-secondary); font-weight: 600;">Holiday</div>
                  <div style="font-size: 18px; font-weight: 900;" id="overview-metric-holiday">00</div>
                </div>
                <div>
                  <div style="width: 20px; height: 3px; background: #F43F5E; border-radius: 2px; margin-bottom: 4px;"></div>
                  <div style="font-size: 11px; color: var(--text-secondary); font-weight: 600;">Leave</div>
                  <div style="font-size: 18px; font-weight: 900;" id="overview-metric-leave">00</div>
                </div>
                <div>
                  <div style="width: 20px; height: 3px; background: #94A3B8; border-radius: 2px; margin-bottom: 4px;"></div>
                  <div style="font-size: 11px; color: var(--text-secondary); font-weight: 600;">Rest Day</div>
                  <div style="font-size: 18px; font-weight: 900;" id="overview-metric-restday">00</div>
                </div>
              </div>

              <!-- Average Work Hours Footer -->
              <div style="border-top: 1px solid var(--border-card); margin-top: 18px; padding-top: 14px; display: flex; justify-content: space-between; align-items: flex-end;">
                <div>
                  <div style="font-size: 11px; color: var(--text-secondary); font-weight: 600;">Average Work Hours</div>
                  <div style="font-size: 22px; font-weight: 900; margin-top: 2px;" id="overview-avg-hours">00:00</div>
                </div>
                <span style="font-size: 11px; font-weight: 800; color: #10B981; background: #ECFDF5; padding: 4px 8px; border-radius: 12px;">Standard 09:00h</span>
              </div>
            </div>
          </div>

        </div>

        <!-- ── SECTION B: PUNCH APPROVALS (Reporting Manager View) ── -->
        <div id="att-punches-section" style="display: none; flex-direction: column; gap: 14px;">
          
          <!-- Company Geofence Range Card (Screenshot 2) -->
          <div class="app-card" style="padding: 16px;">
            <div style="display: flex; align-items: flex-start; gap: 12px;">
              <div style="width: 40px; height: 40px; border-radius: 50%; background: #FFF4E5; color: #D97706; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                <i data-lucide="target" style="width: 20px;"></i>
              </div>
              <div>
                <h3 style="font-size: 14px; font-weight: 800;">Company Geofence Range (20 Meters)</h3>
                <p style="font-size: 11px; color: var(--text-secondary); margin-top: 2px; line-height: 1.3;">
                  Punches logged > 20m from company centers require 2-Level verification (TL → Manager)
                </p>
              </div>
            </div>

            <!-- Building Chips -->
            <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px;">
              <div style="background: var(--bg-card-subtle); padding: 8px 12px; border-radius: 12px; font-size: 11.5px;">
                <div style="font-weight: 800;">🏛 Monarch House (HQ)</div>
                <div style="font-size: 10px; color: var(--text-dim); margin-top: 1px;">18.5229, 73.9069</div>
              </div>
              <div style="background: var(--bg-card-subtle); padding: 8px 12px; border-radius: 12px; font-size: 11.5px;">
                <div style="font-weight: 800;">🏢 Tech Center</div>
                <div style="font-size: 10px; color: var(--text-dim); margin-top: 1px;">18.5204, 73.8567</div>
              </div>
              <div style="background: var(--bg-card-subtle); padding: 8px 12px; border-radius: 12px; font-size: 11.5px;">
                <div style="font-weight: 800;">🏗 Regional Office</div>
                <div style="font-size: 10px; color: var(--text-dim); margin-top: 1px;">18.5312, 73.8445</div>
              </div>
            </div>
          </div>

          <!-- Pending Punches or Zero Card -->
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 style="font-size: 16px; font-weight: 800;" id="punch-req-header">Pending Punch Requests (0)</h3>
            <button onclick="loadPunchApprovals()" class="action-icon-btn" style="width: 32px; height: 32px;"><i data-lucide="rotate-cw" style="width: 15px;"></i></button>
          </div>

          <div id="punch-req-container">
            <div class="app-card" style="padding: 32px 16px; text-align: center;">
              <div style="width: 48px; height: 48px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center; margin: 0 auto 12px auto;">
                <i data-lucide="shield-check" style="width: 24px;"></i>
              </div>
              <h4 style="font-size: 15px; font-weight: 900;">Zero Pending Punches</h4>
              <p style="font-size: 11.5px; color: var(--text-secondary); margin-top: 4px;">
                All subordinate punches are verified within the 20m office range.
              </p>
            </div>
          </div>

        </div>

      </div>

      <!-- ═══════════════════════════════════════════════════════════════════ -->
      <!-- TAB 3: LEAVE MANAGEMENT                                             -->
      <!-- ═══════════════════════════════════════════════════════════════════ -->
      <div id="view-leaves" class="screen-body" style="display: none;">
        
        <!-- Segment Switcher for Privileged Managers -->
        <div id="leaves-mgr-tabs" class="segmented-pill-bar" style="display: none;">
          <button id="leaves-subtab-my" onclick="switchLeavesView('my')" class="segment-tab-btn active">
            <i data-lucide="umbrella" style="width: 14px;"></i>
            <span>My Leaves</span>
          </button>
          <button id="leaves-subtab-team" onclick="switchLeavesView('team')" class="segment-tab-btn">
            <i data-lucide="users" style="width: 14px;"></i>
            <span>Team & Approvals</span>
            <span id="leaves-team-badge" style="display: none; background: #FF2A55; color: #FFF; font-size: 9px; padding: 1px 5px; border-radius: 10px;">0</span>
          </button>
        </div>

        <!-- ── SUB-VIEW A: MY LEAVES ── -->
        <div id="leaves-my-view" style="display: flex; flex-direction: column; gap: 14px;">
          
          <!-- Annual Leave Overview Hero Card -->
          <div class="app-card" style="padding: 20px 18px; background: linear-gradient(135deg, rgba(245, 169, 82, 0.12), rgba(245, 169, 82, 0.04));">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
              <div>
                <h3 style="font-size: 16px; font-weight: 800;">Annual Leave Overview</h3>
                <p style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">Fiscal Year 2026 - 2027</p>
              </div>
              <span id="leave-badge-days-left" style="font-size: 11px; font-weight: 800; padding: 4px 10px; border-radius: 14px; background: var(--primary); color: var(--primary-text);">6.0 Days Left</span>
            </div>

            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 18px; text-align: center;">
              <div style="background: var(--bg-card); padding: 12px 6px; border-radius: 14px; border: 1px solid var(--border-card);">
                <div style="font-size: 18px; font-weight: 900;" id="leave-stat-allotted">6.0</div>
                <div style="font-size: 10.5px; color: var(--text-dim); margin-top: 2px;">Allotted</div>
              </div>
              <div style="background: var(--bg-card); padding: 12px 6px; border-radius: 14px; border: 1px solid var(--border-card);">
                <div style="font-size: 18px; font-weight: 900;" id="leave-stat-used">0.0</div>
                <div style="font-size: 10.5px; color: var(--text-dim); margin-top: 2px;">Used</div>
              </div>
              <div style="background: var(--bg-card); padding: 12px 6px; border-radius: 14px; border: 1px solid var(--border-card);">
                <div style="font-size: 18px; font-weight: 900; color: #10B981;" id="leave-stat-rem">6.0</div>
                <div style="font-size: 10.5px; color: var(--text-dim); margin-top: 2px;">Available</div>
              </div>
            </div>
          </div>

          <!-- Apply Leave CTA Card -->
          <div class="app-card" style="padding: 16px; display: flex; align-items: center; justify-content: space-between;">
            <div>
              <h4 style="font-size: 14px; font-weight: 800;">Need Time Off?</h4>
              <p style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">Apply for leave or early regularization</p>
            </div>
            <button onclick="openApplyLeaveModal()" class="btn-solid-primary" style="width: auto; padding: 10px 18px; font-size: 13px;">
              <i data-lucide="plus-circle" style="width: 16px;"></i>
              <span>Apply Leave</span>
            </button>
          </div>

          <!-- Recent Applications Header & Filters -->
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
              <h3 style="font-size: 16px; font-weight: 800;">Recent Applications</h3>
              <div style="display: flex; gap: 4px;">
                <button onclick="filterLeaves('All', this)" class="segment-tab-btn active" style="padding: 4px 10px; font-size: 11px;">All</button>
                <button onclick="filterLeaves('Pending', this)" class="segment-tab-btn" style="padding: 4px 10px; font-size: 11px;">Pending</button>
                <button onclick="filterLeaves('Approved', this)" class="segment-tab-btn" style="padding: 4px 10px; font-size: 11px;">Approved</button>
              </div>
            </div>

            <!-- List of Leaves -->
            <div id="my-leaves-container" style="display: flex; flex-direction: column; gap: 10px;">
              <div class="app-card" style="padding: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="width: 32px; height: 32px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center;">
                      <i data-lucide="check-circle" style="width: 16px;"></i>
                    </div>
                    <div>
                      <div style="font-size: 13.5px; font-weight: 800;">Casual Leave (Personal)</div>
                      <div style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">Earned Leave • 1 Day</div>
                    </div>
                  </div>
                  <span style="font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 10px; background: #DCFCE7; color: #166534;">Approved</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-secondary); margin-top: 10px; background: var(--bg-card-subtle); padding: 8px 10px; border-radius: 8px;">
                  <span>📅 2026-09-18</span>
                  <span>2026-09-18</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Upcoming Holidays -->
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
              <h3 style="font-size: 16px; font-weight: 800; margin: 0;">Upcoming Holidays</h3>
              <button type="button" onclick="openAllHolidaysModal()" style="display: flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 800; color: #D97706; background: #FEF3C7; border: 1px solid #FDE68A; border-radius: 12px; padding: 4px 10px; cursor: pointer; transition: all 0.2s;">
                <i data-lucide="calendar" style="width: 13px;"></i>
                <span>All Holidays</span>
                <i data-lucide="chevron-right" style="width: 13px;"></i>
              </button>
            </div>
            <div id="upcoming-holidays-container" style="display: flex; flex-direction: column; gap: 8px;">
              <div class="app-card" style="padding: 12px 14px; display: flex; justify-content: space-between; align-items: center;">
                <div style="display: flex; align-items: center; gap: 10px;">
                  <div style="width: 32px; height: 32px; border-radius: 8px; background: #EFF6FF; color: #2563EB; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                    <i data-lucide="sparkles" style="width: 16px;"></i>
                  </div>
                  <div>
                    <div style="font-size: 13px; font-weight: 800;">Dussehra</div>
                    <div style="font-size: 10.5px; color: var(--text-dim);">Tuesday</div>
                  </div>
                </div>
                <div style="text-align: right;">
                  <span style="font-size: 11px; font-weight: 700; color: var(--text-secondary);">20 Oct 2026</span>
                  <div style="font-size: 9.5px; font-weight: 800; color: #2563EB; background: #EFF6FF; padding: 1px 6px; border-radius: 6px; margin-top: 2px;">In 5 days</div>
                </div>
              </div>
            </div>
          </div>

        </div>

        <!-- ── SUB-VIEW B: TEAM & APPROVALS (Manager Operations) ── -->
        <div id="leaves-team-view" style="display: none; flex-direction: column; gap: 14px;">
          
          <!-- Manager Operations Hero Card (Screenshot 1) -->
          <div class="app-card" style="padding: 18px; border: 1px solid var(--border-card);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
              <div>
                <h3 style="font-size: 16px; font-weight: 900;">Manager Operations</h3>
                <p style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">Supervisor portal & approval center</p>
              </div>
              <button onclick="loadTeamApprovalsData()" class="action-icon-btn" style="width: 32px; height: 32px;"><i data-lucide="rotate-cw" style="width: 15px;"></i></button>
            </div>

            <!-- 3 Stat Tiles Cluster (Screenshot 1) -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;">
              <div style="background: var(--bg-card-subtle); padding: 12px 8px; border-radius: 14px;">
                <i data-lucide="users" style="width: 16px; color: #2563EB; margin-bottom: 4px;"></i>
                <div style="font-size: 16px; font-weight: 900;" id="mgr-stat-leads">0 Leads</div>
                <div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">Team Leaders</div>
              </div>

              <div style="background: var(--bg-card-subtle); padding: 12px 8px; border-radius: 14px;">
                <i data-lucide="user-check" style="width: 16px; color: #10B981; margin-bottom: 4px;"></i>
                <div style="font-size: 16px; font-weight: 900;" id="mgr-stat-present">2/9</div>
                <div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">Present Today</div>
              </div>

              <div style="background: var(--bg-card-subtle); padding: 12px 8px; border-radius: 14px;">
                <i data-lucide="clipboard-clock" style="width: 16px; color: #EF4444; margin-bottom: 4px;"></i>
                <div style="font-size: 16px; font-weight: 900;" id="mgr-stat-pending">1 Pending</div>
                <div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">Leave Action</div>
              </div>
            </div>
          </div>

          <!-- Leave Requests Status Card (Screenshot 1) -->
          <div class="app-card" style="padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
              <div>
                <h3 style="font-size: 16px; font-weight: 900;">Leave Requests Status</h3>
                <p style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">Monitor leave status across all departments</p>
              </div>
              <span id="mgr-pending-pill" style="font-size: 10.5px; font-weight: 800; padding: 3px 8px; border-radius: 12px; background: #FF2A55; color: #FFF;">1 Pending</span>
            </div>

            <!-- Filter Chips (Screenshot 1) -->
            <div id="team-leaves-filter-container" style="display: flex; gap: 8px; margin-bottom: 10px; overflow-x: auto;">
              <button onclick="filterTeamLeaves('All', this)" class="segment-tab-btn active" style="flex: none; padding: 6px 14px; border-radius: 14px; background: var(--primary); color: var(--primary-text);">All</button>
              <button onclick="filterTeamLeaves('Pending', this)" class="segment-tab-btn" style="flex: none; padding: 6px 14px; border-radius: 14px; background: var(--bg-card); border: 1px solid var(--border-card);">Pending</button>
              <button onclick="filterTeamLeaves('Approved', this)" class="segment-tab-btn" style="flex: none; padding: 6px 14px; border-radius: 14px; background: var(--bg-card); border: 1px solid var(--border-card);">Approved</button>
              <button onclick="filterTeamLeaves('Rejected', this)" class="segment-tab-btn" style="flex: none; padding: 6px 14px; border-radius: 14px; background: var(--bg-card); border: 1px solid var(--border-card);">Rejected</button>
            </div>

            <!-- Department Filter Chips for Admin -->
            <div id="team-leaves-dept-filter-container" style="display: none; gap: 6px; margin-bottom: 14px; overflow-x: auto;"></div>

            <!-- Subordinate Leave Requests Cards List (Screenshot 1) -->
            <div id="team-leaves-list-container" style="display: flex; flex-direction: column; gap: 12px;"></div>
          </div>

          <!-- Live Team Attendance Monitor List -->
          <div>
            <h3 style="font-size: 16px; font-weight: 900; margin-bottom: 10px;">Live Team Attendance</h3>
            <div id="team-members-list-container" style="display: flex; flex-direction: column; gap: 8px;"></div>
          </div>

        </div>

      </div>

      <!-- ═══════════════════════════════════════════════════════════════════ -->
      <!-- TAB 4: PROFILE                                                      -->
      <!-- ═══════════════════════════════════════════════════════════════════ -->
      <div id="view-profile" class="screen-body" style="display: none;">
        
        <!-- User Hero Card -->
        <div class="app-card" style="text-align: center; padding: 24px 16px;">
          <div class="user-avatar-pill" style="width: 68px; height: 68px; font-size: 28px; margin: 0 auto 12px auto;" id="prof-hero-avatar">
            <span>U</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: center; gap: 4px;">
            <h2 style="font-size: 19px; font-weight: 900; letter-spacing: -0.3px;" id="prof-hero-name">Utkarsh Rajendra Pingale</h2>
            <i data-lucide="badge-check" style="width: 18px; color: #F5A952; fill: #F5A952;"></i>
          </div>
          <p style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;" id="prof-hero-role">Developer • IT Department</p>

          <div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; margin: 14px 0;">
            <span style="font-size: 11px; font-weight: 700; background: var(--bg-card-subtle); padding: 4px 10px; border-radius: 12px;" id="prof-hero-empid">#1951</span>
            <span style="font-size: 11px; font-weight: 700; background: var(--bg-card-subtle); padding: 4px 10px; border-radius: 12px;" id="prof-hero-doj">📅 Joined 27 Apr 2026</span>
            <span style="font-size: 11px; font-weight: 700; background: var(--bg-card-subtle); padding: 4px 10px; border-radius: 12px;" id="prof-hero-phone">📞 8805298115</span>
            <span style="font-size: 11px; font-weight: 700; background: var(--bg-card-subtle); padding: 4px 10px; border-radius: 12px;" id="prof-hero-email">@ utkarshpingale11@gmail.com</span>
          </div>

          <div style="display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 12px; background: #DCFCE7; color: #166534; font-size: 11px; font-weight: 800;">
            <span style="width: 5px; height: 5px; border-radius: 50%; background: #166534;"></span>
            <span>Active</span>
          </div>
        </div>

        <!-- Profile Complete 100% Card -->
        <div class="app-card" style="padding: 14px; border: 1.5px solid #10B981; background: var(--bg-card);">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="width: 32px; height: 32px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center;">
                <i data-lucide="check" style="width: 16px;"></i>
              </div>
              <div>
                <div style="font-size: 13.5px; font-weight: 800;">Profile Complete 🎉</div>
                <div style="font-size: 10.5px; color: var(--text-secondary);">All required details verified 100%</div>
              </div>
            </div>
            <span style="font-size: 10.5px; font-weight: 800; padding: 3px 8px; border-radius: 12px; background: #10B981; color: #FFF;">100%</span>
          </div>
          <div style="width: 100%; height: 5px; background: #E2E8F0; border-radius: 4px; margin-top: 10px; overflow: hidden;">
            <div style="width: 100%; height: 100%; background: #10B981;"></div>
          </div>
        </div>

        <!-- Employee Information Form -->
        <div class="app-card" style="padding: 16px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 14px;">
            <div style="width: 32px; height: 32px; border-radius: 8px; background: var(--bg-card-subtle); display: flex; align-items: center; justify-content: center;">
              <i data-lucide="user-round" style="width: 16px;"></i>
            </div>
            <div>
              <h3 style="font-size: 14px; font-weight: 800;">Employee Information</h3>
              <p style="font-size: 10.5px; color: var(--text-dim);">Update details to reach 100% completion</p>
            </div>
          </div>

          <form onsubmit="handleProfileSave(event)" style="display: flex; flex-direction: column; gap: 12px;">
            <div>
              <label class="field-label">FULL NAME</label>
              <input type="text" id="prof-form-name" class="field-input" value="Utkarsh Rajendra Pingale">
            </div>

            <div>
              <label class="field-label">EMPLOYEE ID (FIXED)</label>
              <input type="text" id="prof-form-empid" class="field-input" value="1951" readonly style="opacity: 0.7;">
            </div>

            <div>
              <label class="field-label">PHONE NUMBER</label>
              <input type="tel" id="prof-form-phone" class="field-input" value="8805298115">
            </div>

            <div>
              <label class="field-label">EMAIL ADDRESS</label>
              <input type="email" id="prof-form-email" class="field-input" value="utkarshpingale11@gmail.com">
            </div>

            <button type="submit" class="btn-solid-primary" style="margin-top: 6px;">
              <i data-lucide="check-circle" style="width: 16px;"></i>
              <span>Save & Verify Profile</span>
            </button>
          </form>
        </div>

        <!-- Monthly Performance Card -->
        <div class="app-card" style="padding: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div>
              <h3 style="font-size: 14px; font-weight: 800;">Monthly Performance</h3>
              <div style="font-size: 10px; font-weight: 700; color: var(--text-dim); letter-spacing: 0.6px;">ATTENDANCE SNAPSHOT</div>
            </div>
            <span style="font-size: 10.5px; font-weight: 800; padding: 3px 8px; border-radius: 12px; background: var(--bg-card-subtle);">This Month</span>
          </div>

          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; text-align: center;">
            <div style="background: var(--bg-card-subtle); padding: 12px 6px; border-radius: 14px;">
              <div style="width: 24px; height: 24px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center; margin: 0 auto 6px auto;">
                <i data-lucide="check" style="width: 13px;"></i>
              </div>
              <div style="font-size: 16px; font-weight: 900;">98%</div>
              <div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">Present Rate</div>
            </div>

            <div style="background: var(--bg-card-subtle); padding: 12px 6px; border-radius: 14px;">
              <div style="width: 24px; height: 24px; border-radius: 50%; background: #EFF6FF; color: #2563EB; display: flex; align-items: center; justify-content: center; margin: 0 auto 6px auto;">
                <i data-lucide="calendar" style="width: 13px;"></i>
              </div>
              <div style="font-size: 16px; font-weight: 900;">22</div>
              <div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">Work Days</div>
            </div>

            <div style="background: var(--bg-card-subtle); padding: 12px 6px; border-radius: 14px;">
              <div style="width: 24px; height: 24px; border-radius: 50%; background: #FEF3C7; color: #D97706; display: flex; align-items: center; justify-content: center; margin: 0 auto 6px auto;">
                <i data-lucide="clock" style="width: 13px;"></i>
              </div>
              <div style="font-size: 16px; font-weight: 900;">96%</div>
              <div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">Punctuality</div>
            </div>
          </div>
        </div>

        <!-- Shift & Work Details Card -->
        <div class="app-card" style="padding: 16px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
            <div style="width: 32px; height: 32px; border-radius: 8px; background: var(--bg-card-subtle); display: flex; align-items: center; justify-content: center;">
              <i data-lucide="briefcase" style="width: 16px;"></i>
            </div>
            <div>
              <h3 style="font-size: 14px; font-weight: 800;">Shift & Work Details</h3>
              <p style="font-size: 10.5px; color: var(--text-dim);">Assigned corporate workstation & roster</p>
            </div>
          </div>

          <div style="background: var(--bg-card-subtle); padding: 12px; border-radius: 14px; display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <i data-lucide="alarm-clock" style="width: 18px; color: #2563EB;"></i>
              <div>
                <div style="font-size: 11px; color: var(--text-dim); font-weight: 600;">Regular Shift</div>
                <div style="font-size: 13.5px; font-weight: 800; margin-top: 1px;">09:30 AM - 06:30 PM</div>
              </div>
            </div>
            <span style="font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 8px; background: var(--bg-card);">Mon - Fri</span>
          </div>
        </div>

        <!-- Attendance Settings Card -->
        <div class="app-card" style="padding: 16px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
            <div style="width: 32px; height: 32px; border-radius: 8px; background: var(--bg-card-subtle); display: flex; align-items: center; justify-content: center;">
              <i data-lucide="settings" style="width: 16px;"></i>
            </div>
            <div>
              <h3 style="font-size: 14px; font-weight: 800;">Attendance Settings</h3>
              <p style="font-size: 10.5px; color: var(--text-dim);">Automation triggers and compliance options</p>
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="width: 32px; height: 32px; border-radius: 50%; background: var(--bg-card-subtle); display: flex; align-items: center; justify-content: center;">
                <i data-lucide="bell" style="width: 16px;"></i>
              </div>
              <div>
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span style="font-size: 13px; font-weight: 800;">Daily Check-in Reminder</span>
                  <span style="font-size: 9.5px; font-weight: 800; padding: 1px 6px; border-radius: 8px; background: #FEF3C7; color: #D97706;">🕒 08:55 AM</span>
                </div>
                <div style="font-size: 10.5px; color: var(--text-dim); margin-top: 1px;">Ping at 08:55 AM (5 min prior)</div>
              </div>
            </div>
            <label style="position: relative; display: inline-block; width: 44px; height: 24px; cursor: pointer;">
              <input type="checkbox" checked style="opacity: 0; width: 0; height: 0;">
              <span style="position: absolute; inset: 0; background-color: var(--primary); border-radius: 24px; transition: .3s;"></span>
              <span style="position: absolute; content: ''; height: 18px; width: 18px; left: 22px; bottom: 3px; background-color: white; border-radius: 50%; transition: .3s;"></span>
            </label>
          </div>
        </div>

        <!-- Account Security / Sign Out -->
        <div class="app-card" style="padding: 16px;">
          <h3 style="font-size: 14px; font-weight: 800; margin-bottom: 12px;">Account Security</h3>
          <form onsubmit="handlePasswordUpdate(event)" style="display: flex; flex-direction: column; gap: 10px;">
            <div>
              <label class="field-label">Current Password</label>
              <input type="password" id="pwd-old" class="field-input" placeholder="••••••••" required>
            </div>
            <div>
              <label class="field-label">New Password</label>
              <input type="password" id="pwd-new" class="field-input" placeholder="••••••••" required minlength="6">
            </div>
            <button type="submit" class="btn-solid-primary" style="padding: 10px; font-size: 13px; margin-top: 4px;">Update Password</button>
          </form>
          
          <button onclick="handleLogout()" class="btn-reject-outline" style="width: 100%; margin-top: 14px; padding: 12px; border-radius: var(--radius-pill);">
            <i data-lucide="log-out" style="width: 16px;"></i>
            <span>Sign Out of Account</span>
          </button>
        </div>

      </div>

    </div>

    <!-- ── 4. FLOATING BOTTOM NAVIGATION CAPSULE ─────────────────────────── -->
    <nav id="phone-nav-bar" class="floating-nav-container" style="display: none;">
      <div class="nav-item active" id="nav-item-dashboard" onclick="switchNavTab('dashboard')">
        <i data-lucide="home" style="width: 19px;"></i>
        <span>Home</span>
      </div>
      <div class="nav-item" id="nav-item-attendance" onclick="switchNavTab('attendance')">
        <i data-lucide="calendar" style="width: 19px;"></i>
        <span>History</span>
        <span class="nav-badge-dot" id="nav-punch-dot" style="display: none;">0</span>
      </div>
      <div class="nav-item" id="nav-item-leaves" onclick="switchNavTab('leaves')">
        <i data-lucide="umbrella" style="width: 19px;"></i>
        <span>Leave</span>
        <span class="nav-badge-dot" id="nav-leaves-dot" style="display: none;">0</span>
      </div>
      <div class="nav-item" id="nav-item-profile" onclick="switchNavTab('profile')">
        <i data-lucide="user" style="width: 19px;"></i>
        <span>Profile</span>
        <span class="avatar-alert-dot" id="nav-profile-alert-dot" style="display: none; top: 4px; right: 14px;"></span>
      </div>
    </nav>

  </div>

  <!-- ── 5. MODAL 1: WORK ENTRY SHEET ───────────────────────────────────── -->
  <div id="modal-work-entry" class="app-modal-backdrop">
    <div class="app-modal-sheet">
      <!-- Drag Handle -->
      <div style="width: 44px; height: 5px; background: var(--text-secondary); opacity: 0.35; border-radius: 10px; margin: -6px auto 4px auto;"></div>

      <div style="display: flex; justify-content: space-between; align-items: center;">
        <h3 style="font-size: 17.5px; font-weight: 800; letter-spacing: -0.2px;">Log Project Work</h3>
        <button type="button" onclick="closeWorkEntryModal()" class="action-icon-btn" style="width: 32px; height: 32px; border-radius: 50%;"><i data-lucide="x" style="width: 16px;"></i></button>
      </div>

      <!-- Live Loading Bar -->
      <div id="we-loading-bar" style="height: 2px; width: 100%; background: #F5A952; display: none; border-radius: 2px; animation: pulse 1s infinite;"></div>

      <!-- WORK DATE & PROJECT ID Card -->
      <div class="app-card" style="padding: 15px; border-radius: 20px;">
        <!-- WORK DATE -->
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <i data-lucide="calendar" style="width: 15px; color: #38BDF8;"></i>
            <span class="field-label" style="margin-bottom: 0; font-size: 11px; font-weight: 800; letter-spacing: 0.8px;">WORK DATE</span>
          </div>
          <span style="font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 8px; background: rgba(16, 185, 129, 0.15); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.3);">Automated</span>
        </div>

        <div style="position: relative; cursor: pointer;" onclick="const el=document.getElementById('we-work-date'); if(el.showPicker) el.showPicker(); else el.focus();">
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-input); padding: 11px 14px; border-radius: 14px; border: 1px solid var(--border-input);">
            <span style="font-size: 14px; font-weight: 700; color: var(--text-primary);" id="we-work-date-display">13-10-2026</span>
            <i data-lucide="calendar-days" style="width: 17px; color: var(--text-secondary);"></i>
          </div>
          <input type="date" id="we-work-date" style="position: absolute; opacity: 0; inset: 0; width: 100%; height: 100%; cursor: pointer;" onchange="onWorkEntryDateChange(this.value)">
        </div>

        <!-- PROJECT ID / NAME -->
        <div style="margin-top: 15px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 6px;">
              <i data-lucide="folder-kanban" style="width: 15px; color: #F59E0B;"></i>
              <span class="field-label" style="margin-bottom: 0; font-size: 11px; font-weight: 800; letter-spacing: 0.8px;">PROJECT ID / NAME</span>
            </div>
            <span style="font-size: 10px; font-weight: 700; color: #EF4444;">Required</span>
          </div>

          <!-- Searchable project selector -->
          <div class="we-project-search-container" style="position: relative;">
            <div style="display: flex; align-items: center; background: var(--bg-input); border: 1px solid var(--border-input); border-radius: 14px; padding: 3px 10px; transition: border-color 0.2s;" id="we-project-input-box">
              <input type="text" id="we-project-search" placeholder="Type or select project..." autocomplete="off"
                     style="flex: 1; background: transparent; border: none; outline: none; padding: 8px 4px; font-size: 13px; font-weight: 600; color: var(--text-primary);"
                     onfocus="openProjectDropdown()" oninput="filterProjectDropdown(this.value)">
              <button type="button" id="we-project-clear-btn" onclick="clearProjectSelection()" style="display: none; background: transparent; border: none; color: var(--text-secondary); cursor: pointer; padding: 4px;">
                <i data-lucide="x" style="width: 14px;"></i>
              </button>
              <button type="button" onclick="toggleProjectDropdown()" style="background: transparent; border: none; color: var(--text-secondary); cursor: pointer; padding: 4px;">
                <i data-lucide="chevron-down" style="width: 18px;"></i>
              </button>
            </div>

            <!-- Dropdown options list -->
            <div id="we-project-dropdown-list" style="display: none; position: absolute; top: calc(100% + 4px); left: 0; right: 0; max-height: 220px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 14px; box-shadow: 0 10px 30px rgba(0,0,0,0.25); z-index: 50;">
              <!-- Filled dynamically via JS -->
            </div>
          </div>
          <input type="hidden" id="we-selected-project-id" value="">
          <input type="hidden" id="we-selected-project-name" value="">
        </div>
      </div>

      <!-- ASSIGNMENT SCOPE Card -->
      <div class="app-card" style="padding: 15px; border-radius: 20px;">
        <div style="display: flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 800; color: #D97706; letter-spacing: 0.8px; margin-bottom: 12px;">
          <i data-lucide="git-fork" style="width: 15px;"></i>
          <span>ASSIGNMENT SCOPE</span>
        </div>

        <!-- DEPARTMENT -->
        <div style="margin-bottom: 12px;">
          <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
            <i data-lucide="building-2" style="width: 14px; color: var(--text-secondary);"></i>
            <label class="field-label" style="margin-bottom: 0;">DEPARTMENT</label>
          </div>
          <select id="we-dept" class="field-select" onchange="onWorkEntryDeptChange()">
            <!-- Loaded dynamically from DB -->
          </select>
        </div>

        <!-- TASK -->
        <div style="margin-bottom: 12px;">
          <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
            <i data-lucide="folder" style="width: 14px; color: var(--text-secondary);"></i>
            <label class="field-label" style="margin-bottom: 0;">TASK</label>
          </div>
          <select id="we-task" class="field-select" onchange="onWorkEntryTaskChange()">
            <!-- Loaded dynamically based on Dept -->
          </select>
        </div>

        <!-- SUBTASK -->
        <div>
          <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
            <i data-lucide="pin" style="width: 14px; color: var(--text-secondary);"></i>
            <label class="field-label" style="margin-bottom: 0;">SUBTASK</label>
          </div>
          <select id="we-subtask" class="field-select">
            <!-- Loaded dynamically based on Task -->
          </select>
        </div>
      </div>

      <!-- OUTPUT & EFFORT Card -->
      <div class="app-card" style="padding: 15px; border-radius: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div style="display: flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 800; color: #0D9488; letter-spacing: 0.8px;">
            <i data-lucide="timer" style="width: 15px;"></i>
            <span>OUTPUT & EFFORT</span>
          </div>
          <span id="we-total-effort-text" style="font-size: 11px; font-weight: 700; color: var(--text-secondary);">Total: 0h 0m</span>
        </div>

        <!-- QUANTITY & UNIT -->
        <div style="display: flex; gap: 10px; margin-bottom: 12px;">
          <div style="flex: 3;">
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
              <i data-lucide="gauge" style="width: 14px; color: var(--text-secondary);"></i>
              <label class="field-label" style="margin-bottom: 0;">QUANTITY PRODUCED</label>
            </div>
            <input type="number" id="we-qty" class="field-input" placeholder="0.0" step="any" min="0">
          </div>
          <div style="flex: 2;">
            <label class="field-label" style="margin-bottom: 6px;">UNIT</label>
            <select id="we-unit" class="field-select">
              <!-- Loaded dynamically from DB -->
            </select>
          </div>
        </div>

        <!-- HOURS & MINUTES -->
        <div style="display: flex; gap: 10px; margin-bottom: 12px;">
          <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
              <i data-lucide="clock" style="width: 14px; color: var(--text-secondary);"></i>
              <label class="field-label" style="margin-bottom: 0;">HOURS</label>
            </div>
            <input type="number" id="we-hours" class="field-input" placeholder="0" min="0" oninput="updateWorkEntryTotalEffort()">
          </div>
          <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
              <i data-lucide="hourglass" style="width: 14px; color: var(--text-secondary);"></i>
              <label class="field-label" style="margin-bottom: 0;">MINUTES</label>
            </div>
            <input type="number" id="we-mins" class="field-input" placeholder="0" min="0" max="59" oninput="updateWorkEntryTotalEffort()">
          </div>
        </div>

        <!-- REVISION -->
        <div>
          <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
            <i data-lucide="history" style="width: 14px; color: var(--text-secondary);"></i>
            <label class="field-label" style="margin-bottom: 0;">REVISION</label>
          </div>
          <select id="we-rev" class="field-select">
            <!-- Loaded dynamically from DB -->
          </select>
        </div>
      </div>

      <!-- REMARKS Card (MANDATORY) -->
      <div class="app-card" id="we-remarks-card" style="padding: 15px; border-radius: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <i data-lucide="message-square" style="width: 15px; color: #A855F7;"></i>
            <span class="field-label" style="margin-bottom: 0; font-size: 11px; font-weight: 800; letter-spacing: 0.8px;">REMARKS</span>
          </div>
          <span style="font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 8px; background: rgba(239, 68, 68, 0.15); color: #EF4444; border: 1px solid rgba(239, 68, 68, 0.3);">Required</span>
        </div>

        <textarea id="we-remarks" class="field-textarea" rows="3" placeholder="Explain work done today..." oninput="updateWorkEntryRemarksValidation()"></textarea>

        <!-- Quick chips -->
        <div style="display: flex; gap: 6px; overflow-x: auto; padding-top: 10px; scrollbar-width: none;">
          <button type="button" class="we-quick-chip" onclick="addWorkEntryQuickChip('+ Delayed by weather')">+ Delayed by weather</button>
          <button type="button" class="we-quick-chip" onclick="addWorkEntryQuickChip('+ Milestone reached')">+ Milestone reached</button>
          <button type="button" class="we-quick-chip" onclick="addWorkEntryQuickChip('+ Equipment issue')">+ Equipment issue</button>
          <button type="button" class="we-quick-chip" onclick="addWorkEntryQuickChip('+ Client site visit')">+ Client site visit</button>
          <button type="button" class="we-quick-chip" onclick="addWorkEntryQuickChip('+ QA Approved')">+ QA Approved</button>
        </div>
      </div>

      <!-- Footer Buttons -->
      <div style="display: flex; gap: 10px; margin-top: 4px; padding-bottom: calc(20px + env(safe-area-inset-bottom, 16px));">
        <button type="button" onclick="closeWorkEntryModal()" style="flex: 1; padding: 13px; border-radius: 20px; font-weight: 700; font-size: 13px; border: 1px solid var(--border-card); background: transparent; color: var(--text-secondary); cursor: pointer;">
          Cancel
        </button>
        <button type="button" id="btn-save-we" onclick="saveWorkEntry()" class="btn-solid-primary" style="flex: 2; padding: 13px; border-radius: 20px; font-weight: 800; font-size: 13.5px; display: flex; align-items: center; justify-content: center; gap: 8px;">
          <i data-lucide="check-circle" style="width: 17px;"></i>
          <span id="btn-save-we-text">Save Work Entry</span>
        </button>
      </div>
    </div>
  </div>

  <!-- ── 6. MODAL 2: APPLY LEAVE / REGULARIZATION ────────────────────────── -->
  <div id="modal-apply-leave" class="app-modal-backdrop">
    <div class="app-modal-sheet">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
          <h3 style="font-size: 18px; font-weight: 900;">Apply Leave / Regularization</h3>
          <p style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">Submit leave application or attendance regularization</p>
        </div>
        <button onclick="closeApplyLeaveModal()" class="action-icon-btn" style="width: 32px; height: 32px;"><i data-lucide="x" style="width: 16px;"></i></button>
      </div>

      <!-- Blue Callout Box -->
      <div style="background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 14px; padding: 12px; display: flex; gap: 10px; font-size: 11px; color: #1E40AF; line-height: 1.4;">
        <i data-lucide="info" style="width: 18px; flex-shrink: 0; color: #2563EB;"></i>
        <div>
          <b>What is Regularization?</b> Company provides concession to go home up to 2 hours early or regularize forgotten punch-outs with manager approval without leave deduction.
        </div>
      </div>

      <form onsubmit="handleApplyLeaveFormSubmit(event)" style="display: flex; flex-direction: column; gap: 14px;">
        <div>
          <label class="field-label">Request / Leave type <span style="color: #EF4444;">*</span></label>
          <select id="apply-leave-type" class="field-select" style="border-color: #2563EB;" onchange="onApplyLeaveTypeChange()">
            <option value="Earned Leave">Earned Leave</option>
            <option value="Casual Leave">Casual Leave</option>
            <option value="Half Day Leave">Half Day Leave</option>
            <option value="Compensatory Off">Compensatory Off</option>
            <option value="Regularization">Attendance Regularization</option>
          </select>
        </div>

        <div style="display: grid; grid-template-columns: 1.5fr 1fr; gap: 8px;">
          <div>
            <label class="field-label">From date <span style="color: #EF4444;">*</span></label>
            <input type="date" id="apply-from-date" class="field-input" required value="2026-10-09" onchange="onApplyFromDateChange()">
          </div>
          <div>
            <label class="field-label">Session</label>
            <select id="apply-from-session" class="field-select" onchange="recalculateLeaveDays()">
              <option value="Session 1">Session 1</option>
              <option value="Session 2">Session 2</option>
            </select>
          </div>
        </div>

        <div id="apply-to-date-row" style="display: grid; grid-template-columns: 1.5fr 1fr; gap: 8px;">
          <div>
            <label class="field-label">To date <span style="color: #EF4444;">*</span></label>
            <input type="date" id="apply-to-date" class="field-input" required value="2026-10-09" onchange="recalculateLeaveDays()">
          </div>
          <div>
            <label class="field-label">Session</label>
            <select id="apply-to-session" class="field-select" onchange="recalculateLeaveDays()">
              <option value="Session 2">Session 2</option>
              <option value="Session 1">Session 1</option>
            </select>
          </div>
        </div>

        <!-- Dynamic Calculation Card -->
        <div id="apply-calc-card" style="background: #ECFDF5; border: 1.5px solid #10B981; border-radius: 14px; padding: 12px; display: flex; gap: 10px; transition: all 0.2s ease;">
          <div id="apply-calc-icon-wrapper" style="width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px;">
            <i id="apply-calc-icon" data-lucide="check-circle" style="width: 18px; color: #10B981;"></i>
          </div>
          <div style="flex: 1;">
            <div id="apply-calc-title" style="font-size: 12.5px; font-weight: 800; color: #065F46;">1 Day (Earned Leave)</div>
            <div id="apply-calc-desc" style="font-size: 11px; color: #047857; margin-top: 1px;">Will deduct 1 day(s) from Earned Leave balance (<span id="apply-leave-avail-days">6.0</span> Days currently available).</div>
          </div>
        </div>

        <!-- Reporting Manager / Approver -->
        <div>
          <label class="field-label">REPORTING MANAGER / APPROVER</label>
          <div style="background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 14px; padding: 12px; display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="width: 34px; height: 34px; border-radius: 8px; background: #DBEAFE; color: #2563EB; display: flex; align-items: center; justify-content: center;">
                <i data-lucide="user-check" style="width: 18px;"></i>
              </div>
              <div>
                <div style="font-size: 13.5px; font-weight: 800; color: var(--text-primary);" id="leave-approver-name">Vishwas Damodar Kulal</div>
                <div style="font-size: 10.5px; color: var(--text-dim);">Direct 1-on-1 Approver for this request</div>
              </div>
            </div>
            <span style="font-size: 10.5px; font-weight: 800; padding: 3px 8px; border-radius: 10px; background: #DCFCE7; color: #166534; display: flex; align-items: center; gap: 3px;">
              <i data-lucide="check" style="width: 12px;"></i>
              <span>1-on-1</span>
            </span>
          </div>
        </div>

        <div>
          <label class="field-label">REASON / PURPOSE</label>
          <input type="text" id="apply-reason" class="field-input" placeholder="e.g. Family Vacation or Medical Emergency" required>
        </div>

        <div>
          <label class="field-label">NOTE FOR MANAGER (OPTIONAL)</label>
          <textarea id="apply-note" class="field-textarea" rows="2" placeholder="Provide additional details..."></textarea>
        </div>

        <div style="display: flex; gap: 10px; margin-top: 6px; padding-bottom: calc(20px + env(safe-area-inset-bottom, 16px));">
          <button type="button" onclick="closeApplyLeaveModal()" style="flex: 1; padding: 14px; border-radius: var(--radius-pill); border: 1px solid var(--border-card); background: var(--bg-card); font-weight: 800; font-size: 14px; cursor: pointer; color: var(--text-primary);">Cancel</button>
          <button type="submit" class="btn-solid-primary" style="flex: 1.5;">
            <span>Submit Request</span>
            <i data-lucide="arrow-right" style="width: 16px;"></i>
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- ── MODAL: ALL COMPANY HOLIDAYS ────────────────────────────────── -->
  <div id="modal-all-holidays" class="app-modal-backdrop">
    <div class="app-modal-sheet" style="max-height: 82vh; display: flex; flex-direction: column;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-shrink: 0;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <div style="width: 36px; height: 36px; border-radius: 10px; background: #FEF3C7; color: #D97706; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
            <i data-lucide="calendar" style="width: 18px;"></i>
          </div>
          <div>
            <h3 style="font-size: 17px; font-weight: 900; margin: 0;">Company Holidays (2026)</h3>
            <p style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">Official company & gazetted holidays list</p>
          </div>
        </div>
        <button type="button" onclick="closeAllHolidaysModal()" class="action-icon-btn" style="width: 32px; height: 32px;"><i data-lucide="x" style="width: 16px;"></i></button>
      </div>

      <div id="all-holidays-list-container" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding-right: 2px;">
        <!-- Dynamically rendered list of holidays -->
      </div>
    </div>
  </div>

  <!-- ── 7. CONFIRMATION ALERT DIALOG MODAL ────────────────────────────── -->
  <div id="modal-confirm-dialog" class="app-modal-backdrop" style="align-items: center;">
    <div class="alert-dialog-card">
      <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
        <div id="dialog-icon-wrapper" style="width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
          <i id="dialog-icon" data-lucide="alert-circle" style="width: 20px;"></i>
        </div>
        <h3 id="dialog-title" style="font-size: 16px; font-weight: 800;">Confirm Action</h3>
      </div>
      
      <p id="dialog-msg" style="font-size: 12.5px; color: var(--text-secondary); line-height: 1.4; margin-bottom: 16px;"></p>

      <div style="display: flex; gap: 10px;">
        <button onclick="resolveConfirmDialog(false)" style="flex: 1; padding: 10px; border-radius: 12px; border: 1px solid var(--border-card); background: var(--bg-card); font-size: 13px; font-weight: 700; cursor: pointer;">Cancel</button>
        <button id="dialog-confirm-btn" onclick="resolveConfirmDialog(true)" class="btn-solid-primary" style="flex: 1; padding: 10px; font-size: 13px; border-radius: 12px;">Confirm</button>
      </div>
    </div>
  </div>

  <!-- ── 8. FRONTEND JAVASCRIPT LOGIC ───────────────────────────────────── -->
  <script>
    const DEFAULT_HOLIDAYS_LIST = [
      { id: 15, title: "New Year", date: "2026-01-01", weekday: "Thursday" },
      { id: 16, title: "Republic Day", date: "2026-01-26", weekday: "Monday" },
      { id: 17, title: "Holi (Dhulivandan)", date: "2026-03-03", weekday: "Tuesday" },
      { id: 18, title: "Gudhi Padwa", date: "2026-03-19", weekday: "Thursday" },
      { id: 19, title: "Maharashtra Day", date: "2026-05-01", weekday: "Friday" },
      { id: 20, title: "Independence Day", date: "2026-08-15", weekday: "Saturday" },
      { id: 21, title: "Ganesh Chaturthi", date: "2026-09-14", weekday: "Monday" },
      { id: 22, title: "Anant Chaturdashi", date: "2026-09-25", weekday: "Friday" },
      { id: 23, title: "Gandhi Jayanti", date: "2026-10-02", weekday: "Friday" },
      { id: 24, title: "Dussehra", date: "2026-10-20", weekday: "Tuesday" },
      { id: 25, title: "Diwali (Narak Chaturdashi / Laxmi Pujan)", date: "2026-11-08", weekday: "Sunday" },
      { id: 26, title: "Diwali", date: "2026-11-09", weekday: "Monday" },
      { id: 27, title: "Diwali (Bali Pratipada / Padwa)", date: "2026-11-10", weekday: "Tuesday" },
      { id: 28, title: "Diwali (Bhaubij)", date: "2026-11-11", weekday: "Wednesday" }
    ];

    function getInitialPayrollCycleMonth() {
      const now = new Date();
      // Monarch HR attendance cycle runs from 26th of previous month to 25th of current month
      // If current date is >= 26, the active payroll cycle belongs to next month (e.g. 26 Oct - 25 Nov is Nov 2026)
      if (now.getDate() >= 26) {
        return new Date(now.getFullYear(), now.getMonth() + 1, 1);
      } else {
        return new Date(now.getFullYear(), now.getMonth(), 1);
      }
    }

    let state = {
      token: localStorage.getItem('token') || null,
      user: (() => { try { return JSON.parse(localStorage.getItem('user') || 'null'); } catch(_) { return null; } })(),
      clockedIn: false,
      clockInTime: null,
      sessionId: null,
      stopwatchInterval: null,
      autoSyncInterval: null,
      currentTab: 'dashboard',
      attendanceSubTab: 'Day wise',
      attendanceMainSegment: 'my',
      leavesSubTab: 'my',
      currentPayrollCycleMonth: getInitialPayrollCycleMonth(),
      attendanceLogs: (() => { try { return JSON.parse(sessionStorage.getItem('attendanceLogs') || '[]'); } catch(_) { return []; } })(),
      holidays: (() => {
        try {
          const cached = JSON.parse(sessionStorage.getItem('holidays') || '[]');
          return (Array.isArray(cached) && cached.length > 0) ? cached : DEFAULT_HOLIDAYS_LIST;
        } catch(_) {
          return DEFAULT_HOLIDAYS_LIST;
        }
      })(),
      selectedDayDate: null,
      myLeaves: (() => { try { return JSON.parse(sessionStorage.getItem('myLeaves') || '[]'); } catch(_) { return []; } })(),
      teamLeaves: [],
      teamPunchRequests: [],
      teamMembers: []
    };

    let confirmDialogCallback = null;
    let _lucideRaf = null;
    function safeCreateIcons() {
      if (_lucideRaf) cancelAnimationFrame(_lucideRaf);
      _lucideRaf = requestAnimationFrame(() => {
        try { lucide.createIcons(); } catch(_) {}
      });
    }

    document.addEventListener('DOMContentLoaded', () => {
      initTheme();

      if (state.token) {
        launchApp(); // Instant render in 0ms without waiting for network!
        verifySession(); // Silent background validation
      } else {
        showLogin();
      }

      safeCreateIcons();
    });

    // ── Theme Switcher ──
    function initTheme() {
      const saved = localStorage.getItem('theme') || 'light';
      document.documentElement.className = saved;
      updateThemeIcon(saved === 'dark');
    }

    function toggleTheme() {
      const isDark = document.documentElement.classList.toggle('dark');
      document.documentElement.classList.toggle('light', !isDark);
      localStorage.setItem('theme', isDark ? 'dark' : 'light');
      updateThemeIcon(isDark);
    }

    function updateThemeIcon(isDark) {
      const icon = document.getElementById('theme-icon');
      const loginIcon = document.getElementById('theme-icon-login');
      const iconName = isDark ? 'sun' : 'moon';
      const color = isDark ? '#F5A952' : '#2563EB';

      if (icon) {
        icon.setAttribute('data-lucide', iconName);
        icon.style.color = color;
      }
      if (loginIcon) {
        loginIcon.setAttribute('data-lucide', iconName);
        loginIcon.style.color = color;
      }
      safeCreateIcons();
    }

    function togglePasswordVisibility() {
      const p = document.getElementById('login-pwd');
      const eye = document.getElementById('pwd-eye-icon');
      if (p.type === 'password') {
        p.type = 'text';
        eye.setAttribute('data-lucide', 'eye-off');
      } else {
        p.type = 'password';
        eye.setAttribute('data-lucide', 'eye');
      }
      safeCreateIcons();
    }

    // ── Auth Handling ──
    async function handleLoginSubmit(e) {
      e.preventDefault();
      const idVal = document.getElementById('login-emp-id').value.trim();
      const pwdVal = document.getElementById('login-pwd').value;
      const errBox = document.getElementById('login-err-box');
      const submitBtn = document.getElementById('btn-login-submit');

      errBox.style.display = 'none';
      submitBtn.disabled = true;

      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ emp_id: idVal, identifier: idVal, username: idVal, password: pwdVal })
        });
        const data = await res.json();
        if (!res.ok || data.error) {
          errBox.innerText = data.error || 'Invalid credentials';
          errBox.style.display = 'block';
          submitBtn.disabled = false;
          return;
        }

        state.token = data.token;
        state.user = data.user;
        localStorage.setItem('token', data.token);
        try { localStorage.setItem('user', JSON.stringify(data.user)); } catch (_) {}
        submitBtn.disabled = false;
        launchApp();
      } catch (_) {
        errBox.innerText = 'Cannot connect to server';
        errBox.style.display = 'block';
        submitBtn.disabled = false;
      }
    }

    async function verifySession() {
      try {
        const res = await fetch('/api/user/profile', {
          headers: { 'Authorization': `Bearer ${state.token}` }
        });
        if (res.ok) {
          const freshUser = await res.json();
          state.user = freshUser;
          try { localStorage.setItem('user', JSON.stringify(freshUser)); } catch (_) {}
          applyUserDataToUI();
        } else {
          handleLogout();
        }
      } catch (_) {}
    }

    function handleLogout() {
      state.token = null;
      state.user = null;
      state.teamLeaves = [];
      state.teamMembers = [];
      state.teamPunchRequests = [];
      state.myLeaves = [];
      state.attendanceLogs = [];
      state.leavesSubTab = 'my';
      state.attendanceMainSegment = 'my';
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      try { sessionStorage.clear(); } catch (_) {}
      if (state.stopwatchInterval) clearInterval(state.stopwatchInterval);
      if (state.autoSyncInterval) clearInterval(state.autoSyncInterval);

      const teamLeavesEl = document.getElementById('team-leaves-list-container');
      if (teamLeavesEl) teamLeavesEl.innerHTML = '';
      const teamMembEl = document.getElementById('team-members-list-container');
      if (teamMembEl) teamMembEl.innerHTML = '';
      const myLeavesEl = document.getElementById('my-leaves-container');
      if (myLeavesEl) myLeavesEl.innerHTML = '';
      const banner = document.getElementById('dash-manager-pending-banner');
      if (banner) banner.style.display = 'none';
      const badge = document.getElementById('leaves-team-badge');
      if (badge) badge.style.display = 'none';
      const navLeavesDot = document.getElementById('nav-leaves-dot');
      if (navLeavesDot) navLeavesDot.style.display = 'none';
      const pBadge = document.getElementById('att-punch-count-badge');
      if (pBadge) pBadge.style.display = 'none';
      const navPunchDot = document.getElementById('nav-punch-dot');
      if (navPunchDot) navPunchDot.style.display = 'none';

      switchLeavesView('my');
      switchAttMainSegment('my');
      showLogin();
    }

    let _lastSyncTimestamp = Date.now();

    function startAutoSync() {
      if (state.autoSyncInterval) clearInterval(state.autoSyncInterval);
      state.autoSyncInterval = setInterval(() => {
        if (!state.token) return;
        const now = Date.now();
        if (now - _lastSyncTimestamp < 15000) return;
        _lastSyncTimestamp = now;
        if (state.currentTab === 'dashboard') {
          loadDashboardData();
        } else if (state.currentTab === 'attendance') {
          loadAttendanceData();
        } else if (state.currentTab === 'leaves') {
          loadLeavesData();
        }
      }, 15000);
    }

    window.addEventListener('focus', () => {
      if (!state.token) return;
      const now = Date.now();
      // On mobile devices, taps often fire focus; avoid spamming network requests
      if (now - _lastSyncTimestamp < 30000) return;
      _lastSyncTimestamp = now;
      if (state.currentTab === 'dashboard') loadDashboardData();
      else if (state.currentTab === 'attendance') loadAttendanceData();
      else if (state.currentTab === 'leaves') loadLeavesData();
    });

    function showLogin() {
      document.getElementById('screen-login').style.display = 'flex';
      document.getElementById('phone-appbar').style.display = 'none';
      document.getElementById('main-screens-wrap').style.display = 'none';
      document.getElementById('phone-nav-bar').style.display = 'none';
      safeCreateIcons();
    }

    function applyUserDataToUI() {
      const u = state.user || {};
      const initial = (u.name || 'U')[0].toUpperCase();

      const tbAv = document.getElementById('topbar-avatar');
      if (tbAv) tbAv.querySelector('span').innerText = initial;
      const dAv = document.getElementById('dash-avatar');
      if (dAv) dAv.querySelector('span').innerText = initial;
      const pAv = document.getElementById('prof-hero-avatar');
      if (pAv) pAv.querySelector('span').innerText = initial;

      document.getElementById('dash-fullname').innerText = u.name || 'Employee';
      document.getElementById('dash-role-dept').innerText = `${u.designation || u.role || 'Staff'} • ${u.department || 'General'}`;

      const dashDateEl = document.getElementById('dash-date-label');
      if (dashDateEl) {
        const now = new Date();
        const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        dashDateEl.innerText = `${dayNames[now.getDay()]}, ${String(now.getDate()).padStart(2, '0')} ${monthNames[now.getMonth()]} ${now.getFullYear()}`;
      }

      document.getElementById('prof-hero-name').innerText = u.name || 'Employee';
      document.getElementById('prof-hero-role').innerText = `${u.designation || u.role || 'Staff'} • ${u.department || 'General'}`;
      document.getElementById('prof-hero-empid').innerText = `#${u.employee_no || u.emp_id || '1951'}`;
      document.getElementById('prof-hero-doj').innerText = `📅 Joined ${u.date_of_joining ? u.date_of_joining.split('T')[0] : '2026-04-27'}`;
      document.getElementById('prof-hero-phone').innerText = `📞 ${u.phone_number || u.mobile_number || '8805298115'}`;
      document.getElementById('prof-hero-email').innerText = `@ ${u.email || u.personal_email || 'utkarshpingale11@gmail.com'}`;

      document.getElementById('prof-form-name').value = u.name || '';
      document.getElementById('prof-form-empid').value = u.employee_no || u.emp_id || '';
      document.getElementById('prof-form-phone').value = u.phone_number || u.mobile_number || '';
      document.getElementById('prof-form-email').value = u.email || u.personal_email || '';

      if (u.reporting_manager) {
        document.getElementById('leave-approver-name').innerText = u.reporting_manager;
      }

      const roleStr = (u.role || '').toLowerCase().replace(/[\s_-]/g, '');
      const isMgr = roleStr.includes('leader') || roleStr.includes('lead') || roleStr.includes('manager') || roleStr === 'admin' || roleStr === 'hr';

      const leavesMgrTabs = document.getElementById('leaves-mgr-tabs');
      if (leavesMgrTabs) leavesMgrTabs.style.display = isMgr ? 'flex' : 'none';
      const attMgrTopBar = document.getElementById('att-mgr-top-bar');
      if (attMgrTopBar) attMgrTopBar.style.display = isMgr ? 'flex' : 'none';

      if (!isMgr) {
        state.teamLeaves = [];
        state.teamMembers = [];
        state.teamPunchRequests = [];

        const banner = document.getElementById('dash-manager-pending-banner');
        if (banner) banner.style.display = 'none';
        const badge = document.getElementById('leaves-team-badge');
        if (badge) badge.style.display = 'none';
        const navLeavesDot = document.getElementById('nav-leaves-dot');
        if (navLeavesDot) navLeavesDot.style.display = 'none';
        const pBadge = document.getElementById('att-punch-count-badge');
        if (pBadge) pBadge.style.display = 'none';
        const navPunchDot = document.getElementById('nav-punch-dot');
        if (navPunchDot) navPunchDot.style.display = 'none';

        const teamLeavesEl = document.getElementById('team-leaves-list-container');
        if (teamLeavesEl) teamLeavesEl.innerHTML = '';
        const teamMembEl = document.getElementById('team-members-list-container');
        if (teamMembEl) teamMembEl.innerHTML = '';

        switchLeavesView('my');
        switchAttMainSegment('my');
        switchAttSubTab('Day wise');
      }
    }

    function launchApp() {
      document.getElementById('screen-login').style.display = 'none';
      document.getElementById('phone-appbar').style.display = 'flex';
      document.getElementById('main-screens-wrap').style.display = 'flex';
      document.getElementById('phone-nav-bar').style.display = 'flex';

      applyUserDataToUI();

      // Instant Synchronous UI pre-render from memory/cache (0ms delay)
      if (state.attendanceLogs && state.attendanceLogs.length > 0) {
        updateDashboardPunches(state.attendanceLogs);
      }
      renderPayrollCalendar();
      renderUpcomingHolidays();

      // Background silent data fetch
      loadDashboardData();

      const roleStr = ((state.user && state.user.role) || '').toLowerCase().replace(/[\s_-]/g, '');
      const isMgr = roleStr.includes('leader') || roleStr.includes('lead') || roleStr.includes('manager') || roleStr === 'admin' || roleStr === 'hr';
      if (isMgr) {
        loadPunchApprovals();
        // Defer 1.1MB team hierarchy fetch by 2.5s so initial startup & first clicks have 0ms latency
        setTimeout(() => {
          if (state.token) loadTeamApprovalsData();
        }, 2500);
      } else {
        state.teamLeaves = [];
        state.teamMembers = [];
        state.teamPunchRequests = [];
        switchLeavesView('my');
        switchAttMainSegment('my');
      }

      startAutoSync();
      safeCreateIcons();
    }

    // ── Navigation Switching ──
    function switchNavTab(tabName, subTab) {
      if (state.currentTab === tabName && !subTab) return;
      state.currentTab = tabName;
      
      const allScreens = document.querySelectorAll('.screen-body');
      for (let i = 0; i < allScreens.length; i++) allScreens[i].style.display = 'none';

      const allNavItems = document.querySelectorAll('.nav-item');
      for (let i = 0; i < allNavItems.length; i++) allNavItems[i].classList.remove('active');

      const screen = document.getElementById(`view-${tabName}`);
      if (screen) screen.style.display = 'flex';

      const navBtn = document.getElementById(`nav-item-${tabName}`);
      if (navBtn) navBtn.classList.add('active');

      const titles = {
        'dashboard': 'Dashboard',
        'attendance': 'Attendance History',
        'leaves': 'Leave Management',
        'profile': 'Profile'
      };
      const titleEl = document.getElementById('topbar-title');
      if (titleEl) titleEl.innerText = titles[tabName] || 'Monarch HR';
      const logoutBtn = document.getElementById('topbar-logout-btn');
      if (logoutBtn) logoutBtn.style.display = tabName === 'dashboard' ? 'flex' : 'none';

      // ── Zero-Latency Instant Render from Memory ──
      if (tabName === 'dashboard') {
        if (state.attendanceLogs && state.attendanceLogs.length > 0) {
          updateDashboardPunches(state.attendanceLogs);
        }
        loadDashboardData();
      } else if (tabName === 'attendance') {
        const u = state.user || {};
        const roleStr = (u.role || '').toLowerCase().replace(/[\s_-]/g, '');
        const isMgr = roleStr.includes('leader') || roleStr.includes('lead') || roleStr.includes('manager') || roleStr === 'admin' || roleStr === 'hr';
        if (!isMgr) switchAttMainSegment('my');
        if (subTab) switchAttSubTab(subTab);
        renderAttendanceViews(); // Instant synchronous render! 0ms latency!
        loadAttendanceData();    // Background silent refresh
      } else if (tabName === 'leaves') {
        const u = state.user || {};
        const roleStr = (u.role || '').toLowerCase().replace(/[\s_-]/g, '');
        const isMgr = roleStr.includes('leader') || roleStr.includes('lead') || roleStr.includes('manager') || roleStr === 'admin' || roleStr === 'hr';
        if (!isMgr) {
          switchLeavesView('my');
        } else if (subTab === 'team') {
          switchLeavesView('team');
        }
        if (state.myLeaves && state.myLeaves.length > 0) {
          renderMyLeavesList(state.myLeaves);
        }
        renderUpcomingHolidays();
        loadLeavesData();
      }

      safeCreateIcons();
    }

    // ── Date & Time Utility Helpers ──
    function toDateStr(d) {
      if (!d) return '';
      if (typeof d === 'string') {
        if (d.includes('T')) return d.split('T')[0];
        if (d.length === 10 && d.includes('-')) return d;
      }
      const dt = (d instanceof Date) ? d : new Date(d);
      if (isNaN(dt.getTime())) return '';
      const y = dt.getFullYear();
      const m = String(dt.getMonth() + 1).padStart(2, '0');
      const day = String(dt.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    }

    function formatTime12(val) {
      if (!val || val === '-- : --') return '-- : --';
      if (typeof val === 'string') {
        if (val.includes('AM') || val.includes('PM')) return val;
        if (val.includes('T')) {
          const dt = new Date(val);
          if (!isNaN(dt.getTime())) {
            let h = dt.getHours();
            const m = String(dt.getMinutes()).padStart(2, '0');
            const ampm = h >= 12 ? 'PM' : 'AM';
            h = h % 12 || 12;
            return `${String(h).padStart(2, '0')}:${m} ${ampm}`;
          }
        }
        const parts = val.split(':');
        if (parts.length >= 2) {
          let h = parseInt(parts[0], 10);
          const m = (parts[1] || '00').substring(0, 2).padStart(2, '0');
          if (!isNaN(h)) {
            const ampm = h >= 12 ? 'PM' : 'AM';
            h = h % 12 || 12;
            return `${String(h).padStart(2, '0')}:${m} ${ampm}`;
          }
        }
      }
      return val;
    }

    function parseMinutes(timeStr) {
      if (!timeStr) return 0;
      const parts = timeStr.split(':');
      return parseInt(parts[0], 10) * 60 + parseInt(parts[1] || '0', 10);
    }

    function formatDuration(minutes) {
      if (!minutes || minutes <= 0) return '0h 0m';
      const h = Math.floor(minutes / 60);
      const m = minutes % 60;
      return `${h}h ${m}m`;
    }

    function formatDurationCol(minutes) {
      if (!minutes || minutes <= 0) return '00:00';
      const h = String(Math.floor(minutes / 60)).padStart(2, '0');
      const m = String(minutes % 60).padStart(2, '0');
      return `${h}:${m}`;
    }

    function monthShortName(idx) {
      const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return m[idx] || '';
    }

    function formatPunchLocation(s, type) {
      const loc = (type === 'out' ? (s.clock_out_location || s.punch_out_location) : (s.clock_in_location || s.punch_in_location)) || s.location || '';
      if (loc && !loc.includes('#99')) return loc;
      if (s.nearest_building) return `Mobile Phone (GPS) • ${s.nearest_building}`;
      return 'Monarch House (HQ)';
    }

    // ── Dashboard Live Punches & Stopwatch ──
    async function loadDashboardData() {
      _lastSyncTimestamp = Date.now();
      try {
        const [attRes, leavesRes, holRes] = await Promise.all([
          fetch('/api/attendance/me', { headers: { 'Authorization': `Bearer ${state.token}` } }),
          fetch('/api/leaves/me', { headers: { 'Authorization': `Bearer ${state.token}` } }),
          fetch('/api/holidays', { headers: { 'Authorization': `Bearer ${state.token}` } })
        ]);

        if (attRes.ok) {
          const records = await attRes.json();
          state.attendanceLogs = records;
          try { sessionStorage.setItem('attendanceLogs', JSON.stringify(records)); } catch(_) {}
          updateDashboardPunches(records);
        }

        if (holRes.ok) {
          state.holidays = await holRes.json();
          try { sessionStorage.setItem('holidays', JSON.stringify(state.holidays)); } catch(_) {}
          renderUpcomingHolidays();
        }

        if (leavesRes.ok) {
          const lData = await leavesRes.json();
          updateLeaveStatsDisplay(lData);

          const lList = Array.isArray(lData.leaves) ? lData.leaves : [];
          const pendingCount = lList.filter(l => (l.status || '').toLowerCase().includes('pending')).length;
          const pendEl = document.getElementById('overview-pending-req');
          if (pendEl) pendEl.innerText = pendingCount;
          state.myLeaves = lList;
          try { sessionStorage.setItem('myLeaves', JSON.stringify(lList)); } catch(_) {}
          if (state.currentTab === 'leaves') renderMyLeavesList(lList);
        }

        if (state.currentTab === 'attendance') {
          renderAttendanceViews();
        }
      } catch (_) {}
    }

    function updateDashboardPunches(records) {
      const now = new Date();
      const todayStr = toDateStr(now);

      // Find today's record
      const todayRecs = (records || []).filter(r => {
        if (!r.date && !r.clock_in) return false;
        const dStr = r.date || (r.clock_in ? r.clock_in.split('T')[0] : '');
        return dStr === todayStr;
      });

      let firstIn = '-- : --';
      let lastOut = '-- : --';
      let isActive = false;
      let inDateTime = null;
      let completedSecs = 0;

      if (todayRecs.length > 0) {
        todayRecs.forEach(r => {
          if (r.sign_in && r.sign_out) {
            const inM = parseMinutes(r.sign_in);
            const outM = parseMinutes(r.sign_out);
            if (outM > inM) completedSecs += (outM - inM) * 60;
          } else if (r.total_minutes != null && Number(r.total_minutes) > 0) {
            completedSecs += Number(r.total_minutes) * 60;
          }
        });

        const active = todayRecs.find(r => (r.clock_in || r.sign_in) && !r.clock_out && (!r.sign_out || r.sign_out.startsWith('00:00')));
        if (active) {
          isActive = true;
          state.sessionId = active.id;
          const sIn = active.sign_in || (active.clock_in ? active.clock_in.split('T')[1] : '08:48:00');
          inDateTime = new Date(`${todayStr}T${sIn.substring(0, 8)}`);
        }

        const r = todayRecs[0];
        if (r.sign_in || r.clock_in) {
          firstIn = formatTime12(r.sign_in || r.clock_in);
        }
        if (r.sign_out || r.clock_out) {
          lastOut = formatTime12(r.sign_out || r.clock_out);
        }
      }

      document.getElementById('box-checkin-time').innerText = firstIn;
      document.getElementById('box-checkout-time').innerText = lastOut;

      state.clockedIn = isActive;
      state.clockInTime = inDateTime;

      const statusBadge = document.getElementById('dash-shift-badge');
      const statusText = document.getElementById('dash-shift-status-text');
      const punchBtnText = document.getElementById('btn-punch-text');

      if (isActive) {
        statusBadge.style.background = 'rgba(16, 185, 129, 0.15)';
        statusBadge.style.color = '#146C43';
        statusText.innerText = 'On Shift';
        punchBtnText.innerText = 'Check Out';
        startStopwatch(inDateTime, completedSecs);
      } else if (completedSecs > 0) {
        statusBadge.style.background = 'rgba(16, 185, 129, 0.15)';
        statusBadge.style.color = '#146C43';
        statusText.innerText = 'Shift Completed';
        punchBtnText.innerText = 'Check In';
        if (state.stopwatchInterval) clearInterval(state.stopwatchInterval);
        const hrs = String(Math.floor(completedSecs / 3600)).padStart(2, '0');
        const mins = String(Math.floor((completedSecs % 3600) / 60)).padStart(2, '0');
        const secs = String(completedSecs % 60).padStart(2, '0');
        document.getElementById('box-working-hrs').innerText = `${hrs}:${mins}:${secs}`;
      } else {
        statusBadge.style.background = 'rgba(100, 116, 139, 0.15)';
        statusBadge.style.color = '#64748B';
        statusText.innerText = 'Off Shift';
        punchBtnText.innerText = 'Check In';
        if (state.stopwatchInterval) clearInterval(state.stopwatchInterval);
        document.getElementById('box-working-hrs').innerText = '00:00:00';
      }

      // Update Activity Log list on dashboard
      const actList = document.getElementById('dash-activity-list');
      if (actList) {
        if (todayRecs.length > 0) {
          let html = '';
          todayRecs.forEach((r, idx) => {
            const inTimeStr = formatTime12(r.sign_in || r.clock_in);
            const inLoc = formatPunchLocation(r, 'in');
            html += `
              <div class="app-card" style="padding: 12px 14px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <div style="width: 38px; height: 38px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center;">
                    <i data-lucide="log-in" style="width: 18px;"></i>
                  </div>
                  <div>
                    <div style="display: flex; align-items: center; gap: 6px;">
                      <span style="font-size: 14px; font-weight: 800;">Punch In</span>
                      <span style="font-size: 9.5px; font-weight: 800; padding: 2px 6px; border-radius: 8px; background: #DCFCE7; color: #166534;">Verified</span>
                    </div>
                    <div style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">${inLoc}</div>
                  </div>
                </div>
                <div style="text-align: right;">
                  <div style="font-size: 14px; font-weight: 800;">${inTimeStr}</div>
                  <div style="font-size: 10.5px; font-weight: 700; color: #146C43; margin-top: 1px;">On Time</div>
                </div>
              </div>
            `;
            if (r.sign_out || r.clock_out) {
              const outTimeStr = formatTime12(r.sign_out || r.clock_out);
              const outLoc = formatPunchLocation(r, 'out');
              html += `
                <div class="app-card" style="padding: 12px 14px; display: flex; align-items: center; justify-content: space-between;">
                  <div style="display: flex; align-items: center; gap: 12px;">
                    <div style="width: 38px; height: 38px; border-radius: 50%; background: #EFF6FF; color: #2563EB; display: flex; align-items: center; justify-content: center;">
                      <i data-lucide="log-out" style="width: 18px;"></i>
                    </div>
                    <div>
                      <div style="display: flex; align-items: center; gap: 6px;">
                        <span style="font-size: 14px; font-weight: 800;">Punch Out</span>
                        <span style="font-size: 9.5px; font-weight: 800; padding: 2px 6px; border-radius: 8px; background: #EFF6FF; color: #1D4ED8;">Recorded</span>
                      </div>
                      <div style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">${outLoc}</div>
                    </div>
                  </div>
                  <div style="text-align: right;">
                    <div style="font-size: 14px; font-weight: 800;">${outTimeStr}</div>
                    <div style="font-size: 10.5px; font-weight: 700; color: #2563EB; margin-top: 1px;">Completed</div>
                  </div>
                </div>
              `;
            }
          });
          actList.innerHTML = html;
        } else {
          actList.innerHTML = `
            <div class="app-card" style="padding: 18px; text-align: center; color: var(--text-secondary); font-size: 12px;">
              No check-ins recorded yet today. Use the button above to punch in.
            </div>
          `;
        }
      }
      safeCreateIcons();
    }

    function formatTimeStr(dtStr) {
      return formatTime12(dtStr);
    }

    function startStopwatch(startDate, baseSecs = 0) {
      if (state.stopwatchInterval) clearInterval(state.stopwatchInterval);
      const start = startDate ? new Date(startDate) : new Date();

      state.stopwatchInterval = setInterval(() => {
        const activeDiff = Math.max(0, Math.floor((new Date() - start) / 1000));
        const diff = activeDiff + baseSecs;
        const hrs = String(Math.floor(diff / 3600)).padStart(2, '0');
        const mins = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
        const secs = String(diff % 60).padStart(2, '0');
        document.getElementById('box-working-hrs').innerText = `${hrs}:${mins}:${secs}`;
      }, 1000);
    }

    // ── Punch Confirmation Dialog & Actions ──
    function showConfirmDialog(title, msg, isDestructive, confirmText = 'Confirm') {
      return new Promise((resolve) => {
        confirmDialogCallback = resolve;
        document.getElementById('dialog-title').innerText = title;
        document.getElementById('dialog-msg').innerText = msg;
        
        const iconWrap = document.getElementById('dialog-icon-wrapper');
        const icon = document.getElementById('dialog-icon');
        const btn = document.getElementById('dialog-confirm-btn');

        btn.innerText = confirmText;

        if (isDestructive) {
          iconWrap.style.background = 'rgba(239, 68, 68, 0.15)';
          iconWrap.style.color = '#EF4444';
          icon.setAttribute('data-lucide', 'log-out');
          btn.style.background = '#E11D48';
          btn.style.color = '#FFFFFF';
        } else {
          iconWrap.style.background = 'rgba(245, 158, 11, 0.15)';
          iconWrap.style.color = '#F59E0B';
          icon.setAttribute('data-lucide', 'info');
          btn.style.background = '#F5A952';
          btn.style.color = '#6B3F00';
        }

        document.getElementById('modal-confirm-dialog').classList.add('active');
        safeCreateIcons();
      });
    }

    function resolveConfirmDialog(result) {
      document.getElementById('modal-confirm-dialog').classList.remove('active');
      if (confirmDialogCallback) {
        confirmDialogCallback(result);
        confirmDialogCallback = null;
      }
    }

    async function handlePunchButtonPress() {
      if (state.clockedIn) {
        const inTime = document.getElementById('box-checkin-time').innerText;
        const proceed = await showConfirmDialog(
          'Confirm Check Out',
          `Are you sure you want to punch out and end your active shift? (Current Check-In: ${inTime})`,
          true,
          'Yes, Check Out'
        );
        if (!proceed) return;
        await executePunchOut();
      } else {
        const outTime = document.getElementById('box-checkout-time').innerText;
        if (outTime !== '-- : --') {
          const proceed = await showConfirmDialog(
            'Already Punched Today',
            'You have already completed your punch in and punch out for today. Do you want to Check In again for overtime / new session?',
            false,
            'Yes, Check In'
          );
          if (!proceed) return;
        }
        await executePunchIn();
      }
    }

    async function executePunchIn() {
      try {
        const res = await fetch('/api/attendance/clock-in', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({
            lat: 18.5229,
            lng: 73.9069,
            client_time: new Date().toISOString()
          })
        });
        const data = await res.json();
        if (data.error) {
          alert(data.error);
        } else {
          alert('✅ Checked in at Monarch House (HQ) — Verified ≤ 20m');
          loadDashboardData();
        }
      } catch (_) {
        alert('Network error while checking in.');
      }
    }

    async function executePunchOut() {
      try {
        const res = await fetch('/api/attendance/clock-out', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({
            lat: 18.5229,
            lng: 73.9069,
            client_time: new Date().toISOString()
          })
        });
        const data = await res.json();
        if (data.error) {
          alert(data.error);
        } else {
          alert('✅ Checked out successfully');
          loadDashboardData();
        }
      } catch (_) {
        alert('Network error while checking out.');
      }
    }

    // ── Attendance Sub-Tabs & Punch Approvals ──
    function switchAttMainSegment(seg) {
      const u = state.user || {};
      const roleStr = (u.role || '').toLowerCase().replace(/[\s_-]/g, '');
      const isMgr = roleStr.includes('leader') || roleStr.includes('lead') || roleStr.includes('manager') || roleStr === 'admin' || roleStr === 'hr';
      if (!isMgr) seg = 'my';
      state.attendanceMainSegment = seg;
      const myBtn = document.getElementById('att-main-my');
      if (myBtn) myBtn.classList.toggle('active', seg === 'my');
      const punchBtn = document.getElementById('att-main-punches');
      if (punchBtn) punchBtn.classList.toggle('active', seg === 'punches');
      const mySec = document.getElementById('att-my-section');
      if (mySec) mySec.style.display = seg === 'my' ? 'flex' : 'none';
      const punchSec = document.getElementById('att-punches-section');
      if (punchSec) punchSec.style.display = seg === 'punches' ? 'flex' : 'none';
      if (seg === 'punches' && isMgr) loadPunchApprovals();
      safeCreateIcons();
    }

    function switchAttSubTab(sub) {
      state.attendanceSubTab = sub;
      document.getElementById('att-subtab-day').classList.toggle('active', sub === 'Day wise');
      document.getElementById('att-subtab-weekly').classList.toggle('active', sub === 'Weekly');
      document.getElementById('att-subtab-overview').classList.toggle('active', sub === 'Overview');

      document.getElementById('att-view-daywise').style.display = sub === 'Day wise' ? 'flex' : 'none';
      document.getElementById('att-view-weekly').style.display = sub === 'Weekly' ? 'flex' : 'none';
      document.getElementById('att-view-overview').style.display = sub === 'Overview' ? 'flex' : 'none';
      if (sub === 'Weekly') renderWeeklyView();
      if (sub === 'Overview') renderOverviewView();
      safeCreateIcons();
    }

    function shiftPayrollCycle(delta) {
      state.currentPayrollCycleMonth = new Date(
        state.currentPayrollCycleMonth.getFullYear(),
        state.currentPayrollCycleMonth.getMonth() + delta,
        1
      );
      renderAttendanceViews();
    }

    function toggleLegendBox() {
      const box = document.getElementById('att-legend-box');
      box.style.display = box.style.display === 'none' ? 'flex' : 'none';
    }

    function renderAttendanceViews() {
      renderPayrollCalendar();
      if (state.attendanceSubTab === 'Weekly') {
        renderWeeklyView();
      } else if (state.attendanceSubTab === 'Overview') {
        renderOverviewView();
      } else {
        const dt = state.currentPayrollCycleMonth;
        const startCycle = new Date(dt.getFullYear(), dt.getMonth() - 1, 26);
        const endCycle = new Date(dt.getFullYear(), dt.getMonth(), 25);
        const now = new Date();
        const todayStr = toDateStr(now);
        const startCycleStr = toDateStr(startCycle);
        const endCycleStr = toDateStr(endCycle);

        let targetDate = state.selectedDayDate;
        if (!targetDate || targetDate < startCycleStr || targetDate > endCycleStr) {
          if (todayStr >= startCycleStr && todayStr <= endCycleStr) {
            targetDate = todayStr;
          } else {
            targetDate = endCycleStr;
          }
        }
        inspectDate(targetDate);
      }
    }

    function renderPayrollCalendar() {
      const dt = state.currentPayrollCycleMonth;
      const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
      const mName = monthNames[dt.getMonth()];
      const prevMName = monthNames[dt.getMonth() === 0 ? 11 : dt.getMonth() - 1];
      
      const titleEl = document.getElementById('cal-month-title');
      if (titleEl) titleEl.innerText = `${mName} ${dt.getFullYear()}`;
      const rangeEl = document.getElementById('cal-cycle-range');
      if (rangeEl) rangeEl.innerText = `26 ${prevMName.substring(0,3)} – 25 ${mName.substring(0,3)}`;

      const grid = document.getElementById('payroll-cal-grid');
      if (!grid) return;
      let gridHtml = `
        <div class="cal-header-day">Sun</div>
        <div class="cal-header-day">Mon</div>
        <div class="cal-header-day">Tue</div>
        <div class="cal-header-day">Wed</div>
        <div class="cal-header-day">Thu</div>
        <div class="cal-header-day">Fri</div>
        <div class="cal-header-day">Sat</div>
      `;

      const startCycle = new Date(dt.getFullYear(), dt.getMonth() - 1, 26);
      const endCycle = new Date(dt.getFullYear(), dt.getMonth(), 25);
      const daysBadgeEl = document.getElementById('cal-cycle-days-badge');
      if (daysBadgeEl) {
        const cycleDaysCount = Math.round((endCycle - startCycle) / (1000 * 60 * 60 * 24)) + 1;
        daysBadgeEl.innerText = `${cycleDaysCount} Days`;
      }
      const startDayOfWeek = startCycle.getDay();

      for (let b = 0; b < startDayOfWeek; b++) {
        gridHtml += `<div style="opacity: 0;"></div>`;
      }

      const now = new Date();
      const todayStr = toDateStr(now);
      const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());

      // Map holidays
      const holidayMap = {};
      (state.holidays || []).forEach(h => {
        if (h.date) holidayMap[toDateStr(h.date)] = h.title || 'Holiday';
      });

      // Map approved leaves
      const leaveMap = {};
      (state.myLeaves || []).forEach(l => {
        const st = (l.status || '').toLowerCase().trim();
        if (st !== 'approved') return;
        if (!l.start_date) return;
        const sStr = toDateStr(l.start_date);
        const eStr = toDateStr(l.end_date || l.start_date);
        let curL = new Date(sStr + 'T00:00:00');
        const endL = new Date(eStr + 'T00:00:00');
        while (curL <= endL) {
          leaveMap[toDateStr(curL)] = l;
          curL.setDate(curL.getDate() + 1);
        }
      });

      let cur = new Date(startCycle);
      while (cur <= endCycle) {
        const d = cur.getDate();
        const dayOfWeek = cur.getDay();
        const dateStr = toDateStr(cur);

        const isToday = (dateStr === todayStr);
        const isPast = (cur < todayMidnight);
        const isSunday = (dayOfWeek === 0);
        const satIndex = Math.floor((d - 1) / 7) + 1;
        const isEvenSaturday = (dayOfWeek === 6 && satIndex % 2 === 0);
        const isRestDay = isSunday || isEvenSaturday;
        const holidayTitle = holidayMap[dateStr];
        const leaveRecord = leaveMap[dateStr];

        const dayShifts = (state.attendanceLogs || []).filter(r => {
          const rDate = r.date || (r.clock_in ? r.clock_in.split('T')[0] : '');
          return rDate === dateStr;
        });

        let totalMins = 0;
        let hasSession1 = false;
        let hasSession2 = false;
        let hasMissingPunchOut = false;
        let isShiftActive = false;

        dayShifts.forEach(s => {
          if (s.total_minutes != null && Number(s.total_minutes) > 0) {
            totalMins += Number(s.total_minutes);
          } else if (s.sign_in && s.sign_out) {
            const inM = parseMinutes(s.sign_in);
            const outM = parseMinutes(s.sign_out);
            if (outM > inM) totalMins += (outM - inM);
          } else if (isToday && s.sign_in && !s.sign_out) {
            isShiftActive = true;
            const inM = parseMinutes(s.sign_in);
            const nowM = now.getHours() * 60 + now.getMinutes();
            if (nowM > inM) totalMins += (nowM - inM);
          } else if (isPast && s.sign_in && !s.sign_out) {
            hasMissingPunchOut = true;
          }

          if (s.sign_in) {
            const h = parseInt(s.sign_in.split(':')[0], 10);
            const m = parseInt(s.sign_in.split(':')[1], 10);
            if (h < 13 || (h === 13 && m <= 30)) hasSession1 = true;
            if (h > 13 || (h === 13 && m > 30)) hasSession2 = true;
          }
          if (s.sign_out) {
            const h = parseInt(s.sign_out.split(':')[0], 10);
            if (h >= 17) hasSession2 = true;
          }
        });

        let cellCls = 'future-plan';
        let code = '--';
        let sub = 'PLAN';

        const uJoinStr = (state.currentUser && (state.currentUser.date_of_joining || state.currentUser.joining_date)) ? String(state.currentUser.date_of_joining || state.currentUser.joining_date).split('T')[0] : null;
        const uJoinDate = uJoinStr ? new Date(uJoinStr + 'T00:00:00') : null;

        if (uJoinDate && cur < uJoinDate) {
          cellCls = 'future-plan';
          code = '--';
          sub = '--';
        } else if (isToday) {
          cellCls = 'today-active';
          code = 'P';
          sub = isShiftActive ? 'ACTIVE' : (totalMins >= 530 ? 'GEN' : (totalMins > 0 ? 'ACTIVE' : 'PLAN'));
        } else if (leaveRecord) {
          cellCls = 'leave';
          const lt = ((leaveRecord.leave_type || leaveRecord.title || '') + '').toLowerCase();
          if (lt.includes('loss') || lt.includes('lop') || lt.includes('unpaid')) {
            code = 'LP';
          } else if (lt.includes('comp') || lt.includes('co')) {
            code = 'CO';
          } else if (lt.includes('reg')) {
            code = 'P';
            sub = 'REG';
            cellCls = 'present';
          } else {
            code = 'EL';
            sub = 'LEAVE';
          }
        } else if (holidayTitle) {
          cellCls = 'holiday';
          code = 'H';
          sub = 'FEST';
        } else if (isRestDay) {
          cellCls = 'week-off';
          code = 'Off';
          sub = 'WEEK';
        } else if (hasMissingPunchOut) {
          cellCls = 'missed-punch';
          code = 'M:P';
          sub = 'MISSED';
        } else if (totalMins >= 530) {
          cellCls = 'present';
          code = 'P';
          sub = 'GEN';
        } else if (totalMins >= 180 || (dayShifts.some(s => s.sign_out || s.clock_out) && totalMins > 0)) {
          cellCls = 'half-day';
          let isFirstHalfLeave = false;
          if (dayShifts.length > 0 && dayShifts[0].sign_in) {
            const firstShift = dayShifts[0];
            const lastShift = dayShifts[dayShifts.length - 1];
            const h = parseInt(firstShift.sign_in.split(':')[0], 10);
            const m = parseInt(firstShift.sign_in.split(':')[1], 10);
            const inMins = h * 60 + m;
            const outH = lastShift && lastShift.sign_out ? parseInt(lastShift.sign_out.split(':')[0], 10) : 0;
            if (inMins >= 690 && outH >= 16) {
              isFirstHalfLeave = true;
            } else if (inMins < 690 && outH > 0 && outH < 17) {
              isFirstHalfLeave = false;
            } else if (inMins >= 690) {
              isFirstHalfLeave = true;
            }
          } else if (leaveRecord) {
            const sess = ((leaveRecord.session || leaveRecord.from_session || leaveRecord.title || leaveRecord.note || '') + '').toLowerCase();
            if (sess.includes('session 1') && !sess.includes('session 2')) {
              isFirstHalfLeave = true;
            } else if (sess.includes('session 2') && !sess.includes('session 1')) {
              isFirstHalfLeave = false;
            } else if (sess.includes('first half') || sess.includes('1st half') || sess.includes('morning')) {
              isFirstHalfLeave = true;
            } else if (sess.includes('second half') || sess.includes('2nd half') || sess.includes('afternoon')) {
              isFirstHalfLeave = false;
            }
          }
          code = isFirstHalfLeave ? 'A:P' : 'P:A';
          sub = 'HALF';
        } else if (isPast) {
          cellCls = 'absent';
          code = 'A';
          sub = 'ABSENT';
        }

        const isSelected = (state.selectedDayDate === dateStr);
        const selectedCls = isSelected ? 'selected-day' : '';

        const dayBadgeHtml = isToday
          ? `<span style="background: #895100; color: #FFFFFF; padding: 1px 5px; border-radius: 10px; font-size: 9.5px; font-weight: 800; display: inline-flex; align-items: center; gap: 2px;">${d} <span style="font-size: 8px;">✓</span></span>`
          : `<span>${d}</span>`;

        gridHtml += `
          <div class="cal-cell ${cellCls} ${selectedCls}" id="cal-cell-${dateStr}" onclick="inspectDate('${dateStr}')">
            ${dayBadgeHtml}
            <span style="font-size: 10px; font-weight: 900; margin-top: 1px;">${code}</span>
            <span class="code-sub">${sub}</span>
          </div>
        `;

        cur.setDate(cur.getDate() + 1);
      }

      grid.innerHTML = gridHtml;
    }

    function inspectDate(dateStr) {
      if (!dateStr) return;
      state.selectedDayDate = dateStr;

      // Update grid selection highlight
      document.querySelectorAll('.cal-cell').forEach(el => el.classList.remove('selected-day'));
      const activeCell = document.getElementById(`cal-cell-${dateStr}`);
      if (activeCell) activeCell.classList.add('selected-day');

      const card = document.getElementById('selected-day-card');
      if (!card) return;
      card.style.display = 'block';

      const now = new Date();
      const todayStr = toDateStr(now);
      const isToday = (dateStr === todayStr);
      const dObj = new Date(dateStr + 'T00:00:00');
      const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
      const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
      const headerDateStr = `${dayNames[dObj.getDay()]}, ${dObj.getDate()} ${monthNames[dObj.getMonth()].substring(0,3)} ${dObj.getFullYear()}`;
      document.getElementById('sel-day-date-str').innerText = headerDateStr;

      const dayShifts = (state.attendanceLogs || []).filter(r => {
        const rDate = r.date || (r.clock_in ? r.clock_in.split('T')[0] : '');
        return rDate === dateStr;
      });

      const holiday = (state.holidays || []).find(h => toDateStr(h.date) === dateStr);
      const leave = (state.myLeaves || []).find(l => {
        const sStr = toDateStr(l.start_date);
        const eStr = toDateStr(l.end_date || l.start_date);
        return dateStr >= sStr && dateStr <= eStr && (l.status || '').toLowerCase().trim() === 'approved';
      });

      const dayOfWeek = dObj.getDay();
      const satIndex = Math.floor((dObj.getDate() - 1) / 7) + 1;
      const isRestDay = (dayOfWeek === 0) || (dayOfWeek === 6 && satIndex % 2 === 0);
      const isPast = (dObj < new Date(now.getFullYear(), now.getMonth(), now.getDate()));

      let totalMins = 0;
      let firstIn = null;
      let lastOut = null;
      let hasMissingPunchOut = false;
      let isShiftActive = false;

      dayShifts.forEach(s => {
        if (!firstIn && (s.sign_in || s.clock_in)) {
          firstIn = s.sign_in || s.clock_in;
        }
        if (s.sign_out || s.clock_out) {
          lastOut = s.sign_out || s.clock_out;
        }
        if (s.total_minutes != null && Number(s.total_minutes) > 0) {
          totalMins += Number(s.total_minutes);
        } else if (s.sign_in && s.sign_out) {
          const inM = parseMinutes(s.sign_in);
          const outM = parseMinutes(s.sign_out);
          if (outM > inM) totalMins += (outM - inM);
        } else if (isToday && s.sign_in && !s.sign_out) {
          isShiftActive = true;
          const inM = parseMinutes(s.sign_in);
          const nowM = now.getHours() * 60 + now.getMinutes();
          if (nowM > inM) totalMins += (nowM - inM);
        } else if (isPast && s.sign_in && !s.sign_out) {
          hasMissingPunchOut = true;
        }
      });

      const pill = document.getElementById('sel-day-status-pill');
      const missedAlert = document.getElementById('sel-day-missed-alert');
      const hoursBadge = document.getElementById('sel-day-hours-badge');
      const shiftSub = document.getElementById('sel-day-shift-sub');

      missedAlert.style.display = 'none';

      if (isToday) {
        if (dayShifts.length > 0 && !lastOut) {
          pill.innerText = 'Shift Active';
          pill.style.background = '#DCFCE7';
          pill.style.color = '#166534';
          hoursBadge.innerText = 'Shift in progress';
          hoursBadge.style.color = '#16A34A';
          shiftSub.innerText = 'Shift: 08:30 AM – In Progress';
        } else if (totalMins >= 530) {
          pill.innerText = 'Shift Completed';
          pill.style.background = '#DCFCE7';
          pill.style.color = '#166534';
          hoursBadge.innerText = 'Standard Met (Full Day)';
          hoursBadge.style.color = '#16A34A';
          shiftSub.innerText = 'Shift: 08:30 AM – 06:00 PM';
        } else {
          pill.innerText = 'Shift Active';
          pill.style.background = '#DCFCE7';
          pill.style.color = '#166534';
          hoursBadge.innerText = 'Shift in progress';
          hoursBadge.style.color = '#16A34A';
          shiftSub.innerText = 'Shift: 08:30 AM – In Progress';
        }
      } else if (hasMissingPunchOut) {
        pill.innerText = 'Missed Punch Out';
        pill.style.background = '#FEF3C7';
        pill.style.color = '#B45309';
        hoursBadge.innerText = 'Action Required';
        hoursBadge.style.color = '#D97706';
        shiftSub.innerText = 'Shift: Punch In Recorded, Out Missing';
        missedAlert.style.display = 'block';
      } else if (totalMins >= 530) {
        pill.innerText = 'Shift Completed • Full Day';
        pill.style.background = '#DCFCE7';
        pill.style.color = '#166534';
        hoursBadge.innerText = 'Standard Met (Full Day)';
        hoursBadge.style.color = '#16A34A';
        shiftSub.innerText = 'Shift: 09:00 AM – 06:00 PM';
      } else if (totalMins >= 180 || (dayShifts.length > 0 && totalMins > 0)) {
        pill.innerText = 'Half Day Shift';
        pill.style.background = '#FFF3E0';
        pill.style.color = '#D97706';
        hoursBadge.innerText = '0.5 Day Count';
        hoursBadge.style.color = '#D97706';
        shiftSub.innerText = 'Shift: Half Day Session';
      } else if (holiday) {
        pill.innerText = `Holiday (${holiday.title || 'Public'})`;
        pill.style.background = '#EFF6FF';
        pill.style.color = '#2563EB';
        hoursBadge.innerText = 'Gazetted Public Holiday';
        hoursBadge.style.color = '#2563EB';
        shiftSub.innerText = `Company Holiday: ${holiday.title || 'Official'}`;
      } else if (leave) {
        pill.innerText = `${leave.leave_type || 'Leave'} • Approved`;
        pill.style.background = '#FDF2F8';
        pill.style.color = '#DB2777';
        hoursBadge.innerText = 'Approved Leave';
        hoursBadge.style.color = '#DB2777';
        shiftSub.innerText = `Leave: ${leave.title || leave.leave_type}`;
      } else if (isRestDay) {
        pill.innerText = 'Week Off';
        pill.style.background = '#F9FAFB';
        pill.style.color = '#4B5563';
        hoursBadge.innerText = 'Scheduled Rest Day';
        hoursBadge.style.color = '#64748B';
        shiftSub.innerText = 'Company Weekend Off';
      } else if (Boolean(state.currentUser && (state.currentUser.date_of_joining || state.currentUser.joining_date) && new Date(dateStr + 'T00:00:00') < new Date(String(state.currentUser.date_of_joining || state.currentUser.joining_date).split('T')[0] + 'T00:00:00'))) {
        const uJoinStr = String(state.currentUser.date_of_joining || state.currentUser.joining_date).split('T')[0];
        pill.innerText = 'Pre-Joining';
        pill.style.background = '#F1F5F9';
        pill.style.color = '#64748B';
        hoursBadge.innerText = `Joined on ${uJoinStr}`;
        hoursBadge.style.color = '#64748B';
        shiftSub.innerText = 'Prior to employment start date';
      } else if (isPast) {
        pill.innerText = 'Absent (Unrecorded)';
        pill.style.background = '#FEE2E2';
        pill.style.color = '#DC2626';
        hoursBadge.innerText = 'No punches recorded';
        hoursBadge.style.color = '#DC2626';
        shiftSub.innerText = 'Shift: Unrecorded Working Day';
      } else {
        pill.innerText = 'Planned Shift';
        pill.style.background = '#F1F5F9';
        pill.style.color = '#64748B';
        hoursBadge.innerText = 'Upcoming Shift';
        hoursBadge.style.color = '#64748B';
        shiftSub.innerText = 'Shift: 09:00 AM – 06:00 PM';
      }

      // Total work hours
      const workHoursEl = document.getElementById('sel-day-work-hours');
      const otHoursEl = document.getElementById('sel-day-ot-hours');
      if (totalMins > 0) {
        workHoursEl.innerText = `${formatDurationCol(totalMins)} hrs`;
        if (totalMins > 540) {
          otHoursEl.innerText = `${formatDurationCol(totalMins - 540)} hrs`;
        } else {
          otHoursEl.innerText = '00:00 hrs';
        }
      } else {
        workHoursEl.innerText = '00:00 hrs';
        otHoursEl.innerText = '00:00 hrs';
      }

      // In & Out comparisons
      const inTimeEl = document.getElementById('sel-day-in-time');
      const inStatusEl = document.getElementById('sel-day-in-status');
      const outTimeEl = document.getElementById('sel-day-out-time');
      const outStatusEl = document.getElementById('sel-day-out-status');

      inTimeEl.innerText = firstIn ? formatTime12(firstIn) : '-- : --';
      inStatusEl.innerText = firstIn ? 'On Time' : (isPast ? 'Missed' : 'Scheduled');
      inStatusEl.style.color = firstIn ? '#16A34A' : '#64748B';

      outTimeEl.innerText = lastOut ? formatTime12(lastOut) : (isToday ? 'Active' : (firstIn ? 'Missing' : '-- : --'));
      outStatusEl.innerText = lastOut ? 'Approved' : (isToday ? 'In Progress' : (firstIn ? 'Action Req' : 'Scheduled'));
      outStatusEl.style.color = lastOut ? '#16A34A' : (isToday ? '#16A34A' : (firstIn ? '#D97706' : '#64748B'));

      // Timeline touchpoints
      const timelineList = document.getElementById('sel-day-timeline-list');
      const tpCountEl = document.getElementById('sel-day-touchpoint-count');
      if (timelineList) {
        if (dayShifts.length > 0) {
          let count = 0;
          let html = '';
          dayShifts.forEach((s, idx) => {
            count++;
            const sIn = formatTime12(s.sign_in || s.clock_in);
            const inLoc = formatPunchLocation(s, 'in');
            html += `
              <div style="background: var(--bg-card-subtle); padding: 10px 12px; border-radius: 12px; display: flex; align-items: center; justify-content: space-between;">
                <div style="display: flex; align-items: center; gap: 10px;">
                  <div style="width: 32px; height: 32px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center;">
                    <i data-lucide="log-in" style="width: 15px;"></i>
                  </div>
                  <div>
                    <div style="font-size: 13px; font-weight: 800;">Punch In ${dayShifts.length > 1 ? `(#${idx+1})` : ''}</div>
                    <div style="font-size: 10.5px; color: var(--text-secondary); margin-top: 1px;">${inLoc}</div>
                  </div>
                </div>
                <div style="text-align: right;">
                  <div style="font-size: 13.5px; font-weight: 800;">${sIn}</div>
                  <div style="font-size: 9.5px; font-weight: 700; color: #16A34A;">Verified</div>
                </div>
              </div>
            `;
            if (s.sign_out || s.clock_out) {
              count++;
              const sOut = formatTime12(s.sign_out || s.clock_out);
              const outLoc = formatPunchLocation(s, 'out');
              html += `
                <div style="background: var(--bg-card-subtle); padding: 10px 12px; border-radius: 12px; display: flex; align-items: center; justify-content: space-between;">
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="width: 32px; height: 32px; border-radius: 50%; background: #EFF6FF; color: #2563EB; display: flex; align-items: center; justify-content: center;">
                      <i data-lucide="log-out" style="width: 15px;"></i>
                    </div>
                    <div>
                      <div style="font-size: 13px; font-weight: 800;">Punch Out ${dayShifts.length > 1 ? `(#${idx+1})` : ''}</div>
                      <div style="font-size: 10.5px; color: var(--text-secondary); margin-top: 1px;">${outLoc}</div>
                    </div>
                  </div>
                  <div style="text-align: right;">
                    <div style="font-size: 13.5px; font-weight: 800;">${sOut}</div>
                    <div style="font-size: 9.5px; font-weight: 700; color: #2563EB;">Approved</div>
                  </div>
                </div>
              `;
            }
          });
          tpCountEl.innerText = `${count} Touchpoint${count > 1 ? 's' : ''}`;
          timelineList.innerHTML = html;
        } else {
          tpCountEl.innerText = '0 Touchpoints';
          timelineList.innerHTML = `
            <div style="text-align: center; padding: 14px; font-size: 11.5px; color: var(--text-secondary); background: var(--bg-card-subtle); border-radius: 12px;">
              No shift punch records logged on this date.
            </div>
          `;
        }
      }
      safeCreateIcons();
    }

    function openLeaveModalForDate(leaveType, isHalfDay) {
      openApplyLeaveModal();
      const dStr = state.selectedDayDate || toDateStr(new Date());
      const typeEl = document.getElementById('apply-leave-type');
      if (typeEl && leaveType) typeEl.value = leaveType;
      const fEl = document.getElementById('apply-from-date');
      if (fEl) fEl.value = dStr;
      const tEl = document.getElementById('apply-to-date');
      if (tEl) tEl.value = dStr;
      const reasonEl = document.getElementById('apply-reason');
      if (reasonEl) reasonEl.value = isHalfDay ? 'Half Day Leave' : (leaveType || 'Regularization');
      if (typeof recalculateLeaveDays === 'function') recalculateLeaveDays();
    }

    function renderWeeklyView() {
      const now = new Date();
      const todayStr = toDateStr(now);

      const dayOfWeek = now.getDay();
      const sun = new Date(now);
      sun.setDate(now.getDate() - dayOfWeek);
      sun.setHours(0, 0, 0, 0);

      const holidayDates = new Set((state.holidays || []).map(h => toDateStr(h.date)));
      const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

      let totalWeekMins = 0;
      let totalOvertimeMins = 0;
      const weekDailyMins = [];
      const currentWeekShifts = [];

      for (let i = 0; i < 7; i++) {
        const d = new Date(sun);
        d.setDate(sun.getDate() + i);
        const dStr = toDateStr(d);
        const isToday = (dStr === todayStr);

        const shifts = (state.attendanceLogs || []).filter(r => {
          const rDate = r.date || (r.clock_in ? r.clock_in.split('T')[0] : '');
          return rDate === dStr;
        });

        let dayMins = 0;
        shifts.forEach(s => {
          currentWeekShifts.push({ ...s, dateKey: dStr, dayName: dayNames[i] });
          if (s.total_minutes != null && Number(s.total_minutes) > 0) {
            dayMins += Number(s.total_minutes);
          } else if (s.sign_in && s.sign_out) {
            const inM = parseMinutes(s.sign_in);
            const outM = parseMinutes(s.sign_out);
            if (outM > inM) dayMins += (outM - inM);
          } else if (isToday && s.sign_in && !s.sign_out) {
            const inM = parseMinutes(s.sign_in);
            const curM = now.getHours() * 60 + now.getMinutes();
            if (curM > inM) dayMins += (curM - inM);
          }
        });

        weekDailyMins.push(dayMins);
        totalWeekMins += dayMins;
        if (dayMins > 540) {
          totalOvertimeMins += (dayMins - 540);
        }
      }

      const totH = Math.floor(totalWeekMins / 60);
      const totM = totalWeekMins % 60;
      const otH = Math.floor(totalOvertimeMins / 60);
      const otM = totalOvertimeMins % 60;

      const totHrsEl = document.getElementById('weekly-total-hrs');
      if (totHrsEl) {
        totHrsEl.innerHTML = `${String(totH).padStart(2, '0')}:${String(totM).padStart(2, '0')} <span style="font-size: 14px; font-weight: 700; color: var(--text-secondary);">hrs</span>`;
      }
      const otHrsEl = document.getElementById('weekly-overtime-hrs');
      if (otHrsEl) {
        otHrsEl.innerHTML = `${String(otH).padStart(2, '0')}:${String(otM).padStart(2, '0')} <span style="font-size: 13px; font-weight: 700; color: var(--text-secondary);">hrs</span>`;
      }

      const dashGoal = document.getElementById('dash-weekly-goal-text');
      if (dashGoal) {
        dashGoal.innerText = `${totH}/45h`;
      }

      const chartContainer = document.getElementById('weekly-bar-chart-container');
      if (chartContainer) {
        let barsHtml = '';
        for (let i = 0; i < 7; i++) {
          const d = new Date(sun);
          d.setDate(sun.getDate() + i);
          const dStr = toDateStr(d);
          const dayMins = weekDailyMins[i];
          const isHoliday = holidayDates.has(dStr);
          const isSunday = (i === 0);
          const satIndex = Math.floor((d.getDate() - 1) / 7) + 1;
          const isEvenSaturday = (i === 6 && satIndex % 2 === 0);
          const isOff = isSunday || isEvenSaturday;

          let pillCls = 'regular';
          let heightPct = 8;
          let innerText = '';
          let titleAttr = '';

          if (dayMins === 0) {
            if (isHoliday) {
              pillCls = 'holiday';
              heightPct = 50;
              innerText = '<span style="writing-mode: vertical-rl; transform: rotate(180deg); font-size: 8px;">FEST</span>';
              titleAttr = 'Company Holiday';
            } else if (isOff) {
              pillCls = 'dayoff';
              heightPct = 50;
              innerText = '<span style="writing-mode: vertical-rl; transform: rotate(180deg); font-size: 8px;">DAY OFF</span>';
              titleAttr = 'Week Off';
            } else {
              pillCls = 'empty';
              heightPct = 8;
              titleAttr = '0h 0m';
            }
          } else {
            pillCls = 'regular';
            heightPct = Math.min(100, Math.max(12, Math.round((dayMins / 600) * 100)));
            const h = Math.floor(dayMins / 60);
            const m = dayMins % 60;
            titleAttr = `${h}h ${m}m`;
            innerText = `<span style="font-size: 7.5px; margin-top: 4px;">${h}h</span>`;
          }

          barsHtml += `
            <div class="bar-col" title="${titleAttr}">
              <div class="bar-pill ${pillCls}" style="height: ${heightPct}%; cursor: pointer;" onclick="inspectDate('${dStr}')">
                ${innerText}
              </div>
              <span style="font-size: 11px; font-weight: 700; color: ${isOff ? '#7C3AED' : (isHoliday ? '#2563EB' : 'inherit')};">${dayNames[i]}</span>
            </div>
          `;
        }
        chartContainer.innerHTML = barsHtml;
      }

      const breakdownContainer = document.getElementById('weekly-breakdown-list');
      if (breakdownContainer) {
        if (currentWeekShifts.length === 0) {
          breakdownContainer.innerHTML = `
            <div class="app-card" style="padding: 20px; text-align: center; color: var(--text-secondary); font-size: 12px;">
              No shift records recorded for this week.
            </div>
          `;
        } else {
          currentWeekShifts.sort((a, b) => (b.dateKey || '').localeCompare(a.dateKey || ''));
          let listHtml = '';
          currentWeekShifts.forEach(s => {
            const inTime = formatTime12(s.sign_in || s.clock_in);
            const outTime = s.sign_out || s.clock_out ? formatTime12(s.sign_out || s.clock_out) : (s.dateKey === todayStr ? 'Active' : 'Missing');
            const dObj = new Date(s.dateKey + 'T00:00:00');
            const dateFmt = `${s.dayName}, ${dObj.getDate()} ${monthShortName(dObj.getMonth())}`;
            
            let durStr = '--';
            if (s.total_minutes != null && Number(s.total_minutes) > 0) {
              const h = Math.floor(Number(s.total_minutes) / 60);
              const m = Number(s.total_minutes) % 60;
              durStr = `${h}h ${m}m`;
            } else if (s.sign_in && s.sign_out) {
              const inM = parseMinutes(s.sign_in);
              const outM = parseMinutes(s.sign_out);
              if (outM > inM) durStr = `${Math.floor((outM - inM)/60)}h ${(outM - inM)%60}m`;
            } else if (s.dateKey === todayStr) {
              durStr = 'In Progress';
            }

            const badgeText = s.dateKey === todayStr && !s.sign_out ? 'On Shift' : 'On Time';
            const badgeBg = '#DCFCE7';
            const badgeCol = '#166534';

            listHtml += `
              <div class="app-card" style="padding: 12px 14px; display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="inspectDate('${s.dateKey}')">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <div style="width: 36px; height: 36px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center;">
                    <i data-lucide="log-in" style="width: 17px;"></i>
                  </div>
                  <div>
                    <div style="display: flex; align-items: center; gap: 6px;">
                      <span style="font-size: 13.5px; font-weight: 800;">${dateFmt}</span>
                      <span style="font-size: 9.5px; font-weight: 800; padding: 1px 6px; border-radius: 8px; background: ${badgeBg}; color: ${badgeCol};">${badgeText}</span>
                    </div>
                    <div style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">${inTime} – ${outTime}</div>
                  </div>
                </div>
                <div style="text-align: right;">
                  <div style="font-size: 13.5px; font-weight: 800;">${durStr}</div>
                  <div style="font-size: 10px; color: var(--text-dim);">Net Duration</div>
                </div>
              </div>
            `;
          });
          breakdownContainer.innerHTML = listHtml;
        }
      }
      safeCreateIcons();
    }

    function renderOverviewView() {
      const dt = state.currentPayrollCycleMonth;
      const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
      const mName = monthNames[dt.getMonth()];
      const prevMName = monthNames[dt.getMonth() === 0 ? 11 : dt.getMonth() - 1];

      const startCycle = new Date(dt.getFullYear(), dt.getMonth() - 1, 26);
      const endCycle = new Date(dt.getFullYear(), dt.getMonth(), 25);

      const rangeLabel = `26 ${prevMName.substring(0,3)} - 25 ${mName.substring(0,3)}`;
      const rangeEl = document.getElementById('overview-cycle-range');
      if (rangeEl) rangeEl.innerText = rangeLabel;

      const now = new Date();
      const todayStr = toDateStr(now);
      const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());

      const holidayDates = new Set((state.holidays || []).map(h => toDateStr(h.date)));

      const leaveMap = {};
      (state.myLeaves || []).forEach(l => {
        const st = (l.status || '').toLowerCase().trim();
        if (st !== 'approved') return;
        if (!l.start_date) return;
        const sStr = toDateStr(l.start_date);
        const eStr = toDateStr(l.end_date || l.start_date);
        let curL = new Date(sStr + 'T00:00:00');
        const endL = new Date(eStr + 'T00:00:00');
        while (curL <= endL) {
          leaveMap[toDateStr(curL)] = l;
          curL.setDate(curL.getDate() + 1);
        }
      });

      const dailyMinutesMap = {};
      (state.attendanceLogs || []).forEach(r => {
        const dKey = r.date || (r.clock_in ? r.clock_in.split('T')[0] : '');
        if (!dKey) return;
        let mins = 0;
        if (r.total_minutes != null && Number(r.total_minutes) > 0) {
          mins = Number(r.total_minutes);
        } else if (r.sign_in && r.sign_out) {
          const inM = parseMinutes(r.sign_in);
          const outM = parseMinutes(r.sign_out);
          if (outM > inM) mins = (outM - inM);
        } else if (dKey === todayStr && r.sign_in && !r.sign_out) {
          const inM = parseMinutes(r.sign_in);
          const curM = now.getHours() * 60 + now.getMinutes();
          if (curM > inM) mins = (curM - inM);
        }
        dailyMinutesMap[dKey] = (dailyMinutesMap[dKey] || 0) + mins;
      });

      let presentCount = 0;
      let absentCount = 0;
      let holidayCount = 0;
      let leaveCount = 0;
      let restDayCount = 0;
      let workingDaysCount = 0;
      let totalMinutesWorked = 0;
      let totalCycleDays = 0;

      let cur = new Date(startCycle);
      while (cur <= endCycle) {
        totalCycleDays++;
        const dStr = toDateStr(cur);
        const dayOfWeek = cur.getDay();
        const dNum = cur.getDate();
        const isSunday = (dayOfWeek === 0);
        const satIndex = Math.floor((dNum - 1) / 7) + 1;
        const isEvenSaturday = (dayOfWeek === 6 && satIndex % 2 === 0);
        const isRestDay = isSunday || isEvenSaturday;
        const isHoliday = holidayDates.has(dStr);
        const isLeave = Boolean(leaveMap[dStr]);
        const minsWorked = dailyMinutesMap[dStr] || 0;
        const isPast = cur < todayMidnight;
        const isToday = (dStr === todayStr);

        const uJoinStr = (state.currentUser && (state.currentUser.date_of_joining || state.currentUser.joining_date)) ? String(state.currentUser.date_of_joining || state.currentUser.joining_date).split('T')[0] : null;
        const uJoinDate = uJoinStr ? new Date(uJoinStr + 'T00:00:00') : null;

        if (uJoinDate && cur < uJoinDate) {
          cur.setDate(cur.getDate() + 1);
          continue;
        }

        if (isHoliday) {
          holidayCount++;
        } else if (isRestDay) {
          restDayCount++;
        } else {
          workingDaysCount++;
          if (isLeave) {
            leaveCount++;
          } else if (minsWorked >= 240) {
            presentCount++;
            totalMinutesWorked += minsWorked;
          } else if (isToday) {
            if (minsWorked > 0) {
              presentCount++;
              totalMinutesWorked += minsWorked;
            }
          } else if (isPast) {
            absentCount++;
          }
        }
        cur.setDate(cur.getDate() + 1);
      }

      const workingDaysEl = document.getElementById('overview-working-days');
      if (workingDaysEl) workingDaysEl.innerText = `${workingDaysCount} Working days`;

      const pEl = document.getElementById('overview-metric-present');
      if (pEl) pEl.innerText = String(presentCount).padStart(2, '0');

      const aEl = document.getElementById('overview-metric-absent');
      if (aEl) aEl.innerText = String(absentCount).padStart(2, '0');

      const hEl = document.getElementById('overview-metric-holiday');
      if (hEl) hEl.innerText = String(holidayCount).padStart(2, '0');

      const lEl = document.getElementById('overview-metric-leave');
      if (lEl) lEl.innerText = String(leaveCount).padStart(2, '0');

      const rEl = document.getElementById('overview-metric-restday');
      if (rEl) rEl.innerText = String(restDayCount).padStart(2, '0');

      const avgMinutes = presentCount > 0 ? Math.round(totalMinutesWorked / presentCount) : 540;
      const avgH = String(Math.floor(avgMinutes / 60)).padStart(2, '0');
      const avgM = String(avgMinutes % 60).padStart(2, '0');
      const avgEl = document.getElementById('overview-avg-hours');
      if (avgEl) avgEl.innerText = `${avgH}:${avgM}`;

      const dashRateText = document.getElementById('dash-rate-text');
      const dashRateTag = document.getElementById('dash-rate-tag');
      if (dashRateText && workingDaysCount > 0) {
        const rate = Math.min(100, Math.round((presentCount / Math.max(1, (presentCount + absentCount))) * 100));
        dashRateText.innerText = `${rate}%`;
        if (dashRateTag) dashRateTag.innerText = rate >= 90 ? 'Excellent' : (rate >= 75 ? 'Good' : 'Needs Attn');
      }

      const donutWrap = document.getElementById('overview-donut-wrapper');
      if (donutWrap && totalCycleDays > 0) {
        const segments = [
          { val: presentCount, col: '#10B981' },
          { val: holidayCount, col: '#06B6D4' },
          { val: leaveCount, col: '#F43F5E' },
          { val: restDayCount, col: '#94A3B8' },
          { val: absentCount, col: '#EF4444' }
        ];

        let offset = 0;
        let circlesHtml = '';
        segments.forEach(seg => {
          if (seg.val <= 0) return;
          const pct = (seg.val / totalCycleDays) * 100;
          const strokeDash = `${pct.toFixed(2)} ${(100 - pct).toFixed(2)}`;
          circlesHtml += `
            <circle cx="21" cy="21" r="15.91549430918954" fill="transparent"
              stroke="${seg.col}" stroke-width="4.8"
              stroke-dasharray="${strokeDash}" stroke-dashoffset="${(-offset).toFixed(2)}">
            </circle>
          `;
          offset += pct;
        });

        if (offset < 99.9) {
          const rem = 100 - offset;
          circlesHtml += `
            <circle cx="21" cy="21" r="15.91549430918954" fill="transparent"
              stroke="#E2E8F0" stroke-width="4.8" stroke-dasharray="${rem.toFixed(2)} ${offset.toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}">
            </circle>
          `;
        }

        donutWrap.innerHTML = `
          <svg viewBox="0 0 42 42" style="width: 100%; height: 100%; transform: rotate(-90deg);">
            ${circlesHtml}
          </svg>
        `;
      }
    }

    async function loadAttendanceData() {
      _lastSyncTimestamp = Date.now();
      try {
        const [attRes, holRes, leavesRes] = await Promise.all([
          fetch('/api/attendance/me', { headers: { 'Authorization': `Bearer ${state.token}` } }),
          fetch('/api/holidays', { headers: { 'Authorization': `Bearer ${state.token}` } }),
          fetch('/api/leaves/me', { headers: { 'Authorization': `Bearer ${state.token}` } })
        ]);
        if (attRes.ok) {
          state.attendanceLogs = await attRes.json();
          try { sessionStorage.setItem('attendanceLogs', JSON.stringify(state.attendanceLogs)); } catch(_) {}
        }
        if (holRes.ok) {
          state.holidays = await holRes.json();
          try { sessionStorage.setItem('holidays', JSON.stringify(state.holidays)); } catch(_) {}
          renderUpcomingHolidays();
        }
        if (leavesRes.ok) {
          const lData = await leavesRes.json();
          state.myLeaves = Array.isArray(lData.leaves) ? lData.leaves : [];
          try { sessionStorage.setItem('myLeaves', JSON.stringify(state.myLeaves)); } catch(_) {}
          updateLeaveStatsDisplay(lData);
        }
      } catch (_) {}
      renderAttendanceViews();
    }

    async function loadPunchApprovals() {
      const u = state.user || {};
      const roleStr = (u.role || '').toLowerCase().replace(/[\s_-]/g, '');
      const isMgr = roleStr.includes('leader') || roleStr.includes('lead') || roleStr.includes('manager') || roleStr === 'admin' || roleStr === 'hr';
      if (!isMgr) {
        state.teamPunchRequests = [];
        const badge = document.getElementById('att-punch-count-badge');
        if (badge) badge.style.display = 'none';
        const navPunchDot = document.getElementById('nav-punch-dot');
        if (navPunchDot) navPunchDot.style.display = 'none';
        return;
      }
      try {
        const res = await fetch('/api/team/punch-requests', { headers: { 'Authorization': `Bearer ${state.token}` } });
        if (res.ok) {
          const data = await res.json();
          const list = data.punch_requests || [];
          state.teamPunchRequests = list;
          
          document.getElementById('punch-req-header').innerText = `Pending Punch Requests (${list.length})`;
          const badge = document.getElementById('att-punch-count-badge');
          const navPunchDot = document.getElementById('nav-punch-dot');

          if (list.length > 0) {
            badge.innerText = list.length;
            badge.style.display = 'inline-block';
            navPunchDot.innerText = list.length;
            navPunchDot.style.display = 'block';
          } else {
            badge.style.display = 'none';
            navPunchDot.style.display = 'none';
          }

          const container = document.getElementById('punch-req-container');
          if (list.length === 0) {
            container.innerHTML = `
              <div class="app-card" style="padding: 32px 16px; text-align: center;">
                <div style="width: 48px; height: 48px; border-radius: 50%; background: #DCFCE7; color: #166534; display: flex; align-items: center; justify-content: center; margin: 0 auto 12px auto;">
                  <i data-lucide="shield-check" style="width: 24px;"></i>
                </div>
                <h4 style="font-size: 15px; font-weight: 900;">Zero Pending Punches</h4>
                <p style="font-size: 11.5px; color: var(--text-secondary); margin-top: 4px;">
                  All subordinate punches are verified within the 20m office range.
                </p>
              </div>
            `;
          } else {
            let html = '';
            list.forEach(p => {
              html += `
                <div class="app-card" style="padding: 14px; margin-bottom: 10px; border-color: #F5A952;">
                  <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                      <h4 style="font-size: 14px; font-weight: 800;">${p.employee_name || p.name}</h4>
                      <p style="font-size: 11px; color: var(--text-secondary);">${p.role || 'Staff'} • ${p.department || 'General'}</p>
                    </div>
                    <span style="font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 10px; background: #FEF3C7; color: #D97706;">Out of Geofence</span>
                  </div>
                  <div style="font-size: 11.5px; color: var(--text-secondary); margin: 8px 0; background: var(--bg-card-subtle); padding: 8px 10px; border-radius: 8px;">
                    📍 ${p.location || 'Mobile GPS'} (${p.distance_meters || '>20'}m from ${p.nearest_building || 'Office'})
                  </div>
                  <div style="display: flex; gap: 8px;">
                    <button onclick="reviewPunchRequest(${p.id || p._id}, 'approve')" class="btn-approve-solid" style="padding: 6px 12px; font-size: 11.5px;">Approve Punch</button>
                    <button onclick="reviewPunchRequest(${p.id || p._id}, 'reject')" class="btn-reject-outline" style="padding: 6px 12px; font-size: 11.5px;">Reject Punch</button>
                  </div>
                </div>
              `;
            });
            container.innerHTML = html;
          }
          safeCreateIcons();
        }
      } catch (_) {}
    }

    async function reviewPunchRequest(id, action) {
      if (!confirm(`Are you sure you want to ${action} this punch?`)) return;
      try {
        await fetch(`/api/team/punch-requests/${id}/action`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ action: action })
        });
        alert(`✅ Punch request ${action}d successfully!`);
        loadPunchApprovals();
      } catch (_) {
        alert('Action failed');
      }
    }

    // ── Leave Management Sub-Views & Manager Approvals ──
    function switchLeavesView(view) {
      const u = state.user || {};
      const roleStr = (u.role || '').toLowerCase().replace(/[\s_-]/g, '');
      const isMgr = roleStr.includes('leader') || roleStr.includes('lead') || roleStr.includes('manager') || roleStr === 'admin' || roleStr === 'hr';
      if (!isMgr) view = 'my';
      state.leavesSubTab = view;
      const myBtn = document.getElementById('leaves-subtab-my');
      if (myBtn) myBtn.classList.toggle('active', view === 'my');
      const teamBtn = document.getElementById('leaves-subtab-team');
      if (teamBtn) teamBtn.classList.toggle('active', view === 'team');
      const myView = document.getElementById('leaves-my-view');
      if (myView) myView.style.display = view === 'my' ? 'flex' : 'none';
      const teamView = document.getElementById('leaves-team-view');
      if (teamView) teamView.style.display = view === 'team' ? 'flex' : 'none';
      if (view === 'team' && isMgr) loadTeamApprovalsData();
      safeCreateIcons();
    }

    function updateLeaveStatsDisplay(lData) {
      if (!lData) return;
      const bal = lData.balance || lData;
      const total = bal.total_allotted != null ? Number(bal.total_allotted) : 6.0;
      const used = bal.used_days != null ? Number(bal.used_days) : 0.0;
      const rem = Math.max(0, Math.round((total - used) * 100) / 100);

      const elOver = document.getElementById('overview-leaves-left');
      if (elOver) elOver.innerText = rem;

      const elBadge = document.getElementById('leave-badge-days-left');
      if (elBadge) elBadge.innerText = `${rem} Days Left`;

      const elRem = document.getElementById('leave-stat-rem');
      if (elRem) elRem.innerText = rem;

      const elAllot = document.getElementById('leave-stat-allotted');
      if (elAllot) elAllot.innerText = total;

      const elUsed = document.getElementById('leave-stat-used');
      if (elUsed) elUsed.innerText = used;

      const elApplyAvail = document.getElementById('apply-leave-avail-days');
      if (elApplyAvail) elApplyAvail.innerText = rem;
    }

    async function loadLeavesData() {
      _lastSyncTimestamp = Date.now();
      try {
        const fetchHols = (!state.holidays || state.holidays.length === 0);
        const [leavesRes, holRes] = await Promise.all([
          fetch('/api/leaves/me', { headers: { 'Authorization': `Bearer ${state.token}` } }),
          fetchHols ? fetch('/api/holidays', { headers: { 'Authorization': `Bearer ${state.token}` } }) : Promise.resolve(null)
        ]);
        if (leavesRes && leavesRes.ok) {
          const lData = await leavesRes.json();
          updateLeaveStatsDisplay(lData);
          state.myLeaves = Array.isArray(lData.leaves) ? lData.leaves : [];
          renderMyLeavesList(state.myLeaves);
        }
        if (holRes && holRes.ok) {
          state.holidays = await holRes.json();
          try { sessionStorage.setItem('holidays', JSON.stringify(state.holidays)); } catch(_) {}
        }
      } catch (_) {}
      renderUpcomingHolidays();
    }

    function renderUpcomingHolidays() {
      const container = document.getElementById('upcoming-holidays-container');
      if (!container) return;

      const list = (state.holidays && state.holidays.length > 0) ? state.holidays : DEFAULT_HOLIDAYS_LIST;
      const now = new Date();
      const todayStr = toDateStr(now);
      const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());

      // Strict filter for holidays on or after today (past holidays like Gandhi Jayanti are excluded)
      const upcoming = list.filter(h => {
        const dStr = toDateStr(h.date);
        return dStr && dStr >= todayStr;
      });

      upcoming.sort((a, b) => toDateStr(a.date).localeCompare(toDateStr(b.date)));

      if (upcoming.length === 0) {
        container.innerHTML = `
          <div class="app-card" style="padding: 18px; text-align: center; color: var(--text-secondary); font-size: 12px;">
            <i data-lucide="calendar-check" style="width: 22px; color: #10B981; margin: 0 auto 6px auto; display: block;"></i>
            No upcoming holidays remaining for ${now.getFullYear()}
          </div>
        `;
        safeCreateIcons();
        return;
      }

      // Display up to 4 upcoming holidays
      const displayList = upcoming.slice(0, 4);
      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

      let html = '';
      displayList.forEach(h => {
        const dStr = toDateStr(h.date);
        const dObj = new Date(dStr + 'T00:00:00');
        const dayNum = String(dObj.getDate()).padStart(2, '0');
        const mName = monthNames[dObj.getMonth()];
        const yNum = dObj.getFullYear();
        const formattedDate = `${dayNum} ${mName} ${yNum}`;
        const weekday = h.weekday || ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][dObj.getDay()];

        const targetMidnight = new Date(dObj.getFullYear(), dObj.getMonth(), dObj.getDate());
        const diffDays = Math.round((targetMidnight - todayMidnight) / (1000 * 60 * 60 * 24));
        let badgeText = '';
        let badgeBg = '#EFF6FF';
        let badgeColor = '#2563EB';

        if (diffDays === 0) {
          badgeText = 'Today';
          badgeBg = '#DCFCE7';
          badgeColor = '#166534';
        } else if (diffDays === 1) {
          badgeText = 'Tomorrow';
          badgeBg = '#FEF3C7';
          badgeColor = '#B45309';
        } else if (diffDays > 1) {
          badgeText = `In ${diffDays} days`;
        }

        html += `
          <div class="app-card" style="padding: 12px 14px; display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="width: 32px; height: 32px; border-radius: 8px; background: #EFF6FF; color: #2563EB; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                <i data-lucide="sparkles" style="width: 16px;"></i>
              </div>
              <div>
                <div style="font-size: 13px; font-weight: 800; color: var(--text-primary);">${h.title || 'Holiday'}</div>
                <div style="font-size: 10.5px; color: var(--text-dim);">${weekday}</div>
              </div>
            </div>
            <div style="text-align: right;">
              <span style="font-size: 11px; font-weight: 700; color: var(--text-secondary);">${formattedDate}</span>
              ${badgeText ? `<div style="font-size: 9.5px; font-weight: 800; color: ${badgeColor}; background: ${badgeBg}; padding: 1px 6px; border-radius: 6px; margin-top: 2px;">${badgeText}</div>` : ''}
            </div>
          </div>
        `;
      });

      container.innerHTML = html;
      safeCreateIcons();
    }

    function openAllHolidaysModal() {
      const modal = document.getElementById('modal-all-holidays');
      if (!modal) return;
      renderAllHolidaysModalList();
      modal.classList.add('active');
      safeCreateIcons();
    }

    function closeAllHolidaysModal() {
      const modal = document.getElementById('modal-all-holidays');
      if (modal) modal.classList.remove('active');
    }

    function renderAllHolidaysModalList() {
      const c = document.getElementById('all-holidays-list-container');
      if (!c) return;
      const list = (state.holidays && state.holidays.length > 0) ? state.holidays : DEFAULT_HOLIDAYS_LIST;
      const now = new Date();
      const todayStr = toDateStr(now);
      const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

      const sorted = [...list].sort((a, b) => toDateStr(a.date).localeCompare(toDateStr(b.date)));

      let html = '';
      sorted.forEach(h => {
        const dStr = toDateStr(h.date);
        const dObj = new Date(dStr + 'T00:00:00');
        const dayNum = String(dObj.getDate()).padStart(2, '0');
        const mName = monthNames[dObj.getMonth()];
        const yNum = dObj.getFullYear();
        const formattedDate = `${dayNum} ${mName} ${yNum}`;
        const weekday = h.weekday || ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][dObj.getDay()];

        const isPast = dStr < todayStr;
        const isToday = dStr === todayStr;
        const targetMidnight = new Date(dObj.getFullYear(), dObj.getMonth(), dObj.getDate());
        const diffDays = Math.round((targetMidnight - todayMidnight) / (1000 * 60 * 60 * 24));

        let badgeHtml = '';
        let iconBg = '#EFF6FF';
        let iconColor = '#2563EB';

        if (isToday) {
          badgeHtml = `<span style="font-size: 9.5px; font-weight: 800; background: #DCFCE7; color: #166534; padding: 2px 7px; border-radius: 6px;">Today</span>`;
          iconBg = '#DCFCE7';
          iconColor = '#166534';
        } else if (isPast) {
          badgeHtml = `<span style="font-size: 9.5px; font-weight: 700; background: #F1F5F9; color: #64748B; padding: 2px 7px; border-radius: 6px;">Passed</span>`;
          iconBg = '#F1F5F9';
          iconColor = '#94A3B8';
        } else {
          badgeHtml = `<span style="font-size: 9.5px; font-weight: 800; background: #EFF6FF; color: #1D4ED8; padding: 2px 7px; border-radius: 6px;">In ${diffDays} days</span>`;
        }

        html += `
          <div class="app-card" style="padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; ${isPast ? 'opacity: 0.72;' : 'border-left: 3px solid #2563EB;'}">
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="width: 32px; height: 32px; border-radius: 8px; background: ${iconBg}; color: ${iconColor}; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                <i data-lucide="${isPast ? 'calendar-check' : 'sparkles'}" style="width: 16px;"></i>
              </div>
              <div>
                <div style="font-size: 13px; font-weight: 800; color: var(--text-primary);">${h.title || 'Holiday'}</div>
                <div style="font-size: 10.5px; color: var(--text-dim);">${weekday}</div>
              </div>
            </div>
            <div style="text-align: right;">
              <div style="font-size: 11px; font-weight: 700; color: var(--text-secondary);">${formattedDate}</div>
              <div style="margin-top: 2px;">${badgeHtml}</div>
            </div>
          </div>
        `;
      });
      c.innerHTML = html;
      safeCreateIcons();
    }

    function filterLeaves(status, btn) {
      document.querySelectorAll('#leaves-my-view .segment-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (status === 'All') {
        renderMyLeavesList(state.myLeaves);
      } else {
        renderMyLeavesList(state.myLeaves.filter(l => (l.status || '').toLowerCase().includes(status.toLowerCase())));
      }
    }

    function renderMyLeavesList(list) {
      const c = document.getElementById('my-leaves-container');
      if (!c) return;
      if (!list || list.length === 0) {
        c.innerHTML = `<div style="text-align: center; color: var(--text-dim); font-size: 12px; padding: 14px;">No applications found</div>`;
        return;
      }
      let html = '';
      list.forEach(l => {
        const isAppr = l.status === 'Approved';
        const isRej = (l.status || '').toLowerCase().includes('reject');
        const dCount = Number(l.days_count != null ? l.days_count : 1.0);
        let daysText = '';
        if (dCount === 0.5) {
          daysText = `0.5 Day (Half Day${l.from_session ? ' • ' + l.from_session : ''})`;
        } else if (dCount === 1) {
          daysText = '1 Day';
        } else {
          daysText = `${dCount} Days`;
        }

        const dateRange = (l.start_date === l.end_date || !l.end_date)
          ? `${l.start_date}`
          : `${l.start_date} → ${l.end_date}`;

        const statusBg = isAppr ? '#DCFCE7' : (isRej ? '#FEE2E2' : '#FEF3C7');
        const statusColor = isAppr ? '#166534' : (isRej ? '#991B1B' : '#D97706');
        const statusIcon = isAppr ? 'check-circle' : (isRej ? 'x-circle' : 'hourglass');

        html += `
          <div class="app-card" style="padding: 14px; margin-bottom: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
              <div style="display: flex; align-items: center; gap: 10px;">
                <div style="width: 32px; height: 32px; border-radius: 50%; background: ${statusBg}; color: ${statusColor}; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                  <i data-lucide="${statusIcon}" style="width: 16px;"></i>
                </div>
                <div>
                  <div style="font-size: 13.5px; font-weight: 800; color: var(--text-primary);">${l.leave_type || 'Leave'}</div>
                  <div style="font-size: 11px; color: var(--text-secondary); margin-top: 1px;">
                    <span style="font-weight: 700; color: #2563EB;">${daysText}</span>
                    ${l.title ? ` • "${l.title}"` : ''}
                  </div>
                </div>
              </div>
              <span style="font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 10px; background: ${statusBg}; color: ${statusColor};">${l.status}</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--text-secondary); margin-top: 10px; background: var(--bg-card-subtle); padding: 8px 10px; border-radius: 8px;">
              <span>📅 ${dateRange}</span>
              ${dCount === 0.5 && l.from_session ? `<span style="font-weight: 700; background: #DBEAFE; color: #1E40AF; padding: 2px 8px; border-radius: 6px;">${l.from_session}</span>` : `<span>${dCount === 0.5 ? 'Half Day (0.5)' : dCount + ' Day' + (dCount > 1 ? 's' : '')}</span>`}
            </div>
            ${l.rejection_reason ? `<div style="margin-top: 6px; font-size: 11px; color: #DC2626; background: #FEF2F2; padding: 6px 10px; border-radius: 6px;">Reason: ${l.rejection_reason}</div>` : ''}
          </div>
        `;
      });
      c.innerHTML = html;
      safeCreateIcons();
    }

    async function loadTeamApprovalsData() {
      const u = state.user || {};
      const roleStr = (u.role || '').toLowerCase().replace(/[\s_-]/g, '');
      const isMgr = roleStr.includes('leader') || roleStr.includes('lead') || roleStr.includes('manager') || roleStr === 'admin' || roleStr === 'hr';
      if (!isMgr) {
        state.teamLeaves = [];
        state.teamMembers = [];
        const banner = document.getElementById('dash-manager-pending-banner');
        if (banner) banner.style.display = 'none';
        const badge = document.getElementById('leaves-team-badge');
        if (badge) badge.style.display = 'none';
        const navLeavesDot = document.getElementById('nav-leaves-dot');
        if (navLeavesDot) navLeavesDot.style.display = 'none';
        const c1 = document.getElementById('team-leaves-list-container');
        if (c1) c1.innerHTML = '';
        const c2 = document.getElementById('team-members-list-container');
        if (c2) c2.innerHTML = '';
        return;
      }
      try {
        const [leavesRes, teamRes] = await Promise.all([
          fetch('/api/team/leaves', { headers: { 'Authorization': `Bearer ${state.token}` } }),
          fetch('/api/team/hierarchy', { headers: { 'Authorization': `Bearer ${state.token}` } })
        ]);

        if (leavesRes.ok) {
          const rawLeaves = await leavesRes.json();
          const cleanEid = String(state.user?.employee_no || state.user?.emp_id || '').replace(/^0+/, '');
          const roleStr = (state.user?.role || '').toLowerCase().replace(/[\s_-]/g, '');
          const isAdmin = roleStr === 'admin' || roleStr === 'superadmin' || ['965', '1844', '1951', '1009', '1228', '10001', '10003'].includes(cleanEid);
          
          const teamLeavesFilter = document.getElementById('team-leaves-filter-container');
          if (teamLeavesFilter) teamLeavesFilter.style.display = isAdmin ? 'flex' : 'none';

          state.teamLeaves = isAdmin ? rawLeaves : rawLeaves.filter(l => (l.status || '').toLowerCase().includes('pending'));

          const teamLeavesDeptFilter = document.getElementById('team-leaves-dept-filter-container');
          if (teamLeavesDeptFilter) {
            if (isAdmin) {
              const depts = ['All', ...new Set(rawLeaves.map(l => (l.department || '').trim()).filter(Boolean))].sort((a,b) => a === 'All' ? -1 : (b === 'All' ? 1 : a.localeCompare(b)));
              teamLeavesDeptFilter.style.display = 'flex';
              teamLeavesDeptFilter.innerHTML = depts.map(d => {
                const isSel = (state.teamLeavesDeptFilter || 'All').toLowerCase() === d.toLowerCase();
                const dCount = d === 'All' ? rawLeaves.length : rawLeaves.filter(l => (l.department || '').trim().toLowerCase() === d.toLowerCase()).length;
                return `
                  <button onclick="filterTeamLeavesByDept('${d}', this)" class="dept-chip" style="flex: none; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; cursor: pointer; border: 1px solid ${isSel ? 'var(--primary)' : 'var(--border-card)'}; background: ${isSel ? 'var(--primary)' : 'var(--bg-card)'}; color: ${isSel ? 'var(--primary-text)' : 'var(--text-secondary)'};">
                    ${d === 'All' ? '🏢 All Depts' : d} (${dCount})
                  </button>
                `;
              }).join('');
            } else {
              teamLeavesDeptFilter.style.display = 'none';
            }
          }

          applyTeamLeavesFilter();
        }

        if (teamRes.ok) {
          const t = await teamRes.json();
          const members = t.members || [];
          state.teamMembers = members;
          const leads = members.filter(m => (m.role || '').toLowerCase().includes('leader') || (m.role || '').toLowerCase().includes('lead'));
          const present = members.filter(m => m.today_status === 'Clocked In' || m.today_status === 'Clocked Out').length;
          const pending = t.pending_approvals_count || state.teamLeaves.filter(l => (l.status || '').toLowerCase().includes('pending')).length;

          document.getElementById('mgr-stat-leads').innerText = `${leads.length} Leads`;
          document.getElementById('mgr-stat-present').innerText = `${present}/${members.length}`;
          document.getElementById('mgr-stat-pending').innerText = `${pending} Pending`;
          document.getElementById('mgr-pending-pill').innerText = `${pending} Pending`;
          
          const banner = document.getElementById('dash-manager-pending-banner');
          const badge = document.getElementById('leaves-team-badge');
          const navLeavesDot = document.getElementById('nav-leaves-dot');

          if (pending > 0) {
            banner.style.display = 'flex';
            document.getElementById('dash-pending-count-text').innerText = `${pending} pending leave approval(s)`;
            badge.innerText = pending;
            badge.style.display = 'inline-block';
            navLeavesDot.innerText = pending;
            navLeavesDot.style.display = 'block';
          } else {
            banner.style.display = 'none';
            badge.style.display = 'none';
            navLeavesDot.style.display = 'none';
          }

          renderTeamMembersList(members);
        }
      } catch (_) {}
    }

    function filterTeamLeaves(status, btn) {
      document.querySelectorAll('#team-leaves-filter-container .segment-tab-btn').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      state.teamLeavesStatusFilter = status;
      applyTeamLeavesFilter();
    }

    function filterTeamLeavesByDept(dept, btn) {
      state.teamLeavesDeptFilter = dept;
      document.querySelectorAll('#team-leaves-dept-filter-container .dept-chip').forEach(b => {
        const isMatch = b.innerText.includes(dept === 'All' ? 'All Depts' : dept);
        b.style.borderColor = isMatch ? 'var(--primary)' : 'var(--border-card)';
        b.style.background = isMatch ? 'var(--primary)' : 'var(--bg-card)';
        b.style.color = isMatch ? 'var(--primary-text)' : 'var(--text-secondary)';
      });
      applyTeamLeavesFilter();
    }

    function applyTeamLeavesFilter() {
      const st = state.teamLeavesStatusFilter || 'All';
      const dept = state.teamLeavesDeptFilter || 'All';
      let list = state.teamLeaves || [];
      if (st !== 'All') {
        list = list.filter(l => (l.status || '').toLowerCase().includes(st.toLowerCase()));
      }
      if (dept !== 'All') {
        list = list.filter(l => (l.department || '').trim().toLowerCase() === dept.toLowerCase());
      }
      renderTeamLeavesList(list);
    }

    function renderTeamLeavesList(list) {
      const c = document.getElementById('team-leaves-list-container');
      if (!c) return;
      if (!list || list.length === 0) {
        c.innerHTML = `<div style="text-align: center; color: var(--text-dim); font-size: 12px; padding: 14px;">No subordinate leave records found</div>`;
        return;
      }
      let html = '';
      list.forEach(l => {
        const isPend = (l.status || '').toLowerCase().includes('pending');
        const isAppr = l.status === 'Approved';
        const initial = (l.employee_name || 'E')[0].toUpperCase();

        const dCount = Number(l.days_count != null ? l.days_count : 1.0);
        let daysBadgeText = '';
        if (dCount === 0.5) {
          daysBadgeText = '0.5 Day (Half Day)';
        } else if (dCount === 1) {
          daysBadgeText = '1 Day';
        } else {
          daysBadgeText = `${dCount} Days`;
        }

        html += `
          <div class="app-card" style="padding: 16px; border: 1.5px solid ${isPend ? '#FDE68A' : 'var(--border-card)'}; background: var(--bg-card); margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
              <div style="display: flex; align-items: center; gap: 10px;">
                <div style="width: 38px; height: 38px; border-radius: 50%; background: #EFF6FF; color: #2563EB; font-weight: 800; display: flex; align-items: center; justify-content: center;">${initial}</div>
                <div>
                  <div style="font-size: 14px; font-weight: 900;">${l.employee_name}</div>
                  <div style="font-size: 11px; color: var(--text-dim); margin-top: 1px;">${l.role || 'Staff'} • ${l.department || 'General'}</div>
                </div>
              </div>
              <span style="font-size: 10px; font-weight: 800; padding: 3px 8px; border-radius: 12px; background: ${isPend ? '#FEF3C7' : (isAppr ? '#DCFCE7' : '#FFE4E6')}; color: ${isPend ? '#D97706' : (isAppr ? '#166534' : '#EF4444')}; border: 1px solid ${isPend ? '#FDE68A' : 'transparent'}; display: flex; align-items: center; gap: 4px;">
                <span style="width: 5px; height: 5px; border-radius: 50%; background: currentColor;"></span>
                <span>${isPend ? 'Pending Review' : l.status}</span>
              </span>
            </div>

            <div style="background: var(--bg-card-subtle); padding: 12px; border-radius: 14px; margin: 12px 0;">
              <div style="display: flex; align-items: center; gap: 8px; font-size: 10.5px; font-weight: 800; color: var(--text-dim);">
                <i data-lucide="calendar" style="width: 14px; color: #2563EB;"></i>
                <span>LEAVE DATE</span>
              </div>
              <div style="font-size: 13.5px; font-weight: 800; margin: 4px 0 8px 0;">${l.start_date} ${l.end_date && l.end_date !== l.start_date ? '– ' + l.end_date : ''}</div>

              <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                <span style="font-size: 10.5px; font-weight: 800; padding: 2px 8px; border-radius: 8px; background: #FCE7F3; color: #DB2777; display: flex; align-items: center; gap: 4px;">
                  <i data-lucide="plane" style="width: 11px;"></i>
                  <span>${l.leave_type || 'Leave'}</span>
                </span>
                <span style="font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 8px; background: #E2E8F0; color: #475569; display: flex; align-items: center; gap: 4px;">
                  <i data-lucide="clock" style="width: 11px;"></i>
                  <span>${daysBadgeText}</span>
                </span>
                ${dCount === 0.5 && l.from_session ? `
                <span style="font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 8px; background: #DBEAFE; color: #1E40AF; display: flex; align-items: center; gap: 4px;">
                  <i data-lucide="sun" style="width: 11px;"></i>
                  <span>${l.from_session}</span>
                </span>` : ''}
              </div>

              ${(l.title && l.title !== l.leave_type) || l.note ? `
                <div style="margin-top: 8px; font-size: 11.5px; color: var(--text-secondary); background: rgba(0,0,0,0.03); padding: 6px 10px; border-radius: 6px;">
                  <b>Reason:</b> ${l.title || l.note}
                </div>
              ` : ''}
            </div>

            ${isPend ? `
              <div style="display: flex; gap: 10px;">
                <button onclick="reviewSubordinateLeave(${l.id}, 'approve')" class="btn-approve-solid">
                  <i data-lucide="check" style="width: 15px;"></i>
                  <span>Approve</span>
                </button>
                <button onclick="reviewSubordinateLeave(${l.id}, 'reject')" class="btn-reject-outline">
                  <i data-lucide="x" style="width: 15px;"></i>
                  <span>Reject</span>
                </button>
              </div>
            ` : ''}
          </div>
        `;
      });
      c.innerHTML = html;
      safeCreateIcons();
    }

    function renderTeamMembersList(members) {
      const c = document.getElementById('team-members-list-container');
      if (!c) return;
      if (!members || members.length === 0) {
        c.innerHTML = `<div style="text-align: center; color: var(--text-dim); font-size: 12px; padding: 14px;">No team members found</div>`;
        return;
      }
      let html = '';
      members.forEach(m => {
        const isClockedIn = m.today_status === 'Clocked In';
        const isClockedOut = m.today_status === 'Clocked Out';
        const initial = (m.name || 'M')[0].toUpperCase();

        html += `
          <div class="app-card" style="padding: 12px 14px; display: flex; align-items: center; justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <div class="user-avatar-pill" style="width: 36px; height: 36px; font-size: 14px;">${initial}</div>
              <div>
                <div style="font-size: 13.5px; font-weight: 800;">${m.name}</div>
                <div style="font-size: 10.5px; color: var(--text-dim);">${m.designation || m.role} • ${m.department}</div>
              </div>
            </div>
            <span style="font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 10px; background: ${isClockedIn ? '#DCFCE7' : (isClockedOut ? '#EFF6FF' : '#F1F5F9')}; color: ${isClockedIn ? '#166534' : (isClockedOut ? '#2563EB' : '#475569')};">
              ${m.today_status}
            </span>
          </div>
        `;
      });
      c.innerHTML = html;
      safeCreateIcons();
    }

    async function reviewSubordinateLeave(id, action) {
      if (!confirm(`Are you sure you want to ${action} this leave request?`)) return;
      try {
        await fetch(`/api/team/leaves/${id}/action`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ action: action })
        });
        alert(`✅ Leave request ${action}d successfully!`);
        loadTeamApprovalsData();
      } catch (_) {
        alert('Action failed');
      }
    }

    // ── Floating Toast / Snackbar Helper ──
    function showToast(message, type = 'success') {
      const toast = document.getElementById('app-toast');
      if (!toast) {
        alert(message);
        return;
      }
      toast.className = `app-toast-banner toast-${type}`;
      const iconName = type === 'success' ? 'check-circle' : (type === 'error' ? 'alert-triangle' : 'info');
      toast.innerHTML = `
        <i data-lucide="${iconName}" style="width: 18px; flex-shrink: 0;"></i>
        <span>${message}</span>
      `;
      safeCreateIcons();
      toast.style.display = 'flex';
      clearTimeout(toast._timer);
      toast._timer = setTimeout(() => {
        toast.style.display = 'none';
      }, 4000);
    }

    // ── Work Entry Form State & Real-Time Options ──
    const FALLBACK_PMS_OPTIONS = {
      departments: [
        'Engineering',
        'Railway Engineering',
        'Highway Engineering',
        'GIS',
        'Geospatial Technology',
        'Geotech',
        'CAD',
        'Drone',
        'IT Department',
        'Field COE',
        'Project',
        'Traffic & Safety',
        'Admin',
        'Finance & Accounts'
      ],
      tasksByDept: {
        'Civil & Infrastructure': [
          'Subgrade Preparation & Excavation',
          'Pavement Base & Subbase Laying',
          'Drainage & Culvert Construction',
          'Concrete Pouring & Curing',
          'Earthwork & Grading'
        ],
        'Survey & GIS Mapping': [
          'Topographic Survey & Contour Mapping',
          'Boundary Demarcation & Geotagging',
          'Drone Aerial Photogrammetry',
          'As-Built Verification Survey',
          'Control Point Establishment'
        ],
        'Structural & Architectural': [
          'Structural Drafting & Detailing',
          'Column & Beam Rebar Inspection',
          'Foundation Pile Load Testing',
          'Facade & Finishing Execution'
        ],
        'Electrical & MEP': [
          'Underground Cable Trenching',
          'Substation Panel Installation',
          'HVAC Ducting & Plumbing Run'
        ],
        'Project Management & QA': [
          'Quality Control & Material Testing',
          'Safety & Compliance Audit',
          'Daily Progress Report Compilation'
        ],
        'Engineering': [
          'Subgrade Preparation & Excavation',
          'Topographic Survey & Contour Mapping',
          'Structural Drafting & Detailing',
          'Quality Control & Testing'
        ]
      },
      subtasksByTask: {
        'Subgrade Preparation & Excavation': [
          'Trench Trenching Section B (Chainage 12+400)',
          'Soil Compaction Testing Layer 2',
          'Excavation for Retaining Wall Footing',
          'Boulder Clearing & Site Leveling'
        ],
        'Topographic Survey & Contour Mapping': [
          'Total Station Grid Observation (5m interval)',
          'Benchmark Level Verification with DGPS',
          'Cadastral Boundary Superimposition'
        ],
        'Pavement Base & Subbase Laying': [
          'GSB Laying & Compaction Chainage 4+200',
          'WMM Base Course Spreading',
          'Bituminous Concrete Surface Dressing'
        ],
        'Structural Drafting & Detailing': [
          'Foundation Pile Load Testing',
          'Column & Beam Rebar Detailing',
          'GIRDER Alignment CAD Drawing'
        ],
        'Quality Control & Testing': [
          'Cube Compressive Strength 28 Days',
          'Field Density Sand Replacement Method',
          'Slump Test & Mix Verification'
        ]
      }
    };

    let workEntryOptions = {
      loaded: false,
      projects: [],
      departments: [],
      tasksByDept: {},
      subtasksByTask: {},
      units: ['KM', 'M', 'Nos', 'Ton', 'SqM', 'CuM', 'Hrs', 'Points', 'Sheets', 'Km/Hr', 'Days'],
      revisions: [
        'Rev 0 — Initial Working Execution',
        'Rev 1 — Client Feedback Iteration',
        'Rev 2 — Quality Review Revision',
        'Rev 3 — Final Site Alignment',
        'New',
        'Final'
      ]
    };

    async function loadWorkEntryFormOptions() {
      const loadingBar = document.getElementById('we-loading-bar');
      if (loadingBar) loadingBar.style.display = 'block';

      try {
        const res = await fetch('/api/work-entries/form-options', {
          headers: state.token ? { 'Authorization': `Bearer ${state.token}` } : {}
        });
        if (res.ok) {
          const data = await res.json();

          if (data.is_pms_user === false) {
            workEntryOptions.is_pms_user = false;
            workEntryOptions.pms_error = data.pms_error || 'Employee does not exist in PMS directory.';
          } else {
            workEntryOptions.is_pms_user = true;
            workEntryOptions.pms_error = null;
          }

          // 1. Projects filtering (matching Flutter work_entry_sheet.dart)
          if (Array.isArray(data.projects) && data.projects.length > 0) {
            const filtered = data.projects.map(p => ({
              id: String(p.id || '').trim(),
              name: String(p.name || p.project_name || p.id || '').trim()
            })).filter(p => {
              const idU = p.id.toUpperCase();
              const nameU = p.name.toUpperCase();
              return p.id.length > 0 &&
                !p.id.startsWith('$') &&
                !p.id.startsWith('.') &&
                !idU.includes('RECYCLE') &&
                !idU.includes('SYSTEM VOLUME') &&
                !idU.includes('DO NOT TOUCH') &&
                !idU.includes('REFERENCE PLEASE') &&
                !nameU.includes('DO NOT TOUCH') &&
                !nameU.includes('REFERENCE PLEASE');
            });

            const seen = new Set();
            workEntryOptions.projects = [];
            for (const p of filtered) {
              if (!seen.has(p.id)) {
                seen.add(p.id);
                workEntryOptions.projects.push(p);
              }
            }
          }

          // 2. Departments
          if (Array.isArray(data.departments) && data.departments.length > 0) {
            const deptSet = new Set(data.departments.map(d => String(d).trim()).filter(Boolean));
            FALLBACK_PMS_OPTIONS.departments.forEach(d => deptSet.add(d));
            workEntryOptions.departments = Array.from(deptSet).sort((a, b) => a.localeCompare(b));
          } else {
            workEntryOptions.departments = [...FALLBACK_PMS_OPTIONS.departments].sort();
          }

          // 3. Tasks by Department
          workEntryOptions.tasksByDept = Object.assign({}, FALLBACK_PMS_OPTIONS.tasksByDept);
          if (data.tasks_by_dept && typeof data.tasks_by_dept === 'object') {
            for (const [dept, tasks] of Object.entries(data.tasks_by_dept)) {
              if (Array.isArray(tasks) && tasks.length > 0) {
                workEntryOptions.tasksByDept[dept] = Array.from(new Set(tasks.map(t => String(t).trim()).filter(Boolean)));
              }
            }
          }

          // 4. Subtasks by Task
          workEntryOptions.subtasksByTask = Object.assign({}, FALLBACK_PMS_OPTIONS.subtasksByTask);
          if (data.subtasks_by_task && typeof data.subtasks_by_task === 'object') {
            for (const [task, subtasks] of Object.entries(data.subtasks_by_task)) {
              if (Array.isArray(subtasks) && subtasks.length > 0) {
                workEntryOptions.subtasksByTask[task] = Array.from(new Set(subtasks.map(s => String(s).trim()).filter(Boolean)));
              }
            }
          }

          // 5. Units & Revisions
          if (Array.isArray(data.units) && data.units.length > 0) {
            workEntryOptions.units = Array.from(new Set(data.units));
          }
          if (Array.isArray(data.revisions) && data.revisions.length > 0) {
            workEntryOptions.revisions = Array.from(new Set(data.revisions));
          }

          workEntryOptions.loaded = true;
        }
      } catch (err) {
        console.warn('Could not load live work entry options, using fallback PMS data:', err);
        if (!workEntryOptions.loaded) {
          workEntryOptions.departments = [...FALLBACK_PMS_OPTIONS.departments].sort();
          workEntryOptions.tasksByDept = Object.assign({}, FALLBACK_PMS_OPTIONS.tasksByDept);
          workEntryOptions.subtasksByTask = Object.assign({}, FALLBACK_PMS_OPTIONS.subtasksByTask);
        }
      } finally {
        if (loadingBar) loadingBar.style.display = 'none';
        populateWorkEntryFormDropdowns();
      }
    }

    function populateWorkEntryFormDropdowns() {
      // 1. Projects Dropdown List
      renderProjectDropdownList(workEntryOptions.projects);

      const curPrjId = document.getElementById('we-selected-project-id').value;
      if (!curPrjId && workEntryOptions.projects.length > 0) {
        selectProject(workEntryOptions.projects[0]);
      }

      // 2. Department Dropdown
      const deptSelect = document.getElementById('we-dept');
      const userDept = (state.user?.department || 'Engineering').trim();
      deptSelect.innerHTML = '';

      let targetDept = null;
      workEntryOptions.departments.forEach(dept => {
        const opt = document.createElement('option');
        opt.value = dept;
        opt.textContent = dept;
        deptSelect.appendChild(opt);
        if (!targetDept && dept.toLowerCase() === userDept.toLowerCase()) {
          targetDept = dept;
        }
      });

      if (targetDept) {
        deptSelect.value = targetDept;
      } else if (workEntryOptions.departments.includes('Engineering')) {
        deptSelect.value = 'Engineering';
      } else if (workEntryOptions.departments.length > 0) {
        deptSelect.value = workEntryOptions.departments[0];
      }

      // 3. Units
      const unitSelect = document.getElementById('we-unit');
      unitSelect.innerHTML = '';
      workEntryOptions.units.forEach(u => {
        const opt = document.createElement('option');
        opt.value = u;
        opt.textContent = u;
        unitSelect.appendChild(opt);
      });
      unitSelect.value = 'KM';

      // 4. Revisions
      const revSelect = document.getElementById('we-rev');
      revSelect.innerHTML = '';
      workEntryOptions.revisions.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r;
        opt.textContent = r;
        revSelect.appendChild(opt);
      });
      if (workEntryOptions.revisions.includes('Rev 0 — Initial Working Execution')) {
        revSelect.value = 'Rev 0 — Initial Working Execution';
      }

      // Cascade to Task & Subtask
      onWorkEntryDeptChange();
    }

    function onWorkEntryDeptChange() {
      const dept = document.getElementById('we-dept').value;
      const taskSelect = document.getElementById('we-task');
      taskSelect.innerHTML = '';

      let tasks = workEntryOptions.tasksByDept[dept];
      if (!tasks || tasks.length === 0) {
        const matchKey = Object.keys(workEntryOptions.tasksByDept).find(k => k.toLowerCase() === dept.toLowerCase());
        if (matchKey) tasks = workEntryOptions.tasksByDept[matchKey];
      }

      if (!tasks || tasks.length === 0) {
        tasks = FALLBACK_PMS_OPTIONS.tasksByDept['Engineering'] || ['General Site Work'];
      }

      tasks.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        taskSelect.appendChild(opt);
      });

      if (tasks.length > 0) {
        taskSelect.value = tasks[0];
      }

      onWorkEntryTaskChange();
    }

    function onWorkEntryTaskChange() {
      const task = document.getElementById('we-task').value;
      const subtaskSelect = document.getElementById('we-subtask');
      subtaskSelect.innerHTML = '';

      let subtasks = workEntryOptions.subtasksByTask[task];
      if (!subtasks || subtasks.length === 0) {
        const matchKey = Object.keys(workEntryOptions.subtasksByTask).find(k => k.toLowerCase() === task.toLowerCase());
        if (matchKey) subtasks = workEntryOptions.subtasksByTask[matchKey];
      }

      if (!subtasks || subtasks.length === 0) {
        subtasks = [
          'Trench Trenching Section B (Chainage 12+400)',
          'Execution & Baseline Verification',
          'Field Inspection & Documentation',
          'Material Handling & QA Signoff'
        ];
      }

      subtasks.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        subtaskSelect.appendChild(opt);
      });

      if (subtasks.length > 0) {
        subtaskSelect.value = subtasks[0];
      }
    }

    // ── Searchable Project Dropdown Logic ──
    function formatProjectLabel(p) {
      const id = String(p.id || '').trim();
      const name = String(p.name || '').trim();
      if (!id) return name;
      if (!name || id === name) return `#${id}`;
      return `#${id} — ${name}`;
    }

    function selectProject(p) {
      document.getElementById('we-selected-project-id').value = p.id;
      document.getElementById('we-selected-project-name').value = p.name;
      const label = formatProjectLabel(p);
      document.getElementById('we-project-search').value = label;
      document.getElementById('we-project-clear-btn').style.display = 'block';
      closeProjectDropdown();
    }

    function clearProjectSelection() {
      document.getElementById('we-selected-project-id').value = '';
      document.getElementById('we-selected-project-name').value = '';
      document.getElementById('we-project-search').value = '';
      document.getElementById('we-project-clear-btn').style.display = 'none';
      renderProjectDropdownList(workEntryOptions.projects);
      openProjectDropdown();
    }

    function toggleProjectDropdown() {
      const dropdown = document.getElementById('we-project-dropdown-list');
      if (dropdown.style.display === 'block') {
        closeProjectDropdown();
      } else {
        openProjectDropdown();
      }
    }

    function openProjectDropdown() {
      const dropdown = document.getElementById('we-project-dropdown-list');
      dropdown.style.display = 'block';
      filterProjectDropdown(document.getElementById('we-project-search').value);
    }

    function closeProjectDropdown() {
      const dropdown = document.getElementById('we-project-dropdown-list');
      if (dropdown) dropdown.style.display = 'none';
    }

    function filterProjectDropdown(query) {
      const q = String(query || '').trim().toLowerCase().replace(/^#/, '');
      let list = workEntryOptions.projects;
      if (q) {
        list = list.filter(p => {
          const id = p.id.toLowerCase();
          const name = p.name.toLowerCase();
          return id.includes(q) || name.includes(q);
        });
      }
      renderProjectDropdownList(list);
      document.getElementById('we-project-clear-btn').style.display = query ? 'block' : 'none';
    }

    function renderProjectDropdownList(list) {
      const container = document.getElementById('we-project-dropdown-list');
      if (!container) return;
      container.innerHTML = '';

      if (list.length === 0) {
        container.innerHTML = `<div style="padding: 12px; font-size: 12px; color: var(--text-dim); text-align: center;">No matching projects found</div>`;
        return;
      }

      const selectedId = document.getElementById('we-selected-project-id').value;

      list.slice(0, 100).forEach(p => {
        const item = document.createElement('div');
        const isSel = (p.id === selectedId);
        item.className = 'we-project-option-item';
        item.style.cssText = `
          padding: 10px 14px;
          font-size: 12.5px;
          font-weight: ${isSel ? '800' : '600'};
          color: var(--text-primary);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: space-between;
          border-bottom: 1px solid var(--border-card);
          background: ${isSel ? 'var(--primary-subtle)' : 'transparent'};
          transition: background 0.15s ease;
        `;
        item.innerHTML = `
          <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px;">${formatProjectLabel(p)}</span>
          ${isSel ? '<i data-lucide="check" style="width: 15px; color: var(--primary); flex-shrink: 0;"></i>' : ''}
        `;
        item.onmouseenter = () => { if (!isSel) item.style.background = 'var(--bg-card-subtle)'; };
        item.onmouseleave = () => { if (!isSel) item.style.background = 'transparent'; };
        item.onmousedown = (e) => {
          e.preventDefault();
          selectProject(p);
        };
        container.appendChild(item);
      });
      safeCreateIcons();
    }

    document.addEventListener('click', (e) => {
      const container = document.querySelector('.we-project-search-container');
      if (container && !container.contains(e.target)) {
        closeProjectDropdown();
      }
    });

    // ── Work Date & Effort Calculation ──
    function onWorkEntryDateChange(val) {
      if (!val) return;
      const parts = val.split('-');
      if (parts.length === 3) {
        document.getElementById('we-work-date-display').innerText = `${parts[2]}-${parts[1]}-${parts[0]}`;
      }
    }

    function initWorkEntryDate() {
      const today = new Date();
      const yyyy = today.getFullYear();
      const mm = String(today.getMonth() + 1).padStart(2, '0');
      const dd = String(today.getDate()).padStart(2, '0');
      const isoDate = `${yyyy}-${mm}-${dd}`;
      const dateInput = document.getElementById('we-work-date');
      if (dateInput) {
        if (!dateInput.value) {
          dateInput.value = isoDate;
        }
        const curVal = dateInput.value || isoDate;
        const parts = curVal.split('-');
        if (parts.length === 3) {
          document.getElementById('we-work-date-display').innerText = `${parts[2]}-${parts[1]}-${parts[0]}`;
        }
      }
    }

    function updateWorkEntryTotalEffort() {
      const hrs = parseInt(document.getElementById('we-hours').value, 10) || 0;
      const mins = parseInt(document.getElementById('we-mins').value, 10) || 0;
      const totalEl = document.getElementById('we-total-effort-text');
      if (totalEl) {
        totalEl.innerText = `Total: ${hrs}h ${mins}m`;
      }
    }

    function addWorkEntryQuickChip(chipText) {
      const clean = chipText.replace(/^\+\s*/, '').trim();
      const textarea = document.getElementById('we-remarks');
      const current = textarea.value.trim();
      if (!current) {
        textarea.value = clean;
      } else if (!current.includes(clean)) {
        textarea.value = `${current}. ${clean}.`;
      }
      updateWorkEntryRemarksValidation();
      textarea.focus();
    }

    function updateWorkEntryRemarksValidation() {
      const card = document.getElementById('we-remarks-card');
      const text = document.getElementById('we-remarks').value.trim();
      if (card) {
        if (text.length > 0) {
          card.style.borderColor = 'var(--border-card)';
          card.style.borderWidth = '1px';
        }
      }
    }

    // ── Open / Close Work Entry Modal ──
    function openWorkEntryModal() {
      initWorkEntryDate();
      document.getElementById('modal-work-entry').classList.add('active');
      if (!workEntryOptions.loaded) {
        loadWorkEntryFormOptions();
      }
      safeCreateIcons();
    }

    function closeWorkEntryModal() {
      closeProjectDropdown();
      document.getElementById('modal-work-entry').classList.remove('active');
    }

    // ── Save Work Entry Submission ──
    async function saveWorkEntry() {
      let prjId = document.getElementById('we-selected-project-id').value.trim();
      let prjName = document.getElementById('we-selected-project-name').value.trim();
      const searchInputVal = document.getElementById('we-project-search').value.trim();

      // If user typed custom project name
      if (!prjId && searchInputVal) {
        const cleanId = searchInputVal.replace(/^#/, '').split(' — ')[0].trim();
        const found = workEntryOptions.projects.find(p =>
          formatProjectLabel(p).toLowerCase() === searchInputVal.toLowerCase() ||
          p.id.toLowerCase() === cleanId.toLowerCase() ||
          p.name.toLowerCase() === searchInputVal.toLowerCase()
        );
        if (found) {
          prjId = found.id;
          prjName = found.name;
        } else {
          prjId = cleanId;
          prjName = searchInputVal;
        }
      }

      // Automatic fallback if still empty
      if (!prjId && !prjName && workEntryOptions.projects.length > 0) {
        prjId = workEntryOptions.projects[0].id;
        prjName = workEntryOptions.projects[0].name;
      }

      if (!prjId && !prjName) {
        showToast('⚠️ Please select or type a Project.', 'error');
        document.getElementById('we-project-search').focus();
        return;
      }

      const dept = document.getElementById('we-dept').value.trim();
      const task = document.getElementById('we-task').value.trim();
      const subtask = document.getElementById('we-subtask').value.trim();
      const qty = parseFloat(document.getElementById('we-qty').value) || 0.0;
      const unit = document.getElementById('we-unit').value.trim() || 'KM';
      const hrs = parseInt(document.getElementById('we-hours').value, 10) || 0;
      const mins = parseInt(document.getElementById('we-mins').value, 10) || 0;
      const rev = document.getElementById('we-rev').value.trim() || 'Rev 0 — Initial Working Execution';
      const remarks = document.getElementById('we-remarks').value.trim();
      const workDate = document.getElementById('we-work-date').value || new Date().toISOString().split('T')[0];

      // Validation matching Flutter work_entry_sheet.dart
      if (!remarks) {
        const card = document.getElementById('we-remarks-card');
        if (card) {
          card.style.borderColor = '#EF4444';
          card.style.borderWidth = '1.5px';
        }
        showToast('⚠️ Remarks are mandatory. Please provide details of work completed.', 'error');
        document.getElementById('we-remarks').focus();
        return;
      }

      if (hrs === 0 && mins === 0) {
        showToast('⚠️ Please enter hours or minutes spent on this task.', 'error');
        document.getElementById('we-hours').focus();
        return;
      }

      if (workEntryOptions.is_pms_user === false) {
        showToast(workEntryOptions.pms_error || 'Employee does not exist in PMS user directory. Work entry cannot be submitted.', 'error');
        return;
      }

      const saveBtn = document.getElementById('btn-save-we');
      const btnText = document.getElementById('btn-save-we-text');
      const originalText = btnText ? btnText.innerText : 'Save Work Entry';

      try {
        if (saveBtn) saveBtn.disabled = true;
        if (btnText) btnText.innerText = 'Saving Entry...';

        const payload = {
          work_date: workDate,
          project_id: prjId,
          project_name: prjName,
          department: dept,
          task: task,
          subtask: subtask,
          quantity: qty,
          unit: unit,
          hours: hrs,
          minutes: mins,
          revision: rev,
          remarks: remarks
        };

        const res = await fetch('/api/work-entries', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${state.token}`
          },
          body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok || data.error) {
          showToast(data.error || 'Failed to save work entry.', 'error');
        } else {
          showToast(`✅ Work Entry saved for ${prjName || prjId} (${hrs}h ${mins}m)`, 'success');

          // Reset fields
          document.getElementById('we-qty').value = '';
          document.getElementById('we-hours').value = '';
          document.getElementById('we-mins').value = '';
          document.getElementById('we-remarks').value = '';
          updateWorkEntryTotalEffort();

          closeWorkEntryModal();
          if (typeof loadDashboardData === 'function') {
            loadDashboardData();
          }
        }
      } catch (err) {
        showToast('Network error: Failed to save work entry.', 'error');
      } finally {
        if (saveBtn) saveBtn.disabled = false;
        if (btnText) btnText.innerText = originalText;
      }
    }

    // ── Leave Application Calculations ──
    function calculateLeaveDaysCount(fromDateStr, fromSession, toDateStr, toSession, leaveType) {
      if (leaveType === 'Regularization') {
        return 0.0;
      }
      if (leaveType === 'Half Day Leave') {
        return 0.5;
      }
      if (!fromDateStr || !toDateStr) {
        return 1.0;
      }

      const d1 = new Date(fromDateStr + 'T00:00:00');
      const d2 = new Date(toDateStr + 'T00:00:00');

      if (isNaN(d1.getTime()) || isNaN(d2.getTime())) {
        return 1.0;
      }

      // Invalid range
      if (d2 < d1) {
        return -1;
      }

      const diffTime = d2.getTime() - d1.getTime();
      const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24)) + 1;

      if (diffDays === 1) {
        // Single calendar day
        if (fromSession === toSession) {
          // Session 1 to Session 1 or Session 2 to Session 2 -> exactly half day
          return 0.5;
        } else if (fromSession === 'Session 2' && toSession === 'Session 1') {
          // Inverted same-day session selection -> half day
          return 0.5;
        } else {
          // Session 1 to Session 2 -> full day
          return 1.0;
        }
      } else {
        // Multi-day
        let count = diffDays;
        if (fromSession === 'Session 2') {
          count -= 0.5;
        }
        if (toSession === 'Session 1') {
          count -= 0.5;
        }
        return Math.max(0.5, count);
      }
    }

    function recalculateLeaveDays() {
      const typeEl = document.getElementById('apply-leave-type');
      const fromDateEl = document.getElementById('apply-from-date');
      const fromSessionEl = document.getElementById('apply-from-session');
      const toDateEl = document.getElementById('apply-to-date');
      const toSessionEl = document.getElementById('apply-to-session');
      const cardEl = document.getElementById('apply-calc-card');
      const iconWrap = document.getElementById('apply-calc-icon-wrapper');
      const titleEl = document.getElementById('apply-calc-title');
      const descEl = document.getElementById('apply-calc-desc');
      const availEl = document.getElementById('apply-leave-avail-days');

      if (!typeEl || !fromDateEl || !toDateEl || !cardEl || !titleEl || !descEl) return;

      const type = typeEl.value;
      const fromDate = fromDateEl.value;
      const fromSession = fromSessionEl ? fromSessionEl.value : 'Session 1';
      let toDate = toDateEl.value;
      let toSession = toSessionEl ? toSessionEl.value : 'Session 2';

      if (type === 'Half Day Leave') {
        if (toDateEl.value !== fromDate) {
          toDateEl.value = fromDate;
          toDate = fromDate;
        }
        if (toSessionEl && toSessionEl.value !== fromSession) {
          toSessionEl.value = fromSession;
          toSession = fromSession;
        }
      }

      const days = calculateLeaveDaysCount(fromDate, fromSession, toDate, toSession, type);
      const availDays = availEl ? (parseFloat(availEl.innerText) || 0) : 0;

      if (days < 0) {
        cardEl.style.background = '#FEF2F2';
        cardEl.style.borderColor = '#EF4444';
        if (iconWrap) iconWrap.innerHTML = '<i data-lucide="alert-triangle" style="width: 18px; color: #EF4444;"></i>';
        titleEl.style.color = '#991B1B';
        titleEl.innerText = 'Invalid Date Range';
        descEl.style.color = '#B91C1C';
        descEl.innerText = 'To date cannot be earlier than From date. Please select valid dates.';
        safeCreateIcons();
        return;
      }

      if (type === 'Regularization') {
        cardEl.style.background = '#EFF6FF';
        cardEl.style.borderColor = '#3B82F6';
        if (iconWrap) iconWrap.innerHTML = '<i data-lucide="info" style="width: 18px; color: #2563EB;"></i>';
        titleEl.style.color = '#1E40AF';
        titleEl.innerText = 'Attendance Regularization (Concession)';
        descEl.style.color = '#1D4ED8';
        descEl.innerText = 'Company concession with manager approval — 0 days deducted from leave balance.';
        safeCreateIcons();
        return;
      }

      cardEl.style.background = '#ECFDF5';
      cardEl.style.borderColor = '#10B981';
      if (iconWrap) iconWrap.innerHTML = '<i data-lucide="check-circle" style="width: 18px; color: #10B981;"></i>';
      titleEl.style.color = '#065F46';
      descEl.style.color = '#047857';

      if (days === 0.5) {
        const sLabel = fromSession === 'Session 1' ? 'First Half (Session 1)' : 'Second Half (Session 2)';
        titleEl.innerText = `0.5 Day (${type}) • Half Day [${sLabel}]`;
        descEl.innerHTML = `Will deduct <b>0.5 day</b> from ${type} balance (<span id="apply-leave-avail-days">${availDays}</span> Days currently available).`;
      } else if (days === 1.0) {
        titleEl.innerText = `1 Day (${type})`;
        descEl.innerHTML = `Will deduct <b>1 day</b> from ${type} balance (<span id="apply-leave-avail-days">${availDays}</span> Days currently available).`;
      } else {
        titleEl.innerText = `${days} Days (${type})`;
        descEl.innerHTML = `Will deduct <b>${days} days</b> from ${type} balance (<span id="apply-leave-avail-days">${availDays}</span> Days currently available).`;
      }
      safeCreateIcons();
    }

    function onApplyLeaveTypeChange() {
      const typeEl = document.getElementById('apply-leave-type');
      const fromDateEl = document.getElementById('apply-from-date');
      const toDateEl = document.getElementById('apply-to-date');
      const fromSessionEl = document.getElementById('apply-from-session');
      const toSessionEl = document.getElementById('apply-to-session');
      if (typeEl && typeEl.value === 'Half Day Leave') {
        if (toDateEl && fromDateEl) toDateEl.value = fromDateEl.value;
        if (toSessionEl && fromSessionEl) toSessionEl.value = fromSessionEl.value;
      }
      recalculateLeaveDays();
    }

    function onApplyFromDateChange() {
      const fromDateEl = document.getElementById('apply-from-date');
      const toDateEl = document.getElementById('apply-to-date');
      const typeEl = document.getElementById('apply-leave-type');
      if (fromDateEl && toDateEl) {
        if (!toDateEl.value || toDateEl.value < fromDateEl.value || (typeEl && typeEl.value === 'Half Day Leave')) {
          toDateEl.value = fromDateEl.value;
        }
      }
      recalculateLeaveDays();
    }

    function openApplyLeaveModal() {
      const todayStr = new Date().toISOString().split('T')[0];
      const fromEl = document.getElementById('apply-from-date');
      const toEl = document.getElementById('apply-to-date');
      if (fromEl && !fromEl.value) fromEl.value = todayStr;
      if (toEl && !toEl.value) toEl.value = todayStr;

      const elApplyAvail = document.getElementById('apply-leave-avail-days');
      const elRem = document.getElementById('leave-stat-rem');
      if (elApplyAvail && elRem && elRem.innerText) {
        elApplyAvail.innerText = elRem.innerText;
      }

      recalculateLeaveDays();
      document.getElementById('modal-apply-leave').classList.add('active');
    }

    function closeApplyLeaveModal() {
      document.getElementById('modal-apply-leave').classList.remove('active');
    }

    async function handleApplyLeaveFormSubmit(e) {
      e.preventDefault();
      const type = document.getElementById('apply-leave-type').value;
      const start = document.getElementById('apply-from-date').value;
      const fromSession = document.getElementById('apply-from-session') ? document.getElementById('apply-from-session').value : 'Session 1';
      const end = document.getElementById('apply-to-date').value;
      const toSession = document.getElementById('apply-to-session') ? document.getElementById('apply-to-session').value : 'Session 2';
      const reason = document.getElementById('apply-reason').value;
      const note = document.getElementById('apply-note').value;

      const daysCount = calculateLeaveDaysCount(start, fromSession, end, toSession, type);
      if (daysCount < 0) {
        alert('❌ Error: "To date" cannot be earlier than "From date".');
        return;
      }

      const isHalfDay = (daysCount === 0.5 || type === 'Half Day Leave');

      try {
        const res = await fetch('/api/leaves', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ 
            title: reason,
            leave_type: type,
            start_date: start,
            end_date: end,
            from_session: fromSession,
            to_session: toSession,
            session: fromSession,
            days_count: daysCount,
            is_half_day: isHalfDay,
            note: note
          })
        });
        const d = await res.json();
        if (d.error) {
          alert('❌ ' + d.error);
        } else {
          alert(`✅ Leave application for ${daysCount === 0.5 ? '0.5 Day (Half Day)' : daysCount + (daysCount === 1 ? ' Day' : ' Days')} submitted to Manager!`);
          closeApplyLeaveModal();
          loadLeavesData();
        }
      } catch (_) {
        alert('Failed to submit application');
      }
    }

    // ── Profile Updates ──
    async function handleProfileSave(e) {
      e.preventDefault();
      const name = document.getElementById('prof-form-name').value;
      const phone = document.getElementById('prof-form-phone').value;
      const email = document.getElementById('prof-form-email').value;

      try {
        await fetch('/api/user/profile', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ name: name, phone_number: phone, email: email })
        });
        alert('✅ Profile details verified and saved 100%!');
        verifySession();
      } catch (_) {
        alert('Failed to update profile.');
      }
    }

    async function handlePasswordUpdate(e) {
      e.preventDefault();
      const oldP = document.getElementById('pwd-old').value.trim();
      const newP = document.getElementById('pwd-new').value.trim();

      if (!oldP || !newP) {
        alert('Please enter both your current password and new password.');
        return;
      }
      if (newP.length < 6) {
        alert('New password must be at least 6 characters long.');
        return;
      }

      try {
        const res = await fetch('/api/auth/change-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
          body: JSON.stringify({ old_password: oldP, new_password: newP })
        });
        const d = await res.json();
        if (d.error) {
          alert('❌ ' + d.error);
        } else {
          alert('✅ Password updated successfully!');
          document.getElementById('pwd-old').value = '';
          document.getElementById('pwd-new').value = '';
        }
      } catch (err) {
        alert('Password update failed: ' + (err && err.message ? err.message : 'Please check your connection.'));
      }
    }
  </script>
</body>
</html>
"""

# ─── Mount Phone-Identical Web UI Routes exclusively for web_app.py ───────────
def serve_phone_web_ui():
    """Serves the rich modern phone-identical Single-Page Web Application."""
    return render_template_string(INDEX_HTML)

# Ensure web_app.py serves the Phone UI on /, /login, /dashboard, etc.
# (Overriding the Admin Dashboard root route inherited from postgres_api_server)
original_admin_view = app.view_functions.get('serve_admin_dashboard_ui')
def route_web_ui_handler(subpath=None):
    if request.path in ('/', '/login', '/dashboard', '/attendance', '/leaves', '/team', '/profile'):
        return serve_phone_web_ui()
    if original_admin_view:
        return original_admin_view(subpath=subpath)
    return serve_phone_web_ui()

app.view_functions['serve_admin_dashboard_ui'] = route_web_ui_handler
app.view_functions['serve_phone_web_ui'] = serve_phone_web_ui

for rule_path in ['/login', '/dashboard', '/attendance', '/leaves', '/team', '/profile']:
    endpoint_name = f'phone_{rule_path.strip("/")}'
    if endpoint_name not in app.view_functions:
        app.add_url_rule(rule_path, endpoint=endpoint_name, view_func=serve_phone_web_ui, methods=['GET'])


# ─── Main Entrypoint ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    logger.info("=" * 70)
    logger.info(" MONARCH HR & WORKTRACK WEB APPLICATION (PHONE-IDENTICAL UI)")
    logger.info("=" * 70)
    logger.info(f" • Server starting on port {PORT}...")
    logger.info(f" • Local Web UI URL: http://127.0.0.1:{PORT}")
    logger.info(f" • Network Web UI URL: http://0.0.0.0:{PORT}")
    logger.info("=" * 70)
    app.run(host='0.0.0.0', port=PORT, debug=False)
