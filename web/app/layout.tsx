import './style.css';
import type { Metadata } from 'next';
export const metadata: Metadata = {title:'ReelNotes',description:'Evidence-linked coding guides from your Reel playlists'};
export default function Layout({children}:{children:React.ReactNode}) {return <html lang="en"><body><header><a href="/">ReelNotes</a><span>Local coding guides</span></header><main>{children}</main></body></html>}
