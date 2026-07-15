import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";

// Comes from frontend/.env.local — copy frontend/.env.example and paste in
// your own Firebase web app config (Firebase console > Project settings >
// General > Your apps > Web).
//
// These values aren't secrets: Firebase web config ships in every public
// frontend bundle by design, and access is controlled by Firestore security
// rules plus the allowed-email check on the backend, not by hiding them.
// They live in env anyway so the repo isn't tied to one person's project.
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

if (!firebaseConfig.apiKey) {
  // Failing loudly here beats a cryptic Firebase error three screens later.
  throw new Error(
    "Firebase isn't configured. Copy frontend/.env.example to frontend/.env.local and fill in your Firebase web config — see SETUP.md.",
  );
}

export const firebaseApp = initializeApp(firebaseConfig);
export const auth = getAuth(firebaseApp);
export const googleProvider = new GoogleAuthProvider();
