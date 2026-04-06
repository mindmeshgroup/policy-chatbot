'use client';
import { useState } from 'react';

export default function Home() {
  const [messages, setMessages] = useState([
    { role: 'assistant', text: 'Hi! Ask me anything about La Trobe University policies.' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const sendMessage = () => {
    if (!input.trim()) return;
    setMessages([...messages, { role: 'user', text: input }]);
    setInput('');
    setLoading(true);
    setTimeout(() => {
      setMessages(prev => [...prev, { role: 'assistant', text: 'This is a placeholder response. Backend coming soon!' }]);
      setLoading(false);
    }, 2000);
  };

  return (
    <div style={{ backgroundColor: '#f5f5f5', minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>

      {/* Card Container */}
      <div style={{ width: '100%', maxWidth: '780px', backgroundColor: 'white', borderRadius: '20px', boxShadow: '0 8px 40px rgba(0,0,0,0.12)', overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '85vh' }}>

        {/* Header */}
        <div style={{ backgroundColor: '#C8102E', padding: '20px 28px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <img
            src="/latrobe-logo.png"
            alt="La Trobe Logo"
            style={{ height: '40px', objectFit: 'contain', filter: 'brightness(0) invert(1)' }}
          />
          <div>
            <h1 style={{ color: 'white', fontSize: '18px', fontWeight: '700', margin: 0 }}>Policy Chatbot</h1>
            <p style={{ color: 'rgba(255,255,255,0.8)', fontSize: '12px', margin: 0 }}>Ask questions about La Trobe University policies - Developed by Mind Mesh Group</p>
          </div>
          <div style={{ marginLeft: 'auto', backgroundColor: 'rgba(255,255,255,0.2)', borderRadius: '20px', padding: '4px 12px' }}>
            <span style={{ color: 'white', fontSize: '11px' }}>● Online</span>
          </div>
        </div>

        {/* Disclaimer Banner */}
        <div style={{ backgroundColor: '#fff8e1', borderBottom: '1px solid #ffe082', padding: '8px 28px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '13px', color: '#7a6000' }}>⚠️ Responses are based on official La Trobe policy documents. For legal advice, contact university staff.</span>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px', display: 'flex', flexDirection: 'column', gap: '16px', backgroundColor: '#fafafa' }}>
          {messages.map((msg, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start', alignItems: 'flex-end', gap: '8px' }}>

              {/* Bot Avatar */}
              {msg.role === 'assistant' && (
                <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: '#C8102E', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <span style={{ color: 'white', fontSize: '14px' }}>L</span>
                </div>
              )}

              <div style={{
                maxWidth: '65%',
                padding: '12px 16px',
                borderRadius: msg.role === 'user' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                backgroundColor: msg.role === 'user' ? '#C8102E' : 'white',
                color: msg.role === 'user' ? 'white' : '#1a1a1a',
                fontSize: '14px',
                lineHeight: '1.5',
                boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
                border: msg.role === 'assistant' ? '1px solid #eee' : 'none'
              }}>
                {msg.text}
              </div>

              {/* User Avatar */}
              {msg.role === 'user' && (
                <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: '#1a1a1a', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <span style={{ color: 'white', fontSize: '14px' }}>Y</span>
                </div>
              )}
            </div>
          ))}

          {/* Loading Dots */}
          {loading && (
            <div style={{ display: 'flex', justifyContent: 'flex-start', alignItems: 'flex-end', gap: '8px' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: '#C8102E', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ color: 'white', fontSize: '14px' }}>L</span>
              </div>
              <div style={{ backgroundColor: 'white', border: '1px solid #eee', borderRadius: '18px 18px 18px 4px', padding: '14px 18px', boxShadow: '0 1px 4px rgba(0,0,0,0.08)', display: 'flex', gap: '5px', alignItems: 'center' }}>
                {[0, 150, 300].map((delay, i) => (
                  <span key={i} className="animate-bounce" style={{ width: '8px', height: '8px', backgroundColor: '#C8102E', borderRadius: '50%', display: 'inline-block', animationDelay: `${delay}ms` }}></span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Input Area */}
        <div style={{ padding: '16px 28px', backgroundColor: 'white', borderTop: '1px solid #eee', display: 'flex', gap: '12px', alignItems: 'center' }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            placeholder="Ask a policy question..."
            style={{ flex: 1, border: '1.5px solid #e0e0e0', borderRadius: '25px', padding: '12px 20px', fontSize: '14px', outline: 'none', backgroundColor: '#fafafa' }}
          />
          <button
            onClick={sendMessage}
            disabled={loading}
            style={{ backgroundColor: loading ? '#e0e0e0' : '#C8102E', color: 'white', border: 'none', borderRadius: '25px', padding: '12px 24px', fontSize: '14px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer', transition: 'all 0.2s' }}
          >
            Send
          </button>
        </div>

        {/* Footer */}
        <div style={{ backgroundColor: '#1a1a1a', padding: '8px 28px', textAlign: 'center' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: '11px' }}>La Trobe University Policy Chatbot · For official use only</span>
        </div>

      </div>
    </div>
  );
}