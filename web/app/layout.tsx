import './style.css';
import AccountGate from '@/components/AccountGate';
import ThemeToggle from '@/components/ThemeToggle';
import type { Metadata } from 'next';
export const metadata: Metadata = {
  title: 'ReelNotes',
  description: 'Evidence-linked coding guides from your Reel playlists',
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en" suppressHydrationWarning><head>
    <link id="theme-icon" rel="icon" type="image/svg+xml" href="/reelnotes-favicon.svg" suppressHydrationWarning />
    <script dangerouslySetInnerHTML={{ __html: `(function(){var t;try{t=localStorage.getItem('reelnotes-theme')}catch(e){}if(t!=='dark'&&t!=='light')t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';document.documentElement.dataset.theme=t;var i=document.getElementById('theme-icon');if(i)i.href=t==='dark'?'/reelnotes-favicon-dark.svg':'/reelnotes-favicon.svg';})();` }} />
  </head><body>
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="site-header"><div className="header-inner">
      <a className="brand" href="/" aria-label="ReelNotes home"><img className="logo-light" src="/reelnotes-logo.svg" width="179" height="40" alt="ReelNotes" /><img className="logo-dark" src="/reelnotes-logo-dark.svg" width="179" height="40" alt="ReelNotes" /></a>
      <nav aria-label="Main navigation"><ThemeToggle /><a href="/">Playlists <span aria-hidden="true">↗</span></a></nav>
    </div></header>
    <main id="main"><AccountGate>{children}</AccountGate></main>
    <footer className="site-footer"><span>ReelNotes</span><span>From saved advice to working instructions.</span></footer>
  </body></html>;
}
