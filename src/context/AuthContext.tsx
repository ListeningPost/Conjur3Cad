"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { onAuthStateChanged, signOut, type User } from "firebase/auth";
import {
  collectionGroup,
  onSnapshot,
  query,
  where,
} from "firebase/firestore";
import { auth, db } from "@/firebase/config";
import { isPlatformAdmin } from "@/lib/platform";
import { normalizeRole, type Membership, type Role } from "@/lib/types";
import { Spinner } from "@/components/ui";

export type { Role };

export interface AuthState {
  user: User | null;
  /**
   * All org memberships (multi-org), live from Firestore. Empty while signed
   * out or when the user hasn't joined/created any organization yet.
   */
  memberships: Membership[];
  /** True while the FIRST membership snapshot for the current user loads. */
  membershipsLoading: boolean;
  /** Whether the signed-in user's email address has been verified. */
  emailVerified: boolean;
  /** Conjur3 staff (allowlisted email) — elevated key/admin powers. */
  platformAdmin: boolean;
  loading: boolean;
  /** Reload the user record from Firebase (picks up a freshly-verified email). */
  reloadUser: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  memberships: [],
  membershipsLoading: true,
  emailVerified: false,
  platformAdmin: false,
  loading: true,
  reloadUser: async () => {},
  logout: async () => {},
});

export const useAuthContext = () => useContext(AuthContext);

export function AuthContextProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Memberships are tagged with the uid they were loaded for, so a user switch
  // reads as "loading" the instant it happens (derived in render, no effect
  // race) — route guards never act on the previous user's memberships.
  const [memberState, setMemberState] = useState<{
    uid: string | null;
    list: Membership[];
    ready: boolean;
  }>({ uid: null, list: [], ready: false });
  const [emailVerified, setEmailVerified] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, (u) => {
      setUser(u);
      setEmailVerified(!!u?.emailVerified);
      setLoading(false);
    });
    return () => unsub();
  }, []);

  // Live memberships across ALL orgs (collection-group on member docs keyed by
  // uid — rules allow reading your own). Replaces the old single-org custom
  // claims, so joins/role changes apply instantly without a token refresh.
  useEffect(() => {
    if (!user) {
      setMemberState({ uid: null, list: [], ready: true });
      return;
    }
    const uid = user.uid;
    const q = query(collectionGroup(db, "members"), where("uid", "==", uid));
    const unsub = onSnapshot(
      q,
      (snap) => {
        setMemberState({
          uid,
          ready: true,
          list: snap.docs
            .map((d) => {
              const orgId = d.ref.parent.parent?.id;
              return orgId
                ? { orgId, role: normalizeRole(d.get("role")) }
                : null;
            })
            .filter((m): m is Membership => m !== null),
        });
      },
      () => setMemberState({ uid, list: [], ready: true }),
    );
    return () => unsub();
  }, [user]);

  const membershipsCurrent =
    memberState.ready && memberState.uid === (user?.uid ?? null);
  const memberships = membershipsCurrent ? memberState.list : [];
  const membershipsLoading = !!user && !membershipsCurrent;

  const reloadUser = useCallback(async () => {
    const u = auth.currentUser;
    if (!u) return;
    await u.reload();
    // Force-refresh the ID token FIRST so it carries the new email_verified
    // claim, THEN flip emailVerified. Consumers that act on verification (e.g.
    // calling a function that requires a verified email) then send a fresh
    // token rather than racing the refresh.
    await u.getIdToken(true);
    setEmailVerified(!!auth.currentUser?.emailVerified);
  }, []);

  const logout = useCallback(async () => {
    await signOut(auth);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        memberships,
        membershipsLoading,
        emailVerified,
        platformAdmin: isPlatformAdmin(user?.email),
        loading,
        reloadUser,
        logout,
      }}
    >
      {loading ? (
        <div className="flex min-h-screen items-center justify-center">
          <Spinner label="Loading" />
        </div>
      ) : (
        children
      )}
    </AuthContext.Provider>
  );
}
