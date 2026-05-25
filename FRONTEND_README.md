# Frontend — PolicyDB Chatbot

La Trobe University Policy Chatbot frontend built with Next.js 16, React 19, and Tailwind CSS v4.

---

## Tech Stack

| Technology | Version | Purpose |
|---|---|---|
| Next.js | 16.1.7 | React framework, App Router, SSR |
| React | 19.2.3 | UI library |
| Tailwind CSS | v4 | Utility-first styling |
| DM Sans | @fontsource/dm-sans | Primary typeface |

---

## Project Structure

```
policy-chatbot/
├── app/
│   ├── layout.js          # Root layout — font imports, metadata, <html> shell
│   ├── globals.css        # Global styles — Tailwind import, box-sizing, body reset
│   ├── page.js            # Login page — role selection (Student / Staff)
│   ├── favicon.ico
│   └── chat/
│       └── page.js        # Chat page — full chatbot UI
├── public/
│   └── latrobe-logo.png   # La Trobe University logo
├── next.config.mjs        # Next.js config
├── package.json
└── postcss.config.js      # Tailwind/PostCSS config
```

---

## Pages

### `/` — Login Page (`app/page.js`)

The entry point. Asks the user to identify their role before entering the chat.

- Two buttons: **I'M A STUDENT** and **I'M A STAFF**
- Clicking either navigates to `/chat?role=student` or `/chat?role=staff`
- The `role` query param controls the entire chat experience (colours, labels, sidebar theme)

### `/chat` — Chat Page (`app/chat/page.js`)

The main chatbot interface. Reads the `?role=` query parameter on load.

---

## Getting Started

### Prerequisites

- Node.js 18+
- Backend running on `http://localhost:8000` (FastAPI)

### Install dependencies

```bash
npm install
```

### Environment variable

Create a `.env.local` file in the project root:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

This tells the frontend where the backend API is. Without it, the `/ask` fetch will fail silently.

### Run development server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Build for production

```bash
npm run build
npm run start
```

---

## Role System

The app supports two roles, selected on the login page and passed as a URL query parameter:

| Role | URL | Accent Colour | Sidebar | Staff Badge |
|---|---|---|---|---|
| Student | `/chat?role=student` | La Trobe Red `#C8102E` | White / dark | Hidden |
| Staff | `/chat?role=staff` | Deep Maroon `#8B0000` | Deep red | Shown |

The role is also sent in every API request body (`"role": "Student"` or `"role": "Staff"`) so the backend retrieval layer can apply role-aware filtering.

---

## Dark Mode

A toggle button in the top navbar switches between light and dark mode. This is managed entirely in React state (`useState`) — no localStorage persistence between sessions. All theme values are defined in the `t` object inside `ChatContent`.

---

## API Integration

The chat page sends requests to the backend `/ask` endpoint:

```js
fetch(`${process.env.NEXT_PUBLIC_API_URL}/ask`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ question: userText, role: isStaff ? 'Staff' : 'Student' })
})
```

**Expected response shape:**

```json
{
  "answer": "string",
  "is_fallback": false,
  "citations": [
    {
      "title": "Policy Document Title",
      "url": "https://policies.latrobe.edu.au/...",
      "breadcrumb": "Policy > Section > Sub-section",
      "escalation_contact": "Contact info",
      "excerpt": "Short excerpt from the policy..."
    }
  ]
}
```

---

## Accessibility

The frontend is built with accessibility as a first-class concern:

- Screen reader live region (`aria-live="polite"`) announces each bot response
- All interactive elements have `aria-label` attributes
- Chat message log uses `role="log"`
- Loading indicator uses `role="status"` with `aria-label="Chatbot is typing"`
- Input field has a visually hidden `<label>` linked via `htmlFor`
- Character countdown is announced via `aria-live="polite"`
- All focus states have visible ring outlines using the accent colour
- Mobile nav buttons use `aria-current="page"` for the active item

---

## Known Limitations

- Chat history in the sidebar is static placeholder data — it is not persisted or fetched from a backend
- Dark mode preference resets on page refresh (no localStorage)
- The user avatar shows a hardcoded initial "Y" — not connected to authentication
- Mobile nav tabs (Home, History, Profile) are visual only — only Chat is functional
