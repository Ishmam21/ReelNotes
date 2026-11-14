export const API = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
 const response = await fetch(`${API}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers }, cache: 'no-store' });
 if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || 'Request failed')); }
 return response.status === 204 ? undefined as T : response.json();
}
export const post = (body?: unknown): RequestInit => ({method:'POST',body:body === undefined ? undefined : JSON.stringify(body)});
export type Card = {video_id:string;position:number;title:string|null;source_url:string;thumbnail_url:string|null;state:string;error_code:string|null;error_message?:string|null;message?:string|null};
export type Playlist = {id:string;name:string;items:Card[]};
export type Guide = {id:string;markdown:string;created_at?:string};
export type Segment = {id:string;start_ms:number;end_ms:number;text:string};
