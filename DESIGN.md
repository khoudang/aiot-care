---
name: AIoT Care
description: A Home Assistant-inspired smart-home dashboard for family care.
colors:
  sidebar: "#111b26"
  sidebar-selected: "#263746"
  background: "#f2f3f5"
  surface: "#ffffff"
  surface-muted: "#f7f8fa"
  text: "#202b36"
  text-muted: "#66727e"
  divider: "#d9dde2"
  accent: "#039be5"
  healthy: "#2e7d32"
  caution: "#9a6700"
  caution-surface: "#fff4d6"
  incident: "#c62828"
  incident-surface: "#fdebea"
typography:
  headline:
    fontFamily: "Roboto, Segoe UI, system-ui, sans-serif"
    fontSize: "25px"
    fontWeight: 500
    lineHeight: 1.25
  title:
    fontFamily: "Roboto, Segoe UI, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 500
  body:
    fontFamily: "Roboto, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "4px"
  md: "6px"
spacing:
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  room-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "15px"
  primary-action:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
---

# Design System: AIoT Care

## Overview

The dashboard follows the familiar Home Assistant smart-home pattern: a persistent dark sidebar, a compact app header, room views, and information grouped into small entity-like cards. The interface keeps AIoT Care's own name, Vietnamese labels, room data, and safety workflows.

**Creative North Star: “Nhà thông minh, dễ quan sát”**

Use a neutral light workspace framed by a dark slate navigation rail. Roboto, restrained borders, compact cards, and clear state colors keep the interface dense and scannable. The login and registration forms share the same neutral surfaces and blue action color.

**Key Characteristics:**
- Dark left navigation with a clear selected-room treatment.
- White, compact cards over a quiet gray background.
- Blue is the action color; green, amber, and red communicate state.
- Responsive room navigation opens as a drawer on narrow screens.

## Colors

The dark sidebar anchors the shell, while white cards and a pale-gray workspace keep readings legible. Blue marks actions and selected controls. Green means confirmed healthy, amber means caution or missing connection data, and red is reserved for incidents.

**The State-Color Rule.** Keep operational colors semantic; never use green to imply safety when a node is offline or data is missing.

## Typography

**Display Font:** Roboto (with Segoe UI, system-ui fallback)  
**Body Font:** Roboto (with Segoe UI, system-ui fallback)

**Character:** Neutral, compact sans-serif text supports quick scanning of room names and readings.

### Hierarchy
- **Headline** (500, 25px): Overview greeting and main page heading.
- **Title** (500, 18px): Room and section headings.
- **Body** (400, 14px, 1.5): Standard explanatory text.
- **Label** (400–600, 11–12px): Sensor captions, badges, and compact status text.

## Layout

A 256px desktop sidebar frames the workspace. The app header shows the current view plus realtime and node connectivity. The overview leads with the system status, followed by a three-column room grid; at narrower widths, the grid becomes two columns and then one. On mobile, the sidebar becomes a hamburger-triggered drawer and the room cards remain stacked in the main view.

Room details reuse the same card vocabulary for sensor readings, camera, history, and controls. Authentication uses a centered, compact form card.

## Elevation & Depth

The interface is mostly flat. Thin borders separate cards from the background; small shadows provide just enough separation to identify interactive cards. Hover elevation stays subtle. Focus outlines remain visible and distinct from selection.

## Shapes

Use compact 4px corners for controls and 6px corners for cards. Status chips may use a pill shape. Avoid oversized rounded panels and decorative gradients.

## Components

### Navigation
- **Sidebar:** Dark slate with light icons and labels; selected item uses a raised slate surface and blue leading marker.
- **Mobile:** Open the same navigation in a drawer; keep the room view itself full width.

### Room Cards
- **Content:** Room identity and connection state first, readings next, direct “Mở phòng” action last.
- **States:** Amber for unavailable connections or uncertain data; red attention treatment only for an active incident.

### Controls and Sensor Cards
- **Sensors:** Show the current measurement with its unit and a short label; preserve an explicit empty value when no reading is available.
- **Controls:** Keep existing toggles, sliders, camera mode buttons, and recovery actions. Use blue for primary controls and preserve disabled states when realtime is unavailable.

### Authentication
- **Fields:** White fill, neutral border, compact radius, and blue focus outline.
- **Primary action:** Blue button with white text.

## Do's and Don'ts

### Do:
- **Do** keep connectivity and safety state visible in the shared header and overview.
- **Do** organize content into compact cards and room views.
- **Do** preserve the existing device functions and server events.
- **Do** use explicit missing-data copy when devices are offline.

### Don't:
- **Don't** use Home Assistant logos or claim this product is Home Assistant.
- **Don't** show fabricated weather or sensor readings.
- **Don't** present unknown states as safe.
