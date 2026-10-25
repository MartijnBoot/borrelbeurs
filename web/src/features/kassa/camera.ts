/**
 * Whether the kassa may offer the camera (B-05 SD17, AC42): a browser opens one
 * only in a secure context (HTTPS on Render, `localhost`). At the venue the page
 * is plain HTTP on a LAN address, so it offers "Code typen" alone, with no error.
 */
export function canUseCamera(): boolean {
  return window.isSecureContext && typeof navigator.mediaDevices?.getUserMedia === 'function'
}
