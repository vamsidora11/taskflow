export const MIN_PASSWORD = 12

export function validatePassword(password: string): string | null {
  if (!password) return 'Enter a password.'
  if (password.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`
  return null
}
