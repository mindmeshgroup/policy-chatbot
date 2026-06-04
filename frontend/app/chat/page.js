'use client';
import { useState, useEffect, useRef, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

const chatHistoryItems = [
  { id: 1, text: 'Attendance : Average Rate of attendi..' },
  { id: 2, text: 'Exam Rules: Academic Integrity' },
  { id: 3, text: 'Fee Policy : How to pay my uni fees?' },
  { id: 4, text: 'Refund Policy: Can I get a refund?' },
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
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (!loading) inputRef.current?.focus();
  }, [loading]);

  const handleSend = () => {
    if (inputValue.trim() === '' || loading) return;
    const userText = inputValue.trim();
    setMessages(prev => [...prev, { id: prev.length + 1, sender: 'user', text: userText }]);
    setInputValue('');
    setLoading(true);
    setTimeout(() => {
      setMessages(prev => [...prev, {
        id: prev.length + 1,
        sender: 'bot',
        text: 'This is a placeholder response. Backend coming soon!',
        sources: ['Academic Policy 2024, Page 3', 'Student Handbook 2024']
      }]);
      setLoading(false);
    }, 2000);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSend();
  };

  const navItems = [
    { label: 'Home', icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
        <polyline points="9 22 9 12 15 12 15 22"/>
      </svg>
    )},
    { label: 'Chat', icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
    )},
    { label: 'History', icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <polyline points="12 6 12 12 16 14"/>
      </svg>
    )},
    { label: 'Profile', icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
        <circle cx="12" cy="7" r="4"/>
      </svg>
    )},
  ];

  return (
    <div style={{ backgroundColor: '#f5f5f5', minHeight: '100vh', display: 'flex', flexDirection: 'column', fontFamily: "'DM Sans', sans-serif" }}>

      {/* ── TOP NAVBAR ── */}
      <div style={{ backgroundColor: 'white', padding: '16px 60px', display: 'flex', alignItems: 'center', gap: '24px', borderBottom: '1px solid #eee', position: 'sticky', top: 0, zIndex: 10 }}>

        {/* Logo + Policy Chatbot label */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', flexShrink: 0 }}>
          <img src="/latrobe-logo.png" alt="La Trobe" style={{ height: '80px', objectFit: 'contain' }} />
          <p style={{ fontSize: '12px', fontWeight: '500', color: '#444', margin: '2px 0 0 0', paddingLeft: '4px' }}>Policy Chatbot</p>
        </div>

        {/* Home bar — desktop only */}
        <div className="hidden md:block" style={{ flex: 1, margin: '0 16px' }}>
          <div style={{ border: '3px solid #C8102E', borderRadius: '8px', padding: '14px 24px', fontSize: '18px', fontWeight: '700', color: '#1a1a1a' }}>
            Home
          </div>
        </div>

        {/* Spacer for mobile */}
        <div className="block md:hidden" style={{ flex: 1 }} />

        {/* Y Avatar */}
        <div style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: '#C8102E', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0, boxShadow: '0 4px 8px rgba(0,0,0,0.25)' }}>
          <span style={{ color: 'white', fontWeight: '700', fontSize: '24px' }}>Y</span>
        </div>
      </div>

      {/* ── MAIN LAYOUT ── */}
      <div style={{ display: 'flex', flex: 1, width: '100%', maxWidth: '1440px', margin: '0 auto', padding: '24px 60px', gap: '24px', paddingBottom: '100px' }}>

        {/* ── SIDEBAR — desktop only ── */}
        <div className="hidden md:flex" style={{ width: '315px', flexShrink: 0, backgroundColor: 'white', borderRadius: '12px', border: '2.5px solid #C8102E', padding: '24px 20px', flexDirection: 'column', gap: '16px', height: 'fit-content' }}>
          <div style={{ textAlign: 'center' }}>
            <h2 style={{ fontSize: '18px', fontWeight: '700', color: '#1a1a1a', margin: '0 0 8px 0', fontFamily: "'DM Sans', sans-serif" }}>Chat History</h2>
            <div style={{ height: '2px', backgroundColor: '#C8102E', width: '60%', margin: '0 auto' }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '8px' }}>
            {chatHistoryItems.map(item => (
              <button
                key={item.id}
                onClick={() => setSelectedHistory(item.id)}
                style={{
                  textAlign: 'left', padding: '8px 16px', borderRadius: '8px',
                  border: '1.5px solid #d9d9d9',
                  backgroundColor: selectedHistory === item.id ? '#fff0f0' : 'white',
                  fontSize: '13px', fontWeight: '500', color: '#1a1a1a',
                  cursor: 'pointer', boxShadow: '0 2px 4px rgba(0,0,0,0.08)',
                  transition: 'all 0.2s', fontFamily: "'DM Sans', sans-serif"
                }}
                onMouseOver={e => e.currentTarget.style.backgroundColor = '#fff0f0'}
                onMouseOut={e => e.currentTarget.style.backgroundColor = selectedHistory === item.id ? '#fff0f0' : 'white'}
              >
                {item.text}
              </button>
            ))}
          </div>
        </div>

        {/* ── CHAT PANEL ── */}
        <div style={{ flex: 1, backgroundColor: 'white', borderRadius: '12px', border: '2px solid #a0a0a0', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: '680px' }}>

          {/* Disclaimer */}
          <div style={{ backgroundColor: '#fff8e1', borderBottom: '1px solid #ffe082', padding: '8px 20px' }}>
            <span style={{ fontSize: '12px', color: '#7a6000' }}>⚠️ Responses are based on official La Trobe policy documents. For legal advice, contact university staff.</span>
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {messages.map((msg) => (
              <div key={msg.id}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: msg.sender === 'user' ? 'flex-end' : 'flex-start', gap: '10px' }}>
                  {msg.sender === 'bot' && (
                    <div style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: '#CB0101', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.25)' }}>
                      <span style={{ color: 'white', fontSize: '10px', fontWeight: '700' }}>LTU</span>
                    </div>
                  )}
                  <div style={{
                    maxWidth: '55%', minHeight: '48px', padding: '12px 16px',
                    backgroundColor: 'white', borderRadius: '8px',
                    border: '2px solid #a0a0a0', fontSize: '13px',
                    fontWeight: '500', color: '#1a1a1a', lineHeight: '1.5',
                    fontFamily: "'DM Sans', sans-serif"
                  }}>
                    {msg.text}
                  </div>
                  {msg.sender === 'user' && (
                    <div style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: '#CB0101', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.25)' }}>
                      <span style={{ color: 'white', fontSize: '13px', fontWeight: '700' }}>Y</span>
                    </div>
                  )}
                </div>
                {/* Source Citations */}
                {msg.sources && (
                  <div style={{ marginLeft: msg.sender === 'bot' ? '42px' : '0', marginTop: '6px', display: 'flex', flexWrap: 'wrap', gap: '6px', justifyContent: msg.sender === 'user' ? 'flex-end' : 'flex-start' }}>
                    {msg.sources.map((source, si) => (
                      <span key={si} style={{ fontSize: '11px', backgroundColor: '#fff0f0', color: '#C8102E', border: '1px solid #ffcccc', borderRadius: '12px', padding: '2px 10px' }}>
                        📄 {source}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {/* Loading Dots */}
            {loading && (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: '#CB0101', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <span style={{ color: 'white', fontSize: '10px', fontWeight: '700' }}>LTU</span>
                </div>
                <div style={{ backgroundColor: 'white', border: '2px solid #a0a0a0', borderRadius: '8px', padding: '14px 18px', display: 'flex', gap: '5px', alignItems: 'center' }}>
                  {[0, 150, 300].map((delay, i) => (
                    <span key={i} className="animate-bounce" style={{ width: '8px', height: '8px', backgroundColor: '#CB0101', borderRadius: '50%', display: 'inline-block', animationDelay: `${delay}ms` }} />
                  ))}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div style={{ padding: '16px 24px', borderTop: '1px solid #eee', backgroundColor: 'white' }}>
            <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#f7f7f7', border: '2px solid #a0a0a0', borderRadius: '8px', overflow: 'hidden' }}>
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question........."
                maxLength={500}
                style={{ flex: 1, height: '56px', backgroundColor: 'transparent', padding: '0 20px', fontSize: '13px', fontWeight: '500', color: '#1a1a1a', outline: 'none', border: 'none', fontFamily: "'DM Sans', sans-serif" }}
              />
              <button
                onClick={handleSend}
                disabled={loading || !inputValue.trim()}
                style={{ width: '60px', height: '56px', backgroundColor: loading || !inputValue.trim() ? '#e0e0e0' : '#CB0101', border: 'none', cursor: loading || !inputValue.trim() ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'all 0.2s' }}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13"/>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── MOBILE FOOTER MENU ── */}
      <div className="flex md:hidden" style={{ position: 'fixed', bottom: 0, left: 0, right: 0, backgroundColor: 'white', borderTop: '1px solid #eee', padding: '8px 0 12px', justifyContent: 'space-around', zIndex: 20 }}>
        {navItems.map(item => (
          <button
            key={item.label}
            onClick={() => setActiveNav(item.label)}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', background: 'none', border: 'none', cursor: 'pointer', padding: '6px 16px', borderRadius: '10px', backgroundColor: activeNav === item.label ? '#C8102E' : 'white', boxShadow: activeNav === item.label ? '0 4px 8px rgba(0,0,0,0.2)' : 'none', transition: 'all 0.2s' }}
          >
            <span style={{ color: activeNav === item.label ? 'white' : '#666' }}>{item.icon}</span>
            <span style={{ fontSize: '10px', fontWeight: '500', color: activeNav === item.label ? 'white' : '#666', fontFamily: "'DM Sans', sans-serif" }}>{item.label}</span>
          </button>
        ))}
      </div>

    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: "'DM Sans', sans-serif" }}>Loading...</div>}>
      <ChatContent />
    </Suspense>
  );
}