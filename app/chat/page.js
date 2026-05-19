'use client';
import { useState, useEffect, useRef, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

const chatHistoryItems = [
  { id: 1, text: 'Attendance : Average Rate of attendi..' },
  { id: 2, text: 'Exam Rules: Academic Integrity' },
  { id: 3, text: 'Fee Policy : How to pay my uni fees?' },
  { id: 4, text: 'Refund Policy: Can I get a refund?' },
];

const faqChips = [
  'What is the academic integrity policy?',
  'How do I apply for special consideration?',
  'What is the late withdrawal policy?',
  'How do I appeal my grade?',
  'What are the HDR candidature requirements?',
  'What is the student attendance policy?',
];

function ChatContent() {
  const searchParams = useSearchParams();
  const role = searchParams.get('role') || 'student';

  const [messages, setMessages] = useState([
    { id: 1, sender: 'bot', text: 'Hi! Ask me anything about La Trobe University Policies.' }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [activeNav, setActiveNav] = useState('Chat');
  const [selectedHistory, setSelectedHistory] = useState(null);
  const [chatStarted, setChatStarted] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const messagesEndRef = useRef(null);
  const liveRegionRef = useRef(null);

  // ── Theme ────────────────────────────────────────────────────────────────────
  const t = {
    pageBg:              darkMode ? '#1a1a1a' : 'white',
    navBg:               darkMode ? '#1a1a1a' : 'white',
    navBorder:           darkMode ? '#333'    : '#eee',
    navText:             darkMode ? '#ffffff' : '#1a1a1a',
    navSubText:          darkMode ? '#aaaaaa' : '#444',
    sidebarBg:           darkMode ? '#2d2d2d' : 'white',
    sidebarItemBg:       darkMode ? '#3a3a3a' : 'white',
    sidebarItemBgSel:    darkMode ? '#4a1a20' : '#fff0f0',
    sidebarItemBorder:   darkMode ? '#555'    : '#d9d9d9',
    sidebarItemText:     darkMode ? '#ffffff' : '#1a1a1a',
    chatPanelBg:         darkMode ? '#2d2d2d' : 'white',
    bubbleBg:            darkMode ? '#3a3a3a' : 'white',
    bubbleBorder:        darkMode ? '#555'    : '#a0a0a0',
    bubbleText:          darkMode ? '#ffffff' : '#1a1a1a',
    disclaimerBg:        darkMode ? '#3a2e00' : '#fff8e1',
    disclaimerBorder:    darkMode ? '#5a4800' : '#ffe082',
    disclaimerText:      darkMode ? '#ffd54f' : '#7a6000',
    inputWrapBg:         darkMode ? '#1a1a1a' : 'white',
    inputWrapBorder:     darkMode ? '#444'    : '#eee',
    inputInnerBg:        darkMode ? '#3a3a3a' : '#f7f7f7',
    inputInnerBorder:    darkMode ? '#555'    : '#a0a0a0',
    inputText:           darkMode ? '#ffffff' : '#1a1a1a',
    faqChipBg:           darkMode ? '#3a1a20' : '#fff0f0',
    faqChipBorder:       darkMode ? 'rgba(200,16,46,0.45)' : 'rgba(200,16,46,0.25)',
    sourceExcerpt:       darkMode ? '#aaaaaa' : '#999',
    sourcesLabel:        darkMode ? '#777'    : '#999',
    loadingBubbleBg:     darkMode ? '#3a3a3a' : 'white',
    loadingBubbleBorder: darkMode ? '#555'    : '#a0a0a0',
    mobileFooterBg:      darkMode ? '#1a1a1a' : 'white',
    mobileFooterBorder:  darkMode ? '#333'    : '#eee',
    mobileNavBtnBg:      darkMode ? '#1a1a1a' : 'white',
    mobileNavLabelColor: darkMode ? '#aaaaaa' : '#666',
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (!loading) inputRef.current?.focus();
  }, [loading]);

  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.sender === 'bot' && liveRegionRef.current) {
      liveRegionRef.current.textContent = lastMsg.text;
    }
  }, [messages]);

  const handleSend = async (overrideText) => {
    const userText = (overrideText || inputValue).trim();
    if (userText === '' || loading) return;
    setChatStarted(true);
    setMessages(prev => [...prev, { id: prev.length + 1, sender: 'user', text: userText }]);
    setInputValue('');
    setLoading(true);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: userText })
      });
      const data = await response.json();
      setMessages(prev => [...prev, {
        id: prev.length + 1,
        sender: 'bot',
        text: data.answer || 'No answer found.',
        sources: data.citations || []
      }]);
    } catch (error) {
      setMessages(prev => [...prev, {
        id: prev.length + 1,
        sender: 'bot',
        text: ' Could not connect to the server. Please try again.',
        sources: []
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleChipClick = (question) => handleSend(question);

  const navItems = [
    {
      label: 'Home', icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          <polyline points="9 22 9 12 15 12 15 22" />
        </svg>
      )
    },
    {
      label: 'Chat', icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      )
    },
    {
      label: 'History', icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      )
    },
    {
      label: 'Profile', icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
      )
    },
  ];

  // Shared toggle button (rendered in both navbars)
  const ThemeToggle = ({ style = {} }) => (
    <button
      onClick={() => setDarkMode(d => !d)}
      aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
      title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
      style={{
        width: '40px',
        height: '40px',
        borderRadius: '50%',
        border: `2px solid ${darkMode ? '#555' : '#ddd'}`,
        backgroundColor: darkMode ? '#3a3a3a' : '#f5f5f5',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: '18px',
        flexShrink: 0,
        outline: 'none',
        transition: 'background-color 0.2s, border-color 0.2s',
        ...style,
      }}
      onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 3px rgba(200,16,46,0.35)'}
      onBlur={e => e.currentTarget.style.boxShadow = 'none'}
    >
      {darkMode ? '☀️' : '🌙'}
    </button>
  );

  return (
    <div style={{ backgroundColor: t.pageBg, minHeight: '100vh', display: 'flex', flexDirection: 'column', fontFamily: "'DM Sans', sans-serif", transition: 'background-color 0.2s' }}>

      {/* Screen reader live region */}
      <div
        ref={liveRegionRef}
        aria-live="polite"
        aria-atomic="true"
        style={{ position: 'absolute', width: '1px', height: '1px', padding: 0, margin: '-1px', overflow: 'hidden', clip: 'rect(0,0,0,0)', border: 0 }}
      />

      {/* ── TOP NAVBAR — DESKTOP ── */}
      <header className="hidden md:flex" style={{ backgroundColor: t.navBg, padding: '16px 60px', alignItems: 'center', gap: '24px', borderBottom: `1px solid ${t.navBorder}`, position: 'sticky', top: 0, zIndex: 10, transition: 'background-color 0.2s' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', flexShrink: 0 }}>
          <img src="/latrobe-logo.png" alt="La Trobe University" style={{ height: '80px', objectFit: 'contain' }} />
          <p style={{ fontSize: '12px', fontWeight: '500', color: t.navSubText, margin: '2px 0 0 0', paddingLeft: '4px' }}>Policy Chatbot</p>
        </div>
        <div style={{ flex: 1, margin: '0 16px' }}>
          <div style={{ border: '3px solid #C8102E', borderRadius: '8px', padding: '14px 24px', fontSize: '18px', fontWeight: '700', color: t.navText }}>
            Home
          </div>
        </div>
        {/* Theme toggle + avatar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
          <ThemeToggle />
          <div
            style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: '#C8102E', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', boxShadow: '0 4px 8px rgba(0,0,0,0.25)' }}
            role="img"
            aria-label="User profile: Yasiru"
          >
            <span style={{ color: 'white', fontWeight: '700', fontSize: '24px' }} aria-hidden="true">Y</span>
          </div>
        </div>
      </header>

      {/* ── TOP NAVBAR — MOBILE ── */}
      <header className="flex md:hidden" style={{ backgroundColor: t.navBg, padding: '16px 20px', flexDirection: 'column', alignItems: 'center', borderBottom: `1px solid ${t.navBorder}`, position: 'sticky', top: 0, zIndex: 10, transition: 'background-color 0.2s' }}>
        <div style={{ width: '100%', display: 'flex', justifyContent: 'flex-end', marginBottom: '4px' }}>
          <ThemeToggle />
        </div>
        <img src="/latrobe-logo.png" alt="La Trobe University" style={{ height: '90px', objectFit: 'contain' }} />
        <p style={{ fontSize: '13px', fontWeight: '500', color: t.navSubText, margin: '4px 0 8px 0', textAlign: 'center' }}>Policy Chatbot</p>
        <div style={{ height: '3px', backgroundColor: '#C8102E', width: '70%', borderRadius: '2px' }} />
      </header>

      {/* ── MAIN LAYOUT ── */}
      <main style={{ display: 'flex', flex: 1, width: '100%', maxWidth: '1440px', margin: '0 auto', padding: '24px 60px', gap: '24px', paddingBottom: '100px' }}>

        {/* ── SIDEBAR — desktop only ── */}
        <nav className="hidden md:flex" aria-label="Chat history" style={{ width: '315px', flexShrink: 0, backgroundColor: t.sidebarBg, borderRadius: '12px', border: '2.5px solid #C8102E', padding: '24px 20px', flexDirection: 'column', gap: '16px', height: 'fit-content', transition: 'background-color 0.2s' }}>
          <div style={{ textAlign: 'center' }}>
            <h2 style={{ fontSize: '18px', fontWeight: '700', color: t.navText, margin: '0 0 8px 0', fontFamily: "'DM Sans', sans-serif" }}>Chat History</h2>
            <div style={{ height: '2px', backgroundColor: '#C8102E', width: '60%', margin: '0 auto' }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '8px' }}>
            {chatHistoryItems.map(item => (
              <button
                key={item.id}
                onClick={() => setSelectedHistory(item.id)}
                aria-pressed={selectedHistory === item.id}
                style={{
                  textAlign: 'left', padding: '8px 16px', borderRadius: '8px',
                  border: `1.5px solid ${t.sidebarItemBorder}`,
                  backgroundColor: selectedHistory === item.id ? t.sidebarItemBgSel : t.sidebarItemBg,
                  fontSize: '13px', fontWeight: '500', color: t.sidebarItemText,
                  cursor: 'pointer', boxShadow: '0 2px 4px rgba(0,0,0,0.08)',
                  transition: 'all 0.2s', fontFamily: "'DM Sans', sans-serif",
                  outline: 'none',
                }}
                onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 3px rgba(200,16,46,0.3)'}
                onBlur={e => e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.08)'}
                onMouseOver={e => e.currentTarget.style.backgroundColor = t.sidebarItemBgSel}
                onMouseOut={e => e.currentTarget.style.backgroundColor = selectedHistory === item.id ? t.sidebarItemBgSel : t.sidebarItemBg}
              >
                {item.text}
              </button>
            ))}
          </div>
        </nav>

        {/* ── CHAT PANEL ── */}
        <section
          className="md:border-[2px] md:border-[#a0a0a0] md:shadow-md"
          aria-label="Chat conversation"
          style={{ flex: 1, backgroundColor: t.chatPanelBg, borderRadius: '12px', display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: '680px', transition: 'background-color 0.2s' }}
        >

          {/* Disclaimer */}
          <div role="note" style={{ backgroundColor: t.disclaimerBg, borderBottom: `1px solid ${t.disclaimerBorder}`, padding: '8px 20px', transition: 'background-color 0.2s' }}>
            <span style={{ fontSize: '12px', color: t.disclaimerText }}>Responses are based on official La Trobe policy documents. For legal advice, contact university staff.</span>
          </div>

          {/* Messages */}
          <div
            role="log"
            aria-label="Chat messages"
            aria-live="off"
            style={{ flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}
          >
            {messages.map((msg) => (
              <div key={msg.id}>

                {/* Bubble */}
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: msg.sender === 'user' ? 'flex-end' : 'flex-start', gap: '10px' }}>
                  {msg.sender === 'bot' && (
                    <div
                      role="img"
                      aria-label="La Trobe Policy Chatbot"
                      style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: '#CB0101', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.25)' }}
                    >
                      <span style={{ color: 'white', fontSize: '10px', fontWeight: '700' }} aria-hidden="true">LTU</span>
                    </div>
                  )}
                  <div
                    role={msg.sender === 'bot' ? 'article' : undefined}
                    aria-label={msg.sender === 'bot' ? 'Chatbot response' : 'Your message'}
                    style={{ maxWidth: '55%', minHeight: '48px', padding: '12px 16px', backgroundColor: t.bubbleBg, borderRadius: '8px', border: `2px solid ${t.bubbleBorder}`, fontSize: '13px', fontWeight: '500', color: t.bubbleText, lineHeight: '1.5', fontFamily: "'DM Sans', sans-serif", transition: 'background-color 0.2s, border-color 0.2s' }}
                  >
                    {msg.text}
                  </div>
                  {msg.sender === 'user' && (
                    <div
                      role="img"
                      aria-label="You"
                      style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: '#CB0101', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.25)' }}
                    >
                      <span style={{ color: 'white', fontSize: '13px', fontWeight: '700' }} aria-hidden="true">Y</span>
                    </div>
                  )}
                </div>

                {/* Source Citations — bot messages only */}
                {msg.sender === 'bot' && msg.sources && msg.sources.length > 0 && (
                  <div style={{ marginLeft: '42px', marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <span style={{ fontSize: '10px', fontWeight: '700', color: t.sourcesLabel, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Sources</span>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {msg.sources.map((source, si) => (
                        <div key={si}>
                          <a
                            href={source.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`Open policy document: ${source.title} (opens in new tab)`}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '5px',
                              fontSize: '11px',
                              fontWeight: '600',
                              color: 'white',
                              backgroundColor: '#C8102E',
                              borderRadius: '999px',
                              padding: '4px 12px',
                              textDecoration: 'none',
                              fontFamily: "'DM Sans', sans-serif",
                              outline: 'none',
                              boxShadow: 'none',
                              transition: 'background-color 0.15s',
                            }}
                            onMouseOver={e => e.currentTarget.style.backgroundColor = '#a00d24'}
                            onMouseOut={e => e.currentTarget.style.backgroundColor = '#C8102E'}
                            onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 3px rgba(200,16,46,0.4)'}
                            onBlur={e => e.currentTarget.style.boxShadow = 'none'}
                          >
                            <span style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{source.title}</span>
                            <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden="true" style={{ flexShrink: 0, opacity: 0.8 }}>
                              <path d="M5.5 1.5H8.5V4.5M8.5 1.5L4.5 5.5M3 2.5H1.5V8.5H7.5V7" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          </a>
                          {source.excerpt && (
                            <p style={{
                              margin: '4px 4px 0 4px',
                              fontSize: '11px',
                              fontStyle: 'italic',
                              color: t.sourceExcerpt,
                              lineHeight: '1.4',
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              overflow: 'hidden',
                              fontFamily: "'DM Sans', sans-serif",
                            }}>
                              {source.excerpt}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              </div>
            ))}

            {/* Loading Dots */}
            {loading && (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }} role="status" aria-label="Chatbot is typing">
                <div style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: '#CB0101', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }} aria-hidden="true">
                  <span style={{ color: 'white', fontSize: '10px', fontWeight: '700' }}>LTU</span>
                </div>
                <div style={{ backgroundColor: t.loadingBubbleBg, border: `2px solid ${t.loadingBubbleBorder}`, borderRadius: '8px', padding: '14px 18px', display: 'flex', gap: '5px', alignItems: 'center' }} aria-hidden="true">
                  {[0, 150, 300].map((delay, i) => (
                    <span key={i} className="animate-bounce" style={{ width: '8px', height: '8px', backgroundColor: '#CB0101', borderRadius: '50%', display: 'inline-block', animationDelay: `${delay}ms` }} />
                  ))}
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* ── FAQ CHIPS — only visible before chat starts ── */}
          {!chatStarted && (
            <div style={{ padding: '0 24px 16px 24px' }}>
              <p style={{ fontSize: '11px', fontWeight: '600', color: t.sourcesLabel, textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 10px 0' }} id="faq-label">Suggested questions</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }} role="group" aria-labelledby="faq-label">
                {faqChips.map((question, i) => (
                  <button
                    key={i}
                    onClick={() => handleChipClick(question)}
                    aria-label={`Ask: ${question}`}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '7px 14px', fontSize: '12px', fontWeight: '500', color: '#C8102E', backgroundColor: t.faqChipBg, border: `1.5px solid ${t.faqChipBorder}`, borderRadius: '20px', cursor: 'pointer', fontFamily: "'DM Sans', sans-serif", transition: 'all 0.15s', outline: 'none' }}
                    onMouseOver={e => { e.currentTarget.style.backgroundColor = darkMode ? '#5a1a25' : '#ffe0e5'; e.currentTarget.style.borderColor = '#C8102E'; }}
                    onMouseOut={e => { e.currentTarget.style.backgroundColor = t.faqChipBg; e.currentTarget.style.borderColor = t.faqChipBorder; }}
                    onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 3px rgba(200,16,46,0.3)'}
                    onBlur={e => e.currentTarget.style.boxShadow = 'none'}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <circle cx="12" cy="12" r="10" />
                      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                      <line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                    {question}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Input */}
          <div style={{ padding: '16px 24px', borderTop: `1px solid ${t.inputWrapBorder}`, backgroundColor: t.inputWrapBg, transition: 'background-color 0.2s' }}>
            <div style={{ display: 'flex', alignItems: 'center', backgroundColor: t.inputInnerBg, border: inputFocused ? '2px solid #C8102E' : `2px solid ${t.inputInnerBorder}`, borderRadius: '8px', overflow: 'hidden', transition: 'border-color 0.2s, background-color 0.2s' }}>
              <label htmlFor="chat-input" style={{ position: 'absolute', width: '1px', height: '1px', padding: 0, margin: '-1px', overflow: 'hidden', clip: 'rect(0,0,0,0)', border: 0 }}>
                Type your policy question
              </label>
              <input
                id="chat-input"
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => setInputFocused(true)}
                onBlur={() => setInputFocused(false)}
                placeholder="Ask a question........."
                maxLength={500}
                aria-label="Type your policy question"
                aria-describedby="char-count"
                disabled={loading}
                style={{ flex: 1, height: '56px', backgroundColor: 'transparent', padding: '0 20px', fontSize: '13px', fontWeight: '500', color: t.inputText, outline: 'none', border: 'none', fontFamily: "'DM Sans', sans-serif" }}
              />
              {inputValue.length > 400 && (
                <span id="char-count" style={{ fontSize: '11px', color: inputValue.length > 480 ? '#C8102E' : t.sourcesLabel, padding: '0 8px', flexShrink: 0 }} aria-live="polite">
                  {500 - inputValue.length}
                </span>
              )}
              <button
                onClick={() => handleSend()}
                disabled={loading || !inputValue.trim()}
                aria-label="Send message"
                style={{ width: '60px', height: '56px', backgroundColor: loading || !inputValue.trim() ? (darkMode ? '#444' : '#e0e0e0') : '#CB0101', border: 'none', cursor: loading || !inputValue.trim() ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'all 0.2s', outline: 'none' }}
                onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 3px rgba(200,16,46,0.3)'}
                onBlur={e => e.currentTarget.style.boxShadow = 'none'}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>

        </section>
      </main>

      {/* ── MOBILE FOOTER MENU ── */}
      <nav className="flex md:hidden" aria-label="Main navigation" style={{ position: 'fixed', bottom: 0, left: 0, right: 0, backgroundColor: t.mobileFooterBg, borderTop: `1px solid ${t.mobileFooterBorder}`, padding: '8px 0 12px', justifyContent: 'space-around', zIndex: 20, transition: 'background-color 0.2s' }}>
        {navItems.map(item => (
          <button
            key={item.label}
            onClick={() => setActiveNav(item.label)}
            aria-label={item.label}
            aria-current={activeNav === item.label ? 'page' : undefined}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', background: 'none', border: 'none', cursor: 'pointer', padding: '6px 16px', borderRadius: '10px', backgroundColor: activeNav === item.label ? '#C8102E' : t.mobileNavBtnBg, boxShadow: activeNav === item.label ? '0 4px 8px rgba(0,0,0,0.2)' : 'none', transition: 'all 0.2s', outline: 'none' }}
            onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 3px rgba(200,16,46,0.3)'}
            onBlur={e => e.currentTarget.style.boxShadow = activeNav === item.label ? '0 4px 8px rgba(0,0,0,0.2)' : 'none'}
          >
            <span style={{ color: activeNav === item.label ? 'white' : t.mobileNavLabelColor }}>{item.icon}</span>
            <span style={{ fontSize: '10px', fontWeight: '500', color: activeNav === item.label ? 'white' : t.mobileNavLabelColor, fontFamily: "'DM Sans', sans-serif" }}>{item.label}</span>
          </button>
        ))}
      </nav>

    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: "'DM Sans', sans-serif" }} role="status" aria-label="Loading">Loading...</div>}>
      <ChatContent />
    </Suspense>
  );
}
