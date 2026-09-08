// The API host is derived from whatever host the page was served on, so one
// build works from every device with no per-device config and no rebuild:
//
//   http://localhost:4200      -> http://localhost:8000/api/v1
//   http://Lulusia.local:4200  -> http://Lulusia.local:8000/api/v1
//   http://192.168.1.7:4200    -> http://192.168.1.7:8000/api/v1
//
// A hardcoded `localhost` broke the moment the page was opened from a phone:
// `localhost` there means the PHONE. Safe to touch `window` at module scope —
// this app has no SSR or prerender step.
const apiHost = `${window.location.protocol}//${window.location.hostname}:8000`;

export const environment = {
  production: false,
  apiUrl: `${apiHost}/api/v1`
};
