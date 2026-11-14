'use client';
import {useEffect,useState} from 'react';
import {request,post} from '@/lib/api';
type Item={id:string;name:string;item_count:number};
export default function Home(){const [items,setItems]=useState<Item[]>([]),[name,setName]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
useEffect(()=>{request<Item[]>('/playlists').then(setItems).catch(e=>setError(e.message))},[]);
return <><h1>Your playlists</h1><form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{const p=await request<Item>('/playlists',post({name}));window.location.href=`/playlists/${p.id}`}catch(e){setError((e as Error).message);setBusy(false)}}}><label htmlFor="name">Playlist name</label><div className="controls"><input id="name" required maxLength={200} value={name} onChange={e=>setName(e.target.value)} placeholder="PostgreSQL data integrity"/><button disabled={busy||!name.trim()}>Create</button></div></form>{error&&<p role="alert" className="error">{error}</p>}<ul className="list">{items.map(p=><li key={p.id}><a href={`/playlists/${p.id}`}>{p.name}</a> <small>{p.item_count} Reels</small></li>)}</ul></>}
