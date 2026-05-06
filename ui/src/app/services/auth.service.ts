import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { BehaviorSubject, Observable, tap } from 'rxjs';
import { Router } from '@angular/router';
import { LoginRequest, LoginResponse, TradingWindowUpdate, User } from '../models/user.model';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  private apiUrl = 'http://localhost:8000/api/v1'; // FastAPI endpoint with v1 prefix
  private currentUserSubject = new BehaviorSubject<User | null>(this.getUserFromStorage());
  public currentUser$ = this.currentUserSubject.asObservable();

  constructor() {}

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
        // Store token and user info
        localStorage.setItem('access_token', response.access_token);
        localStorage.setItem('currentUser', JSON.stringify(response.user));
        this.currentUserSubject.next(response.user);
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
}
