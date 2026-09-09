import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { BehaviorSubject, Observable, tap } from 'rxjs';
import { Router } from '@angular/router';
import {
  LoginRequest,
  LoginResponse,
  NotificationPreferences,
  NotificationPreferencesUpdate,
  ProfileUpdate,
  TradingWindowUpdate,
  User,
} from '../models/user.model';
import { environment } from '../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  // environment.apiUrl follows the host the page was served from, so this
  // works from a phone or laptop on the LAN. It was hardcoded to localhost,
  // which on any other device means THAT device — login failed with
  // "check credentials" because the request never reached the API.
  private apiUrl = environment.apiUrl;
  private currentUserSubject = new BehaviorSubject<User | null>(this.getUserFromStorage());
  public currentUser$ = this.currentUserSubject.asObservable();

  constructor() {
    // Re-read the user on boot whenever we hold a token.
    //
    // `currentUser` is otherwise only ever written at login, so a role changed
    // server-side never reaches the UI and a user stored by an older build
    // sticks around indefinitely. Both show up as an admin seeing no Users nav
    // row and a disabled "Done for the day" button. Non-fatal by design: on
    // failure we keep whatever is stored rather than bouncing a working session
    // to the login page, and the backend gates remain the real boundary.
    if (this.isAuthenticated) {
      this.refreshMe().subscribe({
        error: err => console.warn('Could not refresh current user on boot:', err),
      });
    }
  }

  private getUserFromStorage(): User | null {
    const userStr = localStorage.getItem('currentUser');
    if (!userStr || userStr === 'undefined' || userStr === 'null') {
      return null;
    }
    try {
      return JSON.parse(userStr);
    } catch (e) {
      console.error('Error parsing user from storage:', e);
      localStorage.removeItem('currentUser');
      return null;
    }
  }

  private getTokenFromStorage(): string | null {
    return localStorage.getItem('access_token');
  }

  get currentUserValue(): User | null {
    return this.currentUserSubject.value;
  }

  get isAuthenticated(): boolean {
    return !!this.getTokenFromStorage();
  }

  login(credentials: LoginRequest): Observable<LoginResponse> {
    // FastAPI expects form data for OAuth2 password flow
    const formData = new FormData();
    formData.append('username', credentials.username);
    formData.append('password', credentials.password);

    return this.http.post<LoginResponse>(`${this.apiUrl}/auth/login`, formData).pipe(
      tap(response => {
        localStorage.setItem('access_token', response.access_token);
        // `JSON.stringify(undefined)` is undefined, which setItem coerces to
        // the STRING "undefined" — that is how a missing user field used to
        // poison storage and pin every role check to 'user' for the session.
        // If the API ever stops sending the user, fall back to /auth/me rather
        // than writing a value that only looks like a user.
        if (response.user) {
          localStorage.setItem('currentUser', JSON.stringify(response.user));
          this.currentUserSubject.next(response.user);
        } else {
          this.refreshMe().subscribe({
            error: err => console.error('Login returned no user and /auth/me failed:', err),
          });
        }
      })
    );
  }

  logout(): void {
    // Remove user data from storage
    localStorage.removeItem('access_token');
    localStorage.removeItem('currentUser');
    this.currentUserSubject.next(null);
    this.router.navigate(['/login']);
  }

  getToken(): string | null {
    return this.getTokenFromStorage();
  }

  private authHeaders(): HttpHeaders {
    const token = this.getTokenFromStorage();
    return new HttpHeaders({ Authorization: token ? `Bearer ${token}` : '' });
  }

  refreshMe(): Observable<User> {
    return this.http.get<User>(`${this.apiUrl}/auth/me`, { headers: this.authHeaders() }).pipe(
      tap(user => {
        const merged = { ...this.currentUserValue, ...user } as User;
        localStorage.setItem('currentUser', JSON.stringify(merged));
        this.currentUserSubject.next(merged);
      })
    );
  }

  updateTradingWindow(update: TradingWindowUpdate): Observable<User> {
    return this.http.patch<User>(`${this.apiUrl}/auth/me`, update, { headers: this.authHeaders() }).pipe(
      tap(user => {
        const merged = { ...this.currentUserValue, ...user } as User;
        localStorage.setItem('currentUser', JSON.stringify(merged));
        this.currentUserSubject.next(merged);
      })
    );
  }

  updateNotificationPreferences(prefs: NotificationPreferences): Observable<User> {
    const body: NotificationPreferencesUpdate = { notification_preferences: prefs };
    return this.http.patch<User>(`${this.apiUrl}/auth/me`, body, { headers: this.authHeaders() }).pipe(
      tap(user => {
        const merged = { ...this.currentUserValue, ...user } as User;
        localStorage.setItem('currentUser', JSON.stringify(merged));
        this.currentUserSubject.next(merged);
      })
    );
  }

  testDiscordWebhook(webhookUrl: string): Observable<{ ok: boolean; message: string }> {
    return this.http.post<{ ok: boolean; message: string }>(
      `${this.apiUrl}/auth/me/notifications/discord/test`,
      { webhook_url: webhookUrl },
      { headers: this.authHeaders() }
    );
  }

  testEmailReport(): Observable<{ ok: boolean; message: string }> {
    return this.http.post<{ ok: boolean; message: string }>(
      `${this.apiUrl}/auth/me/notifications/email-reports/test`,
      {},
      { headers: this.authHeaders() }
    );
  }

  updateProfile(update: ProfileUpdate): Observable<User> {
    return this.http.patch<User>(`${this.apiUrl}/auth/me`, update, { headers: this.authHeaders() }).pipe(
      tap(user => {
        const merged = { ...this.currentUserValue, ...user } as User;
        localStorage.setItem('currentUser', JSON.stringify(merged));
        this.currentUserSubject.next(merged);
      })
    );
  }
}
