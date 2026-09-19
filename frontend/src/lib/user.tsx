import { createContext, useContext, useState, type ReactNode } from "react";

const STORAGE_KEY = "orchestrator.userId";

function initialUser(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || "demo-user";
  } catch {
    return "demo-user";
  }
}

interface UserContextValue {
  userId: string;
  setUserId: (id: string) => void;
}

const UserContext = createContext<UserContextValue>({ userId: "demo-user", setUserId: () => {} });

export function UserProvider({ children }: { children: ReactNode }) {
  const [userId, setUserIdState] = useState(initialUser);
  const setUserId = (id: string) => {
    const clean = id.trim().replace(/[^\w.@-]/g, "") || "demo-user";
    setUserIdState(clean);
    try {
      localStorage.setItem(STORAGE_KEY, clean);
    } catch {
      /* storage unavailable */
    }
  };
  return <UserContext.Provider value={{ userId, setUserId }}>{children}</UserContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export const useUser = () => useContext(UserContext);
