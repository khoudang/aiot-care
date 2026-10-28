# Product

## Platform

web

## Users

Primary users are family members caring for a patient at home. They use the web interface to check room conditions, recognize safety events, and operate connected devices. Administrators also manage accounts, system settings, and activity logs.

## Product Purpose

AIoT Care monitors and controls the patient room, living room, and kitchen from one web interface. Success means a family member can quickly recognize an incident and identify which room needs attention.

## Positioning

A local gateway gathers data from three ESP32-C3 room nodes over BLE, processes it in a Python backend, and updates the web dashboard in real time. The interface combines patient safety monitoring with environmental readings and household device controls.

## Operating Context

Family members use a phone or laptop browser at home, and may access the web through a remote network connection. Administrators use the same web interface for account, configuration, and log management. The gateway and room nodes may be running independently or disconnected, so connection and data freshness must be clear.

## Capabilities and Constraints

- The patient room provides temperature, humidity, motion, camera, gesture, and fall detection data, with fan, buzzer, and camera controls.
- The living room provides temperature, humidity, light, and motion readings, with light, fan, and automatic-mode controls.
- The kitchen provides gas ADC, smoke, and flame readings, with window, exhaust fan, light, and buzzer controls.
- Preserve the existing Flask, Jinja, and Socket.IO application, routes, APIs, event payloads, JavaScript selectors, and authentication flows.
- The system has no wearable device or weather data source. The interface must not present invented measurements or claim medical advice.

## Brand Commitments

The product is named AIoT Care and its interface is in Vietnamese. The supplied `D:/KLTN/SOURCE/templates/` pages are visual references; they do not define product behavior or factual claims.

## Evidence on Hand

Product behavior and hardware are documented in `README.md`, `docs/API.md`, and `docs/HARDWARE.md`; routes and controls are implemented in `web.py`, `templates/`, and `static/`. The supplied reference templates show the user's desired visual inspiration. There are no approved customer testimonials, weather feeds, or external safety certifications to display.

## Product Principles

- Surface incidents and the affected room before routine measurements.
- Make connection state and missing or stale data explicit.
- Keep room monitoring and controls understandable to a family member.
- Preserve reliable access to existing safety controls.
