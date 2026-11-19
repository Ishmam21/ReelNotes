'use client';

import { useEffect, useState } from 'react';

type Theme = 'light' | 'dark';

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  const icon = document.getElementById('theme-icon') as HTMLLinkElement | null;
  if (icon) icon.href = theme === 'dark' ? '/reelnotes-favicon-dark.svg' : '/reelnotes-favicon.svg';
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>('light');

  useEffect(() => {
    const system = window.matchMedia('(prefers-color-scheme: dark)');
    let saved: string | null = null;
    try { saved = localStorage.getItem('reelnotes-theme'); } catch { /* Storage can be unavailable. */ }
    const initial = saved === 'light' || saved === 'dark' ? saved : system.matches ? 'dark' : 'light';
    applyTheme(initial);
    setTheme(initial);
    const followSystem = (event: MediaQueryListEvent) => {
      let preference: string | null = null;
      try { preference = localStorage.getItem('reelnotes-theme'); } catch { /* Follow the system if storage is unavailable. */ }
      if (preference !== 'light' && preference !== 'dark') {
        const next = event.matches ? 'dark' : 'light';
        applyTheme(next);
        setTheme(next);
      }
    };
    system.addEventListener('change', followSystem);
    return () => system.removeEventListener('change', followSystem);
  }, []);

  return <button className="theme-toggle" type="button" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'night'} mode`} aria-pressed={theme === 'dark'} onClick={() => {
    const next = theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    setTheme(next);
    try { localStorage.setItem('reelnotes-theme', next); } catch { /* Theme still works without persistence. */ }
  }}><svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">{theme === 'dark' ? <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></> : <path d="M20.5 14a8.5 8.5 0 0 1-10.5-10.5A8.5 8.5 0 1 0 20.5 14Z"/>}</svg><span>{theme === 'dark' ? 'Light mode' : 'Night mode'}</span></button>;
}
