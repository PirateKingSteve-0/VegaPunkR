import { inject } from '@angular/core';
import { Router, CanActivateFn } from '@angular/router';
import { AuthService } from '../services/auth.service';

const READ_CROSS_USER_ROLES = ['admin', 'auditor'];

export const adminGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.isAuthenticated) {
    router.navigate(['/login']);
    return false;
  }

  const role = authService.currentUserValue?.role ?? 'user';
  if (READ_CROSS_USER_ROLES.includes(role)) {
    return true;
  }
  router.navigate(['/dashboard/overview']);
  return false;
};
