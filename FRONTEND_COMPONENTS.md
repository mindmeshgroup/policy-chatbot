# Frontend Component Documentation

All UI lives in two page files — `app/page.js` (Login) and `app/chat/page.js` (Chat). There is no separate `components/` directory; all sub-components are defined and used within these files.

---

## `app/layout.js` — RootLayout

The Next.js root layout. Wraps every page.

**Responsibilities:**
- Imports DM Sans font weights (400 and 700) from `@fontsource`
- Imports `globals.css`
- Sets page `<title>` and `<meta description>` via Next.js `metadata` export
- Renders `<html lang="en">` and `<body>` shell

```js
export const metadata = {
  title: "PolicyDB Chatbot",
  description: "La Trobe University Policy Chatbot by MindMesh Group",
};
```

---

## `app/page.js` — LoginPage

**Route:** `/`

The role selection screen shown before entering the chat.

**Behaviour:**
- Renders two buttons: **I'M A STUDENT** and **I'M A STAFF**
- On click, uses `useRouter().push()` to navigate to `/chat?role=student` or `/chat?role=staff`
- Marked `'use client'` because it uses `useRouter`

**Visual:**
- Full-screen La Trobe red-to-maroon gradient background
- White card with logo, title, and role selection panel
- "Powered by: MindMesh Group." footer inside the card

---

## `app/chat/page.js`

Contains three exports/components: `ChatPage`, `ChatContent`, and `ThemeToggle`.

---

### `ChatPage` (default export)

**Route:** `/chat`

A thin wrapper that wraps `ChatContent` in a `<Suspense>` boundary. This is required because `ChatContent` uses `useSearchParams()`, which needs Suspense in Next.js App Router.

```js
export default function ChatPage() {
  return (
    <Suspense fallback={<div role="status" aria-label="Loading">Loading...</div>}>
      <ChatContent />
    </Suspense>
  );
}
```

---

### `ChatContent`

The main component. Contains all chat state and renders the full page layout.

#### Props
None — reads role from URL via `useSearchParams()`.

#### State

| State | Type | Default | Description |
|---|---|---|---|
| `messages` | `Array` | `[bot greeting]` | All chat messages displayed in the conversation |
| `inputValue` | `string` | `''` | Current value of the text input field |
| `loading` | `boolean` | `false` | True while waiting for a backend response |
| `activeNav` | `string` | `'Chat'` | Active item in the mobile bottom navigation |
| `selectedHistory` | `number\|null` | `null` | ID of the selected sidebar history item |
| `chatStarted` | `boolean` | `false` | Becomes true after the first message is sent; hides FAQ chips |
| `inputFocused` | `boolean` | `false` | True when the text input has focus; controls border highlight |
| `darkMode` | `boolean` | `false` | Toggles dark/light theme across the whole page |

#### Refs

| Ref | Attached to | Purpose |
|---|---|---|
| `bottomRef` | Empty `<div>` at end of message list | Auto-scrolls to latest message |
| `inputRef` | Text `<input>` | Re-focuses input after bot responds |
| `liveRegionRef` | Hidden `<div aria-live>` | Pushes bot responses to screen readers |

#### Effects

| Effect | Dependency | Behaviour |
|---|---|---|
| Scroll to bottom | `messages`, `loading` | Calls `scrollIntoView` on `bottomRef` |
| Refocus input | `loading` | Focuses the input field when loading ends |
| Live region update | `messages` | Writes latest bot message text to the ARIA live region |

#### Accent Colours

Derived from the `role` query param:

```js
const accent      = isStaff ? '#8B0000' : '#C8102E';
const accentDark  = isStaff ? '#6B0000' : '#CB0101';
const accentHover = isStaff ? '#6B0000' : '#a00d24';
```

#### Theme Object (`t`)

A flat object of ~25 CSS colour tokens that switch between light/dark mode and student/staff themes. Every colour used in inline styles references a key from `t` rather than hardcoding values. This keeps all theming centralised.

---

#### `handleSend(overrideText?)`

Sends a question to the backend and appends the response to the message list.

**Flow:**
1. Validates the input is not empty and not already loading
2. Sets `chatStarted = true` (hides FAQ chips)
3. Appends user message to `messages`
4. Clears `inputValue`, sets `loading = true`
5. POSTs to `NEXT_PUBLIC_API_URL/ask` with `{ question, role }`
6. On success: appends bot message with `text` and `sources` (citations)
7. On error: appends a connection error message
8. Always sets `loading = false` in `finally`

**Called by:** send button click, Enter keypress, FAQ chip click.

---

#### `handleKeyDown(e)`

Intercepts Enter key on the input to trigger `handleSend()`. Shift+Enter is ignored (allows future multi-line support).

---

#### `handleChipClick(question)`

Calls `handleSend(question)` directly, bypassing the input field. Used by FAQ chips.

---

### `ThemeToggle`

An inline sub-component defined inside `ChatContent`.

**Purpose:** Renders a circular button that toggles `darkMode` state. Shows a sun icon in dark mode, moon icon in light mode.

**Props:**

| Prop | Type | Default | Description |
|---|---|---|---|
| `style` | `object` | `{}` | Additional inline styles merged into the button |

**Accessibility:** Has `aria-label` that updates based on current mode (`"Switch to light mode"` / `"Switch to dark mode"`). Both SVG icons are `aria-hidden="true"`.

---

## Layout Structure

```
<div> (page wrapper)
  <div aria-live="polite" />          ← screen reader live region (invisible)

  <header> (desktop navbar)           ← hidden on mobile (md:flex)
    <img> logo
    <div> "Home" breadcrumb bar
    <ThemeToggle />
    <div> user avatar

  <header> (mobile navbar)            ← hidden on desktop (flex md:hidden)
    <ThemeToggle />
    <img> logo
    <div> accent underline bar

  <main>
    <nav> (sidebar)                   ← desktop only (hidden md:flex)
      "Chat History" heading
      [chatHistoryItems buttons]

    <section> (chat panel)
      <div role="note"> disclaimer
      <div role="log"> message list
        [message bubbles]
        [source citations per bot message]
        [loading dots]
      <div> FAQ chips (hidden after first send)
      <div> input bar
        <input id="chat-input">
        <button> send

  <nav> (mobile footer)               ← mobile only (flex md:hidden)
    [Home, Chat, History, Profile buttons]
```

---

## Static Data

Defined as module-level constants in `app/chat/page.js`:

### `chatHistoryItems`

Placeholder chat history shown in the sidebar. Currently static — not fetched from any API.

```js
const chatHistoryItems = [
  { id: 1, text: 'Attendance : Average Rate of attendi..' },
  { id: 2, text: 'Exam Rules: Academic Integrity' },
  { id: 3, text: 'Fee Policy : How to pay my uni fees?' },
  { id: 4, text: 'Refund Policy: Can I get a refund?' },
];
```

### `faqChips`

Suggested questions displayed before the user starts chatting. Clicking one sends it immediately.

```js
const faqChips = [
  'What is the academic integrity policy?',
  'How do I apply for special consideration?',
  'What is the late withdrawal policy?',
  'How do I appeal my grade?',
  'What are the HDR candidature requirements?',
  'What is the student attendance policy?',
];
```

---

## Message Object Shape

Each entry in the `messages` state array:

```js
{
  id: number,           // incremental, used as React key
  sender: 'user' | 'bot',
  text: string,         // message body
  sources: [            // only present on bot messages, may be empty array
    {
      title: string,
      url: string,
      breadcrumb: string,
      escalation_contact: string,
      excerpt: string,
    }
  ]
}
```

---

## Responsive Behaviour

| Element | Mobile | Desktop |
|---|---|---|
| Top navbar | Centered logo + accent bar | Logo left, breadcrumb center, avatar right |
| Sidebar | Hidden | Visible (315px fixed width) |
| Chat panel padding | `24px` | `60px` horizontal |
| Bottom nav | Fixed footer (4 tabs) | Hidden |
| Staff badge | Shown below logo | Shown inside breadcrumb bar |
