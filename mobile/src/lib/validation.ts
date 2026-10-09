import { z } from 'zod';

/** Mirrors the server rule (backend/app/security/passwords.py); the server remains authoritative. */
export const passwordRule = z
  .string()
  .min(10, 'Use at least 10 characters.')
  .max(128)
  .regex(/[A-Za-z]/, 'Include a letter.')
  .regex(/\d/, 'Include a number.');
