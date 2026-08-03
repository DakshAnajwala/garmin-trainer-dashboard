import { createContext, useContext, useEffect, useState } from "react";
import { onAuthStateChanged, signInWithPopup, signOut as firebaseSignOut } from "firebase/auth";
import { auth, googleProvider } from "./firebase";
import { clearAllCaches } from "./cache";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = still checking, null = signed out

  useEffect(() => onAuthStateChanged(auth, setUser), []);

  const signIn = () => signInWithPopup(auth, googleProvider);

  // Wipe cached responses before dropping the session. This app caches one
  // person's physiology in localStorage; leaving it there for whoever signs in
  // next on a shared machine would be a real leak. Cleared first so it happens
  // even if the Firebase call throws.
  const signOut = () => {
    clearAllCaches();
    return firebaseSignOut(auth);
  };

  return <AuthContext.Provider value={{ user, signIn, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
