'use client';

import { Fragment, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ApiError, post, request } from '@/lib/api';

type Account = { id: string; email: string };
const registrationPasswordPattern = String.raw`(?=.*\p{Lu})(?=.*\p{Ll})(?=.*\p{Nd})(?=.*[\p{P}\p{S}]).+`;

function AccountForm({ onSuccess }: { onSuccess: (account: Account) => void }) {
  const [registering, setRegistering] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const action = registering ? 'Create account' : 'Log in';

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const fields = new FormData(event.currentTarget);
    try {
      const path = registering ? '/auth/register' : '/auth/login';
      onSuccess(await request<Account>(path, post({ email: fields.get('email'), password: fields.get('password') })));
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="create-panel account-panel" aria-labelledby="account-heading">
      <h1 id="account-heading">{registering ? 'Create your account' : 'Log in to ReelNotes'}</h1>
      <form onSubmit={submit}>
        <div>
          <label htmlFor="email">Email</label>
          <input id="email" name="email" type="email" autoComplete="username" maxLength={254} required />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <input key={action} id="password" name="password" type="password" required maxLength={128}
            minLength={registering ? 6 : undefined} pattern={registering ? registrationPasswordPattern : undefined}
            autoComplete={registering ? 'new-password' : 'current-password'}
            aria-describedby={registering ? 'password-hint' : undefined} />
          {registering && <small id="password-hint">Use at least 6 characters, including an uppercase letter, a lowercase letter, a number, and a special character.</small>}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? (registering ? 'Creating account…' : 'Logging in…') : action}</button>
      </form>
      <button className="text-button" type="button" disabled={busy} onClick={() => {
        setError('');
        setRegistering(!registering);
      }}>{registering ? 'Already have an account? Log in' : 'New to ReelNotes? Create an account'}</button>
    </section>
  );
}

export default function AccountGate({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>();
  const [error, setError] = useState('');
  const [signingOut, setSigningOut] = useState(false);
  const sessionCheck = useRef(0);

  function changeAccount(next: Account | null) {
    sessionCheck.current += 1;
    setAccount(next);
  }

  async function loadSession(signal?: AbortSignal) {
    const check = ++sessionCheck.current;
    setError('');
    try {
      const current = await request<Account>('/auth/me', { signal });
      if (check === sessionCheck.current && !signal?.aborted) setAccount(current);
    } catch (error) {
      if (check !== sessionCheck.current || signal?.aborted) return;
      if (error instanceof ApiError && error.status === 401) setAccount(null);
      else setError((error as Error).message);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    function sessionExpired() {
      changeAccount(null);
      setError('');
    }
    function refreshSession() {
      void loadSession(controller.signal);
    }
    window.addEventListener('reelnotes:session-expired', sessionExpired);
    window.addEventListener('focus', refreshSession);
    refreshSession();
    return () => {
      controller.abort();
      window.removeEventListener('reelnotes:session-expired', sessionExpired);
      window.removeEventListener('focus', refreshSession);
    };
  }, []);

  async function signOut() {
    setSigningOut(true);
    setError('');
    try {
      await request<void>('/auth/logout', post());
      changeAccount(null);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setSigningOut(false);
    }
  }

  if (account === undefined) {
    return error
      ? <section className="account-panel"><p className="error" role="alert">{error}</p>
        <button onClick={() => void loadSession()}>Retry</button></section>
      : <p role="status">Checking your session…</p>;
  }
  if (!account) return <AccountForm onSuccess={changeAccount} />;

  return (
    <>
      <div className="account-bar">
        <span>{account.email}</span>
        <button className="secondary" onClick={signOut} disabled={signingOut}>
          {signingOut ? 'Logging out…' : 'Log out'}
        </button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <Fragment key={account.id}>{children}</Fragment>
    </>
  );
}
